from io import BytesIO
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.app.database import SessionLocal
from apps.api.app.config import get_settings
from apps.api.app.main import app
from apps.api.app.models import BidNotice, BidNoticeVersion, NoticeDocument
from apps.api.app.routers import notices as notices_router
from apps.api.app.routers import preflight_cases as preflight_cases_router
from apps.api.app.schemas import BusinessType
from apps.api.app.services.document_storage import (
    LocalDocumentStorage,
    NoticeDocumentDownloader,
)
from apps.api.app.services.notices import save_notice_snapshot


client = TestClient(app)
KST = ZoneInfo("Asia/Seoul")


class FakeFileResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {
            "Content-Length": str(len(content)),
            "Content-Type": "application/x-hwp",
        }

    def __enter__(self) -> "FakeFileResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for position in range(0, len(self.content), chunk_size):
            yield self.content[position : position + chunk_size]


class FakeFileSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def get(self, *_args, **_kwargs) -> FakeFileResponse:
        self.calls += 1
        return FakeFileResponse(self.content)


def _hwpx_content() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(
            "Contents/section0.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <hs:sec xmlns:hs="urn:hancom:section" xmlns:hp="urn:hancom:paragraph">
              <hp:p><hp:run><hp:t>입찰 참가자격은 6억원 이상입니다.</hp:t></hp:run></hp:p>
              <hp:p><hp:run><hp:t>필수 제출서류를 확인하십시오.</hp:t></hp:run></hp:p>
            </hs:sec>""",
        )
    return output.getvalue()


def _item(notice_no: str, estimated_price: str = "123000000") -> dict:
    return {
        "bidNtceNo": notice_no,
        "bidNtceOrd": "00",
        "bidNtceNm": "테스트 정보시스템 구축",
        "ntceKindNm": "일반공고",
        "rgstTyNm": "나라장터",
        "reNtceYn": "N",
        "bidNtceDt": "2026-09-05 09:00:00",
        "chgDt": "2026-09-05 09:00:00",
        "bidBeginDt": "2026-09-06 10:00:00",
        "bidClseDt": "2026-09-10 10:00:00",
        "opengDt": "2026-09-10 11:00:00",
        "ntceInsttCd": "1234567",
        "ntceInsttNm": "테스트 공고기관",
        "dminsttCd": "7654321",
        "dminsttNm": "테스트 수요기관",
        "cntrctCnclsMthdNm": "제한경쟁",
        "asignBdgtAmt": "125000000",
        "presmptPrce": estimated_price,
        "bidNtceDtlUrl": "https://example.test/notices/1",
        "stdNtceDocUrl": "https://example.test/files/request.hwpx",
        "ntceSpecFileNm1": "제안요청서.hwpx",
        "ntceSpecDocUrl1": "https://example.test/files/request.hwpx",
    }


def test_notice_version_deduplication_file_download_and_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notice_no = f"TEST-{uuid4()}"
    file_content = _hwpx_content()
    file_session = FakeFileSession(file_content)
    downloader = NoticeDocumentDownloader(
        storage=LocalDocumentStorage(str(tmp_path)),
        storage_prefix="",
        timeout_seconds=1,
        max_file_size_bytes=1024,
        session=file_session,
    )
    test_settings = get_settings().model_copy(
        update={"document_storage_backend": "LOCAL", "document_storage_path": str(tmp_path)}
    )
    monkeypatch.setattr(notices_router, "get_settings", lambda: test_settings)
    monkeypatch.setattr(preflight_cases_router, "get_settings", lambda: test_settings)
    db = SessionLocal()
    notice_id = None
    try:
        result, notice, first_version = save_notice_snapshot(
            db,
            item=_item(notice_no),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 10, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        notice_id = notice.id
        assert result == "CREATED"
        assert first_version.version_number == 1
        assert file_session.calls == 1

        documents = db.scalars(
            select(NoticeDocument).where(
                NoticeDocument.notice_version_id == first_version.id
            )
        ).all()
        assert len(documents) == 2
        document = documents[0]
        assert document.download_status == "DOWNLOADED"
        assert document.file_size_bytes == len(file_content)
        assert document.file_sha256 is not None
        assert (tmp_path / document.storage_key).read_bytes() == file_content
        assert documents[0].storage_key == documents[1].storage_key
        assert documents[0].file_sha256 == documents[1].file_sha256
        assert all(document.extraction_status == "EXTRACTED" for document in documents)
        assert all(document.text_extractor == "HWPX_XML" for document in documents)
        assert "6억원 이상" in documents[0].extracted_text
        assert documents[0].extracted_blocks[0]["section_index"] == 0

        unchanged, _, same_version = save_notice_snapshot(
            db,
            item=_item(notice_no),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 11, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        assert unchanged == "UNCHANGED"
        assert same_version.id == first_version.id
        assert file_session.calls == 1

        changed, _, second_version = save_notice_snapshot(
            db,
            item=_item(notice_no, estimated_price="130000000"),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 12, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        assert changed == "NEW_VERSION"
        assert second_version.version_number == 2
        assert file_session.calls == 2
        assert db.scalar(
            select(func.count()).select_from(BidNoticeVersion).where(
                BidNoticeVersion.notice_id == notice_id
            )
        ) == 2

        list_response = client.get("/api/v1/notices", params={"q": notice_no})
        assert list_response.status_code == 200, list_response.text
        assert list_response.json()["items"][0]["current_version"] == 2

        detail_response = client.get(f"/api/v1/notices/{notice_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["latest"]["estimated_price"] == 130000000
        assert detail["latest"]["documents"][0]["download_status"] == "DOWNLOADED"
        extracted_document = detail["latest"]["documents"][0]
        assert extracted_document["viewer_type"] == "RHWP"
        assert extracted_document["preview_url"] is None
        source_response = client.get(extracted_document["render_source_url"])
        assert source_response.status_code == 200
        assert source_response.content == file_content
        assert source_response.headers["content-type"] == "application/hwp+zip"
        assert "content-disposition" not in source_response.headers
        text_response = client.get(
            f"/api/v1/notices/{notice_id}/versions/2/documents/"
            f"{extracted_document['id']}/text"
        )
        assert text_response.status_code == 200, text_response.text
        assert "필수 제출서류" in text_response.json()["text"]
        assert text_response.json()["blocks"][0]["location"].startswith("section 1")
        preview_response = client.get(
            f"/api/v1/notices/{notice_id}/versions/2/documents/"
            f"{extracted_document['id']}/preview"
        )
        assert preview_response.status_code == 409
        assert (
            preview_response.json()["error"]["code"]
            == "DOCUMENT_PREVIEW_CONVERSION_REQUIRED"
        )

        case_response = client.post(
            "/api/v1/preflight-cases",
            json={
                "notice_id": str(notice_id),
                "baseline_version_number": 1,
                "current_version_number": 2,
                "title": "변경공고 제안서 검토",
            },
        )
        assert case_response.status_code == 201, case_response.text
        case = case_response.json()
        case_id = case["id"]
        assert case["baseline_version_number"] == 1
        assert case["current_version_number"] == 2
        assert case["status"] == "DRAFT"

        upload_response = client.post(
            f"/api/v1/preflight-cases/{case_id}/documents",
            data={"role": "PROPOSAL"},
            files={
                "file": (
                    "사업제안서.hwpx",
                    file_content,
                    "application/hwp+zip",
                )
            },
        )
        assert upload_response.status_code == 201, upload_response.text
        proposal = upload_response.json()
        assert proposal["viewer_type"] == "RHWP"
        assert proposal["extraction_status"] == "EXTRACTED"
        assert proposal["extracted_char_count"] > 0

        duplicate_response = client.post(
            f"/api/v1/preflight-cases/{case_id}/documents",
            data={"role": "PROPOSAL"},
            files={"file": ("복사본.hwpx", file_content, "application/hwp+zip")},
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["code"] == "DUPLICATE_PROPOSAL_DOCUMENT"

        fetched_case = client.get(f"/api/v1/preflight-cases/{case_id}")
        assert fetched_case.status_code == 200
        assert fetched_case.json()["status"] == "READY"
        assert len(fetched_case.json()["documents"]) == 1

        proposal_source = client.get(proposal["render_source_url"])
        assert proposal_source.status_code == 200
        assert proposal_source.content == file_content
        proposal_text = client.get(proposal["text_url"])
        assert proposal_text.status_code == 200
        assert "입찰 참가자격" in proposal_text.json()["text"]

        versions_response = client.get(f"/api/v1/notices/{notice_id}/versions")
        assert versions_response.status_code == 200
        assert [version["version_number"] for version in versions_response.json()] == [2, 1]
    finally:
        if notice_id is not None:
            persisted = db.get(BidNotice, notice_id)
            if persisted is not None:
                db.delete(persisted)
                db.commit()
        db.close()
