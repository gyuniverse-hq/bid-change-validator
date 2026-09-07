"""AI integration package for Bid Change Validator.

The production boundary starts from backend-managed notice/proposal document blocks.
Low-level file parsing and storage stay in backend services; this package owns
semantic chunking, requirement extraction adapters, retrieval evidence contracts,
judgment adapters, and change/revalidation logic.

Judgment consumes a Backend-produced `CompanyProfileSnapshot`; this package never
imports the ORM, so the profile schema and the judgment rules stay separable.
"""

from .analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from .analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from .assist import AssistAnswer, answer_question, summarize_profile, summarize_state
from .contracts import Evidence, Judgment, QualificationRequirement
from .followup import (
    FollowUpResult,
    ProfileUpdate,
    apply_profile_update,
    parse_followup_answer,
)
from .judgment import judge_analysis_result, judge_requirement, judge_requirements
from .notice_requirements import build_notice_requirements, extract_notice_facts
from .profile import CompanyProfileSnapshot, ProfileView, as_profile_view
from .summary import NoticeSummary, narrate_report, summarize_notice

__all__ = [
    "QualificationRequirement",
    "Evidence",
    "Judgment",
    "AnalysisDiagnostic",
    "RequirementAnalysisResult",
    "QualificationDocumentInput",
    "QualificationAnalysisInput",
    "analyze_qualification_documents",
    "CompanyProfileSnapshot",
    "ProfileView",
    "as_profile_view",
    "judge_requirement",
    "judge_requirements",
    "judge_analysis_result",
    "FollowUpResult",
    "ProfileUpdate",
    "parse_followup_answer",
    "apply_profile_update",
    "extract_notice_facts",
    "build_notice_requirements",
    "NoticeSummary",
    "summarize_notice",
    "narrate_report",
    "AssistAnswer",
    "answer_question",
    "summarize_state",
    "summarize_profile",
]
