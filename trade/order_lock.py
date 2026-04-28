"""
Order Lock
종목별 주문 잠금 - 동시 주문 방지
상태 확정 전까지 lock 해제 금지
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class OrderLock:
    """
    종목별 주문 잠금 관리자
    - 같은 종목에 동시에 하나의 주문만 허용
    - thread-safe
    """

    def __init__(self):
        self._locks: Dict[str, threading.RLock] = {}
        self._locked: Dict[str, str] = {}  # symbol -> order_id
        self._locked_at: Dict[str, datetime] = {}
        self._meta_lock = threading.RLock()
        logger.info("[OrderLock] 초기화")

    def _get_lock(self, symbol: str) -> threading.RLock:
        with self._meta_lock:
            if symbol not in self._locks:
                self._locks[symbol] = threading.RLock()
            return self._locks[symbol]

    def acquire(self, symbol: str, order_id: str) -> bool:
        """
        종목 잠금 획득
        Returns: True if acquired, False if already locked
        """
        with self._meta_lock:
            if symbol in self._locked:
                existing = self._locked.get(symbol, "unknown")
                logger.warning(f"[OrderLock] 잠금 실패: {symbol} (기존 order={existing})")
                return False

        lock = self._get_lock(symbol)
        acquired = lock.acquire(blocking=False)
        if acquired:
            with self._meta_lock:
                self._locked[symbol] = order_id
                self._locked_at[symbol] = datetime.now()
            logger.debug(f"[OrderLock] 잠금 획득: {symbol} order={order_id}")
        else:
            existing = self._locked.get(symbol, "unknown")
            logger.warning(f"[OrderLock] 잠금 실패: {symbol} (기존 order={existing})")
        return acquired

    def release(self, symbol: str, order_id: str) -> bool:
        """
        종목 잠금 해제
        Returns: True if released
        """
        current_order = self._locked.get(symbol)
        if current_order != order_id:
            logger.warning(
                f"[OrderLock] 잠금 해제 불일치: {symbol} "
                f"요청={order_id} 현재={current_order}"
            )
            return False

        lock = self._get_lock(symbol)
        try:
            lock.release()
            with self._meta_lock:
                self._locked.pop(symbol, None)
                self._locked_at.pop(symbol, None)
            logger.debug(f"[OrderLock] 잠금 해제: {symbol} order={order_id}")
            return True
        except RuntimeError:
            logger.error(f"[OrderLock] 잠금 해제 실패: {symbol}")
            return False

    def is_locked(self, symbol: str) -> bool:
        return symbol in self._locked

    def get_locked_order(self, symbol: str) -> Optional[str]:
        return self._locked.get(symbol)

    def get_lock_duration(self, symbol: str) -> Optional[float]:
        """잠금 경과 시간 (초)"""
        locked_at = self._locked_at.get(symbol)
        if locked_at is None:
            return None
        return (datetime.now() - locked_at).total_seconds()

    def get_all_locks(self) -> Dict[str, str]:
        return dict(self._locked)

    def force_release(self, symbol: str) -> None:
        """긴급 잠금 해제 (복구용)"""
        lock = self._get_lock(symbol)
        try:
            lock.release()
        except RuntimeError:
            pass
        with self._meta_lock:
            self._locked.pop(symbol, None)
            self._locked_at.pop(symbol, None)
        logger.warning(f"[OrderLock] 강제 해제: {symbol}")


# 싱글톤
_order_lock: Optional[OrderLock] = None


def get_order_lock() -> OrderLock:
    global _order_lock
    if _order_lock is None:
        _order_lock = OrderLock()
    return _order_lock
