"""
Circuit Guard
일일 손실 한도 초과 시 거래 차단 (서킷브레이커)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitGuard:
    """
    서킷 브레이커
    - 일일 손실 한도 초과 시 신규 매수 차단
    - max_daily_loss_ratio: 기본 3%
    """

    def __init__(self, max_daily_loss_ratio: float = 0.03):
        self.max_daily_loss_ratio = max_daily_loss_ratio
        self._tripped = False
        self._daily_loss_ratio = 0.0
        logger.info(f"[CircuitGuard] 초기화: max_loss={max_daily_loss_ratio:.1%}")

    def update_loss(self, current_loss_ratio: float) -> None:
        """현재 손실률 업데이트 및 차단 여부 확인"""
        self._daily_loss_ratio = current_loss_ratio
        if current_loss_ratio <= -self.max_daily_loss_ratio:
            if not self._tripped:
                self._tripped = True
                logger.critical(
                    f"[CircuitGuard] 일일 손실 한도 초과! "
                    f"손실={current_loss_ratio:.2%} 한도={-self.max_daily_loss_ratio:.2%}"
                )
                try:
                    from risk.risk_manager import get_risk_manager
                    get_risk_manager().set_new_buy_allowed(False)
                except Exception:
                    pass

    def is_tripped(self) -> bool:
        return self._tripped

    def reset(self) -> None:
        """장 시작 시 초기화"""
        self._tripped = False
        self._daily_loss_ratio = 0.0
        logger.info("[CircuitGuard] 초기화됨")

    def check(self) -> None:
        """서킷브레이커 상태 확인. 차단 중이면 예외 발생"""
        from shared.errors import RiskException
        if self._tripped:
            raise RiskException(
                f"서킷브레이커 작동 중 (일일 손실={self._daily_loss_ratio:.2%})"
            )


_circuit_guard: Optional[CircuitGuard] = None


def get_circuit_guard() -> CircuitGuard:
    global _circuit_guard
    if _circuit_guard is None:
        _circuit_guard = CircuitGuard()
    return _circuit_guard
