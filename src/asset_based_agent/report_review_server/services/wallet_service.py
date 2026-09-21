"""Wallet balance and immutable ledger operations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Wallet, WalletLedger
from .auth_service import ServiceError

MONEY_QUANTUM = Decimal("0.00000001")
DISPLAY_QUANTUM = Decimal("0.01")


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def display_money(value: Decimal) -> str:
    return str(value.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP))


class WalletService:
    def get_wallet(self, db: Session, user_id: str, *, lock: bool = False) -> Wallet:
        query = select(Wallet).where(Wallet.user_id == user_id)
        if lock:
            query = query.with_for_update()
        wallet = db.scalar(query)
        if wallet is None:
            raise ServiceError("wallet_not_found", "账户余额记录不存在。", 404)
        return wallet

    def adjust(
        self,
        db: Session,
        *,
        user_id: str,
        amount: Decimal,
        admin_user_id: str,
    ) -> Wallet:
        normalized = money(amount)
        if normalized == 0:
            raise ServiceError("zero_adjustment", "调整金额不能为零。", 422)
        wallet = self.get_wallet(db, user_id, lock=True)
        wallet.balance = money(wallet.balance + normalized)
        db.add(
            WalletLedger(
                user_id=user_id,
                entry_type="admin_adjustment",
                amount=normalized,
                balance_after=wallet.balance,
                admin_user_id=admin_user_id,
            )
        )
        db.commit()
        db.refresh(wallet)
        return wallet

    def charge(
        self,
        db: Session,
        *,
        user_id: str,
        amount: Decimal,
        reference_id: str,
    ) -> Wallet:
        normalized = money(amount)
        wallet = self.get_wallet(db, user_id, lock=True)
        wallet.balance = money(wallet.balance - normalized)
        if normalized:
            db.add(
                WalletLedger(
                    user_id=user_id,
                    entry_type="model_charge",
                    amount=-normalized,
                    balance_after=wallet.balance,
                    reference_id=reference_id,
                )
            )
        return wallet
