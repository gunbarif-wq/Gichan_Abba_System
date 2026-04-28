"""
OrderbookManager — 호가 데이터 관리
WebSocket H0STASP0 TR 수신 데이터를 threading.Lock 으로 안전하게 캐시
매수/매도 최우선호가 제공
"""
import logging
import threading
from typing import Optional

from data.market_data_types import OrderBook

logger = logging.getLogger(__name__)


class OrderbookManager:
    """
    실시간 호가 캐시

    on_orderbook(book): WebSocket 콜백으로 등록
    get_best_bid/ask():  매수/매도 최우선호가 조회
    get_spread():        스프레드 (ask - bid) / bid * 100

    H0STASP0 파싱은 KisWebSocketClient에서 처리 후
    OrderBook 객체로 전달 받는 구조.
    현재 KIS 웹소켓에 H0STASP0 구독 없으면 REST fallback 사용.
    """

    def __init__(self):
        self._books: dict          = {}
        self._lock  = threading.Lock()
        logger.debug("[OrderbookManager] 초기화")

    def on_orderbook(self, book: OrderBook) -> None:
        """WebSocket 콜백 — 호가 캐시 갱신"""
        with self._lock:
            self._books[book.symbol] = book

    def update(self, book: OrderBook) -> None:
        self.on_orderbook(book)

    def get(self, symbol: str) -> Optional[OrderBook]:
        with self._lock:
            return self._books.get(symbol)

    def get_best_bid(self, symbol: str) -> Optional[float]:
        """매수 최우선 호가 (가장 높은 bid)"""
        with self._lock:
            book = self._books.get(symbol)
        if book and book.bids:
            return float(book.bids[0][0])
        return self._rest_fallback_price(symbol)

    def get_best_ask(self, symbol: str) -> Optional[float]:
        """매도 최우선 호가 (가장 낮은 ask)"""
        with self._lock:
            book = self._books.get(symbol)
        if book and book.asks:
            return float(book.asks[0][0])
        return self._rest_fallback_price(symbol)

    def get_spread_pct(self, symbol: str) -> Optional[float]:
        """스프레드 비율 (%) — 슬리피지 추정용"""
        bid = self.get_best_bid(symbol)
        ask = self.get_best_ask(symbol)
        if bid and ask and bid > 0:
            return (ask - bid) / bid * 100
        return None

    def get_mid_price(self, symbol: str) -> Optional[float]:
        """중간가 (bid+ask)/2"""
        bid = self.get_best_bid(symbol)
        ask = self.get_best_ask(symbol)
        if bid and ask:
            return (bid + ask) / 2
        return bid or ask

    @staticmethod
    def _rest_fallback_price(symbol: str) -> Optional[float]:
        """호가 없을 때 DataHub 캐시 현재가 fallback"""
        try:
            from hub.data_hub import get_data_hub
            return get_data_hub().get_current_price(symbol)
        except Exception:
            return None


# 싱글톤
_manager: Optional[OrderbookManager] = None


def get_orderbook_manager() -> OrderbookManager:
    global _manager
    if _manager is None:
        _manager = OrderbookManager()
    return _manager
