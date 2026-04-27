"""
Signal Engine
거래 신호 생성 및 필터링
"""

import logging
from typing import Optional, List

from shared.schemas import Signal, OrderSide

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    신호 엔진
    
    역할:
    - Council에서 생성한 매수 후보 검증
    - 신호 필터링
    - 신호 우선순위 결정
    
    TODO: 실제 신호 필터링 로직 구현
    """
    
    def __init__(self):
        """신호 엔진 초기화"""
        logger.info("[SignalEngine] 초기화 완료")
    
    def validate_signal(self, signal: Signal) -> bool:
        """
        신호 검증
        
        Args:
            signal: 거래 신호
        
        Returns:
            유효한 신호 여부
        """
        logger.debug(f"[SignalEngine] 신호 검증: {signal.symbol} {signal.side.value}")
        
        # Paper 모드: 모든 신호 수락
        return True
    
    def filter_signals(self, signals: List[Signal]) -> List[Signal]:
        """
        신호 필터링
        
        Args:
            signals: 신호 목록
        
        Returns:
            필터링된 신호
        """
        validated = [s for s in signals if self.validate_signal(s)]
        logger.info(f"[SignalEngine] 신호 필터링: {len(signals)} → {len(validated)}")
        return validated
    
    def rank_signals(self, signals: List[Signal]) -> List[Signal]:
        """
        신호 우선순위 결정
        
        Args:
            signals: 신호 목록
        
        Returns:
            우선순위 정렬된 신호
        """
        # TODO: 신뢰도 기반 우선순위 결정
        sorted_signals = sorted(signals, key=lambda s: s.confidence, reverse=True)
        return sorted_signals


# 전역 신호 엔진 인스턴스
_signal_engine: Optional[SignalEngine] = None


def get_signal_engine() -> SignalEngine:
    """신호 엔진 싱글톤 반환"""
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = SignalEngine()
    return _signal_engine
