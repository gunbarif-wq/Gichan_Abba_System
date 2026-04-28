"""KIS broker adapter for mock/live order submission.

This adapter keeps KIS REST calls behind the OrderManager boundary.  It does
not assume an order is filled just because the submit request succeeded.
"""

import logging
from datetime import datetime
from typing import Optional

from shared.schemas import Mode, Order, OrderSide, OrderState, OrderType
from shared.errors import ExecutionException
from trade.retry_policy import RetryPolicy

logger = logging.getLogger(__name__)


class KisBroker:
    """Broker adapter for KIS mock/live clients."""

    def __init__(self, mode: Mode, kis_client=None):
        if mode not in (Mode.MOCK, Mode.LIVE):
            raise ValueError(f"KisBroker requires mock/live mode, got {mode}")
        self.mode = mode
        self._kis = kis_client or self._default_client(mode)
        self._retry = RetryPolicy(self._kis)

    @staticmethod
    def _default_client(mode: Mode):
        if mode == Mode.LIVE:
            from trade.kis_live_client import get_kis_live_client
            return get_kis_live_client()
        from trade.kis_mock_client import get_kis_mock_client
        return get_kis_mock_client()

    @staticmethod
    def _kis_order_type(order: Order) -> str:
        return "01" if order.order_type == OrderType.MARKET else "00"

    @staticmethod
    def _order_price(order: Order) -> int:
        return 0 if order.order_type == OrderType.MARKET else int(order.price)

    def place_order(self, order: Order) -> Order:
        order.sent_time = datetime.now()
        order.state = OrderState.BUY_SENT if order.side == OrderSide.BUY else OrderState.SELL_SENT

        use_sor = bool(order.metadata.get("use_sor", False))
        order_type = self._kis_order_type(order)
        price = self._order_price(order)

        def submit():
            if order.side == OrderSide.BUY:
                return self._kis.place_buy_order(
                    order.symbol, order.quantity, price,
                    order_type=order_type, use_sor=use_sor,
                )
            return self._kis.place_sell_order(
                order.symbol, order.quantity, price,
                order_type=order_type, use_sor=use_sor,
            )

        result = self._retry.execute_with_retry(
            submit,
            context=f"{self.mode.value}:{order.side.value}:{order.symbol}",
        )

        if not result.success:
            order.state = OrderState.UNKNOWN
            order.metadata["submit_error"] = result.last_error
            logger.error(
                "[KisBroker] order submit failed; marked UNKNOWN: %s %s %s",
                order.symbol, order.side.value, result.last_error,
            )
            return order

        output = result.result or {}
        order.metadata["broker_output"] = output
        order.metadata["broker_order_id"] = (
            output.get("ODNO") or output.get("odno") or output.get("order_no")
        )
        logger.info(
            "[KisBroker] order submitted: %s %s qty=%s type=%s route=%s",
            order.symbol, order.side.value, order.quantity, order_type,
            "SOR" if use_sor else "KRX",
        )
        return order

    def cancel_order(self, order_id: str) -> bool:
        logger.warning("[KisBroker] cancel_order is not wired yet: %s", order_id)
        return False

    def get_order_status(self, order_id: str) -> Optional[Order]:
        return None
