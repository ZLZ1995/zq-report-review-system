"""Audited settlement of uncertain holds; never retries provider operations."""
import re
from decimal import Decimal

from sqlalchemy import select

from ..models import BalanceHold, BillingReconciliation, BillingRequest, User, utc_now
from .auth_service import ServiceError
from .wallet_service import WalletService, money


def reconcile_hold(db, *, hold_id, admin_user_id, confirmed_amount, evidence_sha256, evidence_reference):
    """Amount is the verified total customer charge for this hold, not a delta.

    Caller must obtain upstream evidence outside this function. Only its digest
    and a non-secret support reference are retained; no provider documents here.
    """
    try:
        admin = db.get(User, admin_user_id)
        if admin is None or admin.role != 'admin' or admin.status != 'active':
            raise ServiceError('admin_required', '需要管理员权限。', 403)
        if (not isinstance(confirmed_amount, Decimal) or not confirmed_amount.is_finite()
                or confirmed_amount < 0 or confirmed_amount >= Decimal(1000000000000)
                or confirmed_amount != money(confirmed_amount)
                or not isinstance(evidence_sha256, str)
                or not re.fullmatch(r'[0-9a-f]{64}', evidence_sha256)
                or not isinstance(evidence_reference, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', evidence_reference)):
            raise ServiceError('invalid_reconciliation', '核对金额或凭证引用无效。', 422)
        hold = db.scalar(select(BalanceHold).where(BalanceHold.hold_id == hold_id)
                         .with_for_update().execution_options(populate_existing=True))
        if hold is None:
            raise ServiceError('hold_not_found', '冻结记录不存在。', 404)
        prior = db.scalar(select(BillingReconciliation).where(BillingReconciliation.hold_id == hold_id))
        if prior is not None:
            if (prior.confirmed_amount, prior.evidence_sha256, prior.evidence_reference) != (
                    confirmed_amount, evidence_sha256, evidence_reference):
                raise ServiceError('reconciliation_conflict', '该冻结记录已核对，不能覆盖原结论。', 409)
            return prior
        if hold.status != 'uncertain' or confirmed_amount < hold.settled_amount:
            raise ServiceError('reconciliation_not_allowed', '状态不符或核对金额低于已确认费用。', 409)
        requests = list(db.scalars(select(BillingRequest).where(BillingRequest.hold_id == hold_id)))
        if not any(item.status == 'uncertain' for item in requests) or any(
                item.status == 'pending' for item in requests):
            raise ServiceError('reconciliation_not_allowed', '请求尚未满足费用核对条件。', 409)
        record = BillingReconciliation(hold_id=hold_id, admin_user_id=admin_user_id,
            confirmed_amount=confirmed_amount, known_amount=hold.settled_amount,
            evidence_sha256=evidence_sha256, evidence_reference=evidence_reference)
        db.add(record)
        db.flush()
        WalletService().charge(db, user_id=hold.user_id, amount=confirmed_amount,
                               reference_id='reconciliation:' + record.reconciliation_id)
        hold.settled_amount = confirmed_amount
        hold.status = 'captured' if confirmed_amount else 'released'
        for item in requests:
            if item.status == 'uncertain':
                item.status = 'failed'
                item.error_code = 'billing_reconciled_no_result'
                item.completed_at = utc_now()
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        raise
