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
    
    가격/수량/신뢰도 기본 검증 + confidence 내림차순 정렬
    """
    
    def __init__(self):
        """신호 엔진 초기화"""
        logger.info("[SignalEngine] 초기화 완료")
    
    def validate_signal(self, signal: Signal) -> bool:
        """가격/수량 기본 유효성 검사"""
        if signal.price <= 0:
            logger.debug(f"[SignalEngine] 무효 신호 (가격=0): {signal.symbol}")
            return False
        if signal.quantity <= 0:
            logger.debug(f"[SignalEngine] 무효 신호 (수량=0): {signal.symbol}")
            return False
        if signal.confidence < 0.1:
            logger.debug(f"[SignalEngine] 신뢰도 낮음({signal.confidence:.2f}): {signal.symbol}")
            return False
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
        # confidence 내림차순 → 같으면 timestamp 오름차순 (빠른 신호 우선)
        sorted_signals = sorted(
            signals,
            key=lambda s: (-s.confidence, s.timestamp),
        )
        return sorted_signals


# 전역 신호 엔진 인스턴스
_signal_engine: Optional[SignalEngine] = None


def get_signal_engine() -> SignalEngine:
    """신호 엔진 싱글톤 반환"""
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = SignalEngine()
    return _signal_engine
