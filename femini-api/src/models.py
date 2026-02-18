"""
Pydantic models for Femini API request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List

class SubmitRequest(BaseModel):
    """Request model for submitting a new task"""
    prompt: str = Field(..., description="The prompt to send to Gemini", min_length=1)
    is_image: bool = Field(False, description="Whether to generate an image")
    force_json: bool = Field(False, description="Force JSON output format")
    force_text: bool = Field(False, description="Force plain text output")
    return_image_data: bool = Field(False, description="Return base64-encoded image data")
    chat_id: Optional[str] = Field(None, description="Continue in existing chat")
    account_id: Optional[str] = Field(None, description="Account ID for chat")
    credential_mode: Optional[str] = Field(None, description="Override credential selection mode")
    reference_image_name: Optional[str] = Field(None, description="Reference image from Google Drive")
    filename_suffix: str = Field("", description="Suffix for saved filenames")
    save_dir: Optional[str] = Field(None, description="Custom directory to save downloads")
    download: bool = Field(False, description="Whether to save the response to a file (image or text)")
    required_json_keys: Optional[List[str]] = Field(
        None,
        description="When force_json=true, retry if these top-level keys are missing from the JSON response"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "prompt": "Hello! How are you?",
                    "is_image": False,
                    "force_text": True
                },
                {
                    "prompt": "Generate a sunset over mountains",
                    "is_image": True,
                    "return_image_data": True
                }
            ]
        }
    }

class SubmitResponse(BaseModel):
    """Response model for task submission"""
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(..., description="Initial status (pending)")
    created_at: str = Field(..., description="Timestamp of creation")
    stream_url: str = Field(..., description="URL to stream real-time updates")

class StatusResponse(BaseModel):
    """Response model for status check"""
    task_id: str
    status: str = Field(..., description="Current status: pending, processing, completed, failed")
    created_at: str
    updated_at: str
    credential_key: Optional[str] = None
    processing_time: Optional[float] = None
    error: Optional[str] = None

class ResultResponse(BaseModel):
    """Response model for fetching results"""
    task_id: str
    status: str
    prompt: str
    is_image: bool
    created_at: str
    updated_at: str
    credential_key: Optional[str] = None
    processing_time: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class RequestListItem(BaseModel):
    """Model for list item in request listing"""
    task_id: str
    prompt: str
    status: str
    is_image: bool
    created_at: str
    processing_time: Optional[float] = None

class RequestListResponse(BaseModel):
    """Response model for listing requests"""
    requests: List[RequestListItem]
    total: int
    limit: int
    offset: int

class StatsResponse(BaseModel):
    """Response model for system statistics"""
    database: Dict[str, Any]
    worker: Optional[Dict[str, Any]] = None

class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str = "healthy"
    timestamp: str
    database: str = "connected"
    worker: str = "unknown"

class SSEMessage(BaseModel):
    """Model for SSE message data"""
    status: str
    task_id: str
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None
    error: Optional[str] = None
    credential_key: Optional[str] = None
    download: bool = False