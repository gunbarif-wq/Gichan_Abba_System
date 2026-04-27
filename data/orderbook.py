"""Orderbook (Skeleton) - 호가 데이터"""
import logging
from typing import Optional
from data.market_data_types import OrderBook
logger = logging.getLogger(__name__)

class OrderbookManager:
    """호가 데이터 관리 (Skeleton) - TODO: 실시간 연동"""
    def __init__(self):
        self._books: dict = {}

    def update(self, book: OrderBook) -> None:
        self._books[book.symbol] = book

    def get(self, symbol: str) -> Optional[OrderBook]:
        return self._books.get(symbol)

    def get_best_bid(self, symbol: str) -> Optional[float]:
        book = self._books.get(symbol)
        if book and book.bids:
            return book.bids[0][0]
        return None

    def get_best_ask(self, symbol: str) -> Optional[float]:
        book = self._books.get(symbol)
        if book and book.asks:
            return book.asks[0][0]
        return None

def get_orderbook_manager() -> OrderbookManager:
    return OrderbookManager()
