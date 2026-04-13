from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    swagger_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    swagger_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    scan_status: Mapped[str] = mapped_column(String(50), default="pending")
    scan_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_use_cases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_documentation_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_documentation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_analyzed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    auth_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ai_design_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_design_recommendations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    endpoints: Mapped[list[Endpoint]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )
    scan_logs: Mapped[list[ScanLog]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_body_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_request_example: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_response_example: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_use_cases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_required: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    service: Mapped[Service] = relationship(back_populates="endpoints")


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    endpoints_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    service: Mapped[Service] = relationship(back_populates="scan_logs")
