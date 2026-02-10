import os
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from core.base_tool import BaseTool
from dotenv import load_dotenv

load_dotenv()

class IdentityTool(BaseTool):
    """
    Tool specialized in Authentication (AuthN).
    PURE CRYPTO: No web dependencies (No FastAPI).
    Handles password hashing and JWT lifecycle.
    """
    
    def __init__(self):
        self._secret_key = os.getenv("JWT_SECRET", "default-fallback-secret-key-please-change")
        # Use bcrypt_sha256 to avoid the 72-byte limit of standard bcrypt
        self._pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
        self._algorithm = "HS256"

    @property
    def name(self) -> str:
        return "identity"

    def setup(self):
        pass

    def get_interface_description(self) -> str:
        return """
        Identity Tool (identity) - Pure Crypto:
        - hash_password(password: str) -> str
        - verify_password(password: str, hashed: str) -> bool
        - generate_token(data: dict, expires_delta: timedelta = None) -> str
        - decode_token(token: str) -> dict
        """

    # --- Hashing Capabilities ---
    def hash_password(self, password: str) -> str:
        return self._pwd_context.hash(password)

    def verify_password(self, password: str, hashed: str) -> bool:
        return self._pwd_context.verify(password, hashed)

    # --- JWT Capabilities ---
    def generate_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=60)
        
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self._secret_key, algorithm=self._algorithm)

    def decode_token(self, token: str) -> Dict[str, Any]:
        """Pure decoding. Raises standard JWT errors."""
        return jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
