"""Order Manager 테스트"""
import pytest
from shared.schemas import Signal, OrderSide, OrderState, Mode


@pytest.fixture(autouse=True)
def reset_singletons():
    import trade.order_manager as om
    import trade.paper_broker as pb
    om._order_manager = None
    pb._paper_broker = None
    yield


@pytest.fixture
def order_manager():
    from trade.order_manager import get_order_manager
    return get_order_manager()


@pytest.fixture
def buy_signal():
    return Signal(
        symbol="005930",
        name="삼성전자",
        side=OrderSide.BUY,
        price=70000.0,
        quantity=10,
        reason="test",
    )


@pytest.fixture
def sell_signal():
    return Signal(
        symbol="005930",
        name="삼성전자",
        side=OrderSide.SELL,
        price=72000.0,
        quantity=10,
        reason="test",
    )


def test_create_buy_order(order_manager, buy_signal):
    """매수 주문 생성 테스트"""
    order = order_manager.create_order(buy_signal, 70000.0, 10)
    assert order.order_id is not None
    assert order.state == OrderState.BUY_FILLED
    assert order.filled_quantity == 10
    assert order.avg_filled_price == 70000.0


def test_create_sell_order(order_manager, sell_signal):
    """매도 주문 생성 테스트"""
    order = order_manager.create_order(sell_signal, 72000.0, 10)
    assert order.state == OrderState.SELL_FILLED
    assert order.filled_quantity == 10


def test_get_order(order_manager, buy_signal):
    """주문 조회 테스트"""
    created = order_manager.create_order(buy_signal, 70000.0, 10)
    found = order_manager.get_order(created.order_id)
    assert found is not None
    assert found.order_id == created.order_id


def test_get_orders_by_symbol(order_manager, buy_signal):
    """종목별 주문 조회"""
    order_manager.create_order(buy_signal, 70000.0, 10)
    orders = order_manager.get_orders_by_symbol("005930")
    assert len(orders) >= 1


def test_no_pending_buy_after_fill(order_manager, buy_signal):
    """체결 완료 후 미체결 매수 없음"""
    order_manager.create_order(buy_signal, 70000.0, 10)
    assert not order_manager.has_pending_buy("005930")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
