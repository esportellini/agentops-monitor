from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import MemberRole, OrgPlan


class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationOut(OrmBase):
    id: int
    name: str
    slug: str
    plan: OrgPlan
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(BaseModel):
    name: str
    slug: str
    plan: OrgPlan = OrgPlan.FREE

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("slug must be lowercase alphanumeric with hyphens")
        return v


class OrganizationUpdate(BaseModel):
    name: str | None = None
    plan: OrgPlan | None = None


class UserOut(OrmBase):
    id: int
    email: str
    name: str
    is_active: bool
    created_at: datetime


class MemberOut(OrmBase):
    id: int
    organization_id: int
    user_id: int
    role: MemberRole
    created_at: datetime
    user: UserOut


class MemberInvite(BaseModel):
    email: str
    role: MemberRole = MemberRole.VIEWER


class MemberRoleUpdate(BaseModel):
    role: MemberRole
