import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Protocol
from zoneinfo import ZoneInfo

import requests

from ..config import Settings
from ..models import NoticeDocument
from .document_extraction import extract_into_document


KST = ZoneInfo("Asia/Seoul")


class DocumentStorage(Protocol):
    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str: ...


class LocalDocumentStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str:
        del content_type
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("invalid document storage key")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.seek(0)
        with target.open("wb") as output:
            shutil.copyfileobj(source, output)
        return storage_key.replace("\\", "/")


class S3DocumentStorage:
    def __init__(self, bucket: str, region: str | None) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str:
        source.seek(0)
        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self.client.upload_fileobj(source, self.bucket, storage_key, ExtraArgs=extra_args)
        else:
            self.client.upload_fileobj(source, self.bucket, storage_key)
        return storage_key


def safe_storage_segment(value: str, fallback: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value.strip())
    value = value.strip("._")
    return value[:150] or fallback


class NoticeDocumentDownloader:
    def __init__(
        self,
        *,
        storage: DocumentStorage,
        storage_prefix: str,
        timeout_seconds: float,
        max_file_size_bytes: int,
        session: requests.Session | None = None,
    ) -> None:
        self.storage = storage
        self.storage_prefix = storage_prefix.strip("/")
        self.timeout_seconds = timeout_seconds
        self.max_file_size_bytes = max_file_size_bytes
        self.session = session or requests.Session()

    def download(
        self,
        document: NoticeDocument,
        *,
        notice_no: str,
        version_number: int,
        known_storage_by_hash: dict[str, str] | None = None,
    ) -> None:
        try:
            with self.session.get(
                document.url,
                stream=True,
                timeout=self.timeout_seconds,
                allow_redirects=True,
                headers={"User-Agent": "bid-change-validator/0.1"},
            ) as response:
                response.raise_for_status()
                declared_size = int(response.headers.get("Content-Length") or 0)
                if declared_size > self.max_file_size_bytes:
                    raise ValueError("file exceeds configured size limit")

                sha256 = hashlib.sha256()
                size = 0
                with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > self.max_file_size_bytes:
                            raise ValueError("file exceeds configured size limit")
                        sha256.update(chunk)
                        temp.write(chunk)

                    notice_segment = safe_storage_segment(notice_no, "unknown-notice")
                    name_segment = safe_storage_segment(document.name, f"document-{document.document_order}")
                    parts = [
                        notice_segment,
                        f"v{version_number:04d}",
                        f"{document.source_field}-{name_segment}",
                    ]
                    storage_key = "/".join(parts)
                    if self.storage_prefix:
                        storage_key = f"{self.storage_prefix}/{storage_key}"
                    digest = sha256.hexdigest()
                    existing_storage_key = (known_storage_by_hash or {}).get(digest)
                    if existing_storage_key is not None:
                        document.storage_key = existing_storage_key
                    else:
                        document.storage_key = self.storage.put(
                            storage_key,
                            temp,
                            response.headers.get("Content-Type"),
                        )
                        if known_storage_by_hash is not None:
                            known_storage_by_hash[digest] = document.storage_key
                    document.content_type = response.headers.get("Content-Type")
                    document.file_size_bytes = size
                    document.file_sha256 = digest
                    document.downloaded_at = datetime.now(KST)
                    document.download_status = "DOWNLOADED"
                    document.download_error = None
                    extract_into_document(document, temp)
        except (requests.RequestException, OSError, ValueError) as error:
            document.download_status = "FAILED"
            document.download_error = (
                f"파일 다운로드 실패 ({type(error).__name__})"
            )


def build_document_downloader(settings: Settings) -> NoticeDocumentDownloader:
    storage, prefix = build_document_storage(settings)
    return NoticeDocumentDownloader(
        storage=storage,
        storage_prefix=prefix,
        timeout_seconds=settings.document_download_timeout_seconds,
        max_file_size_bytes=settings.document_max_file_size_bytes,
    )


def build_document_storage(settings: Settings) -> tuple[DocumentStorage, str]:
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        storage: DocumentStorage = LocalDocumentStorage(settings.document_storage_path)
        prefix = ""
    elif backend == "S3":
        if not settings.document_s3_bucket:
            raise ValueError("DOCUMENT_S3_BUCKET is required when backend is S3")
        storage = S3DocumentStorage(settings.document_s3_bucket, settings.aws_region)
        prefix = settings.document_s3_prefix
    else:
        raise ValueError("DOCUMENT_STORAGE_BACKEND must be LOCAL or S3")
    return storage, prefix
