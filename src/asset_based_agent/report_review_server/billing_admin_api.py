"""Administrative billing reconciliation; no customer or provider secrets."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BalanceHold, BillingReconciliation
from .services.auth_service import AuthContext, ServiceError
from .services.billing_reconciliation import reconcile_hold


class ReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed_amount: Decimal = Field(ge=0, lt=1_000_000_000_000, max_digits=20, decimal_places=8)
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_reference: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reconciliation_id: str
    hold_id: str
    admin_user_id: str
    confirmed_amount: Decimal
    known_amount: Decimal
    evidence_sha256: str
    evidence_reference: str
    created_at: datetime


def register_billing_admin_routes(app, get_context, get_db):
    @app.get('/api/v1/admin/billing-holds')
    def uncertain_holds(request: Request, context: Annotated[AuthContext, Depends(get_context)],
                        db: Annotated[Session, Depends(get_db)], limit: int = Query(50, ge=1, le=100),
                        offset: int = Query(0, ge=0)):
        request.app.state.auth_service.require_admin(context)
        rows = list(db.scalars(select(BalanceHold).where(BalanceHold.status == 'uncertain')
            .order_by(BalanceHold.created_at, BalanceHold.hold_id).offset(offset).limit(limit + 1)))
        return {'items': [{'hold_id': row.hold_id, 'user_id': row.user_id,
            'model_id': row.model_id, 'client_request_id': row.client_request_id,
            'known_amount': str(row.settled_amount), 'reserved_amount': str(row.reserved_amount),
            'status': row.status, 'created_at': row.created_at.isoformat()} for row in rows[:limit]],
            'next_offset': offset + limit if len(rows) > limit else None}

    @app.get('/api/v1/admin/billing-holds/{hold_id}/reconciliation', response_model=ReconciliationResponse)
    def get_reconciliation(hold_id: str, request: Request, context: Annotated[AuthContext, Depends(get_context)],
                           db: Annotated[Session, Depends(get_db)]):
        request.app.state.auth_service.require_admin(context)
        record = db.scalar(select(BillingReconciliation).where(BillingReconciliation.hold_id == hold_id))
        if record is None:
            raise ServiceError('reconciliation_not_found', '核对记录不存在。', 404)
        return record

    @app.post('/api/v1/admin/billing-holds/{hold_id}/reconciliation', response_model=ReconciliationResponse)
    def submit_reconciliation(hold_id: str, payload: ReconciliationRequest, request: Request,
                              context: Annotated[AuthContext, Depends(get_context)], db: Annotated[Session, Depends(get_db)]):
        request.app.state.auth_service.require_admin(context)
        return reconcile_hold(db, hold_id=hold_id, admin_user_id=context.user.user_id,
                              **payload.model_dump())
