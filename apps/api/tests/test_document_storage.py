from io import BytesIO
from unittest.mock import patch

from app.services.document_storage import S3DocumentStorage, build_s3_client


def test_s3_client_uses_compatible_endpoint() -> None:
    with patch("boto3.client") as client:
        build_s3_client(
            region="ap-osaka-1",
            endpoint_url="https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com/",
        )

    client.assert_called_once_with(
        "s3",
        region_name="ap-osaka-1",
        endpoint_url="https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
    )


def test_s3_storage_passes_endpoint_to_client() -> None:
    with patch("boto3.client") as client:
        S3DocumentStorage(
            "bidcheck-notice-documents",
            "ap-osaka-1",
            "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
        )

    client.assert_called_once_with(
        "s3",
        region_name="ap-osaka-1",
        endpoint_url="https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
    )


def test_s3_storage_uses_put_object_with_known_length_body() -> None:
    with patch("boto3.client") as client_factory:
        client = client_factory.return_value
        storage = S3DocumentStorage(
            "bucket",
            "ap-osaka-1",
            "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
        )
        storage.put("docs/a.pdf", BytesIO(b"payload"), "application/pdf")

    client.put_object.assert_called_once_with(
        Bucket="bucket",
        Key="docs/a.pdf",
        Body=b"payload",
        ContentType="application/pdf",
    )
