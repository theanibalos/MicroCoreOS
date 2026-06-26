"""
S3 object-storage contract parity suite (Issue 22 pattern).

Every tool that acts as "s3" MUST pass this battery — it is the executable
version of the contract defined in extras/available_tools/s3/s3_tool.py
(the reference implementation / gold standard).

Skips itself if no S3-compatible server is reachable. Start RustFS with:

    docker compose -f dev_infra/docker-compose.yml up -d rustfs

Future alternative implementations (Google Cloud Storage, Azure Blob,
local filesystem ...) must pass this exact suite, wired up via their own
fixture variant below.
"""

import io
import socket
import uuid
import pytest
from botocore.client import Config

from extras.available_tools.s3.s3_tool import S3Tool, S3FileSizeError

pytestmark = pytest.mark.anyio

_BUCKET = "parity-test"
_ENDPOINT = "http://localhost:9000"
_S3_CONFIG = Config(s3={"addressing_style": "path"}, signature_version="s3v4")

_SKIP_MSG = (
    "RustFS not available — "
    "docker compose -f dev_infra/docker-compose.yml up -d rustfs"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def minio_available():
    """Check MinIO reachability once per module — avoids 18 × 5 s timeouts."""
    try:
        s = socket.create_connection(("localhost", 9000), timeout=1)
        s.close()
        return True
    except OSError:
        return False


@pytest.fixture
async def s3(minio_available, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "minioadmin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", _ENDPOINT)
    monkeypatch.setenv("AWS_S3_DEFAULT_BUCKET", _BUCKET)
    monkeypatch.setenv("AWS_S3_VERIFY_SSL", "false")
    monkeypatch.setenv("AWS_S3_SIZE_LIMIT_ENABLED", "false")

    if not minio_available:
        pytest.skip(_SKIP_MSG)

    tool = S3Tool()
    await tool.setup()
    if not tool._available:
        pytest.skip(_SKIP_MSG)

    async with tool._session.client(
        "s3", endpoint_url=_ENDPOINT, config=_S3_CONFIG, verify=False
    ) as admin:
        try:
            await admin.create_bucket(Bucket=_BUCKET)
        except Exception:
            pass  # bucket already exists — that is fine

    yield tool

    # Wipe all objects written by this test so runs stay hermetic.
    async with tool._session.client(
        "s3", endpoint_url=_ENDPOINT, config=_S3_CONFIG, verify=False
    ) as admin:
        response = await admin.list_objects_v2(Bucket=_BUCKET)
        for obj in response.get("Contents", []):
            await admin.delete_object(Bucket=_BUCKET, Key=obj["Key"])


def _key(suffix: str = "") -> str:
    """Unique key per call so parallel tests never collide."""
    return f"parity/{uuid.uuid4().hex[:8]}{suffix}"


# ─── upload / download ────────────────────────────────────────────────────────

async def test_upload_bytes_and_download_bytes_roundtrip(s3):
    data = b"hello parity world"
    key = _key(".txt")
    returned_key = await s3.upload_bytes(key, data)
    assert returned_key == key
    assert await s3.download_bytes(key) == data


async def test_upload_fileobj_and_download_bytes_roundtrip(s3):
    data = b"streaming content"
    key = _key(".bin")
    await s3.upload_fileobj(key, io.BytesIO(data), content_type="application/octet-stream")
    assert await s3.download_bytes(key) == data


async def test_upload_with_content_type_stored_in_metadata(s3):
    key = _key(".png")
    await s3.upload_bytes(key, b"\x89PNG", content_type="image/png")
    meta = await s3.get_object_metadata(key)
    assert meta["content_type"] == "image/png"


async def test_upload_with_custom_metadata(s3):
    key = _key()
    await s3.upload_bytes(key, b"data", metadata={"owner": "test"})
    meta = await s3.get_object_metadata(key)
    assert meta["metadata"].get("owner") == "test"


# ─── object_exists ────────────────────────────────────────────────────────────

async def test_object_exists_true_after_upload(s3):
    key = _key()
    await s3.upload_bytes(key, b"exists")
    assert await s3.object_exists(key) is True


async def test_object_exists_false_for_missing_key(s3):
    assert await s3.object_exists(_key()) is False


# ─── delete_object ────────────────────────────────────────────────────────────

async def test_delete_object_removes_it(s3):
    key = _key()
    await s3.upload_bytes(key, b"bye")
    assert await s3.delete_object(key) is True
    assert await s3.object_exists(key) is False


# ─── list_objects ─────────────────────────────────────────────────────────────

async def test_list_objects_returns_uploaded_keys(s3):
    prefix = f"parity/{uuid.uuid4().hex[:8]}/"
    keys = [f"{prefix}a.txt", f"{prefix}b.txt", f"{prefix}c.txt"]
    for k in keys:
        await s3.upload_bytes(k, b"x")
    results = await s3.list_objects(prefix=prefix)
    result_keys = [r["key"] for r in results]
    assert sorted(result_keys) == sorted(keys)


async def test_list_objects_prefix_filters_correctly(s3):
    base = f"parity/{uuid.uuid4().hex[:8]}/"
    await s3.upload_bytes(f"{base}match/file.txt", b"yes")
    await s3.upload_bytes(f"{base}other/file.txt", b"no")
    results = await s3.list_objects(prefix=f"{base}match/")
    assert len(results) == 1 and results[0]["key"].endswith("match/file.txt")


async def test_list_objects_empty_prefix_returns_all(s3):
    prefix = f"parity/{uuid.uuid4().hex[:8]}/"
    for i in range(3):
        await s3.upload_bytes(f"{prefix}{i}", b"v")
    results = await s3.list_objects(prefix=prefix)
    assert len(results) == 3


async def test_list_objects_result_shape(s3):
    key = _key()
    await s3.upload_bytes(key, b"shape test")
    results = await s3.list_objects(prefix=key)
    assert len(results) == 1
    obj = results[0]
    assert {"key", "size", "last_modified", "etag"} <= set(obj)
    assert obj["key"] == key
    assert obj["size"] == len(b"shape test")


# ─── get_object_metadata ──────────────────────────────────────────────────────

async def test_get_object_metadata_returns_size(s3):
    data = b"metadata check"
    key = _key()
    await s3.upload_bytes(key, data)
    meta = await s3.get_object_metadata(key)
    assert meta["size"] == len(data)
    assert "last_modified" in meta
    assert "etag" in meta


# ─── copy_object ──────────────────────────────────────────────────────────────

async def test_copy_object_creates_destination(s3):
    src = _key("-src")
    dst = _key("-dst")
    await s3.upload_bytes(src, b"original")
    assert await s3.copy_object(src, dst) is True
    assert await s3.download_bytes(dst) == b"original"


async def test_copy_object_source_still_exists(s3):
    src = _key("-src")
    dst = _key("-dst")
    await s3.upload_bytes(src, b"copy me")
    await s3.copy_object(src, dst)
    assert await s3.object_exists(src) is True


# ─── presigned URL ────────────────────────────────────────────────────────────

async def test_get_presigned_url_returns_string(s3):
    key = _key()
    await s3.upload_bytes(key, b"presigned")
    url = await s3.get_presigned_url(key)
    assert isinstance(url, str) and url.startswith("http")


async def test_get_presigned_url_put_returns_string(s3):
    key = _key()
    url = await s3.get_presigned_url(key, operation="put")
    assert isinstance(url, str) and url.startswith("http")


# ─── health_check ─────────────────────────────────────────────────────────────

async def test_health_check_returns_true(s3):
    assert await s3.health_check() is True


# ─── size limit (local guard — no network call) ───────────────────────────────

async def test_size_limit_enforced_before_upload(monkeypatch, s3):
    monkeypatch.setattr(s3, "_size_limit_enabled", True)
    monkeypatch.setattr(s3, "_default_max_bytes", 10)
    with pytest.raises(S3FileSizeError):
        await s3.upload_bytes(_key(), b"x" * 11)
