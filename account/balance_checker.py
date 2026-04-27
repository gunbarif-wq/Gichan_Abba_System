"""Balance Checker (Skeleton)"""
import logging
from typing import Optional
logger = logging.getLogger(__name__)

class BalanceChecker:
    """잔고 확인 (Skeleton) - TODO: KIS API 연동"""
    def get_available_cash(self) -> float:
        from account.account_manager import get_account_manager
        return get_account_manager().available_cash

    def get_total_asset(self) -> float:
        from account.account_manager import get_account_manager
        return get_account_manager().get_total_asset()

_checker: Optional[BalanceChecker] = None

def get_balance_checker() -> BalanceChecker:
    global _checker
    if _checker is None:
        _checker = BalanceChecker()
    return _checker
