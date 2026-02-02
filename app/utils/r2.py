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
R2_URL = os.getenv("R2_URL")
R2_BUCKET = os.getenv("R2_BUCKET")


def _get_s3_client():
    if boto3 is None:
        raise RuntimeError("boto3 is required for r2 operations. Install boto3 in your environment.")

    if not (R2_ACCESS_KEY and R2_SECRET_KEY and R2_URL and R2_BUCKET):
        raise RuntimeError("R2 credentials (R2_ACCESS_KEY, R2_SECRET_KEY, R2_URL, R2_BUCKET) are not all set in environment")

    return boto3.client(
        "s3",
        endpoint_url=R2_URL,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
    )


def upload_file(key: str, data: bytes, content_type: Optional[str] = None) -> Tuple[str, str]:
    client = _get_s3_client()

    key = key.lstrip('/')

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    try:
        client.put_object(Bucket=R2_BUCKET, Key=key, Body=data, **extra_args)
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 upload failed: {e}")

    url = f"{R2_URL.rstrip('/')}/{R2_BUCKET}/{key}"
    return key, url


def get_file_bytes(key: str) -> bytes:
    client = _get_s3_client()
    key = key.lstrip('/')
    try:
        obj = client.get_object(Bucket=R2_BUCKET, Key=key)
        return obj["Body"].read()
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"R2 get object failed: {e}")
