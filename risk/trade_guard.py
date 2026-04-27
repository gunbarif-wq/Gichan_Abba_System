"""
Trade Guard
시장 시간 + OpsStatus 기반 주문 차단
Risk Manager와 함께 이중 방어선 역할
"""

import logging
from typing import Optional

from shared.schemas import OpsStatus, Order, OrderSide, Mode
from shared.errors import RiskException, MarketClosed, BuyRestrictedTime

logger = logging.getLogger(__name__)


class TradeGuard:
    """
    거래 가드 - OpsStatus 기반 주문 차단
    Risk Manager보다 먼저 실행되는 1차 방어선
    """

    def __init__(self):
        logger.info("[TradeGuard] 초기화")

    def check(self, order: Order, ops_status: OpsStatus) -> None:
        """
        OpsStatus 기반 주문 차단 검사

        Raises:
            MarketClosed: 거래 시간이 아님
            BuyRestrictedTime: 신규 매수 제한 구간
            RiskException: 기타 거래 불가
        """
        mode = ops_status.mode

        # Paper 모드는 항상 통과
        if mode == Mode.PAPER:
            return

        if not ops_status.is_market_open:
            raise MarketClosed("거래 시간이 아닙니다")

        if order.side == OrderSide.BUY:
            if not ops_status.can_buy:
                raise BuyRestrictedTime("신규 매수 제한 구간입니다")

        if order.side == OrderSide.SELL:
            if not ops_status.can_sell:
                raise RiskException("매도 제한 구간입니다")

        logger.debug(f"[TradeGuard] 통과: {order.symbol} {order.side.value}")


_trade_guard: Optional[TradeGuard] = None


def get_trade_guard() -> TradeGuard:
    global _trade_guard
    if _trade_guard is None:
        _trade_guard = TradeGuard()
    return _trade_guard
