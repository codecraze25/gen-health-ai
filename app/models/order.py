import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OrderStatus(enum.StrEnum):
    NEEDS_REVIEW = "needs_review"
    READY = "ready"


REQUIRED_FIELDS = (
    "patient_first_name",
    "patient_last_name",
    "patient_dob",
    "provider_name",
    "provider_npi",
)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    patient_first_name: Mapped[str | None] = mapped_column(String(100))
    patient_last_name: Mapped[str | None] = mapped_column(String(100))
    patient_dob: Mapped[date | None] = mapped_column(Date)
    provider_name: Mapped[str | None] = mapped_column(String(200))
    provider_npi: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.NEEDS_REVIEW.value)
    # Each issue: {"field", "code", "message", "severity"}. Cleared per field when a user edits it.
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def refresh_status(self) -> None:
        complete = all(getattr(self, f) is not None for f in REQUIRED_FIELDS)
        self.status = (
            OrderStatus.READY.value
            if complete and not self.validation_issues
            else OrderStatus.NEEDS_REVIEW.value
        )
