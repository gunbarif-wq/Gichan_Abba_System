"""
Order State Manager
종목별 주문 상태 추적 및 중복 주문 방지
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Optional

from shared.schemas import OrderState, OrderSide

logger = logging.getLogger(__name__)

# 매수 차단 상태
_BUY_BLOCK_STATES = {
    OrderState.BUY_PENDING,
    OrderState.BUY_SENT,
    OrderState.BUY_PARTIAL,
    OrderState.UNKNOWN,
    OrderState.LOCKED,
}

# 매도 차단 상태
_SELL_BLOCK_STATES = {
    OrderState.SELL_PENDING,
    OrderState.SELL_SENT,
    OrderState.SELL_PARTIAL,
    OrderState.UNKNOWN,
    OrderState.LOCKED,
}


class OrderStateManager:
    """
    종목별 주문 상태 관리자
    - 같은 종목 중복 매수/매도 방지
    - UNKNOWN 상태에서 신규 주문 차단
    """

    def __init__(self):
        self._states: Dict[str, OrderState] = {}
        self._lock = threading.RLock()
        self._history: list = []
        logger.info("[OrderStateManager] 초기화")

    def get_state(self, symbol: str) -> OrderState:
        with self._lock:
            return self._states.get(symbol, OrderState.IDLE)

    def set_state(self, symbol: str, state: OrderState, order_id: str = "") -> None:
        with self._lock:
            old_state = self._states.get(symbol, OrderState.IDLE)
            self._states[symbol] = state
            self._history.append({
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "order_id": order_id,
                "from": old_state.value,
                "to": state.value,
            })
            logger.debug(f"[OrderState] {symbol}: {old_state.value} → {state.value}")

    def can_buy(self, symbol: str) -> tuple:
        """매수 가능 여부. Returns (bool, reason)"""
        state = self.get_state(symbol)
        if state in _BUY_BLOCK_STATES:
            return False, f"매수 차단 상태: {state.value}"
        return True, ""

    def can_sell(self, symbol: str) -> tuple:
        """매도 가능 여부. Returns (bool, reason)"""
        state = self.get_state(symbol)
        if state in _SELL_BLOCK_STATES:
            return False, f"매도 차단 상태: {state.value}"
        return True, ""

    def reset(self, symbol: str) -> None:
        """상태 초기화"""
        self.set_state(symbol, OrderState.IDLE)

    def get_all_states(self) -> Dict[str, str]:
        with self._lock:
            return {sym: st.value for sym, st in self._states.items()}

    def get_history(self, symbol: str = None) -> list:
        if symbol:
            return [h for h in self._history if h["symbol"] == symbol]
        return list(self._history)


# 싱글톤
_order_state_manager: Optional[OrderStateManager] = None


def get_order_state_manager() -> OrderStateManager:
    global _order_state_manager
    if _order_state_manager is None:
        _order_state_manager = OrderStateManager()
    return _order_state_manager
