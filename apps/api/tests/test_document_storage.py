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
