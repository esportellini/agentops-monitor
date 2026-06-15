"""
Security scanner: pure Python, regex-based, no AI dependency.

Design:
- Every detector is a small function that returns a list of RuleMatch.
- The ScanResult aggregates all matches from the pipeline.
- Redaction replaces matched content with canonical placeholders.
- Never raises — malformed input is silently skipped.

Finding types (strings used throughout the system):
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Finding type constants ─────────────────────────────────────────────────────
FINDING_PROMPT_INJECTION = "prompt_injection"
FINDING_SECRET_DETECTED = "secret_detected"
FINDING_PII_EMAIL = "pii_email"
FINDING_PII_PHONE = "pii_phone"
FINDING_PII_CPF = "pii_cpf"
FINDING_PII_CARD = "pii_card"
FINDING_API_KEY = "api_key_detected"
FINDING_BEARER_TOKEN = "bearer_token_detected"
FINDING_CREDENTIAL = "credential_detected"
FINDING_DOMAIN_BLOCKED = "domain_blocked"
FINDING_TOOL_UNAUTHORIZED = "tool_unauthorized"
FINDING_TOKEN_LIMIT = "token_limit_exceeded"
FINDING_COST_LIMIT = "cost_limit_exceeded"
FINDING_SQL_DANGEROUS = "sql_dangerous"
FINDING_SCOPE_VIOLATION = "output_scope_violation"
FINDING_ABNORMAL_BEHAVIOR = "abnormal_behavior"

ALL_FINDING_TYPES = [
    FINDING_PROMPT_INJECTION, FINDING_SECRET_DETECTED, FINDING_PII_EMAIL,
    FINDING_PII_PHONE, FINDING_PII_CPF, FINDING_PII_CARD, FINDING_API_KEY,
    FINDING_BEARER_TOKEN, FINDING_CREDENTIAL, FINDING_DOMAIN_BLOCKED,
    FINDING_TOOL_UNAUTHORIZED, FINDING_TOKEN_LIMIT, FINDING_COST_LIMIT,
    FINDING_SQL_DANGEROUS, FINDING_SCOPE_VIOLATION, FINDING_ABNORMAL_BEHAVIOR,
]

# ── Severity mapping per finding type ─────────────────────────────────────────
_SEVERITY: dict[str, str] = {
    FINDING_PROMPT_INJECTION: "HIGH",
    FINDING_SECRET_DETECTED: "CRITICAL",
    FINDING_PII_EMAIL: "MEDIUM",
    FINDING_PII_PHONE: "MEDIUM",
    FINDING_PII_CPF: "HIGH",
    FINDING_PII_CARD: "CRITICAL",
    FINDING_API_KEY: "CRITICAL",
    FINDING_BEARER_TOKEN: "HIGH",
    FINDING_CREDENTIAL: "HIGH",
    FINDING_DOMAIN_BLOCKED: "HIGH",
    FINDING_TOOL_UNAUTHORIZED: "HIGH",
    FINDING_TOKEN_LIMIT: "MEDIUM",
    FINDING_COST_LIMIT: "MEDIUM",
    FINDING_SQL_DANGEROUS: "HIGH",
    FINDING_SCOPE_VIOLATION: "MEDIUM",
    FINDING_ABNORMAL_BEHAVIOR: "MEDIUM",
}

# ── Redaction placeholders ─────────────────────────────────────────────────────
_REDACT: dict[str, str] = {
    FINDING_PII_EMAIL: "[EMAIL_REDACTED]",
    FINDING_PII_PHONE: "[PHONE_REDACTED]",
    FINDING_PII_CPF: "[CPF_REDACTED]",
    FINDING_PII_CARD: "[CARD_REDACTED]",
    FINDING_API_KEY: "[SECRET_REDACTED]",
    FINDING_BEARER_TOKEN: "[TOKEN_REDACTED]",
    FINDING_CREDENTIAL: "[SECRET_REDACTED]",
    FINDING_SECRET_DETECTED: "[SECRET_REDACTED]",
}

# ── Compiled regexes ───────────────────────────────────────────────────────────

# PII
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
_RE_PHONE_BR = re.compile(
    r"(?<!\d)(?:\+?55[\s\-]?)?(?:\(?\d{2}\)?[\s\-]?)(?:9\d{4}|[2-9]\d{3})[\s\-]?\d{4}(?!\d)"
)
_RE_CPF = re.compile(
    r"\b(\d{3}[.\-]?\d{3}[.\-]?\d{3}[.\-/]?\d{2})\b"
)
_RE_CARD = re.compile(
    r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"
)

# Secrets / credentials
_RE_BEARER = re.compile(
    r"(?i)\bBearer\s+([A-Za-z0-9\-._~+/]+=*)",
)
_RE_API_KEY_GENERIC = re.compile(
    r"(?i)(?:api[_\-]?key|apikey|x\-api\-key)\s*[:=]\s*['\"]?([A-Za-z0-9\-_]{16,})['\"]?"
)
_RE_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")
_RE_ANTHROPIC_KEY = re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{32,}\b")
_RE_AGENTOPS_KEY = re.compile(r"\bagom_[A-Za-z0-9]{16,}\b")
_RE_AWS_KEY = re.compile(r"\bAKIA[A-Z0-9]{16}\b")
_RE_GH_TOKEN = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")

_RE_PASSWORD_FIELD = re.compile(
    r'(?i)(?:password|senha|passwd|pwd|secret|credentials?)\s*[:=]\s*["\']?(\S{4,})["\']?'
)

# Prompt injection patterns
_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(all\s+)?(?:previous|prior|above)\s+(?:instructions?|context|rules?|prompt)\b"),
    re.compile(r"(?i)\bforget\s+(all\s+)?(?:your\s+)?(?:instructions?|context|rules?|guidelines?)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an|the)\b"),
    re.compile(r"(?i)\bact\s+as\s+(?:a|an|if)\b.*\b(?:jailbreak|DAN|evil|unrestricted)\b"),
    re.compile(r"(?i)\bsystem\s*:\s*(ignore|bypass|override)\b"),
    re.compile(r"(?i)</?(?:system|assistant|human|instructions?)>"),
    re.compile(r"(?i)\bpretend\s+(?:you\s+)?(?:are|have\s+no)\s+(?:rules?|restrictions?|guidelines?)\b"),
    re.compile(r"(?i)\boverride\s+(?:your\s+)?(?:training|safety|guidelines?|instructions?)\b"),
    re.compile(r"(?i)\bdo\s+(?:not\s+)?(?:follow|obey|respect)\s+(?:your\s+)?(?:instructions?|rules?)\b"),
    re.compile(r"(?i)(?:###\s*)?NEW\s+INSTRUCTIONS?\s*:"),
    re.compile(r"(?i)\bDAN\s+mode\b"),
    re.compile(r"(?i)\bjailbreak\b"),
]

# Dangerous SQL
_SQL_DANGEROUS = re.compile(
    r"(?i)\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE|DELETE\s+FROM\s+\w+\s*(?:WHERE\s+1\s*=\s*1|;?\s*$)|"
    r"ALTER\s+TABLE|GRANT\s+ALL|INSERT\s+INTO\s+users|xp_cmdshell|EXEC\s*\(|EXECUTE\s*\()\b"
)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class RuleMatch:
    finding_type: str
    severity: str
    title: str
    description: str
    matched_text: str
    redaction_placeholder: str | None = None
    field: str = ""


@dataclass
class ScanResult:
    text_original: str
    text_redacted: str
    matches: list[RuleMatch] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.matches)

    @property
    def highest_severity(self) -> str | None:
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        for s in order:
            if any(m.severity == s for m in self.matches):
                return s
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _luhn(number: str) -> bool:
    """Luhn algorithm to validate credit card numbers."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _valid_cpf(cpf: str) -> bool:
    """Basic CPF structural validation (digit verification)."""
    digits = re.sub(r"\D", "", cpf)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    # First check digit
    s = sum(int(digits[i]) * (10 - i) for i in range(9))
    r = (s * 10 % 11) % 10
    if r != int(digits[9]):
        return False
    # Second check digit
    s = sum(int(digits[i]) * (11 - i) for i in range(10))
    r = (s * 10 % 11) % 10
    return r == int(digits[10])


