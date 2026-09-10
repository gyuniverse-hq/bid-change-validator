"""DB 없이 공고 첨부를 받아 텍스트를 뽑는 경로.

원래 이 패키지는 DB 연결 전 단계의 데모 전체(공고 조회 → 판정 → 리포트)를 담고
있었습니다. 지금은 `app/qualification_analysis.py` 이하 팀 파이프라인이 그 역할을
DB 위에서 하고 있어서, 겹치는 부분은 전부 걷어냈습니다.

남긴 것은 `documents.py` 하나입니다. 첨부를 URL로 직접 받아 캐시하고
`services.document_extraction.extract_document()`(DB를 쓰지 않는 순수 함수)로
텍스트·블록을 뽑습니다. DB 없이 실제 공고문으로 추출·검색 품질을 재려면 이 경로가
필요하고, 팀 파이프라인과 기능이 겹치지 않습니다.

걷어낸 것과 그 이유는 docs/llm-rag/01-branch-comparison.md 를 보십시오.
"""

from .documents import (
    CachedDocumentSource,
    FetchedDocument,
    G2BDocumentSource,
    NoticeDocumentSource,
    extract_hwpml,
    is_hwpml,
    merge_blocks,
    merged_text,
)

__all__ = [
    "NoticeDocumentSource",
    "G2BDocumentSource",
    "CachedDocumentSource",
    "FetchedDocument",
    "merge_blocks",
    "merged_text",
    "is_hwpml",
    "extract_hwpml",
]
