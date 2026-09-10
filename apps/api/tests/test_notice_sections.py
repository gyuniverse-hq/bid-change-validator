from apps.api.app.ai.notice_sections import (
    SECTION_TOPICS,
    build_body,
    select_topic_chunks,
    summarize_sections,
)


def _chunk(chunk_id: str, text: str) -> dict:
    return {"chunk_id": chunk_id, "clause_label": None, "text": text}


NOTICE = [
    _chunk("CHUNK-0001", "1. 사업 개요\n1.1 사업명: 통합플랫폼 구축 용역\n1.2 사업예산: 13억 5천만원"),
    _chunk("CHUNK-0002", "2. 입찰 참가자격\n2.1 소프트웨어사업자로 신고한 업체\n2.2 최근 3년 실적 5억원 이상"),
    _chunk("CHUNK-0003", "3. 과업 내용\n3.1 시스템 분석 및 설계\n3.2 산출물: 설계서, 시험결과서"),
    _chunk("CHUNK-0004", "4. 제출 서류\n사업자등록증 사본 1부, 법인등기부등본 1부를 제출한다."),
    _chunk("CHUNK-0005", "5. 계약 조건\n하자보수는 인수 후 3년간, 지체상금은 100분의 30을 한도로 한다."),
]


# ── 주제 선택 ────────────────────────────────────────────────────────────
def test_each_topic_picks_the_chunk_that_is_actually_about_it() -> None:
    picked = select_topic_chunks(NOTICE)

    assert picked["OVERVIEW"][0]["chunk_id"] == "CHUNK-0001"
    assert "CHUNK-0002" in [chunk["chunk_id"] for chunk in picked["QUALIFICATION"]]
    assert "CHUNK-0004" in [chunk["chunk_id"] for chunk in picked["SUBMISSION"]]
    assert "CHUNK-0005" in [chunk["chunk_id"] for chunk in picked["CONTRACT"]]


def test_a_topic_with_no_matching_text_is_left_out_entirely() -> None:
    # 평가 방법을 다루지 않는 공고에 평가 주제를 만들어내지 않는다.
    picked = select_topic_chunks([_chunk("CHUNK-0001", "1. 사업 개요\n사업명: 테스트 용역")])

    assert "OVERVIEW" in picked
    assert "EVALUATION" not in picked


def test_one_chunk_may_serve_two_topics() -> None:
    # 계약조건과 과업내용이 한 문단에 섞인 공고가 흔하다. 하나에만 배정하면
    # 다른 쪽 요약이 근거를 잃는다.
    chunks = [_chunk("CHUNK-0001", "과업 수행 중 하자가 발생하면 계약상대자가 보수한다.")]
    picked = select_topic_chunks(chunks)

    assert "SCOPE" in picked
    assert "CONTRACT" in picked


def test_a_topic_respects_its_character_budget() -> None:
    long_chunks = [_chunk(f"CHUNK-{i:04d}", "과업 " * 400) for i in range(10)]
    picked = select_topic_chunks(long_chunks, max_chars_per_topic=2_000)

    total = sum(len(chunk["text"]) for chunk in picked["SCOPE"])
    # 첫 청크 하나는 상한을 넘더라도 반드시 담는다 — 아니면 주제가 통째로 빈다.
    assert len(picked["SCOPE"]) < len(long_chunks)
    assert total <= 2_000 + len(long_chunks[0]["text"])


def test_the_body_keeps_document_order_within_a_topic() -> None:
    body = build_body(select_topic_chunks(NOTICE))

    assert "[주제 OVERVIEW · 사업 개요]" in body
    assert body.index("사업 개요") < body.index("계약 조건")


# ── 요약 생성 ────────────────────────────────────────────────────────────
def _extractor(payload: dict):
    calls: list[tuple[str, str, dict]] = []

    def extract(system_prompt: str, user_body: str, schema: dict) -> dict:
        calls.append((system_prompt, user_body, schema))
        return payload

    extract.calls = calls  # type: ignore[attr-defined]
    return extract


def test_sections_come_back_with_the_chunks_they_were_based_on() -> None:
    extractor = _extractor(
        {
            "sections": [
                {"topic": "OVERVIEW", "summary": "이 사업은 통합플랫폼을 구축하는 용역입니다."},
                {"topic": "CONTRACT", "summary": "하자보수는 인수 후 3년간입니다."},
            ]
        }
    )

    result = summarize_sections(NOTICE, structured_extract=extractor, title="테스트 공고")

    assert result.status == "OK"
    by_topic = result.by_topic()
    assert by_topic["OVERVIEW"].label == "사업 개요"
    # 근거 없이는 화면에 요약만 뜨고 담당자가 원문을 확인할 방법이 없다.
    assert by_topic["OVERVIEW"].chunk_ids
    assert "CHUNK-0005" in by_topic["CONTRACT"].chunk_ids
    assert "판정이 아니라 내용 설명" in extractor.calls[0][0]
    assert "테스트 공고" in extractor.calls[0][1]


def test_sections_are_ordered_the_way_a_notice_reads() -> None:
    extractor = _extractor(
        {
            "sections": [
                {"topic": "CONTRACT", "summary": "계약 조건입니다."},
                {"topic": "OVERVIEW", "summary": "사업 개요입니다."},
                {"topic": "QUALIFICATION", "summary": "참가자격입니다."},
            ]
        }
    )

    result = summarize_sections(NOTICE, structured_extract=extractor)

    assert [section.topic for section in result.sections] == [
        "OVERVIEW",
        "QUALIFICATION",
        "CONTRACT",
    ]


def test_a_summary_for_a_topic_we_never_sent_is_discarded() -> None:
    """스키마의 enum 을 보고 본 적 없는 주제를 채워 넣는 일이 있다 — 그건 지어낸 것이다."""
    chunks = [_chunk("CHUNK-0001", "1. 사업 개요\n사업명: 테스트 용역")]
    extractor = _extractor(
        {
            "sections": [
                {"topic": "OVERVIEW", "summary": "테스트 용역입니다."},
                {"topic": "EVALUATION", "summary": "정량평가 60점, 정성평가 40점입니다."},
            ]
        }
    )

    result = summarize_sections(chunks, structured_extract=extractor)

    assert [section.topic for section in result.sections] == ["OVERVIEW"]


def test_a_null_summary_is_dropped_rather_than_rendered_empty() -> None:
    extractor = _extractor(
        {
            "sections": [
                {"topic": "OVERVIEW", "summary": "사업 개요입니다."},
                {"topic": "CONTRACT", "summary": None},
            ]
        }
    )

    result = summarize_sections(NOTICE, structured_extract=extractor)

    assert [section.topic for section in result.sections] == ["OVERVIEW"]


# ── 실패를 조용히 넘기지 않는다 ──────────────────────────────────────────
def test_missing_source_or_extractor_is_stated_not_invented() -> None:
    assert summarize_sections([], structured_extract=_extractor({})).status == "NO_SOURCE"
    assert summarize_sections(NOTICE, structured_extract=None).status == "EXTRACTOR_UNAVAILABLE"


def test_an_extractor_failure_never_breaks_the_caller() -> None:
    def broken(system_prompt: str, user_body: str, schema: dict) -> dict:
        raise RuntimeError("model unavailable")

    result = summarize_sections(NOTICE, structured_extract=broken)

    assert result.status == "FAILED"
    assert "model unavailable" in result.notes
    assert result.available is False


def test_every_topic_has_a_label_and_keywords() -> None:
    for topic, (label, keywords) in SECTION_TOPICS.items():
        assert label, topic
        assert keywords, topic
