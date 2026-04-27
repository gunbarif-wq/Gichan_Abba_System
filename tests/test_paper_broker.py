"""
Paper Broker 테스트
"""

import pytest
from shared.schemas import Order, OrderState, OrderSide, OrderType
from trade.paper_broker import PaperBroker


@pytest.fixture
def broker():
    """브로커 픽스처"""
    return PaperBroker()


@pytest.fixture
def buy_order():
    """매수 주문 픽스처"""
    return Order(
        order_id="test_order_001",
        symbol="005930",
        name="삼성전자",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=70000.0,
        amount=700000.0,
        reason="test buy",
    )


@pytest.fixture
def sell_order():
    """매도 주문 픽스처"""
    return Order(
        order_id="test_order_002",
        symbol="005930",
        name="삼성전자",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=72000.0,
        amount=720000.0,
        reason="test sell",
    )


def test_paper_broker_initialization(broker):
    """브로커 초기화 테스트"""
    assert broker.name == "PaperBroker"
    assert broker.mode == "paper"


def test_place_buy_order(broker, buy_order):
    """매수 주문 체결 테스트"""
    executed = broker.place_order(buy_order)
    
    # 주문 ID 할당 확인
    assert executed.order_id is not None
    
    # 체결 상태 확인
    assert executed.state == OrderState.BUY_FILLED
    
    # 체결 수량 확인
    assert executed.filled_quantity == buy_order.quantity
    
    # 체결가 확인
    assert executed.avg_filled_price == buy_order.price
    
    # 수수료 확인 (0.015%)
    expected_commission = buy_order.amount * 0.00015
    assert abs(executed.commission - expected_commission) < 1


def test_place_sell_order(broker, sell_order):
    """매도 주문 체결 테스트"""
    executed = broker.place_order(sell_order)
    
    # 체결 상태 확인
    assert executed.state == OrderState.SELL_FILLED
    
    # 체결 수량 확인
    assert executed.filled_quantity == sell_order.quantity
    
    # 체결가 확인
    assert executed.avg_filled_price == sell_order.price


def test_commission_calculation(broker, buy_order):
    """수수료 계산 테스트"""
    executed = broker.place_order(buy_order)
    
    # 수수료율 0.015%
    expected_commission = buy_order.amount * 0.00015
    
    assert abs(executed.commission - expected_commission) < 1


def test_cancel_order_not_supported(broker, buy_order):
    """취소 불가 테스트 (Paper 모드)"""
    result = broker.cancel_order("some_order_id")
    assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
