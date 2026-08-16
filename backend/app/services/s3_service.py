import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def upload_file_to_s3(file_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> Optional[str]:
    """
    Upload file bytes to S3 compatible Object Storage (Cloudhost / MinIO / AWS S3).
    Returns the public URL of the uploaded object.
    """
    upload_driver = os.getenv("UPLOAD_DRIVER", "local").lower()
    if upload_driver != "s3":
        return None

    endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "https://is3.cloudhost.id")
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "onechitra")
    prefix = os.getenv("OBJECT_STORAGE_PREFIX", "upload")
    region = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")
    access_key = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "")
    secret_key = os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "")

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
