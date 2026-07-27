"""
HttpContext — response manipulation handle passed to every HTTP handler.

Split out of http_server_tool.py (mechanical move, no behavior change).
See http_server_tool.py's module docstring for the full public contract
(HttpContext API section) and the response contract it participates in.
"""

from typing import Any


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP CONTEXT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class HttpContext:
    """
    Response manipulation handle provided to every HTTP handler.
    Passed as the second argument: async def execute(self, data: dict, context: HttpContext)

    Use to override the status code, set cookies, or add custom headers.
    All mutations are applied to the response before it is sent to the client.
    """

    def __init__(self) -> None:
        self._status_code: int = 200
        self._status_explicit: bool = False
        self._cookies: list[dict] = []
        self._headers: dict[str, str] = {}

    def set_status(self, code: int) -> None:
        """
        Override the HTTP response status code.

        Default: 200 if the handler returns {"success": True, ...}; 400 if
        it returns {"success": False, ...} and set_status() was never called.
        Call this to pick a more specific code (404, 409, 403...) for a
        business error — it always wins over the success-based default.

        Examples:
            context.set_status(201)  # Created
            context.set_status(404)  # Not Found
            context.set_status(204)  # No Content
        """
        self._status_code = code
        self._status_explicit = True

    def set_cookie(
        self,
        key: str,
        value: str,
        max_age: int = 3600,
        httponly: bool = True,
        samesite: str = "lax",
        secure: bool = True,
        path: str = "/",
    ) -> None:
        """
        Set a cookie on the HTTP response.

        Defaults:
            httponly=True: Prevents JavaScript access (XSS protection).
            samesite="lax": Prevents most CSRF attacks.
            secure=True: Cookie only sent over HTTPS. Set to False for local HTTP development.
        """
        self._cookies.append({
            "key": key,
            "value": value,
            "max_age": max_age,
            "httponly": httponly,
            "samesite": samesite,
            "secure": secure,
            "path": path,
        })

    def set_header(self, key: str, value: str) -> None:
        """Add a custom header to the HTTP response."""
        self._headers[key] = value

    def redirect(self, url: str, status: int = 302) -> None:
        """
        Redirect the browser to the given URL.
        The handler's return value is ignored when this is called.

        Example:
            context.redirect("http://localhost:5173/")
            context.redirect("/dashboard", status=301)
        """
        self._redirect_url = url
        self._status_code = status

    def apply_to(self, response: Any) -> None:
        """Apply all accumulated cookies and headers to the given response object."""
        for key, value in self._headers.items():
            response.headers[key] = value
        for cookie in self._cookies:
            response.set_cookie(**cookie)

    def set_binary_response(self, content: bytes, media_type: str = "application/octet-stream") -> None:
        """
        Instruct the tool to return raw binary data instead of the default JSON envelope.
        The handler's return value will be ignored.
        """
        self._binary_content = content
        self._media_type = media_type

    @property
    def binary_content(self) -> tuple[bytes, str] | None:
        content = getattr(self, "_binary_content", None)
        if content is not None:
            return content, getattr(self, "_media_type", "application/octet-stream")
        return None

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def redirect_url(self) -> str | None:
        return getattr(self, "_redirect_url", None)
