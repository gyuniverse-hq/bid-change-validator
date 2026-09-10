from apps.api.app.scripts.goldenset_span_proposer import propose_from_text


def test_proposer_surfaces_candidates_without_auto_labeling_positive() -> None:
    proposals = propose_from_text(
        notice_no="N1",
        document_id="DOC1",
        document_name="입찰공고서.hwpx",
        text="입찰참가자격은 정보통신공사업 업종코드 0036 등록 업체로 제한한다.",
    )

    assert proposals
    assert proposals[0].suggested_role == "NOTICE"
    assert proposals[0].review_hint == "REVIEW"
    assert "참가자격" in proposals[0].keywords
    assert "업종코드" in proposals[0].quote


def test_proposer_marks_penalty_wording_only_as_a_review_hint() -> None:
    proposals = propose_from_text(
        notice_no="N1",
        document_id="DOC2",
        document_name="제안요청서.pdf",
        text="보안정보를 누출하면 입찰참가자격 제한 등 제재를 받을 수 있다.",
    )

    assert proposals[0].suggested_role == "RFP"
    assert proposals[0].review_hint == "LIKELY_TRAP"
