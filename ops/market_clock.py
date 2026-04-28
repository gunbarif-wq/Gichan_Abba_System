"""
Market Clock — 운영 시간 관리
모니터링: 08:00 ~ 20:00
매수:     08:02 ~ 15:20
매도:     08:00 ~ 20:00
"""

import logging
from datetime import datetime, time as dtime
from typing import Optional

from shared.schemas import SessionType, Mode

logger = logging.getLogger(__name__)

# ── 운영 시간 상수 ─────────────────────────────────────────────────────────────
MONITOR_START = dtime(8,  0)   # 모니터링 시작
BUY_START     = dtime(8,  2)   # 매수 시작 (08:02)
BUY_END       = dtime(15, 20)  # 매수 종료 (장마감 전 10분)
SELL_END      = dtime(20,  0)  # 매도/감시 종료
MARKET_OPEN   = dtime(9,  0)   # 정규장 시작
MARKET_CLOSE  = dtime(15, 30)  # 정규장 종료


class MarketClock:

    def __init__(self, mode: Mode, time_check_enabled: bool = True):
        self.mode               = mode
        self.time_check_enabled = time_check_enabled
        logger.info(
            f"[MarketClock] {mode.value} 모드 | "
            f"매수 {BUY_START:%H:%M}~{BUY_END:%H:%M} | "
            f"감시 {MONITOR_START:%H:%M}~{SELL_END:%H:%M}"
        )

    def _now(self) -> dtime:
        return datetime.now().time()

    def is_monitoring(self) -> bool:
        """모니터링 시간 여부 (08:00~20:00)"""
        if not self.time_check_enabled:
            return True
        t = self._now()
        return MONITOR_START <= t <= SELL_END

    def is_market_open(self) -> bool:
        """정규장 여부 (09:00~15:30)"""
        if not self.time_check_enabled:
            return True
        t = self._now()
        return MARKET_OPEN <= t <= MARKET_CLOSE

    def can_buy(self) -> bool:
        """매수 가능 여부 (08:02~15:20)"""
        if not self.time_check_enabled:
            return True
        t = self._now()
        return BUY_START <= t <= BUY_END

    def can_sell(self) -> bool:
        """매도 가능 여부 (08:00~20:00)"""
        if not self.time_check_enabled:
            return True
        t = self._now()
        return MONITOR_START <= t <= SELL_END

    def get_session(self) -> SessionType:
        if not self.time_check_enabled:
            return SessionType.MAIN
        t = self._now()
        if t < MONITOR_START or t > SELL_END:
            return SessionType.CLOSED
        if t < MARKET_OPEN:
            return SessionType.PREMARKET
        if t <= MARKET_CLOSE:
            return SessionType.MAIN
        return SessionType.AFTERMARKET

    def get_current_time(self) -> datetime:
        return datetime.now()

    def format_time(self, dt: datetime = None) -> str:
        if dt is None:
            dt = datetime.now()
        return dt.strftime("%Y-%m-%d %H:%M:%S")


_market_clock: Optional[MarketClock] = None

def get_market_clock() -> MarketClock:
    global _market_clock
    if _market_clock is None:
        _market_clock = MarketClock(Mode.PAPER, time_check_enabled=False)
    return _market_clock

def init_market_clock(mode: Mode, time_check_enabled: bool = True) -> MarketClock:
    global _market_clock
    _market_clock = MarketClock(mode, time_check_enabled)
    return _market_clock
