"""Company profile snapshot and the stable read interface judgment depends on.

Judgment code never reaches into raw profile dictionaries. It reads through
`ProfileView`, so a later profile schema change stays contained in this module
instead of spreading across every judgment rule.

The snapshot is Backend-produced: a Backend service maps company rows into this
shape, and `app.ai` never imports the ORM. That keeps the AI package free of
database state exactly like the rest of the integration boundary.

The critical modelling rule is that *unknown* and *empty* are different answers:

- ``performances=None`` -> the profile never said anything about performances
- ``performances=[]``   -> the company stated it has none

The first must produce a follow-up question, the second can settle an
UNSATISFIED judgment. `ProfileView.has()` is that distinction, and losing it
turns "we don't know" into "you don't qualify".
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SCHEMA_VERSION = "profile.v2"

# How far the supporting documentation for a profile item has been checked.
EVIDENCE_VERIFIED = "verified"  # supporting document confirmed
EVIDENCE_DECLARED = "declared"  # company stated it, document not checked
EVIDENCE_NONE = "none"  # no evidence information at all

EvidenceStatus = Literal["verified", "declared", "none"]

# Company size drives the "대기업·중견기업 참여 제한" style requirement that shows up
# in notices of every industry, so it stays a core field rather than an extension.
SIZE_SMALL = "small"
SIZE_MEDIUM = "medium"
SIZE_LARGE = "large"

CompanySize = Literal["small", "medium", "large"]

SIZE_LABELS = {SIZE_SMALL: "중소기업", SIZE_MEDIUM: "중견기업", SIZE_LARGE: "대기업"}

# Intake forms and uploaded files spell this differently, so Korean labels are
# accepted alongside the canonical values.
_SIZE_ALIASES = {
    "small": SIZE_SMALL,
    "중소": SIZE_SMALL,
    "중소기업": SIZE_SMALL,
    "medium": SIZE_MEDIUM,
    "중견": SIZE_MEDIUM,
    "중견기업": SIZE_MEDIUM,
    "large": SIZE_LARGE,
    "대기업": SIZE_LARGE,
}

_LIST_SECTIONS = ("performances", "certifications", "staff", "fields")


def normalize_company_size(value: Any) -> str | None:
    """Map a company-size spelling onto a canonical value, or None when unknown.

    Returning None instead of guessing matters: an unrecognized spelling must
    reach the follow-up path, not be rounded into a size that decides a judgment.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    return _SIZE_ALIASES.get(text.lower()) or _SIZE_ALIASES.get(text)


class ProfileField(BaseModel):
    """A basic-section value carried together with its label and origin.

    `value` and `label` are untyped because the basic section is heterogeneous:
    a region is a code with one display name, industry codes are a list with a
    parallel list of names.
    """

    value: Any = None
    label: Any = None
    source: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_scalar(cls, data: Any) -> Any:
        """Allow a bare scalar where the wrapper object is overkill."""
        if isinstance(data, dict):
            return data
        return {"value": data}


class ProfileBasic(BaseModel):
    company_name: ProfileField | None = None
    region: ProfileField | None = None
    company_size: ProfileField | None = None
    employee_count: ProfileField | None = None
    industry_codes: ProfileField | None = None


class Performance(BaseModel):
    """One completed project.

    `year` is deliberately a year and not a date: the source records available to
    us do not carry a completion month, so a "최근 3년" boundary year cannot be
    resolved. Judgment treats those boundary rows as uncertain instead of
    silently including or excluding them.
    """

    id: str | None = None
    title: str = ""
    amount: float | None = None
    year: int | None = None
    client_type: str | None = None
    fields: list[str] = Field(default_factory=list)
    source: str | None = None
    evidence_status: EvidenceStatus = EVIDENCE_NONE


class Certification(BaseModel):
    """A licence, registration or certification.

    Licences and certifications share one list because a requirement sentence
    rarely distinguishes them cleanly; matching is done on the display name.
    """

    code: str | None = None
    label: str | None = None
    issued_year: int | None = None
    source: str | None = None
    evidence_status: EvidenceStatus = EVIDENCE_NONE


class StaffMember(BaseModel):
    """One employee. Industry-neutral on purpose: no engineer grade lives here.

    Software engineer grades exist only in software service contracts. Putting a
    grade field here would push that industry onto every company that signs up,
    so grades arrive through `app.ai.extensions` only when a notice asks.
    """

    id: str | None = None
    role: str | None = None
    career_years: float | None = None
    source: str | None = None
    evidence_status: EvidenceStatus = EVIDENCE_NONE


class ExtensionValue(BaseModel):
    """A notice-specific answer collected on demand. See `app.ai.extensions`."""

    value: Any = None
    label: str | None = None
    source: str | None = None
    evidence_status: EvidenceStatus = EVIDENCE_NONE


