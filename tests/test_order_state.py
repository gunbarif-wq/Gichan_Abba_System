"""Order State / Order Lock 테스트"""
import pytest
from shared.schemas import OrderState
from trade.order_state import OrderStateManager
from trade.order_lock import OrderLock


def test_initial_state_is_idle():
    mgr = OrderStateManager()
    assert mgr.get_state("005930") == OrderState.IDLE


def test_can_buy_when_idle():
    mgr = OrderStateManager()
    ok, reason = mgr.can_buy("005930")
    assert ok is True


def test_cannot_buy_when_pending():
    mgr = OrderStateManager()
    mgr.set_state("005930", OrderState.BUY_PENDING)
    ok, reason = mgr.can_buy("005930")
    assert ok is False
    assert "BUY_PENDING" in reason


def test_cannot_buy_when_unknown():
    mgr = OrderStateManager()
    mgr.set_state("005930", OrderState.UNKNOWN)
    ok, _ = mgr.can_buy("005930")
    assert ok is False


def test_cannot_sell_when_sell_pending():
    mgr = OrderStateManager()
    mgr.set_state("005930", OrderState.SELL_PENDING)
    ok, _ = mgr.can_sell("005930")
    assert ok is False


def test_state_reset():
    mgr = OrderStateManager()
    mgr.set_state("005930", OrderState.BUY_FILLED)
    mgr.reset("005930")
    assert mgr.get_state("005930") == OrderState.IDLE


def test_order_lock_acquire_release():
    lock = OrderLock()
    assert lock.acquire("005930", "order_001") is True
    assert lock.is_locked("005930") is True
    assert lock.release("005930", "order_001") is True
    assert lock.is_locked("005930") is False


def test_order_lock_double_acquire():
    lock = OrderLock()
    lock.acquire("005930", "order_001")
    assert lock.acquire("005930", "order_002") is False


def test_order_lock_wrong_order_id():
    lock = OrderLock()
    lock.acquire("005930", "order_001")
    assert lock.release("005930", "wrong_id") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
