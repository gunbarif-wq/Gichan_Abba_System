"""
Position Manager
보유 포지션 추적 및 관리
"""

import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List

from shared.schemas import Position, Order, OrderSide, Fill

logger = logging.getLogger(__name__)


class PositionManager:
    """
    포지션 관리자
    - 보유 종목별 매입가, 수량, 손익 추적
    - 실제 계좌 조회 결과가 우선됨
    """
    
    def __init__(self):
        """포지션 관리자 초기화"""
        self.positions: Dict[str, Position] = {}
        self._lock = threading.RLock()
        self._realized_pnl: Dict[str, float] = {}  # symbol → 누적 실현 손익
        logger.info("[PositionManager] 초기화 완료")
    
    def add_buy_fill(self, symbol: str, name: str, quantity: int, price: float, 
                     commission: float = 0.0) -> Position:
        """
        매수 체결 반영
        
        Args:
            symbol: 종목 코드
            name: 종목명
            quantity: 체결 수량
            price: 체결 가격
            commission: 수수료
        
        Returns:
            업데이트된 포지션
        """
        logger.info(
            f"[PositionManager] 매수 반영: {symbol} {quantity}주 @ {price:,}원"
        )
        
        if symbol not in self.positions:
            # 새로운 포지션 생성
            self.positions[symbol] = Position(
                symbol=symbol,
                name=name,
                quantity=quantity,
                avg_buy_price=price,
                total_buy_amount=quantity * price,
            )
        else:
            # 기존 포지션 업데이트 (평가 매입가 계산)
            pos = self.positions[symbol]
            total_quantity = pos.quantity + quantity
            total_amount = pos.total_buy_amount + (quantity * price)
            new_avg_price = total_amount / total_quantity
            
            pos.quantity = total_quantity
            pos.avg_buy_price = new_avg_price
            pos.total_buy_amount = total_amount
        
        position = self.positions[symbol]
        position.last_update = datetime.now()
        
        logger.debug(
            f"[PositionManager] {symbol} 포지션 업데이트: "
            f"수량={position.quantity} 평균가={position.avg_buy_price:,}"
        )
        
        return position
    
    def add_sell_fill(self, symbol: str, quantity: int,
                     sell_price: float = 0.0,
                     commission: float = 0.0,
                     tax: float = 0.0) -> Optional[Position]:
        """
        매도 체결 반영 + 실현 손익 기록
        sell_price: 체결 가격 (0이면 손익 계산 생략)
        """
        if symbol not in self.positions:
            logger.warning(f"[PositionManager] {symbol} 포지션 없음")
            return None

        position = self.positions[symbol]

        if position.quantity < quantity:
            logger.warning(
                f"[PositionManager] {symbol} 매도 수량 초과: "
                f"보유={position.quantity} 매도={quantity}"
            )
            return None

        # 실현 손익 계산 (매도 단가 - 평균 매입가) * 수량 - 비용
        if sell_price > 0:
            realized = (sell_price - position.avg_buy_price) * quantity - commission - tax
            self._realized_pnl[symbol] = self._realized_pnl.get(symbol, 0.0) + realized
            logger.info(
                f"[PositionManager] {symbol} 매도 실현 손익: "
                f"{realized:+,.0f}원 (누적 {self._realized_pnl[symbol]:+,.0f}원)"
            )

        position.quantity -= quantity
        position.total_buy_amount = position.avg_buy_price * position.quantity
        position.last_update = datetime.now()

        if position.quantity == 0:
            del self.positions[symbol]
            logger.info(f"[PositionManager] {symbol} 포지션 제거 (수량=0)")

        return position
    
    def update_position_price(self, symbol: str, current_price: float) -> Optional[Position]:
        """
        현재가로 포지션 손익 계산
        
        Args:
            symbol: 종목 코드
            current_price: 현재가
        
        Returns:
            업데이트된 포지션 또는 None
        """
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        position.current_price = current_price
        
        # 손익 계산
        position.unrealized_pnl = (current_price - position.avg_buy_price) * position.quantity
        
        if position.total_buy_amount > 0:
            position.unrealized_pnl_ratio = (position.unrealized_pnl / position.total_buy_amount) * 100
        
        position.last_update = datetime.now()
        
        return position
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        포지션 조회
        
        Args:
            symbol: 종목 코드
        
        Returns:
            포지션 객체 또는 None
        """
        with self._lock:
            return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """
        모든 포지션 조회
        
        Returns:
            포지션 딕셔너리
        """
        with self._lock:
            return self.positions.copy()
    
    def get_total_position_amount(self) -> float:
        """
        총 포지션 금액 계산
        
        Returns:
            총 매입 금액
        """
        with self._lock:
            return sum(pos.total_buy_amount for pos in self.positions.values())
    
    def get_total_unrealized_pnl(self) -> float:
        """
        총 미실현 손익 계산
        
        Returns:
            총 미실현 손익
        """
        with self._lock:
            return sum(pos.unrealized_pnl for pos in self.positions.values())
    
    def clear_all_positions(self) -> None:
        """모든 포지션 삭제"""
        with self._lock:
            self.positions.clear()
        logger.info("[PositionManager] 모든 포지션 삭제")
    
    def has_position(self, symbol: str) -> bool:
        """
        포지션 보유 여부
        
        Args:
            symbol: 종목 코드
        
        Returns:
            보유 여부
        """
        with self._lock:
            return symbol in self.positions and self.positions[symbol].quantity > 0
    
    def get_position_quantity(self, symbol: str) -> int:
        """
        포지션 수량 조회
        
        Args:
            symbol: 종목 코드
        
        Returns:
            보유 수량 (없으면 0)
        """
        with self._lock:
            if symbol not in self.positions:
                return 0
            return self.positions[symbol].quantity


# 전역 포지션 관리자 인스턴스
_position_manager: Optional[PositionManager] = None


def get_position_manager() -> PositionManager:
    """포지션 관리자 싱글톤 반환"""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
