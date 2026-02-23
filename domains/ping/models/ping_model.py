from pydantic import BaseModel, Field

class PingResponse(BaseModel):
    status: str = Field(default="ok", description="Status of the server")
    message: str = Field(default="pong", description="Response message")
