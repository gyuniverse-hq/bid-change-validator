"""Deterministic span-based quality measurement for qualification retrieval."""

from .fixtures import GoldenCase, GoldenDocument, load_cases, load_case_chunks
from .funnel import evaluate_case_funnel
from .scoring import score_case
from .spans import GoldenSpan

__all__ = [
    "GoldenCase",
    "GoldenDocument",
    "GoldenSpan",
    "evaluate_case_funnel",
    "load_case_chunks",
    "load_cases",
    "score_case",
]
