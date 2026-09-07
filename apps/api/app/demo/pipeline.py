"""One notice plus one company profile in; a verdict with its grounds out.

This is the composition root the demo runs on. It holds no rules of its own — it
arranges the pieces that already exist:

    NoticeSource        공고 원본 (나라장터 API)
      → extract_notice_facts       사업 정보·가격 (표시용)
      → build_notice_requirements  API 필드 → 자격요건
      → judge_requirements         적/부 판정 (코드, LLM 미개입)
      → summarize_notice           공고 내용 요약 (LLM, 서술 전용)
      → IndustryCatalog            업종코드 → 명칭·근거법규

The overall verdict is deliberately three-valued. "부적격" and "판단할 정보가 없음"
are different answers, and collapsing them would tell a company it cannot bid when
the truth is that nobody has filled in its profile yet.

When the database arrives this file becomes `services/analysis.py` with the same
shape: swap the connectors, keep the flow.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..ai.backend_blocks import canonical_source_blocks
from ..ai.chunking import chunk_source_blocks
from ..ai.clause_review import ClauseFinding, detect_patterns, detect_standard_diff
from ..ai.contracts import Judgment, QualificationRequirement
from ..ai.notice_requirements import (
    NoticeFacts,
    build_notice_requirements,
    extract_notice_facts,
)
from ..ai.profile import CompanyProfileSnapshot, as_profile_view
from ..ai.requirement_extraction import StructuredExtractor
from ..ai.summary import Narrator, NoticeSummary, summarize_notice
from .connectors import IndustryCatalog, NoticeSource, PriceBoard, ProfileStore


OverallVerdict = Literal["ELIGIBLE", "INELIGIBLE", "NEEDS_INFO"]

VERDICT_LABELS: dict[str, str] = {
    "ELIGIBLE": "적격",
    "INELIGIBLE": "부적격",
    "NEEDS_INFO": "확인 필요",
}


class IndustryNote(BaseModel):
    """An industry code resolved to its name and the statute behind it."""

    code: str | None = None
    name: str | None = None
    classification: str | None = None
    legal_basis: str | None = None
    source: str  # "NOTICE" | "COMPANY"


class EligibilityReport(BaseModel):
    """Everything the demo shows for one notice/company pair."""

    notice_no: str
    notice: NoticeFacts
    summary: NoticeSummary
    profile_id: str | None = None
    company_name: str | None = None
    is_demo_profile: bool = False
    scenario: str | None = None

    verdict: OverallVerdict
    requirements: list[QualificationRequirement] = Field(default_factory=list)
    judgments: list[Judgment] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    industries: list[IndustryNote] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    clause_findings: list[ClauseFinding] = Field(default_factory=list)

    def flagged_clauses(self) -> list[ClauseFinding]:
        return [item for item in self.clause_findings if item.verdict == "NEEDS_REVIEW"]

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS[self.verdict]

    def counts(self) -> dict[str, int]:
        tally = {"SATISFIED": 0, "UNSATISFIED": 0, "UNKNOWN": 0}
        for judgment in self.judgments:
            tally[judgment.status] += 1
        return tally


def decide_overall(judgments: list[Judgment]) -> OverallVerdict:
    """Roll per-requirement judgments into one answer.

    A single failed requirement disqualifies, so UNSATISFIED wins outright.
    Otherwise anything still unknown holds the answer open — reporting 적격 while
    a requirement is unanswered would be claiming more than was checked.
    """
    if any(judgment.status == "UNSATISFIED" for judgment in judgments):
        return "INELIGIBLE"
    if any(judgment.status == "UNKNOWN" for judgment in judgments):
        return "NEEDS_INFO"
    return "ELIGIBLE" if judgments else "NEEDS_INFO"


def _industry_notes(
    item: dict[str, Any],
    profile: CompanyProfileSnapshot | None,
    catalog: IndustryCatalog | None,
) -> list[IndustryNote]:
    if catalog is None:
        return []

    notes: list[IndustryNote] = []
    seen: set[tuple[str, str | None]] = set()

    def add(code_or_name: str, source: str) -> None:
        entry = getattr(catalog, "describe", None)
        found = entry(code_or_name) if entry else catalog.by_code(code_or_name)
        key = (source, found.code if found else code_or_name)
        if key in seen:
            return
        seen.add(key)
        if found is None:
            notes.append(IndustryNote(code=code_or_name, source=source))
            return
        notes.append(
            IndustryNote(
                code=found.code,
                name=found.name,
                classification=found.classification,
                legal_basis=found.legal_basis,
                source=source,
            )
        )

    view = as_profile_view(profile)
    for code in view.industry_codes:
        add(code, "COMPANY")
    for label in view.industry_labels:
        add(label, "COMPANY")

    permitted = item.get("permsnIndstrytyList") or item.get("lcnsLmtNm")
    if permitted:
        import re

        for _name, code in re.findall(r"([^,\[\]/]+)/(\d+)", str(permitted)):
            add(code, "NOTICE")

    return notes


def blocks_from_text(text: str) -> list[dict[str, Any]]:
    """Turn plain notice text into the block shape Backend extraction produces.

    Backend hands the AI package blocks with source locators. A pasted or
    downloaded text file has no page or section, so each non-empty line becomes
    one paragraph block. That keeps the same chunker and the same evidence
    locators working, instead of adding a second path for loose text.
    """
    blocks: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        blocks.append(
            {
                "block_index": len(blocks),
                "page": None,
                "section_index": None,
                "paragraph_index": index,
                "text": line,
            }
        )
    return blocks


def chunks_from_text(text: str, *, document_id: str = "DEMO-RFP") -> list[dict[str, Any]]:
    canonical = canonical_source_blocks(
        document_id=document_id, blocks=blocks_from_text(text)
    )
    chunks = chunk_source_blocks(canonical)
    return [{**chunk, "chunk_id": f"CHUNK-{index:04d}"} for index, chunk in enumerate(chunks)]


def review_notice(
    notice_no: str,
    *,
    notice_source: NoticeSource,
    profile: CompanyProfileSnapshot | None = None,
    profile_id: str | None = None,
    profile_store: ProfileStore | None = None,
    industry_catalog: IndustryCatalog | None = None,
    price_board: PriceBoard | None = None,
    narrate: Narrator | None = None,
    rfp_text: str | None = None,
    standard_clauses: list[dict[str, Any]] | None = None,
    structured_extract: StructuredExtractor | None = None,
    use_embedding_fallback: bool = False,
) -> EligibilityReport | None:
    """Review one notice against one company. Returns None when the notice is unknown.

    Requirements come from two places and are judged together:

    - the notice API record, which is free but only carries what the endpoint
      exposes (often a restriction flag with no value behind it);
    - the notice document, when `rfp_text` is supplied, which is where the actual
      participation conditions live.

    Clause review runs on the document too, and needs no model at all.
    """
    item = notice_source.fetch(notice_no)
    if item is None:
        return None

    if profile is None and profile_id and profile_store is not None:
        profile = profile_store.get(profile_id)

    facts = extract_notice_facts(item)
    if price_board is not None:
        facts.price = price_board.price_of(item)

    notice_version_id = f"{facts.notice_no or notice_no}-{facts.notice_order or '000'}"
    requirements, diagnostics = build_notice_requirements(
        item, notice_version_id=notice_version_id
    )

    clause_findings: list[ClauseFinding] = []
    if rfp_text:
        chunks = chunks_from_text(rfp_text)

        if standard_clauses:
            # Tier two costs model calls, so it is opt-in and only reached for
            # rules tier one could not settle (see clause_review.standard_diff).
            fallback = None
            if use_embedding_fallback and structured_extract is not None:
                from ..ai.clause_review import make_embedding_fallback

                fallback = make_embedding_fallback(structured_extract)

            clause_findings.extend(
                detect_standard_diff(
                    chunks,
                    standard_clauses,
                    notice_version_id=notice_version_id,
                    embedding_fallback=fallback,
                )
            )
        clause_findings.extend(
            detect_patterns(chunks, notice_version_id=notice_version_id)
        )

        if structured_extract is not None:
            from ..ai.analysis_pipeline import (
                QualificationAnalysisInput,
                QualificationDocumentInput,
                analyze_qualification_documents,
            )

            analysis = analyze_qualification_documents(
                QualificationAnalysisInput(
                    notice_id=facts.notice_no or notice_no,
                    notice_version_id=notice_version_id,
                    documents=[
                        QualificationDocumentInput(
                            document_id="DEMO-RFP",
                            extracted_blocks=blocks_from_text(rfp_text),
                        )
                    ],
                ),
                structured_extract=structured_extract,
            )
            requirements = requirements + analysis.requirements
            diagnostics = diagnostics + [
                item.model_dump() for item in analysis.diagnostics
            ]

    from ..ai.judgment import judge_requirements

    judgments = judge_requirements(
        requirements,
        profile,
        preflight_case_id=f"demo-{notice_version_id}",
    )

    # The summary reads the notice document when we have its text; with only the
    # API record there is no prose to summarize, and saying so beats inventing it.
    summary = summarize_notice(rfp_text or "", title=facts.title, narrate=narrate)

    raw_profile: dict[str, Any] = {}
    if profile_id and profile_store is not None and hasattr(profile_store, "raw"):
        raw_profile = profile_store.raw(profile_id) or {}

    view = as_profile_view(profile)
    return EligibilityReport(
        notice_no=facts.notice_no or notice_no,
        notice=facts,
        summary=summary,
        profile_id=profile_id or view.profile_id,
        company_name=view.company_name or None,
        is_demo_profile=bool(raw_profile.get("_demo")),
        scenario=raw_profile.get("_시나리오") or raw_profile.get("_scenario"),
        verdict=decide_overall(judgments),
        requirements=requirements,
        judgments=judgments,
        diagnostics=diagnostics,
        industries=_industry_notes(item, profile, industry_catalog),
        open_questions=[
            judgment.follow_up_question
            for judgment in judgments
            if judgment.follow_up_question
        ],
        clause_findings=clause_findings,
    )
