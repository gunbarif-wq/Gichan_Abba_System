"""
Market Clock
시장 시간 관리
"""

import logging
from datetime import datetime
from enum import Enum

from shared.schemas import SessionType, Mode

logger = logging.getLogger(__name__)


class MarketClock:
    """
    시장 시간 관리자
    
    Paper 모드:
    - 시간 제한 없음
    - 항상 거래 가능
    
    Mock/Live 모드:
    - 실제 거래시간 체크
    """
    
    def __init__(self, mode: Mode, time_check_enabled: bool = True):
        """
        시장 시간 관리자 초기화
        
        Args:
            mode: 운영 모드
            time_check_enabled: 시간 체크 활성화 여부
        """
        self.mode = mode
        self.time_check_enabled = time_check_enabled
        logger.info(
            f"[MarketClock] 초기화: {mode.value} 모드, "
            f"시간체크={'활성화' if time_check_enabled else '비활성화'}"
        )
    
    def is_market_open(self) -> bool:
        """
        현재 거래시간 여부
        
        Returns:
            거래 가능 여부
        """
        if self.mode == Mode.PAPER or not self.time_check_enabled:
            # Paper 모드는 항상 열려있음
            return True
        
        # TODO: Mock/Live 모드에서 실제 시간 체크
        return True
    
    def can_buy(self) -> bool:
        """
        신규 매수 가능 여부
        
        Returns:
            매수 가능 여부
        """
        if self.mode == Mode.PAPER or not self.time_check_enabled:
            return True
        
        # TODO: 신규 매수 제한 시간 체크
        # 08:50~09:30, 15:20~15:40 제한
        return True
    
    def can_sell(self) -> bool:
        """
        매도 가능 여부
        
        Returns:
            매도 가능 여부
        """
        if self.mode == Mode.PAPER or not self.time_check_enabled:
            return True
        
        return True
    
    def get_session(self) -> SessionType:
        """
        현재 거래 세션
        
        Returns:
            세션 타입
        """
        if self.mode == Mode.PAPER or not self.time_check_enabled:
            return SessionType.MAIN
        
        # TODO: 실제 시간 기반 세션 결정
        now = datetime.now().time()
        
        # KRX 정규장: 09:00 ~ 15:30
        morning = datetime.strptime("09:00", "%H:%M").time()
        afternoon = datetime.strptime("15:30", "%H:%M").time()
        
        if morning <= now <= afternoon:
            return SessionType.MAIN
        else:
            return SessionType.CLOSED
    
    def get_current_time(self) -> datetime:
        """현재 시간"""
        return datetime.now()
    
    def format_time(self, dt: datetime = None) -> str:
        """시간 포맷"""
        if dt is None:
            dt = datetime.now()
        return dt.strftime("%Y-%m-%d %H:%M:%S")


# 전역 시장 시간 관리자 인스턴스
_market_clock: MarketClock = None


def get_market_clock() -> MarketClock:
    """시장 시간 관리자 싱글톤 반환"""
    global _market_clock
    if _market_clock is None:
        _market_clock = MarketClock(Mode.PAPER, time_check_enabled=False)
    return _market_clock


def init_market_clock(mode: Mode, time_check_enabled: bool = True) -> MarketClock:
    """시장 시간 관리자 초기화"""
    global _market_clock
    _market_clock = MarketClock(mode, time_check_enabled)
    return _market_clock
