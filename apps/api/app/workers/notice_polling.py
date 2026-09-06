from __future__ import annotations

import logging
import signal
from datetime import datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from ..config import Settings, get_settings
from ..database import SessionLocal, engine
from ..models import NoticeCollectionRun
from ..schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from ..services.document_storage import build_document_downloader
from ..services.g2b import G2BClient
from ..services.notices import run_notice_sync


KST = ZoneInfo("Asia/Seoul")
WORKER_LOCK_KEY = 7_040_021_615
MAX_RECOVERY_WINDOW = timedelta(days=30)
logger = logging.getLogger("notice-polling")


def build_changed_notice_request(
    settings: Settings,
    *,
    business_type: BusinessType,
    now: datetime,
    last_completed_window_end: datetime | None,
) -> NoticeSyncRequest:
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    if last_completed_window_end is None:
        window_start = now - timedelta(minutes=settings.notice_poll_lookback_minutes)
    else:
        completed_at = last_completed_window_end.astimezone(KST)
        window_start = completed_at - timedelta(
            minutes=settings.notice_poll_overlap_minutes
        )

    window_start = max(window_start, now - MAX_RECOVERY_WINDOW)
    window_start = min(window_start, now)
    return NoticeSyncRequest(
        business_type=business_type,
        inquiry_type=NoticeInquiryType.CHANGED,
        window_started_at=window_start,
        window_ended_at=now,
        page_size=settings.notice_poll_page_size,
        max_pages=settings.notice_poll_max_pages,
    )


def _last_completed_window_end(business_type: BusinessType) -> datetime | None:
    with SessionLocal() as db:
        return db.scalar(
            select(NoticeCollectionRun.window_ended_at)
            .where(
                NoticeCollectionRun.business_type == business_type.value,
                NoticeCollectionRun.inquiry_type == NoticeInquiryType.CHANGED.value,
                NoticeCollectionRun.status == "COMPLETED",
            )
            .order_by(NoticeCollectionRun.window_ended_at.desc())
            .limit(1)
        )


def run_poll_cycle(settings: Settings, *, now: datetime | None = None) -> None:
    service_key = settings.decoded_g2b_service_key
    if service_key is None:
        raise RuntimeError("G2B_SERVICE_KEY is not configured")

    cycle_time = now or datetime.now(KST)
    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    downloader = build_document_downloader(settings)

    for business_type in settings.notice_poll_business_type_list:
        request = build_changed_notice_request(
            settings,
            business_type=business_type,
            now=cycle_time,
            last_completed_window_end=_last_completed_window_end(business_type),
        )
        try:
            with SessionLocal() as db:
                run = run_notice_sync(
                    db,
                    request=request,
                    client=client,
                    document_downloader=downloader,
                )
            logger.info(
                "poll completed business_type=%s fetched=%s created=%s versions=%s unchanged=%s",
                business_type.value,
                run.fetched_count,
                run.created_count,
                run.new_version_count,
                run.unchanged_count,
            )
        except Exception:
            logger.exception("poll failed business_type=%s", business_type.value)


def _run_cycle_with_lock(settings: Settings) -> bool:
    with engine.connect() as lock_connection:
        acquired = bool(
            lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK_KEY}
            )
        )
        if not acquired:
            logger.info("another notice polling worker owns the database lock")
            return False
        try:
            run_poll_cycle(settings)
            return True
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK_KEY}
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    if settings.decoded_g2b_service_key is None:
        raise SystemExit("G2B_SERVICE_KEY is required for notice polling")

    stopped = Event()

    def stop(_signum, _frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    logger.info(
        "worker started interval=%ss business_types=%s",
        settings.notice_poll_interval_seconds,
        ",".join(item.value for item in settings.notice_poll_business_type_list),
    )
    while not stopped.is_set():
        try:
            _run_cycle_with_lock(settings)
        except Exception:
            logger.exception("poll cycle failed")
        stopped.wait(settings.notice_poll_interval_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
