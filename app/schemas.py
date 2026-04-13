from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ServiceCreate(BaseModel):
    name: str
    swagger_url: str  # use str instead of HttpUrl for simplicity


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    swagger_url: Optional[str] = None


class EndpointResponse(BaseModel):
    id: int
    path: str
    method: str
    summary: Optional[str] = None
    description: Optional[str] = None
    parameters_json: Optional[str] = None
    request_body_json: Optional[str] = None
    response_json: Optional[str] = None
    tags: Optional[str] = None
    deprecated: bool = False
    ai_summary: Optional[str] = None
    ai_request_example: Optional[str] = None
    ai_response_example: Optional[str] = None
    ai_use_cases: Optional[str] = None
    ai_notes: Optional[str] = None
    auth_required: Optional[bool] = None
    model_config = ConfigDict(from_attributes=True)


class ServiceResponse(BaseModel):
    id: int
    name: str
    swagger_url: str
    description: Optional[str] = None
    swagger_version: Optional[str] = None
    base_url: Optional[str] = None
    last_scanned_at: Optional[datetime] = None
    scan_status: str
    scan_error: Optional[str] = None
    ai_overview: Optional[str] = None
    ai_use_cases: Optional[str] = None
    ai_documentation_score: Optional[int] = None
    ai_documentation_notes: Optional[str] = None
    auth_type: Optional[str] = None
    ai_design_score: Optional[int] = None
    ai_design_recommendations: Optional[str] = None
    ai_analyzed_at: Optional[datetime] = None
    endpoints: list[EndpointResponse] = []
    model_config = ConfigDict(from_attributes=True)


class ServiceListResponse(BaseModel):
    id: int
    name: str
    swagger_url: str
    scan_status: str
    last_scanned_at: Optional[datetime] = None
    endpoint_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class ScanTriggerResponse(BaseModel):
    message: str
    service_id: int


class ScanAllResponse(BaseModel):
    message: str
    service_count: int


class ScanByNameResponse(BaseModel):
    message: str
    service_name: str
    service_count: int
    service_ids: list[int]


class ScanStatusResponse(BaseModel):
    service_id: int
    scan_status: str
    last_scanned_at: Optional[datetime] = None
    scan_error: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
