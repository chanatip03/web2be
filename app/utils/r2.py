import os
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception


R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")   # ใช้สำหรับ boto3
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")  # ใช้สร้างลิงก์
R2_BUCKET = os.getenv("R2_BUCKET")
R2_BUCKET = os.getenv("R2_BUCKET")


def _get_s3_client():
    if boto3 is None:
        raise RuntimeError("boto3 is required for r2 operations. Install boto3 in your environment.")

    if not (R2_ACCESS_KEY and R2_SECRET_KEY and R2_ENDPOINT and R2_BUCKET):
        raise RuntimeError("R2 credentials (R2_ACCESS_KEY, R2_SECRET_KEY, R2_ENDPOINT, R2_BUCKET) are not all set in environment")

    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
    )


def upload_file(key: str, data: bytes, content_type: Optional[str] = None) -> Tuple[str, str]:
    client = _get_s3_client()
    key = key.lstrip('/')

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    client.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=data,
        **extra_args
    )

    # สร้าง public url
    url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}"

    return key, url


def get_file_bytes(key: str) -> bytes:
    client = _get_s3_client()
    key = key.lstrip('/')
    try:
        obj = client.get_object(Bucket=R2_BUCKET, Key=key)
        return obj["Body"].read()
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 get object failed: {e}")

def download_file_to_disk(key: str, dest_path: str) -> None:
    """Download a file from R2 directly to disk. This is safer for large files than reading into memory."""
    client = _get_s3_client()
    key = key.lstrip('/')
    try:
        import os
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        # Using download_file handles multipart downloads and retries automatically
        client.download_file(R2_BUCKET, key, dest_path)
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 download file failed: {e}")
    
def delete_file(url: str) -> bool:
    client = _get_s3_client()
    
    key = url.replace(R2_PUBLIC_URL.rstrip('/') + "/", "")
    try:
        client.delete_object(
            Bucket=R2_BUCKET,
            Key=key
        )
        return True
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 delete object failed: {e}")
