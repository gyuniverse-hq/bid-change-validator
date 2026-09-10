from types import SimpleNamespace

import pytest

from apps.api.app.document_rag import (
    DocumentChunkMetadata,
    DocumentChunkRecord,
    VersionFaissIndex,
    build_notice_version_records,
)


class FakeEmbeddings:
    @staticmethod
    def _vector(text: str) -> list[float]:
        if "실적" in text:
            return [1.0, 0.0, 0.0]
        if "지역" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _record(version_id: str, chunk_id: str, text: str) -> DocumentChunkRecord:
    return DocumentChunkRecord(
        text=text,
        metadata=DocumentChunkMetadata(
            notice_id="notice-1",
            notice_version_id=version_id,
            version_number=1,
            document_id="doc-1",
            document_name="공고문.pdf",
            document_role="standard_notice",
            chunk_id=chunk_id,
        ),
    )


def test_build_notice_version_records_preserves_document_scope_and_locator():
    document = SimpleNamespace(
        id="doc-1",
        document_order=0,
        name="공고문.pdf",
        source_field="standard_notice",
        extraction_status="EXTRACTED",
        file_sha256="file-sha",
        extracted_text_sha256="text-sha",
        extracted_blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "제3조 참가자격\n최근 3년간 1억원 이상의 수행실적을 보유한 업체",
            }
        ],
    )
    version = SimpleNamespace(
        id="version-1",
        notice_id="notice-1",
        version_number=1,
        documents=[document],
    )

    records = build_notice_version_records(version)

    assert len(records) == 1
    metadata = records[0].metadata
    assert metadata.notice_version_id == "version-1"
    assert metadata.document_id == "doc-1"
    assert metadata.chunk_id == "doc-1:CHUNK-0000"
    assert metadata.page == 3
    assert metadata.block_start == 0
    assert metadata.block_end == 0
    assert metadata.source_locations == ["p.3"]
    assert metadata.source_sha256 == "file-sha"
    assert metadata.extracted_text_sha256 == "text-sha"


def test_version_faiss_index_round_trip_and_search(tmp_path):
    embeddings = FakeEmbeddings()
    records = [
        _record("version-1", "chunk-performance", "수행실적 1억원 이상"),
        _record("version-1", "chunk-region", "서울특별시 소재 업체"),
    ]
    index = VersionFaissIndex.build(records, embeddings=embeddings, embedding_model="fake")
    target = tmp_path / "version-1"

    index.save(target)
    loaded = VersionFaissIndex.load(
        target,
        embeddings=embeddings,
        expected_notice_version_id="version-1",
    )
    hits = loaded.search("실적 조건 알려줘", k=2)

    assert hits[0].metadata.chunk_id == "chunk-performance"
    assert hits[0].score == pytest.approx(1.0)


def test_version_faiss_index_rejects_mixed_versions():
    with pytest.raises(ValueError, match="multiple notice versions"):
        VersionFaissIndex.build(
            [
                _record("version-1", "chunk-1", "실적"),
                _record("version-2", "chunk-2", "지역"),
            ],
            embeddings=FakeEmbeddings(),
        )


def test_loaded_index_rejects_wrong_expected_version(tmp_path):
    embeddings = FakeEmbeddings()
    index = VersionFaissIndex.build(
        [_record("version-1", "chunk-1", "실적")],
        embeddings=embeddings,
        embedding_model="fake",
    )
    target = tmp_path / "version-1"
    index.save(target)

    with pytest.raises(ValueError, match="expected notice version"):
        VersionFaissIndex.load(
            target,
            embeddings=embeddings,
            expected_notice_version_id="version-2",
        )
