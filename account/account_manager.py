"""
Account Manager
계좌 관리 및 현금/자산 추적
"""

import logging
from datetime import datetime
from typing import Optional

from shared.schemas import Account, Position, Mode, Order, OrderSide
from shared.errors import InsufficientCash, ZeroHoldings
from trade.position_manager import get_position_manager

logger = logging.getLogger(__name__)


class AccountManager:
    """
    계좌 관리자
    - 현금 관리
    - 포지션 관리
    - 자산 추적
    """
    
    def __init__(self, mode: Mode, initial_cash: float):
        """
        계좌 관리자 초기화
        
        Args:
            mode: 운영 모드
            initial_cash: 초기 현금
        """
        self.mode = mode
        self.total_cash = initial_cash
        self.available_cash = initial_cash
        self.position_manager = get_position_manager()
        logger.info(
            f"[AccountManager] 초기화: {mode.value} 모드, "
            f"초기 현금 {initial_cash:,}원"
        )
    
    def get_account(self) -> Account:
        """
        계좌 정보 조회
        
        Returns:
            계좌 객체
        """
        # 포지션 총액 계산
        position_amount = self.position_manager.get_total_position_amount()
        
        # 총 자산 = 현금 + 포지션 가치
        total_asset = self.total_cash + position_amount
        
        account = Account(
            mode=self.mode,
            total_cash=self.total_cash,
            available_cash=self.available_cash,
            total_asset=total_asset,
            positions=self.position_manager.get_all_positions(),
            timestamp=datetime.now(),
        )
        
        return account
    
    def can_buy(self, symbol: str, quantity: int, price: float, 
                commission_rate: float = 0.00015) -> bool:
        """
        매수 가능 여부 확인
        
        Args:
            symbol: 종목 코드
            quantity: 주문 수량
            price: 주문 가격
            commission_rate: 수수료율
        
        Returns:
            매수 가능 여부
        """
        order_amount = quantity * price
        commission = order_amount * commission_rate
        total_required = order_amount + commission
        
        if self.available_cash < total_required:
            logger.warning(
                f"[AccountManager] {symbol} 매수 불가: "
                f"필요금액={total_required:,} > 가능금액={self.available_cash:,}"
            )
            return False
        
        return True
    
    def can_sell(self, symbol: str, quantity: int) -> bool:
        """
        매도 가능 여부 확인
        
        Args:
            symbol: 종목 코드
            quantity: 매도 수량
        
        Returns:
            매도 가능 여부
        """
        position = self.position_manager.get_position(symbol)
        
        if not position or position.quantity == 0:
            logger.warning(f"[AccountManager] {symbol} 보유 수량 없음")
            return False
        
        if position.quantity < quantity:
            logger.warning(
                f"[AccountManager] {symbol} 매도 수량 초과: "
                f"보유={position.quantity} 요청={quantity}"
            )
            return False
        
        return True
    
    def deduct_for_buy(self, symbol: str, quantity: int, price: float,
                       commission: float) -> None:
        """
        매수 시 현금 차감
        
        Args:
            symbol: 종목 코드
            quantity: 매수 수량
            price: 매수 가격
            commission: 수수료
        
        Raises:
            InsufficientCash: 현금 부족
        """
        order_amount = quantity * price
        total_deduct = order_amount + commission
        
        if self.available_cash < total_deduct:
            raise InsufficientCash(
                f"현금 부족: 필요={total_deduct:,} 가능={self.available_cash:,}"
            )
        
        self.available_cash -= total_deduct
        
        logger.info(
            f"[AccountManager] {symbol} 매수 현금 차감: {total_deduct:,}원 "
            f"(남은 현금: {self.available_cash:,}원)"
        )
    
    def add_for_sell(self, symbol: str, quantity: int, price: float,
                     commission: float, tax: float = 0.0) -> None:
        """
        매도 시 현금 추가
        
        Args:
            symbol: 종목 코드
            quantity: 매도 수량
            price: 매도 가격
            commission: 수수료
            tax: 거래세
        """
        sell_amount = quantity * price
        net_proceed = sell_amount - commission - tax
        
        self.available_cash += net_proceed
        
        logger.info(
            f"[AccountManager] {symbol} 매도 현금 추가: {net_proceed:,}원 "
            f"(남은 현금: {self.available_cash:,}원)"
        )
    
    def update_position(self, symbol: str, name: str, quantity: int,
                        price: float, commission: float = 0.0) -> Position:
        """
        포지션 업데이트 (매수 반영)
        
        Args:
            symbol: 종목 코드
            name: 종목명
            quantity: 매수 수량
            price: 매수 가격
            commission: 수수료
        
        Returns:
            업데이트된 포지션
        """
        position = self.position_manager.add_buy_fill(
            symbol=symbol,
            name=name,
            quantity=quantity,
            price=price,
            commission=commission
        )
        
        logger.debug(
            f"[AccountManager] {symbol} 포지션 업데이트: "
            f"수량={position.quantity} 평균가={position.avg_buy_price:,}"
        )
        
        return position
    
    def remove_position(self, symbol: str, quantity: int) -> Optional[Position]:
        """
        포지션 감소 (매도 반영)
        
        Args:
            symbol: 종목 코드
            quantity: 매도 수량
        
        Returns:
            업데이트된 포지션 또는 None
        """
        position = self.position_manager.add_sell_fill(symbol, quantity)
        
        if position:
            logger.debug(
                f"[AccountManager] {symbol} 포지션 감소: "
                f"남은 수량={position.quantity}"
            )
        
        return position
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        포지션 조회
        
        Args:
            symbol: 종목 코드
        
        Returns:
            포지션 객체 또는 None
        """
        return self.position_manager.get_position(symbol)
    
    def get_all_positions(self) -> dict[str, Position]:
        """
        모든 포지션 조회
        
        Returns:
            포지션 딕셔너리
        """
        return self.position_manager.get_all_positions()
    
    def get_total_asset(self) -> float:
        """
        총 자산 계산 (현금 + 포지션 가치)
        
        Returns:
            총 자산
        """
        position_amount = self.position_manager.get_total_position_amount()
        return self.total_cash + position_amount
    
    def get_cash_ratio(self) -> float:
        """
        현금 비율 계산
        
        Returns:
            현금 / 총자산 비율
        """
        total_asset = self.get_total_asset()
        if total_asset == 0:
            return 1.0
        return self.available_cash / total_asset
    
    def get_position_amount(self) -> float:
        """
        포지션 총액 계산
        
        Returns:
            포지션 총액
        """
        return self.position_manager.get_total_position_amount()
    
    def get_position_ratio(self, symbol: str) -> float:
        """
        종목별 비중 계산
        
        Args:
            symbol: 종목 코드
        
        Returns:
            종목 비중 (0~1)
        """
        total_asset = self.get_total_asset()
        if total_asset == 0:
            return 0.0
        
        position = self.position_manager.get_position(symbol)
        if not position:
            return 0.0
        
        return position.total_buy_amount / total_asset
    
    def clear_all(self) -> None:
        """모든 계좌 정보 초기화"""
        self.position_manager.clear_all_positions()
        self.available_cash = self.total_cash
        logger.info("[AccountManager] 모든 계좌 초기화")


# 전역 계좌 관리자 인스턴스
_account_manager: Optional[AccountManager] = None


def get_account_manager() -> AccountManager:
    """계좌 관리자 싱글톤 반환"""
    global _account_manager
    if _account_manager is None:
        raise RuntimeError("AccountManager not initialized")
    return _account_manager


def init_account_manager(mode: Mode, initial_cash: float) -> AccountManager:
    """계좌 관리자 초기화"""
    global _account_manager
    _account_manager = AccountManager(mode, initial_cash)
    return _account_manager
