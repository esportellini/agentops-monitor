from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, current_user, require_admin, require_owner, require_org_member
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.enums import MemberRole, OrgPlan, Severity
from app.models.organization import Organization, OrganizationMember, User
from app.repositories import organization as org_repo
from app.repositories import user as user_repo
from app.schemas.organization import (
    MemberInvite,
    MemberOut,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.services import audit as audit_svc

router = APIRouter(prefix="/organizations", tags=["organizations"])
log = get_logger(__name__)


# ── List orgs for current user ────────────────────────────────────────────────

@router.get("", response_model=list[OrganizationOut])
async def list_organizations(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await org_repo.list_for_user(db, user.id)


# ── Create org ────────────────────────────────────────────────────────────────

@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await org_repo.get_by_slug(db, body.slug)
    if existing:
        raise HTTPException(status_code=409, detail="Slug already taken")

    org = Organization(name=body.name, slug=body.slug, plan=body.plan)
    db.add(org)
    await db.flush()

    # Creator becomes OWNER
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=MemberRole.OWNER,
    )
    db.add(member)

    await audit_svc.write(
        db,
        organization_id=org.id,
        user_id=user.id,
        event_type="org.created",
        entity_type="organization",
        entity_id=str(org.id),
        message=f"Organization '{org.name}' created by {user.email}",
        severity=Severity.INFO,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(org)
    return org


# ── Get org ───────────────────────────────────────────────────────────────────

@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    org = await org_repo.get_by_id(db, ctx.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


# ── Update org (ADMIN+) ───────────────────────────────────────────────────────

@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    body: OrganizationUpdate,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org = await org_repo.get_by_id(db, ctx.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    before = {"name": org.name, "plan": org.plan.value}
    if body.name is not None:
        org.name = body.name
    if body.plan is not None:
        org.plan = body.plan
    after = {"name": org.name, "plan": org.plan.value}

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="org.updated",
        entity_type="organization",
        entity_id=str(org.id),
        message=f"Organization updated by {ctx.user.email}",
        before_data=before,
        after_data=after,
    )
    await db.commit()
    await db.refresh(org)
    return org


# ── Members — list ────────────────────────────────────────────────────────────

@router.get("/{org_id}/members", response_model=list[MemberOut])
async def list_members(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await org_repo.list_members(db, ctx.org_id)


# ── Members — invite ─────────────────────────────────────────────────────────

@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: MemberInvite,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Only OWNER can assign OWNER or ADMIN roles
    if body.role in (MemberRole.OWNER, MemberRole.ADMIN) and ctx.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Only owners can assign admin or owner roles")

    target = await user_repo.get_by_email(db, body.email)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await org_repo.get_member(db, ctx.org_id, target.id)
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    member = OrganizationMember(
        organization_id=ctx.org_id,
        user_id=target.id,
        role=body.role,
        invited_by_id=ctx.user.id,
    )
    db.add(member)
    await db.flush()

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="org.member_added",
        entity_type="user",
        entity_id=str(target.id),
        message=f"{target.email} added to org as {body.role} by {ctx.user.email}",
        after_data={"role": body.role.value},
        severity=Severity.INFO,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(member)
    # Load user relationship for response
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.id == member.id)
        .options(selectinload(OrganizationMember.user))
    )
    return result.scalar_one()


# ── Members — update role ─────────────────────────────────────────────────────

@router.patch("/{org_id}/members/{member_id}", response_model=MemberOut)
async def update_member_role(
    member_id: int,
    body: MemberRoleUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    member = await org_repo.get_member_by_id(db, member_id, ctx.org_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Only OWNER can promote to OWNER or ADMIN
    if body.role in (MemberRole.OWNER, MemberRole.ADMIN) and ctx.role != MemberRole.OWNER:
        raise HTTPException(status_code=403, detail="Only owners can assign admin or owner roles")

    # Prevent last owner demotion
    if member.role == MemberRole.OWNER and body.role != MemberRole.OWNER:
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.count()).where(
                OrganizationMember.organization_id == ctx.org_id,
                OrganizationMember.role == MemberRole.OWNER,
            )
        )
        if result.scalar() <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last owner")

    before_role = member.role
    member.role = body.role

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="org.member_role_changed",
        entity_type="user",
        entity_id=str(member.user_id),
        message=f"Member role changed from {before_role} to {body.role} by {ctx.user.email}",
        before_data={"role": before_role.value},
        after_data={"role": body.role.value},
        severity=Severity.MEDIUM,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(member)
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.id == member.id)
        .options(selectinload(OrganizationMember.user))
    )
    return result.scalar_one()


# ── Members — remove ─────────────────────────────────────────────────────────

@router.delete("/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    member = await org_repo.get_member_by_id(db, member_id, ctx.org_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent removing last owner
    if member.role == MemberRole.OWNER:
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.count()).where(
                OrganizationMember.organization_id == ctx.org_id,
                OrganizationMember.role == MemberRole.OWNER,
            )
        )
        if result.scalar() <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last owner")

    removed_user_id = member.user_id
    await db.delete(member)

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="org.member_removed",
        entity_type="user",
        entity_id=str(removed_user_id),
        message=f"Member (user_id={removed_user_id}) removed by {ctx.user.email}",
        severity=Severity.MEDIUM,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
