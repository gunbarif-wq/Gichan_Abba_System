"""
Balance Checker — 현금 잔고 조회
1순위: KIS API (실투자/모의투자)
2순위: AccountManager (Paper 모드 / fallback)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BalanceChecker:
    """
    가용 현금 및 총 자산 조회
    KIS API 성공 시 AccountManager도 동기화
    """

    def __init__(self, kis_client=None):
        self._kis = kis_client

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def get_available_cash(self) -> float:
        """가용 현금 조회"""
        # KIS API 시도
        kis = self._get_kis()
        if kis is not None:
            try:
                output = kis.get_balance()
                # 주문가능현금: ord_psbl_cash 또는 nxdy_excc_amt
                cash = float(output.get("ord_psbl_cash") or
                             output.get("nxdy_excc_amt") or 0)
                if cash > 0:
                    self._sync_account_cash(cash)
                    return cash
            except Exception as e:
                logger.warning(f"[BalanceChecker] KIS API 실패, fallback: {e}")

        # Fallback: AccountManager
        try:
            from account.account_manager import get_account_manager
            return get_account_manager().available_cash
        except Exception:
            return 0.0

    def get_total_asset(self) -> float:
        """총 자산 = 현금 + 보유 종목 평가액"""
        try:
            from account.account_manager import get_account_manager
            return get_account_manager().get_total_asset()
        except Exception:
            return self.get_available_cash()

    def _sync_account_cash(self, cash: float) -> None:
        """KIS 잔고를 AccountManager에 동기화"""
        try:
            from account.account_manager import get_account_manager
            mgr = get_account_manager()
            mgr.available_cash = cash
        except Exception:
            pass

    def summary(self) -> str:
        cash  = self.get_available_cash()
        total = self.get_total_asset()
        return f"현금={cash:,.0f}원 / 총자산={total:,.0f}원"


_checker: Optional[BalanceChecker] = None


def get_balance_checker(kis_client=None) -> BalanceChecker:
    global _checker
    if _checker is None:
        _checker = BalanceChecker(kis_client)
    return _checker
