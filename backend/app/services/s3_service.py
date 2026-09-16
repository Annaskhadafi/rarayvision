import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from app.core.config import BASE_DIR
except ImportError:
    from backend.app.core.config import BASE_DIR


def get_s3_credentials():
    """Retrieve S3 / Object storage credentials from environment variables."""
    endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT") or os.getenv("S3_ENDPOINT_URL") or "https://is3.cloudhost.id"
    bucket = os.getenv("OBJECT_STORAGE_BUCKET") or os.getenv("S3_BUCKET_NAME") or "onechitra"
    prefix = os.getenv("OBJECT_STORAGE_PREFIX") or os.getenv("S3_PREFIX") or "upload"
    region = os.getenv("OBJECT_STORAGE_REGION") or os.getenv("S3_REGION_NAME") or "us-east-1"
    access_key = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID") or ""
    secret_key = os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or ""
    return endpoint, bucket, prefix, region, access_key, secret_key


def upload_file_to_s3(file_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> Optional[str]:
    """
    Upload file bytes to S3 compatible Object Storage (Cloudhost / MinIO / AWS S3).
    Returns the public URL of the uploaded object.
    """
    upload_driver = os.getenv("UPLOAD_DRIVER", "local").lower()
    endpoint, bucket, prefix, region, access_key, secret_key = get_s3_credentials()

    if not access_key or not secret_key:
        logger.warning("[S3] Object storage credentials missing in environment.")
        return None

    try:
        import boto3
        from botocore.client import Config
        import requests

        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                connect_timeout=3.0,
                read_timeout=5.0
            )
        )

        s3_key = f"{prefix}/{filename}" if prefix else filename
        
        # Use presigned URL upload for Cloudhost S3 proxy compatibility
        url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={'Bucket': bucket, 'Key': s3_key, 'ContentType': content_type},
            ExpiresIn=3600
        )

        headers = {'Content-Length': str(len(file_bytes)), 'Content-Type': content_type}
        resp = requests.put(url, data=file_bytes, headers=headers, timeout=10)
        
        if resp.status_code in (200, 201):
            public_url = f"{endpoint.rstrip('/')}/{bucket}/{s3_key}"
            logger.info(f"[S3] Uploaded file to Cloudhost S3: {public_url}")
            return public_url
        else:
            logger.error(f"[S3] Upload failed with status {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"[S3] Cloudhost upload error: {e}")
        return None


def get_presigned_download_url(filename: str, expires_in: int = 3600) -> Optional[str]:
    """
    Generates an authorized presigned GET URL for downloading/viewing private S3 Cloudhost objects.
    """
    endpoint, bucket, prefix, region, access_key, secret_key = get_s3_credentials()

    if not access_key or not secret_key:
        return None

    try:
        import boto3
        from botocore.client import Config

        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4"
            )
        )

        clean_name = filename.lstrip("/")
        if prefix and clean_name.startswith(f"{prefix}/"):
            s3_key = clean_name
        elif prefix:
            s3_key = f"{prefix}/{clean_name}"
        else:
            s3_key = clean_name

        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=expires_in
        )
    except Exception as e:
        logger.error(f"[S3] Failed to generate presigned GET url for {filename}: {e}")
        return None


class S3Service:
    """Class wrapper for Object Storage with seamless local fallback."""
    def __init__(self):
        self.local_s3_dir = os.path.join(BASE_DIR, "uploads", "s3_storage")
        os.makedirs(self.local_s3_dir, exist_ok=True)

    def upload_bytes(self, data: bytes, s3_key: str, content_type: str = "image/jpeg") -> str:
        s3_key = s3_key.lstrip("/")
        res = upload_file_to_s3(data, s3_key, content_type=content_type)
        if res:
            return res

        # Local storage fallback
        local_path = os.path.join(self.local_s3_dir, s3_key.replace("/", os.sep))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return f"/api/v1/uploads/s3_storage/{s3_key}"

    def upload_file(self, local_path: str, s3_key: str, content_type: Optional[str] = None) -> str:
        s3_key = s3_key.lstrip("/")
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                data = f.read()
            return self.upload_bytes(data, s3_key, content_type=content_type or "application/octet-stream")
        return f"/api/v1/uploads/s3_storage/{s3_key}"

    def get_url(self, s3_key: str) -> str:
        s3_key = s3_key.lstrip("/")
        endpoint, bucket, prefix, _, access_key, _ = get_s3_credentials()
        if access_key and endpoint:
            return f"{endpoint.rstrip('/')}/{bucket}/{s3_key}"
        return f"/api/v1/uploads/s3_storage/{s3_key}"


# Singleton instance
s3_service = S3Service()
