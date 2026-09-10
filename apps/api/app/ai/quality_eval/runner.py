"""Offline runner using Core public functions, without a parallel extractor."""

from ..qualification.extraction.analysis_pipeline import analyze_qualification_documents
from ..qualification.extraction.backend_blocks import canonical_source_blocks
from ..qualification.extraction.chunking import chunk_source_blocks
from ..qualification.extraction.requirement_extraction import build_extraction_body, select_eligibility_chunks
from .scoring import score_case


def evaluate_case(case, *, structured_extract=None):
    chunks = []
    for doc in case.analysis_input.documents:
        blocks = canonical_source_blocks(document_id=doc.document_id,
                                        blocks=doc.extracted_blocks,
                                        file_sha256=doc.file_sha256,
                                        text_sha256=doc.extracted_text_sha256)
        for chunk in chunk_source_blocks(blocks):
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
    selected = select_eligibility_chunks(chunks)
    result = None
    calls = 0
    if structured_extract is not None:
        def observed(system, body, schema):
            nonlocal calls
            if body != build_extraction_body(selected):
                raise ValueError("evaluation context differs from Core context")
            calls += 1
            return structured_extract(system, body, schema)
        result = analyze_qualification_documents(case.analysis_input, structured_extract=observed)
        if result.target_chunk_ids != [c["chunk_id"] for c in selected]:
            raise ValueError("evaluation selection differs from Core selection")
        if chunks and not calls:
            raise ValueError("Core did not receive the expected evaluation context")
    report = score_case(case.spans, chunks, selected, result)
    return {"case_id": case.spec.case_id, "notice_no": case.spec.notice_no,
            "notice_version_id": case.spec.notice_version_id,
            "provenance": case.spec.provenance, "extractor_calls": calls if structured_extract is not None else None,
            **report, "analysis": None if result is None else result.model_dump(mode="json")}
