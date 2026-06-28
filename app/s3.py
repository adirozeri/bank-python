"""S3 helpers — presigned URLs for serving objects to the UI.

A presigned URL is a time-limited, signed link that lets the *browser* fetch a
private S3 object directly, without the object being public and without the
browser ever seeing AWS credentials. The backend (which holds the creds)
generates the link; the UI just renders it with `st.image(url)`.

boto3.client("s3") uses the standard credential chain: locally it reads
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION from the
environment (loaded from .env in app/main.py), and on EC2 it would use the
instance's IAM role.
"""

import boto3

# Hardcoded for now (this is a boto3 practice feature). Fill in your real bucket
# and object key. A follow-up could move these to config / make the key a param.
BUCKET = "adir-learning-bucket-2026"
IMAGE_KEY = "Screenshot from 2026-06-28 13-32-58.png"
EXPIRES_IN = 3600  # seconds the presigned URL stays valid


def generate_image_url(key: str = IMAGE_KEY, expires_in: int = EXPIRES_IN) -> str:
    """Return a presigned GET URL for an image object in the bucket."""
    client = boto3.client("s3")  # region/creds from env or EC2 IAM role
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
