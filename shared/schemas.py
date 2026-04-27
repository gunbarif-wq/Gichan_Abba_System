"""
공통 데이터 스키마 정의
모든 모듈은 이 스키마를 사용해 데이터를 주고받는다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


# ==================== Enums ====================

class OrderState(str, Enum):
    """주문 상태"""
    IDLE = "IDLE"
    CREATED = "CREATED"
    BUY_PENDING = "BUY_PENDING"
    BUY_SENT = "BUY_SENT"
    BUY_PARTIAL = "BUY_PARTIAL"
    BUY_FILLED = "BUY_FILLED"
    SELL_PENDING = "SELL_PENDING"
    SELL_SENT = "SELL_SENT"
    SELL_PARTIAL = "SELL_PARTIAL"
    SELL_FILLED = "SELL_FILLED"
    REJECTED = "REJECTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    LOCKED = "LOCKED"


class OrderSide(str, Enum):
    """매매 방향"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """주문 타입"""
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class SessionType(str, Enum):
    """거래 세션"""
    PREMARKET = "PREMARKET"
    MAIN = "MAIN"
    AFTERMARKET = "AFTERMARKET"
    CLOSED = "CLOSED"


class Mode(str, Enum):
    """운영 모드"""
    PAPER = "paper"
    MOCK = "mock"
    LIVE = "live"


# ==================== Dataclasses ====================

@dataclass
class Signal:
    """거래 신호"""
    symbol: str
    name: str
    side: OrderSide
    price: float
    quantity: int
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0
    agent_source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentScore:
    """에이전트 점수"""
    agent_name: str
    symbol: str
    score: float  # 0~100
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    """매수 후보 종목"""
    symbol: str
    name: str
    scores: List[AgentScore] = field(default_factory=list)
    avg_score: float = 0.0
    recommendation: str = "HOLD"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    """주문"""
    order_id: str
    symbol: str
    name: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float
    amount: float  # quantity * price
    state: OrderState = OrderState.CREATED
    timestamp: datetime = field(default_factory=datetime.now)
    sent_time: Optional[datetime] = None
    filled_time: Optional[datetime] = None
    filled_quantity: int = 0
    avg_filled_price: float = 0.0
    commission: float = 0.0
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Fill:
    """체결"""
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime = field(default_factory=datetime.now)
    commission: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """포지션"""
    symbol: str
    name: str
    quantity: int  # 보유 수량
    avg_buy_price: float
    total_buy_amount: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_ratio: float = 0.0
    current_price: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Account:
    """계좌"""
    mode: Mode
    total_cash: float
    available_cash: float
    total_asset: float
    positions: Dict[str, Position] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeResult:
    """매매 결과"""
    symbol: str
    name: str
    mode: Mode
    buy_order_id: str
    sell_order_id: Optional[str] = None
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_avg_price: float = 0.0
    sell_avg_price: float = 0.0
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    buy_commission: float = 0.0
    sell_commission: float = 0.0
    tax: float = 0.0
    pnl: float = 0.0  # 순손익금
    pnl_ratio: float = 0.0  # 순손익률 (%)
    realized_pnl: float = 0.0
    remaining_quantity: int = 0
    buy_time: datetime = field(default_factory=datetime.now)
    sell_time: Optional[datetime] = None
    holding_time: Optional[float] = None  # 시간
    sell_reason: str = ""
    status: str = "PENDING"  # PENDING, COMPLETED, PARTIAL
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PnlReport:
    """손익 리포트"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_pnl_ratio: float
    avg_win: float
    avg_loss: float
    win_rate: float
    trades: List[TradeResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OpsStatus:
    """운영 상태"""
    mode: Mode
    is_market_open: bool
    can_buy: bool
    can_sell: bool
    session: SessionType
    current_time: datetime = field(default_factory=datetime.now)
    health_status: str = "OK"  # OK, WARNING, ERROR
    system_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandRequest:
    """명령 요청"""
    user_id: str
    command: str
    args: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """명령 결과"""
    request_id: str
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    """리스크 체크 결과"""
    passed: bool
    reason: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
