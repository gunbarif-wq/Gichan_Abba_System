"""Holdings Checker (Skeleton)"""
import logging
from typing import Dict, Optional
from shared.schemas import Position
logger = logging.getLogger(__name__)

class HoldingsChecker:
    """보유 종목 확인 (Skeleton) - TODO: KIS API 연동"""
    def get_holdings(self) -> Dict[str, Position]:
        from account.account_manager import get_account_manager
        return get_account_manager().get_all_positions()

    def get_holding(self, symbol: str) -> Optional[Position]:
        from account.account_manager import get_account_manager
        return get_account_manager().get_position(symbol)

_checker: Optional[HoldingsChecker] = None

def get_holdings_checker() -> HoldingsChecker:
    global _checker
    if _checker is None:
        _checker = HoldingsChecker()
    return _checker
