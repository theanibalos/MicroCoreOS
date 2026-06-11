import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from tools.s3.s3_tool import S3Tool, S3FileSizeError

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
