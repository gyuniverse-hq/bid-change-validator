import hashlib
import json
from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import (
    BidNotice,
    BidNoticeVersion,
    NoticeCollectionRun,
    NoticeDocument,
    NoticeRelation,
)
from ..schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from .g2b import G2BClient
from .document_storage import NoticeDocumentDownloader
from .document_extraction import copy_extraction
from .notice_facts import upsert_g2b_notice_facts


KST = ZoneInfo("Asia/Seoul")
SaveResult = Literal["CREATED", "NEW_VERSION", "UNCHANGED"]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _required_text(item: dict[str, Any], field: str) -> str:
    value = _text(item.get(field))
    if value is None:
        raise ValueError(f"G2B item is missing {field}")
    return value


def _datetime(value: Any) -> datetime | None:
    normalized = _text(value)
    if normalized is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(normalized, pattern).replace(tzinfo=KST)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


def _decimal(value: Any) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return Decimal(normalized.replace(",", ""))
    except InvalidOperation:
        return None


def _payload_hash(item: dict[str, Any]) -> str:
    canonical = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _documents(item: dict[str, Any]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    standard_url = _text(item.get("stdNtceDocUrl"))
    if standard_url:
        documents.append(
            {
                "document_order": 0,
                "name": "표준공고문",
                "url": standard_url,
                "source_field": "stdNtceDocUrl",
            }
        )
    for order in range(1, 11):
        url_field = f"ntceSpecDocUrl{order}"
        url = _text(item.get(url_field))
        if not url:
            continue
        documents.append(
            {
                "document_order": order,
                "name": _text(item.get(f"ntceSpecFileNm{order}")) or f"첨부파일 {order}",
                "url": url,
                "source_field": url_field,
            }
        )
    return documents


def _resolve_pending_notice_relations(
    db: Session,
    *,
    collected_notice: BidNotice,
    resolved_at: datetime,
) -> None:
    """Resolve relations that referenced a notice before it was collected."""

    db.execute(
        update(NoticeRelation)
        .where(
            NoticeRelation.previous_notice_id.is_(None),
            NoticeRelation.previous_bid_notice_no == collected_notice.bid_notice_no,
            NoticeRelation.notice_id != collected_notice.id,
        )
        .values(previous_notice_id=collected_notice.id, updated_at=resolved_at)
    )


def _upsert_api_notice_relation(
    db: Session,
    *,
    notice: BidNotice,
    item: dict[str, Any],
    updated_at: datetime,
) -> None:
    """Persist the G2B direct previous-notice reference when one is provided."""

    previous_bid_notice_no = _text(item.get("befBidBbancNo"))
    if previous_bid_notice_no is None:
        return

    previous_notice = db.scalar(
        select(BidNotice).where(BidNotice.bid_notice_no == previous_bid_notice_no)
    )
    previous_notice_id = (
        previous_notice.id
        if previous_notice is not None and previous_notice.id != notice.id
        else None
    )

    relation = db.get(NoticeRelation, notice.id)
    if relation is None:
        db.add(
            NoticeRelation(
                notice_id=notice.id,
                previous_notice_id=previous_notice_id,
                previous_bid_notice_no=previous_bid_notice_no,
                match_method="API_FIELD",
                match_confidence="CONFIRMED",
                updated_at=updated_at,
            )
        )
        return

    relation.previous_notice_id = previous_notice_id
    relation.previous_bid_notice_no = previous_bid_notice_no
    relation.match_method = "API_FIELD"
    relation.match_confidence = "CONFIRMED"
    relation.updated_at = updated_at


def save_notice_snapshot(
    db: Session,
    *,
    item: dict[str, Any],
    business_type: BusinessType,
    source_endpoint: str,
    collected_at: datetime | None = None,
    document_downloader: NoticeDocumentDownloader | None = None,
) -> tuple[SaveResult, BidNotice, BidNoticeVersion]:
    collected_at = collected_at or datetime.now(KST)
    notice_no = _required_text(item, "bidNtceNo")
    title = _required_text(item, "bidNtceNm")
    payload_hash = _payload_hash(item)

    notice = db.scalar(
        select(BidNotice)
        .where(BidNotice.bid_notice_no == notice_no)
        .with_for_update()
    )
    if notice is None:
        notice = BidNotice(
            bid_notice_no=notice_no,
            title=title,
            business_type=business_type.value,
            notice_kind=_text(item.get("ntceKindNm")),
            announcing_institution_code=_text(item.get("ntceInsttCd")),
            announcing_institution_name=_text(item.get("ntceInsttNm")),
            demanding_institution_code=_text(item.get("dminsttCd")),
            demanding_institution_name=_text(item.get("dminsttNm")),
            first_seen_at=collected_at,
            last_seen_at=collected_at,
        )
        db.add(notice)
        db.flush()
        version_number = 1
        result: SaveResult = "CREATED"
    else:
        existing = db.scalar(
            select(BidNoticeVersion).where(
                BidNoticeVersion.notice_id == notice.id,
                BidNoticeVersion.payload_hash == payload_hash,
            )
        )
        notice.last_seen_at = collected_at
        if existing is not None:
            _resolve_pending_notice_relations(
                db,
                collected_notice=notice,
                resolved_at=collected_at,
            )
            _upsert_api_notice_relation(
                db,
                notice=notice,
                item=item,
                updated_at=collected_at,
            )
            upsert_g2b_notice_facts(
                db,
                notice_version_id=existing.id,
                item=item,
                updated_at=collected_at,
            )
            db.flush()
            return "UNCHANGED", notice, existing

        db.execute(
            update(BidNoticeVersion)
            .where(
                BidNoticeVersion.notice_id == notice.id,
                BidNoticeVersion.is_current.is_(True),
            )
            .values(is_current=False)
        )
        latest_number = db.scalar(
            select(func.max(BidNoticeVersion.version_number)).where(
                BidNoticeVersion.notice_id == notice.id
            )
        ) or 0
        version_number = latest_number + 1
        result = "NEW_VERSION"

    _resolve_pending_notice_relations(
        db,
        collected_notice=notice,
        resolved_at=collected_at,
    )
    _upsert_api_notice_relation(
        db,
        notice=notice,
        item=item,
        updated_at=collected_at,
    )

    notice.title = title
    notice.business_type = business_type.value
    notice.notice_kind = _text(item.get("ntceKindNm"))
    notice.announcing_institution_code = _text(item.get("ntceInsttCd"))
    notice.announcing_institution_name = _text(item.get("ntceInsttNm"))
    notice.demanding_institution_code = _text(item.get("dminsttCd"))
    notice.demanding_institution_name = _text(item.get("dminsttNm"))

    version = BidNoticeVersion(
        notice_id=notice.id,
        version_number=version_number,
        bid_notice_order=_text(item.get("bidNtceOrd")) or "00",
        is_current=True,
        notice_kind=_text(item.get("ntceKindNm")),
        registration_type=_text(item.get("rgstTyNm")),
        is_reannouncement=(_text(item.get("reNtceYn")) or "N").upper() == "Y",
        posted_at=_datetime(item.get("bidNtceDt")),
        changed_at=_datetime(item.get("chgDt")),
        bid_started_at=_datetime(item.get("bidBeginDt")),
        bid_closed_at=_datetime(item.get("bidClseDt")),
        opened_at=_datetime(item.get("opengDt")),
        allocated_budget=_decimal(item.get("asignBdgtAmt")),
        estimated_price=_decimal(item.get("presmptPrce")),
        contract_method=_text(item.get("cntrctCnclsMthdNm")),
        change_reason=_text(item.get("chgNtceRsn")),
        detail_url=_text(item.get("bidNtceDtlUrl")) or _text(item.get("bidNtceUrl")),
        source_endpoint=source_endpoint,
        payload_hash=payload_hash,
        raw_json=item,
        collected_at=collected_at,
    )
    db.add(version)
    db.flush()
    upsert_g2b_notice_facts(
        db,
        notice_version_id=version.id,
        item=item,
        updated_at=collected_at,
    )
    downloaded_by_url: dict[str, NoticeDocument] = {}
    known_storage_by_hash: dict[str, str] = {}
    for document_values in _documents(item):
        document = NoticeDocument(notice_version_id=version.id, **document_values)
        db.add(document)
        db.flush()
        if document_downloader is not None:
            same_url_document = downloaded_by_url.get(document.url)
            if same_url_document is not None:
                document.download_status = same_url_document.download_status
                document.storage_key = same_url_document.storage_key
                document.content_type = same_url_document.content_type
                document.file_size_bytes = same_url_document.file_size_bytes
                document.file_sha256 = same_url_document.file_sha256
                document.downloaded_at = same_url_document.downloaded_at
                document.download_error = same_url_document.download_error
                copy_extraction(same_url_document, document)
            else:
                document_downloader.download(
                    document,
                    notice_no=notice.bid_notice_no,
                    version_number=version.version_number,
                    known_storage_by_hash=known_storage_by_hash,
                )
                downloaded_by_url[document.url] = document
    db.flush()
    return result, notice, version


def run_notice_sync(
    db: Session,
    *,
    request: NoticeSyncRequest,
    client: G2BClient,
    document_downloader: NoticeDocumentDownloader | None = None,
) -> NoticeCollectionRun:
    run = NoticeCollectionRun(
        business_type=request.business_type.value,
        inquiry_type=request.inquiry_type.value,
        window_started_at=request.window_started_at,
        window_ended_at=request.window_ended_at,
        status="RUNNING",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        pending_previous_numbers: deque[str] = deque()
        queued_previous_numbers: set[str] = set()

        def queue_previous_notice(item: dict[str, Any]) -> None:
            previous_notice_no = _text(item.get("befBidBbancNo"))
            if (
                previous_notice_no is not None
                and previous_notice_no not in queued_previous_numbers
            ):
                queued_previous_numbers.add(previous_notice_no)
                pending_previous_numbers.append(previous_notice_no)

        def count_result(result: SaveResult) -> None:
            run.fetched_count += 1
            if result == "CREATED":
                run.created_count += 1
            elif result == "NEW_VERSION":
                run.new_version_count += 1
            else:
                run.unchanged_count += 1

        page_number = 1
        while page_number <= request.max_pages:
            page = client.fetch_page(
                business_type=request.business_type,
                inquiry_type=request.inquiry_type,
                page_number=page_number,
                page_size=request.page_size,
                window_started_at=request.window_started_at,
                window_ended_at=request.window_ended_at,
                bid_notice_no=request.bid_notice_no,
            )
            run.api_calls += 1
            for item in page.items:
                result, _, _ = save_notice_snapshot(
                    db,
                    item=item,
                    business_type=request.business_type,
                    source_endpoint=page.endpoint,
                    document_downloader=document_downloader,
                )
                count_result(result)
                queue_previous_notice(item)
            db.commit()
            if not page.items or page_number * request.page_size >= page.total_count:
                break
            page_number += 1

        # A reannouncement points to a different notice number. Fetch the direct
        # predecessor immediately so the relation is usable without waiting for
        # that older notice to appear in a later collection window. If the
        # predecessor is itself a reannouncement, follow the same API field as a
        # bounded chain.
        resolved_chain_numbers: set[str] = set()
        while pending_previous_numbers and len(resolved_chain_numbers) < 25:
            previous_notice_no = pending_previous_numbers.popleft()
            if previous_notice_no in resolved_chain_numbers:
                continue
            resolved_chain_numbers.add(previous_notice_no)
            if db.scalar(
                select(BidNotice.id).where(
                    BidNotice.bid_notice_no == previous_notice_no
                )
            ) is not None:
                continue

            previous_page = client.fetch_page(
                business_type=request.business_type,
                inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                page_number=1,
                page_size=100,
                bid_notice_no=previous_notice_no,
            )
            run.api_calls += 1
            for previous_item in previous_page.items:
                if _text(previous_item.get("bidNtceNo")) != previous_notice_no:
                    continue
                result, _, _ = save_notice_snapshot(
                    db,
                    item=previous_item,
                    business_type=request.business_type,
                    source_endpoint=previous_page.endpoint,
                    document_downloader=document_downloader,
                )
                count_result(result)
                queue_previous_notice(previous_item)
            db.commit()

        run.status = "COMPLETED"
        run.completed_at = datetime.now(KST)
        db.commit()
        db.refresh(run)
        return run
    except Exception as error:
        db.rollback()
        run = db.get(NoticeCollectionRun, run.id)
        if run is not None:
            run.status = "FAILED"
            run.error_message = str(error)[:2000]
            run.completed_at = datetime.now(KST)
            db.commit()
        raise
