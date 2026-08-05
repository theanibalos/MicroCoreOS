import inspect
import io

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# This test ships inside the tool's own folder, so it runs from either
# location: extras/available_tools/ before `microcoreos add`, tools/ after.
try:
    from tools.s3.s3_tool import (
        S3FileSizeError,
        S3Tool,
    )
except ModuleNotFoundError:
    from extras.available_tools.s3.s3_tool import (
        S3FileSizeError,
        S3Tool,
    )

pytestmark = pytest.mark.anyio

@pytest.fixture
def tool(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_S3_DEFAULT_BUCKET", "test-bucket")
    monkeypatch.setenv("AWS_S3_SIZE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AWS_S3_MAX_FILE_SIZE_MB", "1") # 1MB limit
    return S3Tool()

async def test_size_limit_intent(tool):
    """
    The intent is to protect system resources by rejecting files that
    exceed the configured limit BEFORE processing the upload.
    """
    large_data = b"x" * (2 * 1024 * 1024) # 2MB, exceeds the 1MB limit
    with pytest.raises(S3FileSizeError):
        await tool.upload_bytes("test.key", large_data)

def _uploaded_file(data: bytes):
    """An `UploadedFile` as a plugin receives it, without importing the http tool."""
    class _Raw:
        filename, content_type = "big.bin", "application/octet-stream"
        def __init__(self): self.file = io.BytesIO(data)
    from tools.http_server.types import UploadedFile
    return UploadedFile.from_starlette(_Raw())


async def test_size_limit_applies_to_an_uploaded_file(tool):
    """
    The size guard must survive the wrapper a plugin actually gets.

    `UploadedFile` has no `.size`, and its `seek` is async with no `tell` at
    all, so a size check written against the raw Starlette upload measures
    nothing here: the limit is skipped in silence and an oversized object
    reaches the bucket. The limit is a pre-flight guard, so a miss is not
    visible in the result.
    """
    with pytest.raises(S3FileSizeError):
        await tool.upload_fileobj("big.key", _uploaded_file(b"x" * (2 * 1024 * 1024)))


async def test_uploaded_file_is_unwrapped_before_it_reaches_boto3(tool):
    """boto3 needs the sync stream: `UploadedFile.read`/`seek` are coroutines."""
    upload = _uploaded_file(b"small")
    mock_s3 = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__.return_value = mock_s3
    with patch.object(tool, "_get_client", return_value=mock_ctx):
        await tool.upload_fileobj("small.key", upload)

    sent = mock_s3.upload_fileobj.call_args[0][0]
    assert sent is upload.file
    assert not inspect.iscoroutinefunction(sent.read)


async def test_a_plain_file_object_still_works(tool):
    """Unwrapping must be a no-op for anything without `.file`."""
    stream = io.BytesIO(b"small")
    mock_s3 = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__.return_value = mock_s3
    with patch.object(tool, "_get_client", return_value=mock_ctx):
        await tool.upload_fileobj("small.key", stream)

    assert mock_s3.upload_fileobj.call_args[0][0] is stream
    assert stream.tell() == 0  # sizing restored the offset


async def test_presigned_url_intent(tool):
    """
    The intent is to provide secure, temporary access to private objects.
    """
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url.return_value = "http://presigned-url"
    # Mock the client's async context manager
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_s3
    with patch.object(tool, "_get_client", return_value=mock_client_ctx):
        url = await tool.get_presigned_url("my-file.png")
        assert url == "http://presigned-url"
        mock_s3.generate_presigned_url.assert_called_with(
            ClientMethod="get_object",
            Params={"Bucket": "test-bucket", "Key": "my-file.png"},
            ExpiresIn=3600
        )

async def test_upload_bytes_intent(tool):
    """
    The intent is to correctly delegate the data upload to S3
    using the configuration parameters (Bucket, Key).
    """
    mock_s3 = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_s3
    with patch.object(tool, "_get_client", return_value=mock_client_ctx):
        await tool.upload_bytes("data.txt", b"hello world", content_type="text/plain")
        mock_s3.put_object.assert_called_with(
            Bucket="test-bucket",
            Key="data.txt",
            Body=b"hello world",
            ContentType="text/plain"
        )

async def test_object_exists_intent(tool):
    """
    The intent is to verify existence without downloading the whole file.
    """
    mock_s3 = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_s3
    with patch.object(tool, "_get_client", return_value=mock_client_ctx):
        # Caso existe
        mock_s3.head_object.return_value = {}
        assert await tool.object_exists("exists.txt") is True
        # Caso no existe (Simulando error 404 de Boto3)
        mock_s3.head_object.side_effect = Exception("An error occurred (404) when calling the HeadObject operation: Not Found")
        assert await tool.object_exists("missing.txt") is False
