"""
Market Clock — 운영 시간 관리

KRX (한국거래소 — KOSPI/KOSDAQ):
  장전 시간외:  07:30~08:30  (전일 종가 단일가)
  동시호가:     08:30~09:00
  정규장:       09:00~15:30
  장후 시간외:  15:40~16:00

NXT (넥스트레이드):
  장전 시간외:  07:00~08:00  (전일 종가 단일가)
  정규장:       08:00~16:00
  장후 시간외:  16:00~18:00

최종 종목 선정: 08:00:10 (양쪽 모두 장전 시간외 매수 가능)
"""

import logging
from datetime import datetime, time as dtime
from typing import Optional

from shared.schemas import SessionType, Mode

logger = logging.getLogger(__name__)

# ── KRX 시간 상수 ──────────────────────────────────────────────────────────────
KRX_PREMARKET_START  = dtime(7, 30)       # KRX 장전 시간외 시작 (전일 종가 단일가)
KRX_PREMARKET_END    = dtime(8, 30)       # KRX 동시호가 시작
KRX_MARKET_OPEN      = dtime(9,  0)       # KRX 정규장 시작
KRX_MARKET_CLOSE     = dtime(15, 30)      # KRX 정규장 종료
KRX_AFTERMARKET_END  = dtime(16,  0)      # KRX 장후 시간외 종료
KRX_BUY_END          = dtime(15, 20)      # KRX 매수 마감 (장마감 10분 전)

# ── NXT 시간 상수 ──────────────────────────────────────────────────────────────
NXT_PREMARKET_START  = dtime(7,  0)       # NXT 장전 단일가 시작
NXT_PREMARKET_END    = dtime(8,  0)       # NXT 정규장 시작
NXT_MARKET_OPEN      = dtime(8,  0)       # NXT 정규장 시작
NXT_MARKET_CLOSE     = dtime(20,  0)      # NXT 정규장 종료 (20:00!)
NXT_AFTERMARKET_END  = dtime(20,  0)      # NXT는 장후 시간외 별도 없음
NXT_BUY_END          = dtime(19, 50)      # NXT 매수 마감 (장마감 10분 전)

# ── 공통 ───────────────────────────────────────────────────────────────────────
SELECTION_TIME  = dtime(8,  0, 10)        # 최종 종목 선정 (08:00:10)
MONITOR_START   = dtime(8,  0)            # 모니터링 시작
SELL_END        = dtime(20,  0)           # 매도/감시 종료 (장후 안전마진 포함)

# 하위 호환용 별칭
BUY_START    = SELECTION_TIME
BUY_END      = KRX_BUY_END
MARKET_OPEN  = KRX_MARKET_OPEN
MARKET_CLOSE = KRX_MARKET_CLOSE


class ExchangeSchedule:
    """거래소별 시간 스케줄"""

    @staticmethod
    def is_premarket(exchange: str) -> bool:
        """현재 장전 시간외 여부"""
        t = datetime.now().time()
        if exchange == "NXT":
            return NXT_PREMARKET_START <= t < NXT_PREMARKET_END
        # KRX (KOSPI / KOSDAQ)
        return KRX_PREMARKET_START <= t < KRX_PREMARKET_END

    @staticmethod
    def is_market_open(exchange: str) -> bool:
        """현재 정규장 여부"""
        t = datetime.now().time()
        if exchange == "NXT":
            return NXT_MARKET_OPEN <= t <= NXT_MARKET_CLOSE
        return KRX_MARKET_OPEN <= t <= KRX_MARKET_CLOSE

    @staticmethod
    def can_buy(exchange: str) -> bool:
        """매수 가능 시간 여부 (장전 시간외 + 정규장)"""
        t = datetime.now().time()
        if exchange == "NXT":
            return NXT_PREMARKET_START <= t <= NXT_BUY_END
        return KRX_PREMARKET_START <= t <= KRX_BUY_END

    @staticmethod
    def buy_order_type(exchange: str) -> str:
        """
        현재 시간 기준 매수 주문 유형 반환
          'premarket'  — 장전 시간외 (전일 종가 단일가)
          'market'     — 정규장 시장가
          'none'       — 매수 불가
        """
        t = datetime.now().time()
        if exchange == "NXT":
            if NXT_PREMARKET_START <= t < NXT_PREMARKET_END:
                return "premarket"
            if NXT_MARKET_OPEN <= t <= NXT_BUY_END:
                return "market"
        else:  # KRX
            if KRX_PREMARKET_START <= t < KRX_PREMARKET_END:
                return "premarket"
            if KRX_MARKET_OPEN <= t <= KRX_BUY_END:
                return "market"
        return "none"

    @staticmethod
    def aftermarket_end(exchange: str) -> dtime:
        return NXT_AFTERMARKET_END if exchange == "NXT" else KRX_AFTERMARKET_END


class MarketClock:

    def __init__(self, mode: Mode, time_check_enabled: bool = True):
        self.mode               = mode
        self.time_check_enabled = time_check_enabled
        logger.info(
            f"[MarketClock] {mode.value} 모드 | "
            f"KRX {KRX_MARKET_OPEN:%H:%M}~{KRX_MARKET_CLOSE:%H:%M} (매수마감 {KRX_BUY_END:%H:%M}) | "
            f"NXT {NXT_MARKET_OPEN:%H:%M}~{NXT_MARKET_CLOSE:%H:%M} (매수마감 {NXT_BUY_END:%H:%M})"
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
        """KRX 정규장 여부 (09:00~15:30) — 하위 호환"""
        if not self.time_check_enabled:
            return True
        return ExchangeSchedule.is_market_open("KRX")

    def can_buy(self, exchange: str = "KRX") -> bool:
        """거래소별 매수 가능 여부"""
        if not self.time_check_enabled:
            return True
        return ExchangeSchedule.can_buy(exchange)

    def buy_order_type(self, exchange: str = "KRX") -> str:
        """거래소별 현재 주문 유형"""
        if not self.time_check_enabled:
            return "market"
        return ExchangeSchedule.buy_order_type(exchange)

    def can_sell(self) -> bool:
        """매도 가능 여부 (08:00~20:00)"""
        if not self.time_check_enabled:
            return True
        t = self._now()
        return MONITOR_START <= t <= SELL_END

    def get_session(self, exchange: str = "KRX") -> SessionType:
        if not self.time_check_enabled:
            return SessionType.MAIN
        t = self._now()
        if t > SELL_END:
            return SessionType.CLOSED
        if ExchangeSchedule.is_premarket(exchange):
            return SessionType.PREMARKET
        if ExchangeSchedule.is_market_open(exchange):
            return SessionType.MAIN
        if t <= ExchangeSchedule.aftermarket_end(exchange):
            return SessionType.AFTERMARKET
        return SessionType.CLOSED

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
