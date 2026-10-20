"""Shared secret and account-scoped financial query outcomes."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class FinanceCredential(Base):
    __tablename__ = 'report_review_finance_credentials'
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(36), ForeignKey('report_review_users.user_id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FinanceRequest(Base):
    __tablename__ = 'report_review_finance_requests'
    __table_args__ = (Index('ix_finance_execution_lease', 'status', 'lease_expires_at'),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('report_review_users.user_id'), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), default='')
    status: Mapped[str] = mapped_column(String(16), default='running')
    result_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
