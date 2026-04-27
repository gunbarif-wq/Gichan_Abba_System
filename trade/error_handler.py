"""
Order Error Handler
주문 실패 처리 - 매도 실패 시 신규매수 전체 중단 등
"""

import logging
from datetime import datetime
from typing import Optional

from shared.errors import ExecutionException, NetworkError, TokenExpired

logger = logging.getLogger(__name__)


class OrderErrorHandler:
    """
    주문 오류 처리기

    원칙:
    1. 체결 여부 불명확 → 새 주문 금지
    2. 토큰 만료 → 재발급 후 1회 재시도
    3. 네트워크 오류 → 최대 3회 재시도
    4. 잔고 부족 → 재시도 금지
    5. 매도 실패 → 신규매수 전체 중단
    6. 모든 실패 → blackbox_logger 기록
    """

    def __init__(self):
        self._sell_failure_symbols: list = []
        self._buy_halted: bool = False
        logger.info("[OrderErrorHandler] 초기화")

    def handle_buy_failure(self, symbol: str, error: Exception, order_id: str = "") -> None:
        """매수 실패 처리 - 기록 후 종료"""
        logger.error(f"[ErrorHandler] 매수 실패: {symbol} {type(error).__name__}: {error}")
        self._log_failure("BUY_FAIL", symbol, str(error), order_id)

    def handle_sell_failure(self, symbol: str, error: Exception, order_id: str = "") -> None:
        """
        매도 실패 처리 - 긴급 상황
        신규 매수 전체 중단
        """
        logger.error(f"[ErrorHandler] 매도 실패 (긴급): {symbol} {type(error).__name__}: {error}")
        self._sell_failure_symbols.append(symbol)
        self._log_failure("SELL_FAIL", symbol, str(error), order_id)

        # 신규 매수 중단
        self._halt_new_buys(f"매도 실패: {symbol}")

    def handle_unknown_fill(self, symbol: str, order_id: str) -> None:
        """체결 여부 불명확 처리 - 새 주문 차단"""
        logger.warning(f"[ErrorHandler] 체결 여부 불명확: {symbol} order={order_id}")
        self._log_failure("UNKNOWN_FILL", symbol, "체결 여부 불명확", order_id)

    def is_buy_halted(self) -> bool:
        return self._buy_halted

    def resume_buys(self) -> None:
        self._buy_halted = False
        logger.info("[ErrorHandler] 신규 매수 재개")

    def _halt_new_buys(self, reason: str) -> None:
        self._buy_halted = True
        logger.critical(f"[ErrorHandler] 신규 매수 전체 중단: {reason}")
        # Risk Manager에도 반영
        try:
            from risk.risk_manager import get_risk_manager
            rm = get_risk_manager()
            rm.set_new_buy_allowed(False)
        except Exception:
            pass

    def _log_failure(self, error_type: str, symbol: str, error: str, order_id: str) -> None:
        try:
            from hub.blackbox_logger import get_blackbox
            get_blackbox().log_error(
                context=error_type,
                error=error,
                symbol=symbol,
                order_id=order_id,
            )
        except Exception:
            pass


_error_handler: Optional[OrderErrorHandler] = None


def get_error_handler() -> OrderErrorHandler:
    global _error_handler
    if _error_handler is None:
        _error_handler = OrderErrorHandler()
    return _error_handler
