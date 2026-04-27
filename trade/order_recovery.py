"""
Order Recovery
UNKNOWN 상태 주문 복구 처리 (Skeleton)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OrderRecovery:
    """
    주문 복구 처리기 (Skeleton)

    UNKNOWN 상태 주문에 대해:
    1. 주문 조회
    2. 잔고 조회
    3. 상태 확정
    4. 필요시 수동 처리 요청

    TODO: KIS API 연동 후 실제 구현
    """

    def __init__(self):
        self._recovery_history: list = []
        logger.info("[OrderRecovery] 초기화")

    def recover_unknown_order(self, order_id: str, symbol: str) -> str:
        """
        UNKNOWN 상태 주문 복구 시도
        Returns: 'FILLED', 'CANCELLED', 'STILL_UNKNOWN'
        """
        logger.warning(f"[OrderRecovery] UNKNOWN 주문 복구 시도: {order_id} {symbol}")
        # TODO: KIS API로 주문 조회 후 상태 확정
        self._recovery_history.append({
            "order_id": order_id,
            "symbol": symbol,
            "result": "STILL_UNKNOWN",
        })
        return "STILL_UNKNOWN"

    def get_history(self) -> list:
        return list(self._recovery_history)


_order_recovery: Optional[OrderRecovery] = None


def get_order_recovery() -> OrderRecovery:
    global _order_recovery
    if _order_recovery is None:
        _order_recovery = OrderRecovery()
    return _order_recovery
