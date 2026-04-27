"""
Broker Interface
다양한 브로커를 지원하기 위한 추상 인터페이스
"""

from abc import ABC, abstractmethod
from typing import Optional

from shared.schemas import Order


class BrokerInterface(ABC):
    """
    브로커 인터페이스
    
    구현체:
    - PaperBroker (완료)
    - KISMockBroker (TODO)
    - KISLiveBroker (TODO)
    - NXTBroker (TODO)
    """
    
    @abstractmethod
    def place_order(self, order: Order) -> Order:
        """
        주문 생성
        
        Args:
            order: 주문 객체
        
        Returns:
            체결된 주문
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소
        
        Args:
            order_id: 주문 ID
        
        Returns:
            취소 성공 여부
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """
        주문 상태 조회
        
        Args:
            order_id: 주문 ID
        
        Returns:
            주문 객체 또는 None
        """
        pass
