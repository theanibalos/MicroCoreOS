"""
S3 Storage Tool — Reference Implementation for Object Storage in MicroCoreOS
=============================================================================

This is the REFERENCE IMPLEMENTATION for object-storage tools. Any replacement
(Google Cloud Storage, Azure Blob, local filesystem, ...) MUST follow this
contract and register under the same injection name: "s3".

PUBLIC CONTRACT (what plugins use):
────────────────────────────────────────────────────────────────────────────────
    key = await s3.upload_bytes("path/file.png", data, content_type="image/png")
    key = await s3.upload_fileobj("path/file.png", fileobj)       # streams
    data = await s3.download_bytes("path/file.png")
    url  = await s3.get_presigned_url("path/file.png", expires_in=3600)
    ok   = await s3.delete_object("path/file.png")
    objs = await s3.list_objects(prefix="path/")
    All methods accept bucket=None → falls back to AWS_S3_DEFAULT_BUCKET.

REPLACEMENT STANDARD (e.g. GCS or Azure Blob — plugins unaffected):
────────────────────────────────────────────────────────────────────────────────
    1. name = "s3" (the injection name is the contract, not the vendor).
    2. ALL methods are async — object storage is always network I/O.
    3. setup() NEVER raises: external infra may be down at boot. Log a warning,
       mark yourself unavailable, retry on first call.
    4. Raise S3UnavailableError (subclass of ToolUnavailableError) when the
       backend is unreachable → ToolProxy marks the tool DEAD immediately.
    5. Preserve the private-bucket + presigned-URL pattern: get_presigned_url()
       must return a time-limited URL a browser can use directly.
    6. Honor the size-limit env vars (AWS_S3_SIZE_LIMIT_ENABLED, max bytes).
"""

import os
import asyncio
from typing import Optional, Any
from botocore.client import Config
from core.base_tool import BaseTool, ToolUnavailableError


class S3Error(Exception):
    """Generic S3 operation error."""
    pass


class S3UnavailableError(S3Error, ToolUnavailableError):
    """S3 is not reachable.

    Inherits ToolUnavailableError so ToolProxy marks the tool DEAD immediately
    (infrastructure failure), unlike plain S3Error (likely business error).
    """
    pass


class S3FileSizeError(S3Error):
    """File exceeds the allowed size limit."""
    pass


