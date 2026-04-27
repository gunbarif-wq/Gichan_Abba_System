"""
Risk Guard 테스트
"""
import pytest
from unittest.mock import patch, MagicMock
from shared.schemas import Order, OrderSide, OrderType, Mode, OrderState
from shared.errors import RiskException
from risk.risk_manager import RiskManager


@pytest.fixture(autouse=True)
def reset_singletons():
    """싱글톤 초기화"""
    import account.account_manager as am
    import trade.order_manager as om
    import trade.position_manager as pm
    am._account_manager = None
    om._order_manager = None
    pm._position_manager = None
    yield


@pytest.fixture
def setup_account():
    from account.account_manager import init_account_manager
    from shared.schemas import Mode
    return init_account_manager(Mode.PAPER, 10_000_000)


@pytest.fixture
def risk_manager():
    rm = RiskManager.__new__(RiskManager)
    rm.config_path = ""
    rm.rejections = []
    rm.rules = {
        "max_position_ratio_per_stock": 0.20,
        "min_cash_ratio": 0.20,
        "max_positions": 5,
        "allow_live_trading": False,
        "new_buy_allowed": True,
        "emergency_stop": False,
    }
    return rm


@pytest.fixture
def buy_order():
    return Order(
        order_id="test_001",
        symbol="005930",
        name="삼성전자",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=70000.0,
        amount=700000.0,
        reason="test",
    )


def test_risk_passes_paper_mode(setup_account, risk_manager, buy_order):
    """Paper 모드 기본 리스크 통과"""
    result = risk_manager.check_order(buy_order, Mode.PAPER)
    assert result.passed is True


def test_live_trading_disabled(risk_manager, buy_order):
    """live_trading=false 이면 LIVE 모드 주문 차단"""
    risk_manager.rules["allow_live_trading"] = False
    with pytest.raises(RiskException):
        risk_manager.check_order(buy_order, Mode.LIVE)


def test_emergency_stop(setup_account, risk_manager, buy_order):
    """긴급 중단 시 주문 차단"""
    risk_manager.rules["emergency_stop"] = True
    with pytest.raises(RiskException):
        risk_manager.check_order(buy_order, Mode.PAPER)


def test_position_ratio_exceeded(setup_account, risk_manager):
    """종목당 최대 비중 초과 차단"""
    # 1천만원 자산에서 30% 주문 (최대 20%)
    large_order = Order(
        order_id="test_002",
        symbol="005930",
        name="삼성전자",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=43,
        price=70000.0,
        amount=3_010_000.0,  # 30.1%
        reason="test",
    )
    with pytest.raises(RiskException):
        risk_manager.check_order(large_order, Mode.PAPER)


def test_duplicate_buy_blocked(setup_account, risk_manager, buy_order):
    """이미 보유 중이면 추가 매수 차단"""
    # 포지션 추가
    from trade.position_manager import get_position_manager
    get_position_manager().add_buy_fill("005930", "삼성전자", 10, 70000.0)

    with pytest.raises(RiskException):
        risk_manager.check_order(buy_order, Mode.PAPER)


def test_sell_no_holdings_blocked(setup_account, risk_manager):
    """보유 없을 때 매도 차단"""
    sell_order = Order(
        order_id="test_003",
        symbol="005930",
        name="삼성전자",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=72000.0,
        amount=720000.0,
        reason="test",
    )
    with pytest.raises(RiskException):
        risk_manager.check_order(sell_order, Mode.PAPER)


def test_new_buy_disabled(setup_account, risk_manager, buy_order):
    """신규 매수 중단 상태에서 차단"""
    risk_manager.rules["new_buy_allowed"] = False
    with pytest.raises(RiskException):
        risk_manager.check_order(buy_order, Mode.PAPER)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
