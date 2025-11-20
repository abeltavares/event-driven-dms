import logging

import aioboto3
from botocore.exceptions import ClientError

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SignatureStorage:
    """Async S3 storage for signatures."""

    def __init__(self):
        self.session = aioboto3.Session(
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        self.endpoint_url = f"http://{settings.minio_endpoint}"

    def _get_client(self):
        return self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name="us-east-1",
            use_ssl=settings.minio_secure,
        )

    async def ensure_bucket(self):
        """Create bucket if it doesn't exist."""
        async with self._get_client() as s3:
            try:
                await s3.head_bucket(Bucket="signatures")
            except ClientError:
                await s3.create_bucket(Bucket="signatures")
                logger.info("Created bucket: signatures")

    async def upload_signature(self, signature_id: str, data: bytes) -> str:
        """Upload signature image to S3."""
        object_name = f"{signature_id}/signature.png"

        async with self._get_client() as s3:
            await s3.put_object(
                Bucket="signatures", Key=object_name, Body=data, ContentType="image/png"
            )

        logger.info(f"Uploaded signature: {object_name}")
        return object_name


storage = SignatureStorage()
