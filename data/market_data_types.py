"""Market Data Types - 시장 데이터 타입 정의"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Tick:
    symbol: str
    price: float
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class Candle:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)
    timeframe: str = "3m"

@dataclass
class OrderBook:
    symbol: str
    bids: list = field(default_factory=list)  # [(price, qty)]
    asks: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