class S3Tool(BaseTool):
    """
    AWS S3 Tool for MicroCoreOS.

    External / eventually available — setup() never raises.
    Compatible with LocalStack and MinIO via AWS_S3_ENDPOINT_URL.
    """

    @property
    def name(self) -> str:
        return "s3"

    def __init__(self) -> None:
        self._access_key    = os.getenv("AWS_ACCESS_KEY_ID")
        self._secret_key    = os.getenv("AWS_SECRET_ACCESS_KEY")
        self._region        = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._endpoint_url  = os.getenv("AWS_S3_ENDPOINT_URL") or None
        self._default_bucket = os.getenv("AWS_S3_DEFAULT_BUCKET") or None
        self._verify_ssl    = os.getenv("AWS_S3_VERIFY_SSL", "true").lower() == "true"

        # Size limit config
        self._size_limit_enabled = os.getenv("AWS_S3_SIZE_LIMIT_ENABLED", "true").lower() == "true"
        self._default_max_bytes  = int(os.getenv("AWS_S3_MAX_FILE_SIZE_MB", "10")) * 1024 * 1024

        self._client    = None
        self._available = False

    async def setup(self) -> None:
        try:
            import aioboto3
            self._session = aioboto3.Session(
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
            )
            await asyncio.wait_for(self._ping(), timeout=5)
            self._available = True
            print(f"[S3Tool] Connected (SSL Verify: {self._verify_ssl}).")
        except Exception as e:
            self._available = False
            print(f"[S3Tool] ⚠️  Not available at startup: {e}. Will retry on first call.")

    async def _ping(self) -> None:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, verify=self._verify_ssl) as s3:
            await s3.list_buckets()

    async def _get_client(self):
        if not self._available:
            await self._try_reconnect()
        if not self._available or not hasattr(self, "_session"):
            raise S3UnavailableError("S3 is not available or session not initialized.")
        
        config = None
        if self._endpoint_url:
            # Force path-style addressing for local providers like MinIO/LocalStack
            config = Config(
                s3={'addressing_style': 'path'},
                signature_version='s3v4'
            )
            
        return self._session.client(
            "s3", 
            endpoint_url=self._endpoint_url, 
            config=config, 
            verify=self._verify_ssl
        )

    async def _try_reconnect(self) -> None:
        try:
            await asyncio.wait_for(self._ping(), timeout=5)
            self._available = True
        except Exception:
            self._available = False

    def _resolve_bucket(self, bucket: Optional[str]) -> str:
        resolved = bucket or self._default_bucket
        if not resolved:
            raise S3Error("No bucket specified and AWS_S3_DEFAULT_BUCKET is not set.")
        return resolved

    def _check_size(self, size_bytes: int, max_size_bytes: Optional[int]) -> None:
        if not self._size_limit_enabled:
            return
        limit = max_size_bytes if max_size_bytes is not None else self._default_max_bytes
        if size_bytes > limit:
            limit_mb = limit / (1024 * 1024)
            actual_mb = size_bytes / (1024 * 1024)
            raise S3FileSizeError(
                f"File size {actual_mb:.2f} MB exceeds the limit of {limit_mb:.2f} MB."
            )

    # ─── PUBLIC API ───────────────────────────────────────

    async def upload_fileobj(
        self,
        key: str,
        fileobj: Any,
        bucket: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
        max_size_bytes: Optional[int] = None,
    ) -> str:
        """
        Upload a file-like object (e.g. FastAPI UploadFile).
        Streams data to S3 without loading everything into memory.
        """
        resolved_bucket = self._resolve_bucket(bucket)

        # 1. Attempt to validate size before streaming
        size = None
        if hasattr(fileobj, "size"): # FastAPI UploadFile has .size
            size = fileobj.size
        elif hasattr(fileobj, "seek") and hasattr(fileobj, "tell"):
            curr = fileobj.tell()
            fileobj.seek(0, 2)
            size = fileobj.tell()
            fileobj.seek(curr)

        if size is not None:
            self._check_size(size, max_size_bytes)

        # 2. Prepare ExtraArgs
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata

        async with await self._get_client() as s3:
            await s3.upload_fileobj(fileobj, resolved_bucket, key, ExtraArgs=extra_args or None)

        return key

    async def upload_file(
        self,
        key: str,
        file_path: str,
        bucket: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
        max_size_bytes: Optional[int] = None,
    ) -> str:
        """Upload a file from disk. Returns the S3 key."""
        resolved_bucket = self._resolve_bucket(bucket)
        file_size = os.path.getsize(file_path)
        self._check_size(file_size, max_size_bytes)

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata

        async with await self._get_client() as s3:
            await s3.upload_file(file_path, resolved_bucket, key, ExtraArgs=extra_args or None)

        return key

    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        bucket: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
        max_size_bytes: Optional[int] = None,
    ) -> str:
        """Upload bytes from memory. Returns the S3 key."""
        resolved_bucket = self._resolve_bucket(bucket)
        self._check_size(len(data), max_size_bytes)

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata

        async with await self._get_client() as s3:
            await s3.put_object(Bucket=resolved_bucket, Key=key, Body=data, **extra_args)

        return key

    async def download_file(
        self,
        key: str,
        destination_path: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Download an object to disk. Returns True on success."""
        resolved_bucket = self._resolve_bucket(bucket)
        async with await self._get_client() as s3:
            await s3.download_file(resolved_bucket, key, destination_path)
        return True

    async def download_bytes(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bytes:
        """Download an object into memory. Returns bytes."""
        resolved_bucket = self._resolve_bucket(bucket)
        async with await self._get_client() as s3:
            response = await s3.get_object(Bucket=resolved_bucket, Key=key)
            return await response["Body"].read()

    async def get_presigned_url(
        self,
        key: str,
        bucket: Optional[str] = None,
        expires_in: int = 3600,
        operation: str = "get",
    ) -> str:
        """
        Generate a presigned URL for private object access.
        operation: 'get' (download) or 'put' (upload).
        expires_in: seconds until expiry (default: 1 hour).
        """
        resolved_bucket = self._resolve_bucket(bucket)
        client_method = "get_object" if operation == "get" else "put_object"
        async with await self._get_client() as s3:
            url = await s3.generate_presigned_url(
                ClientMethod=client_method,
                Params={"Bucket": resolved_bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url

    async def delete_object(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Delete an object. Returns True on success."""
        resolved_bucket = self._resolve_bucket(bucket)
        async with await self._get_client() as s3:
            await s3.delete_object(Bucket=resolved_bucket, Key=key)
        return True

    async def list_objects(
        self,
        prefix: str = "",
        bucket: Optional[str] = None,
        max_keys: int = 1000,
    ) -> list[dict]:
        """
        List objects under a prefix.
        Returns list of {key, size, last_modified, etag}.
        """
        resolved_bucket = self._resolve_bucket(bucket)
        async with await self._get_client() as s3:
            response = await s3.list_objects_v2(
                Bucket=resolved_bucket,
                Prefix=prefix,
                MaxKeys=max_keys,
            )
        return [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "etag": obj["ETag"].strip('"'),
            }
            for obj in response.get("Contents", [])
        ]

    async def object_exists(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Check whether an object exists without downloading it."""
        resolved_bucket = self._resolve_bucket(bucket)
        try:
            async with await self._get_client() as s3:
                await s3.head_object(Bucket=resolved_bucket, Key=key)
            return True
        except Exception as e:
            if "404" in str(e) or "NoSuchKey" in str(e) or "Not Found" in str(e):
                return False
            raise

    async def copy_object(
        self,
        src_key: str,
        dst_key: str,
        src_bucket: Optional[str] = None,
        dst_bucket: Optional[str] = None,
    ) -> bool:
        """Copy an object between keys or buckets."""
        resolved_src = self._resolve_bucket(src_bucket)
        resolved_dst = self._resolve_bucket(dst_bucket)
        async with await self._get_client() as s3:
            await s3.copy_object(
                CopySource={"Bucket": resolved_src, "Key": src_key},
                Bucket=resolved_dst,
                Key=dst_key,
            )
        return True

    async def get_object_metadata(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> dict:
        """
        Returns object metadata: {size, content_type, last_modified, etag, metadata}.
        """
        resolved_bucket = self._resolve_bucket(bucket)
        async with await self._get_client() as s3:
            response = await s3.head_object(Bucket=resolved_bucket, Key=key)
        return {
            "size": response.get("ContentLength"),
            "content_type": response.get("ContentType"),
            "last_modified": response["LastModified"].isoformat() if response.get("LastModified") else None,
            "etag": response.get("ETag", "").strip('"'),
            "metadata": response.get("Metadata", {}),
        }

    async def health_check(self) -> bool:
        """Verify S3 connectivity by listing buckets."""
        try:
            await self._ping()
            self._available = True
            return True
        except Exception:
            self._available = False
            return False

    async def shutdown(self) -> None:
        self._available = False

    def get_interface_description(self) -> str:
        return """
        S3 Storage Tool (s3):
        - PURPOSE: AWS S3 object storage. Private bucket + presigned URLs pattern.
          Compatible with LocalStack and MinIO via AWS_S3_ENDPOINT_URL.
          External tool — setup() never raises; methods fail gracefully if unavailable.
        - SIZE LIMITS:
            Controlled by env vars (AWS_S3_SIZE_LIMIT_ENABLED, AWS_S3_MAX_FILE_SIZE_MB).
            Override per call with max_size_bytes=N. Raises S3FileSizeError if exceeded.
            If size limit is disabled globally, max_size_bytes is also ignored.
        - All methods accept an optional bucket= param. If omitted, uses AWS_S3_DEFAULT_BUCKET.
        - CAPABILITIES:
            - await upload_fileobj(key, fileobj, bucket?, content_type?, metadata?) -> str:
                Upload a file-like object (e.g. FastAPI UploadFile). Streams to S3.
            - await upload_file(key, file_path, bucket?, content_type?, metadata?, max_size_bytes?) -> str:
                Upload a file from disk. Returns the key.
            - await upload_bytes(key, data: bytes, bucket?, content_type?, metadata?, max_size_bytes?) -> str:
                Upload bytes from memory. Returns the key.
            - await download_file(key, destination_path, bucket?) -> bool:
                Download an object to a local path.
            - await download_bytes(key, bucket?) -> bytes:
                Download an object into memory.
            - await get_presigned_url(key, bucket?, expires_in=3600, operation='get'|'put') -> str:
                Generate a temporary signed URL. Use for serving private media to clients.
            - await delete_object(key, bucket?) -> bool:
                Delete an object.
            - await list_objects(prefix='', bucket?, max_keys=1000) -> list[dict]:
                List objects. Each dict: {key, size, last_modified, etag}.
            - await object_exists(key, bucket?) -> bool:
                Check existence without downloading.
            - await copy_object(src_key, dst_key, src_bucket?, dst_bucket?) -> bool:
                Copy between keys or buckets.
            - await get_object_metadata(key, bucket?) -> dict:
                Returns {size, content_type, last_modified, etag, metadata}.
            - await health_check() -> bool:
                Verify S3 connectivity.
        - EXCEPTIONS: S3Error, S3UnavailableError, S3FileSizeError.
        """
