"""Runnable demo: a real notice, a fictional company, a grounded verdict.

The database schema is not delivered yet, so this package stands in for the
Backend seam. Every data source is a protocol in `connectors`, with a working
implementation over the live API and the collected master codes; the pipeline
composes them with `app.ai` and nothing else.

Entry points:

    scripts/run_eligibility_demo.py     CLI
    apps.api.app.demo.api:app           FastAPI (separate app; main.py untouched)

Company profiles used here are fictional and marked `_demo`. Do not present a
verdict produced against them as a statement about any real company.
"""

from .connectors import (
    ChainedNoticeSource,
    CsvIndustryCatalog,
    FileProfileStore,
    FixtureNoticeSource,
    G2BNoticeSource,
    IndustryCatalog,
    NoticePriceBoard,
    NoticeSource,
    ProfileStore,
)
from .pipeline import EligibilityReport, decide_overall, review_notice
from .report import render_report_text

__all__ = [
    "NoticeSource",
    "ChainedNoticeSource",
    "G2BNoticeSource",
    "FixtureNoticeSource",
    "ProfileStore",
    "FileProfileStore",
    "IndustryCatalog",
    "CsvIndustryCatalog",
    "NoticePriceBoard",
    "EligibilityReport",
    "review_notice",
    "decide_overall",
    "render_report_text",
]
