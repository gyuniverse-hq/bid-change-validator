"""AI integration package for Bid Change Validator.

The production boundary starts from backend-managed notice/proposal document blocks.
Low-level file parsing and storage stay in backend services; this package owns
semantic chunking, requirement extraction adapters, retrieval evidence contracts,
judgment adapters, and change/revalidation logic.
"""

from .analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from .contracts import Evidence, Judgment, QualificationRequirement

__all__ = [
    "QualificationRequirement",
    "Evidence",
    "Judgment",
    "AnalysisDiagnostic",
    "RequirementAnalysisResult",
]
