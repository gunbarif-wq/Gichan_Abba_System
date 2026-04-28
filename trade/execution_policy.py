"""
Execution Policy
주문 실행 정책 (지정가/시장가, 분할 주문 등)
"""

import logging
from typing import Optional

from shared.schemas import Order, OrderType

logger = logging.getLogger(__name__)


class ExecutionPolicy:
    """
    주문 실행 정책

    슬리피지 적용, 주문 타입 결정, 금액 기준 수량 계산
    Paper 모드: slippage_rate=0 (즉시 체결)
    Mock/Live: slippage_rate=0.0005 (0.05%) 권장
    """

    def __init__(self, slippage_rate: float = 0.0):
        self.slippage_rate = slippage_rate
        logger.info(f"[ExecutionPolicy] 초기화: slippage={slippage_rate:.4%}")

    def apply_slippage(self, price: float, is_buy: bool) -> float:
        """슬리피지 적용"""
        if is_buy:
            return price * (1 + self.slippage_rate)
        else:
            return price * (1 - self.slippage_rate)

    def determine_order_type(self, symbol: str, mode: str) -> OrderType:
        """주문 타입 결정"""
        # Paper 모드: 항상 지정가
        return OrderType.LIMIT

    def calculate_order_quantity(
        self,
        amount: float,
        price: float,
        commission_rate: float = 0.00015,
    ) -> int:
        """금액 기준 주문 가능 수량 계산"""
        if price <= 0:
            return 0
        net_amount = amount / (1 + commission_rate)
        return int(net_amount // price)


_execution_policy: Optional[ExecutionPolicy] = None


def get_execution_policy() -> ExecutionPolicy:
    global _execution_policy
    if _execution_policy is None:
        _execution_policy = ExecutionPolicy()
    return _execution_policy
