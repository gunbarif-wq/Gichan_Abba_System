"""
Order Manager
주문 생성 및 실행
Risk Guard와 Broker 사이의 중계자
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from shared.schemas import Order, OrderState, OrderSide, OrderType, Signal
from shared.errors import OrderException, ExecutionException
from trade.paper_broker import get_paper_broker

logger = logging.getLogger(__name__)


class OrderManager:
    """
    주문 관리자
    - 주문 생성
    - Broker 호출
    - 주문 상태 추적
    - Risk Guard를 거친 주문만 실행
    """
    
    def __init__(self):
        """주문 관리자 초기화"""
        self.broker = get_paper_broker()
        self.orders: dict[str, Order] = {}
        logger.info("[OrderManager] 초기화 완료")
    
    def create_order(
        self,
        signal: Signal,
        price: float,
        quantity: int,
    ) -> Order:
        """
        주문 생성 및 실행
        
        Args:
            signal: 거래 신호
            price: 주문 가격
            quantity: 주문 수량
        
        Returns:
            생성된 주문 객체
        
        Raises:
            OrderException: 주문 생성 실패
        """
        try:
            logger.info(
                f"[OrderManager] 주문 생성: {signal.symbol} "
                f"{signal.side.value} {quantity}주 @ {price:,}원"
            )
            
            # 주문 객체 생성
            order = Order(
                order_id=str(uuid4()),
                symbol=signal.symbol,
                name=signal.name,
                side=signal.side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
                amount=quantity * price,
                reason=signal.reason,
            )
            
            # 주문 저장
            self.orders[order.order_id] = order
            
            # Broker에 주문 전달
            executed_order = self.broker.place_order(order)
            
            # 주문 업데이트
            self.orders[executed_order.order_id] = executed_order
            
            logger.info(
                f"[OrderManager] 주문 완료: {executed_order.order_id} "
                f"상태={executed_order.state.value}"
            )
            
            return executed_order
            
        except Exception as e:
            logger.error(f"[OrderManager] 주문 생성 실패: {str(e)}")
            raise OrderException(f"주문 생성 실패: {str(e)}")
    
    def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소
        
        Args:
            order_id: 주문 ID
        
        Returns:
            취소 성공 여부
        """
        if order_id not in self.orders:
            logger.warning(f"[OrderManager] 주문을 찾을 수 없음: {order_id}")
            return False
        
        order = self.orders[order_id]
        
        try:
            logger.info(f"[OrderManager] 주문 취소 요청: {order_id}")
            result = self.broker.cancel_order(order_id)
            
            if result:
                order.state = OrderState.CANCELLED
                logger.info(f"[OrderManager] 주문 취소 완료: {order_id}")
            else:
                logger.warning(f"[OrderManager] 주문 취소 실패: {order_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"[OrderManager] 주문 취소 중 오류: {str(e)}")
            return False
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        주문 조회
        
        Args:
            order_id: 주문 ID
        
        Returns:
            주문 객체 또는 None
        """
        return self.orders.get(order_id)
    
    def get_orders_by_symbol(self, symbol: str) -> list[Order]:
        """
        종목별 주문 조회
        
        Args:
            symbol: 종목 코드
        
        Returns:
            주문 목록
        """
        return [order for order in self.orders.values() if order.symbol == symbol]
    
    def get_pending_orders(self, symbol: Optional[str] = None) -> list[Order]:
        """
        미체결 주문 조회
        
        Args:
            symbol: 종목 코드 (선택)
        
        Returns:
            미체결 주문 목록
        """
        pending_states = [
            OrderState.BUY_PENDING,
            OrderState.BUY_SENT,
            OrderState.BUY_PARTIAL,
            OrderState.SELL_PENDING,
            OrderState.SELL_SENT,
            OrderState.SELL_PARTIAL,
        ]
        
        orders = [
            order for order in self.orders.values()
            if order.state in pending_states
        ]
        
        if symbol:
            orders = [order for order in orders if order.symbol == symbol]
        
        return orders
    
    def has_pending_buy(self, symbol: str) -> bool:
        """
        미체결 매수 주문 여부
        
        Args:
            symbol: 종목 코드
        
        Returns:
            미체결 매수 여부
        """
        buy_states = [
            OrderState.BUY_PENDING,
            OrderState.BUY_SENT,
            OrderState.BUY_PARTIAL,
        ]
        
        for order in self.orders.values():
            if order.symbol == symbol and order.side == OrderSide.BUY and order.state in buy_states:
                return True
        
        return False
    
    def has_pending_sell(self, symbol: str) -> bool:
        """
        미체결 매도 주문 여부
        
        Args:
            symbol: 종목 코드
        
        Returns:
            미체결 매도 여부
        """
        sell_states = [
            OrderState.SELL_PENDING,
            OrderState.SELL_SENT,
            OrderState.SELL_PARTIAL,
        ]
        
        for order in self.orders.values():
            if order.symbol == symbol and order.side == OrderSide.SELL and order.state in sell_states:
                return True
        
        return False
    
    def get_all_orders(self) -> dict[str, Order]:
        """
        모든 주문 조회
        
        Returns:
            주문 딕셔너리
        """
        return self.orders.copy()


# 전역 주문 관리자 인스턴스
_order_manager: Optional[OrderManager] = None


def get_order_manager() -> OrderManager:
    """주문 관리자 싱글톤 반환"""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager
