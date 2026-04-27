"""
Fill Checker
체결 확인 (Skeleton)
"""

import logging
from typing import Optional

from shared.schemas import Order, OrderState

logger = logging.getLogger(__name__)


class FillChecker:
    """
    체결 확인 처리기 (Skeleton)
    TODO: KIS API 연동 후 실제 체결 확인 구현
    """

    def __init__(self):
        logger.info("[FillChecker] 초기화")

    def check_fill(self, order: Order) -> Order:
        """
        주문 체결 확인
        Paper 모드: 즉시 체결 가정
        TODO: Mock/Live 모드에서 실제 체결 조회
        """
        logger.debug(f"[FillChecker] 체결 확인: {order.order_id}")
        return order

    def is_filled(self, order: Order) -> bool:
        return order.state in (OrderState.BUY_FILLED, OrderState.SELL_FILLED)

    def is_partial(self, order: Order) -> bool:
        return order.state in (OrderState.BUY_PARTIAL, OrderState.SELL_PARTIAL)


_fill_checker: Optional[FillChecker] = None


def get_fill_checker() -> FillChecker:
    global _fill_checker
    if _fill_checker is None:
        _fill_checker = FillChecker()
    return _fill_checker
