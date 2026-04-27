"""
Paper Mode Broker
가상 계좌로 주문을 즉시 체결한다.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from shared.schemas import Order, Fill, OrderState, OrderSide, OrderType
from shared.errors import ExecutionException

logger = logging.getLogger(__name__)


class PaperBroker:
    """
    Paper 모드 브로커
    - 즉시 체결
    - API 호출 없음
    - 완전한 거래 시뮬레이션
    """
    
    def __init__(self):
        """브로커 초기화"""
        self.name = "PaperBroker"
        self.mode = "paper"
        logger.info(f"[{self.name}] 초기화 완료")
    
    def place_order(self, order: Order) -> Order:
        """
        주문 생성 및 즉시 체결
        
        Args:
            order: 주문 객체
        
        Returns:
            체결된 주문 객체
        
        Raises:
            ExecutionException: 주문 실행 실패
        """
        try:
            logger.info(
                f"[{self.name}] 주문 생성: {order.symbol} "
                f"{order.side.value} {order.quantity}주 @ {order.price:,}원"
            )
            
            # 주문 ID 할당
            if not order.order_id:
                order.order_id = str(uuid4())
            
            # 주문 시간 기록
            order.sent_time = datetime.now()
            order.state = OrderState.BUY_SENT if order.side == OrderSide.BUY else OrderState.SELL_SENT
            
            # Paper 모드: 즉시 체결
            self._execute_fill(order)
            
            logger.info(
                f"[{self.name}] 주문 체결: {order.order_id} "
                f"{order.symbol} {order.filled_quantity}주 @ {order.avg_filled_price:,}원"
            )
            
            return order
            
        except Exception as e:
            logger.error(f"[{self.name}] 주문 실행 실패: {str(e)}")
            order.state = OrderState.FAILED
            raise ExecutionException(f"주문 실행 실패: {str(e)}")
    
    def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소 (Paper 모드는 체결됨)
        
        Args:
            order_id: 주문 ID
        
        Returns:
            취소 성공 여부
        """
        logger.warning(f"[{self.name}] Paper 모드에서 취소 불가: {order_id}")
        return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """
        주문 상태 조회 (Paper 모드는 구현하지 않음)
        
        Args:
            order_id: 주문 ID
        
        Returns:
            주문 객체 또는 None
        """
        logger.debug(f"[{self.name}] 주문 상태 조회: {order_id} (Paper 모드)")
        return None
    
    def _execute_fill(self, order: Order) -> None:
        """
        주문을 즉시 체결 처리
        
        Args:
            order: 주문 객체
        """
        # 전체 수량 체결
        order.filled_quantity = order.quantity
        order.avg_filled_price = order.price
        order.filled_time = datetime.now()
        
        # 수수료 계산 (0.015%)
        commission = order.amount * 0.00015
        order.commission = commission
        
        # 상태 업데이트
        if order.side == OrderSide.BUY:
            order.state = OrderState.BUY_FILLED
        else:
            order.state = OrderState.SELL_FILLED
        
        logger.debug(
            f"[{self.name}] 체결 완료: {order.order_id} "
            f"수량={order.filled_quantity} 평균가={order.avg_filled_price:,} "
            f"수수료={order.commission:.0f}"
        )


# 전역 Paper 브로커 인스턴스
_paper_broker: Optional[PaperBroker] = None


def get_paper_broker() -> PaperBroker:
    """Paper 브로커 싱글톤 반환"""
    global _paper_broker
    if _paper_broker is None:
        _paper_broker = PaperBroker()
    return _paper_broker
