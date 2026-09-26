import os
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError


# =========================================================
# STORAGE MODE
# =========================================================

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND")

if not STORAGE_BACKEND:
    STORAGE_BACKEND = (
        "s3"
        if os.getenv("VERCEL") == "1"
        else "local"
    )

STORAGE_BACKEND = STORAGE_BACKEND.lower()


# =========================================================
# LOCAL STORAGE
# =========================================================

LOCAL_UPLOAD_DIR = Path("uploads/products")

if STORAGE_BACKEND == "local":
    LOCAL_UPLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


# =========================================================
# AWS S3
# =========================================================

AWS_ACCESS_KEY_ID = os.getenv(
    "AWS_ACCESS_KEY_ID"
)

AWS_SECRET_ACCESS_KEY = os.getenv(
    "AWS_SECRET_ACCESS_KEY"
)

AWS_REGION = os.getenv(
    "AWS_REGION",
    "ap-south-1",
)

AWS_S3_BUCKET = os.getenv(
    "AWS_S3_BUCKET"
)

AWS_S3_PUBLIC_BASE_URL = os.getenv(
    "AWS_S3_PUBLIC_BASE_URL"
)


s3_client = None


if STORAGE_BACKEND == "s3":

    if not AWS_ACCESS_KEY_ID:
        raise RuntimeError(
            "AWS_ACCESS_KEY_ID is not configured"
        )

    if not AWS_SECRET_ACCESS_KEY:
        raise RuntimeError(
            "AWS_SECRET_ACCESS_KEY is not configured"
        )

    if not AWS_S3_BUCKET:
        raise RuntimeError(
            "AWS_S3_BUCKET is not configured"
        )

    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


# =========================================================
# UPLOAD IMAGE
# =========================================================

def upload_product_image(
    contents: bytes,
    filename: str,
    extension: str,
    content_type: str,
    base_url: str,
) -> str:

    final_filename = f"{Path(filename).stem}{extension}"

    # =====================================================
    # LOCAL
    # =====================================================

    if STORAGE_BACKEND == "local":

        file_path = (
            LOCAL_UPLOAD_DIR / final_filename
        )

        file_path.write_bytes(contents)

        return (
            f"{base_url.rstrip('/')}"
            f"/uploads/products/{final_filename}"
        )

    # =====================================================
    # S3
    # =====================================================

    object_key = (
        f"products/{final_filename}"
    )

    try:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=object_key,
            Body=contents,
            ContentType=content_type,
        )

    except (
        BotoCoreError,
        ClientError,
    ) as error:

        raise RuntimeError(
            f"Failed to upload image to S3: {error}"
        ) from error

    # Custom public URL / CloudFront URL
    if AWS_S3_PUBLIC_BASE_URL:

        return (
            f"{AWS_S3_PUBLIC_BASE_URL.rstrip('/')}"
            f"/{object_key}"
        )

    return (
        f"https://{AWS_S3_BUCKET}.s3."
        f"{AWS_REGION}.amazonaws.com/"
        f"{object_key}"
    )


# =========================================================
# DELETE IMAGE
# =========================================================

def delete_product_image(
    image_url: str,
) -> None:

    if not image_url:
        return

    # =====================================================
    # LOCAL
    # =====================================================

    if STORAGE_BACKEND == "local":

        parsed = urlparse(image_url)

        filename = Path(
            parsed.path
        ).name

        if not filename:
            return

        file_path = (
            LOCAL_UPLOAD_DIR / filename
        )

        if file_path.exists():
            file_path.unlink()

        return

    # =====================================================
    # S3
    # =====================================================

    parsed = urlparse(image_url)

    object_key = parsed.path.lstrip("/")

    if not object_key:
        return

    try:

        s3_client.delete_object(
            Bucket=AWS_S3_BUCKET,
            Key=object_key,
        )

    except (
        BotoCoreError,
        ClientError,
    ):
        # Database operation should not fail
        # only because old image cleanup failed.
        pass