def _extract_text(obj: Any) -> str:
    """Recursively extract all string content from a dict/list/str."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(_extract_text(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return " ".join(_extract_text(i) for i in obj)
    return str(obj) if obj is not None else ""


# ── Individual detectors ──────────────────────────────────────────────────────

def _detect_email(text: str) -> list[RuleMatch]:
    return [
        RuleMatch(
            finding_type=FINDING_PII_EMAIL,
            severity=_SEVERITY[FINDING_PII_EMAIL],
            title="Email address detected",
            description=f"Email address found in content: {m.group()[:5]}***",
            matched_text=m.group(),
            redaction_placeholder=_REDACT[FINDING_PII_EMAIL],
        )
        for m in _RE_EMAIL.finditer(text)
    ]


def _detect_phone(text: str) -> list[RuleMatch]:
    return [
        RuleMatch(
            finding_type=FINDING_PII_PHONE,
            severity=_SEVERITY[FINDING_PII_PHONE],
            title="Phone number detected",
            description="Phone number found in content",
            matched_text=m.group(),
            redaction_placeholder=_REDACT[FINDING_PII_PHONE],
        )
        for m in _RE_PHONE_BR.finditer(text)
    ]


def _detect_cpf(text: str) -> list[RuleMatch]:
    matches = []
    for m in _RE_CPF.finditer(text):
        raw = m.group()
        if _valid_cpf(raw):
            matches.append(RuleMatch(
                finding_type=FINDING_PII_CPF,
                severity=_SEVERITY[FINDING_PII_CPF],
                title="CPF detected",
                description="Valid CPF number found in content",
                matched_text=raw,
                redaction_placeholder=_REDACT[FINDING_PII_CPF],
            ))
    return matches


def _detect_card(text: str) -> list[RuleMatch]:
    matches = []
    for m in _RE_CARD.finditer(text):
        if _luhn(m.group()):
            matches.append(RuleMatch(
                finding_type=FINDING_PII_CARD,
                severity=_SEVERITY[FINDING_PII_CARD],
                title="Credit/debit card number detected",
                description="Valid card number (Luhn) found in content",
                matched_text=m.group(),
                redaction_placeholder=_REDACT[FINDING_PII_CARD],
            ))
    return matches


def _detect_secrets(text: str) -> list[RuleMatch]:
    matches: list[RuleMatch] = []

    for pat, label in [
        (_RE_OPENAI_KEY, "OpenAI API key"),
        (_RE_ANTHROPIC_KEY, "Anthropic API key"),
        (_RE_AGENTOPS_KEY, "AgentOps API key"),
        (_RE_AWS_KEY, "AWS Access Key ID"),
        (_RE_GH_TOKEN, "GitHub Personal Access Token"),
    ]:
        for m in pat.finditer(text):
            matches.append(RuleMatch(
                finding_type=FINDING_API_KEY,
                severity=_SEVERITY[FINDING_API_KEY],
                title=f"{label} detected",
                description=f"Known API key format ({label}) found in content",
                matched_text=m.group()[:12] + "…",
                redaction_placeholder=_REDACT[FINDING_API_KEY],
            ))

    for m in _RE_API_KEY_GENERIC.finditer(text):
        matches.append(RuleMatch(
            finding_type=FINDING_API_KEY,
            severity=_SEVERITY[FINDING_API_KEY],
            title="API key detected",
            description="Generic API key pattern found in content",
            matched_text=m.group()[:20] + "…",
            redaction_placeholder=_REDACT[FINDING_API_KEY],
        ))

    for m in _RE_BEARER.finditer(text):
        matches.append(RuleMatch(
            finding_type=FINDING_BEARER_TOKEN,
            severity=_SEVERITY[FINDING_BEARER_TOKEN],
            title="Bearer token detected",
            description="HTTP Bearer token found in content",
            matched_text="Bearer " + m.group(1)[:8] + "…",
            redaction_placeholder=_REDACT[FINDING_BEARER_TOKEN],
        ))

    for m in _RE_PASSWORD_FIELD.finditer(text):
        matches.append(RuleMatch(
            finding_type=FINDING_CREDENTIAL,
            severity=_SEVERITY[FINDING_CREDENTIAL],
            title="Credential field detected",
            description="Password/secret field with value found in content",
            matched_text=m.group()[:20] + "…",
            redaction_placeholder=_REDACT[FINDING_CREDENTIAL],
        ))

    return matches


def _detect_injection(text: str) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for pat in _INJECTION_PATTERNS:
        for m in pat.finditer(text):
            matches.append(RuleMatch(
                finding_type=FINDING_PROMPT_INJECTION,
                severity=_SEVERITY[FINDING_PROMPT_INJECTION],
                title="Possible prompt injection attempt",
                description=f"Injection pattern matched: '{m.group()[:60]}'",
                matched_text=m.group()[:80],
            ))
            break  # one match per pattern is enough
    return matches


def _detect_sql(text: str) -> list[RuleMatch]:
    matches = []
    for m in _SQL_DANGEROUS.finditer(text):
        matches.append(RuleMatch(
            finding_type=FINDING_SQL_DANGEROUS,
            severity=_SEVERITY[FINDING_SQL_DANGEROUS],
            title="Dangerous SQL detected",
            description=f"Destructive SQL pattern: '{m.group()}'",
            matched_text=m.group(),
        ))
    return matches


# ── Redactor ──────────────────────────────────────────────────────────────────

def _apply_redactions(text: str, matches: list[RuleMatch]) -> str:
    """Replace all matched texts with their redaction placeholders."""
    result = text
    # Sort longest-first so inner matches don't interfere
    for m in sorted(matches, key=lambda x: -len(x.matched_text)):
        if m.redaction_placeholder and m.matched_text in result:
            result = result.replace(m.matched_text, m.redaction_placeholder)
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def scan_text(text: str, field_name: str = "") -> ScanResult:
    """
    Run all detectors against a single string.
    Returns a ScanResult with matches and the redacted version.
    Never raises.
    """
    try:
        if not isinstance(text, str) or not text.strip():
            return ScanResult(text_original=text or "", text_redacted=text or "")

        all_matches: list[RuleMatch] = []
        all_matches.extend(_detect_email(text))
        all_matches.extend(_detect_phone(text))
        all_matches.extend(_detect_cpf(text))
        all_matches.extend(_detect_card(text))
        all_matches.extend(_detect_secrets(text))
        all_matches.extend(_detect_injection(text))
        all_matches.extend(_detect_sql(text))

        for m in all_matches:
            m.field = field_name

        redacted = _apply_redactions(text, all_matches)
        return ScanResult(text_original=text, text_redacted=redacted, matches=all_matches)
    except Exception:
        return ScanResult(text_original=text or "", text_redacted=text or "")


def scan_object(obj: Any, field_name: str = "") -> ScanResult:
    """Scan any object by extracting its string representation."""
    text = _extract_text(obj)
    return scan_text(text, field_name=field_name)


def get_severity(finding_type: str) -> str:
    return _SEVERITY.get(finding_type, "MEDIUM")


def check_domain(url_or_domain: str, blocked_domains: list[str], allowed_domains: list[str] | None) -> str | None:
    """
    Return the blocked/policy-violating domain string, or None if allowed.
    blocked_domains is checked first (deny-list), then allowed_domains (allow-list).
    """
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url_or_domain if "://" in url_or_domain else f"http://{url_or_domain}")
        domain = parsed.hostname or url_or_domain
    except Exception:
        domain = url_or_domain

    domain = domain.lower().lstrip("www.")

    for bd in blocked_domains:
        bd = bd.lower().lstrip("www.")
        if domain == bd or domain.endswith(f".{bd}"):
            return domain

    if allowed_domains is not None:
        for ad in allowed_domains:
            ad = ad.lower().lstrip("www.")
            if domain == ad or domain.endswith(f".{ad}"):
                return None
        return domain  # not in allowlist → treat as blocked

    return None