class CompanyProfileSnapshot(BaseModel):
    """Everything judgment is allowed to know about the bidding company.

    List sections default to None rather than to an empty list so that a Backend
    adapter which simply has not loaded a section cannot be mistaken for a
    company that has none.
    """

    profile_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    basic: ProfileBasic = Field(default_factory=ProfileBasic)
    performances: list[Performance] | None = None
    certifications: list[Certification] | None = None
    staff: list[StaffMember] | None = None
    fields: list[str] | None = None
    extensions: dict[str, ExtensionValue] = Field(default_factory=dict)


class ProfileView:
    """The read interface judgment rules are written against.

    Rules must not touch `CompanyProfileSnapshot` fields directly. Everything they
    need is exposed here, so a schema revision is absorbed by this class alone.
    """

    def __init__(self, snapshot: CompanyProfileSnapshot | None) -> None:
        self.snapshot = snapshot or CompanyProfileSnapshot()

    def __bool__(self) -> bool:
        """False when the profile carries no information at all."""
        return bool(
            self.snapshot.basic.model_dump(exclude_none=True)
            or self.snapshot.performances is not None
            or self.snapshot.certifications is not None
            or self.snapshot.staff is not None
            or self.snapshot.fields is not None
            or self.snapshot.extensions
        )

    def has(self, section: str) -> bool:
        """Did the profile say anything about this section, even "none"?"""
        if section in _LIST_SECTIONS:
            return getattr(self.snapshot, section) is not None
        if section == "extensions":
            return bool(self.snapshot.extensions)
        return getattr(self.snapshot.basic, section, None) is not None

    # ── basic ────────────────────────────────────────────────────────────
    def _basic(self, name: str) -> ProfileField | None:
        return getattr(self.snapshot.basic, name, None)

    def _value(self, name: str) -> Any:
        field = self._basic(name)
        return field.value if field else None

    def _label(self, name: str) -> Any:
        field = self._basic(name)
        if field is None:
            return None
        if field.label not in (None, "", []):
            return field.label
        return field.value

    @property
    def profile_id(self) -> str | None:
        return self.snapshot.profile_id

    @property
    def company_name(self) -> str:
        return str(self._value("company_name") or "")

    @property
    def region_code(self) -> str:
        return str(self._value("region") or "")

    @property
    def region_label(self) -> str:
        return str(self._label("region") or "")

    @property
    def company_size(self) -> str:
        """Canonical size value, or "" when the profile does not pin it down."""
        return normalize_company_size(self._value("company_size")) or ""

    @property
    def company_size_label(self) -> str:
        label = self._label("company_size")
        if label and str(label) not in _SIZE_ALIASES:
            return str(label)  # keep the wording the company chose
        return SIZE_LABELS.get(self.company_size, "") or (str(label) if label else "")

    @property
    def employee_count(self) -> int | None:
        value = self._value("employee_count")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def industry_codes(self) -> list[str]:
        return _as_list(self._value("industry_codes"))

    @property
    def industry_labels(self) -> list[str]:
        return _as_list(self._label("industry_codes"))

    # ── list sections ────────────────────────────────────────────────────
    @property
    def fields(self) -> list[str]:
        return list(self.snapshot.fields or [])

    @property
    def performances(self) -> list[Performance]:
        return list(self.snapshot.performances or [])

    @property
    def certifications(self) -> list[Certification]:
        return list(self.snapshot.certifications or [])

    @property
    def staff(self) -> list[StaffMember]:
        return list(self.snapshot.staff or [])

    def certification_labels(self) -> list[str]:
        """Names to match requirement text against, falling back to the code."""
        names = []
        for certification in self.certifications:
            name = (certification.label or certification.code or "").strip()
            if name:
                names.append(name)
        return names

    # ── notice-specific extensions ───────────────────────────────────────
    @property
    def extensions(self) -> dict[str, ExtensionValue]:
        return dict(self.snapshot.extensions)

    def has_extension(self, key: str) -> bool:
        entry = self.snapshot.extensions.get(key)
        return entry is not None and entry.value is not None

    def extension_value(self, key: str) -> Any:
        """The stored answer, or None. Never invent one that was not collected."""
        entry = self.snapshot.extensions.get(key)
        return entry.value if entry else None

    def extension_entry(self, key: str) -> ExtensionValue | None:
        return self.snapshot.extensions.get(key)


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def as_profile_view(profile: Any) -> ProfileView:
    """Accept whatever the caller has and hand back a ProfileView."""
    if isinstance(profile, ProfileView):
        return profile
    if isinstance(profile, CompanyProfileSnapshot):
        return ProfileView(profile)
    if profile is None:
        return ProfileView(None)
    return ProfileView(CompanyProfileSnapshot.model_validate(profile))
