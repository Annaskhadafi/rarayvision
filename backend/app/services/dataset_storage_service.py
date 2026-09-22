import logging
from typing import BinaryIO, Dict

logger = logging.getLogger(__name__)


class DatasetStorageError(RuntimeError):
    pass


class DatasetStorageService:
    """S3-compatible client kept separate from the existing app storage."""

    def __init__(self, config: Dict[str, str]):
        self.config = config
        if not config.get("endpoint_url") or not config.get("bucket"):
            raise DatasetStorageError("S3 dataset belum dikonfigurasi.")
        if not config.get("access_key_id") or not config.get("secret_access_key"):
            raise DatasetStorageError("Access key dan secret key S3 dataset wajib diisi.")

    def _client(self):
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:
            raise DatasetStorageError("Library boto3 belum tersedia di backend.") from exc

        return boto3.client(
            "s3",
            endpoint_url=self.config["endpoint_url"],
            aws_access_key_id=self.config["access_key_id"],
            aws_secret_access_key=self.config["secret_access_key"],
            region_name=self.config.get("region") or "us-east-1",
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    def test_connection(self):
        self._client().head_bucket(Bucket=self.config["bucket"])

    def upload_fileobj(self, fileobj: BinaryIO, key: str, content_type: str, content_length: int = 0):
        """Upload through a presigned PUT; Cloudhost's S3 proxy rejects some direct boto3 uploads."""
        try:
            import requests

            client = self._client()
            url = client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.config["bucket"], "Key": key, "ContentType": content_type},
                ExpiresIn=3600,
            )
            fileobj.seek(0)
            response = requests.put(
                url,
                data=fileobj,
                headers={"Content-Type": content_type, "Content-Length": str(max(0, content_length))},
                timeout=(10, 120),
            )
            if response.status_code not in (200, 201):
                detail = (response.text or "").strip()[:500]
                raise DatasetStorageError(f"S3 PUT gagal ({response.status_code}){': ' + detail if detail else '.'}")
        except DatasetStorageError:
            raise
        except Exception as exc:
            raise DatasetStorageError(f"S3 PUT gagal: {exc}") from exc

    def copy_object(self, source_key: str, target_key: str):
        self._client().copy_object(
            Bucket=self.config["bucket"],
            CopySource={"Bucket": self.config["bucket"], "Key": source_key},
            Key=target_key,
        )

    def delete_key(self, key: str):
        self._client().delete_object(Bucket=self.config["bucket"], Key=key)

    def get_object(self, key: str):
        return self._client().get_object(Bucket=self.config["bucket"], Key=key)
