"""
Data Hub — 실시간 시세 데이터 배포
WebSocket tick → 채널별 구독자에게 브로드캐스트
현재가 캐시, 데이터 신선도 모니터링
"""
import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DataHub:
    """
    pub/sub 기반 데이터 허브
    - subscribe(channel, callback): 구독 등록
    - publish(channel, data): 데이터 발행 + 구독자 콜백 호출
    - on_tick(tick): WebSocket tick → "price_<symbol>" 채널 자동 발행
    - get_current_price(symbol): 캐시된 현재가 반환
    """

    PRICE_CHANNEL = "price_{symbol}"

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._last_data:   Dict[str, dict]           = {}
        self._price_cache: Dict[str, float]          = {}   # symbol → price
        self._last_update: Optional[datetime]        = None
        self._lock         = threading.Lock()
        logger.info("[DataHub] 초기화")

    # ── pub/sub ───────────────────────────────────────────────────────────────

    def subscribe(self, channel: str, callback: Callable) -> None:
        with self._lock:
            self._subscribers.setdefault(channel, []).append(callback)
        logger.debug(f"[DataHub] 구독: {channel}")

    def unsubscribe(self, channel: str, callback: Callable) -> None:
        with self._lock:
            subs = self._subscribers.get(channel, [])
            if callback in subs:
                subs.remove(callback)

    def publish(self, channel: str, data: dict) -> None:
        with self._lock:
            self._last_data[channel] = data
            self._last_update        = datetime.now()
            callbacks = list(self._subscribers.get(channel, []))

        for cb in callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"[DataHub] 콜백 오류 {channel}: {e}")

    # ── WebSocket tick 수신 ───────────────────────────────────────────────────

    def on_tick(self, tick) -> None:
        """
        KisWebSocketClient 콜백으로 등록
        tick: RealtimeTick (symbol, price, change_rate, volume, ask_qty, bid_qty)
        """
        symbol = tick.symbol
        price  = float(tick.price)

        with self._lock:
            self._price_cache[symbol] = price
            self._last_update         = datetime.now()

        data = {
            "symbol":      symbol,
            "price":       price,
            "change_rate": tick.change_rate,
            "volume":      tick.volume,
            "ask_qty":     tick.ask_qty,
            "bid_qty":     tick.bid_qty,
            "timestamp":   datetime.now(),
        }
        self.publish(self.PRICE_CHANNEL.format(symbol=symbol), data)
        self.publish("tick", data)  # 전체 구독자용

    # ── 현재가 조회 ───────────────────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> Optional[float]:
        """캐시된 현재가 반환. 없으면 KIS REST API fallback"""
        price = self._price_cache.get(symbol)
        if price:
            return price

        try:
            from trade.kis_mock_client import get_kis_mock_client
            output = get_kis_mock_client().get_current_price(symbol)
            price  = float(output.get("stck_prpr", 0))
            if price > 0:
                with self._lock:
                    self._price_cache[symbol] = price
            return price if price > 0 else None
        except Exception as e:
            logger.debug(f"[DataHub] 현재가 조회 실패 {symbol}: {e}")
            return None

    def update_price(self, symbol: str, price: float) -> None:
        """외부에서 직접 가격 업데이트 (포지션 매니저 등)"""
        with self._lock:
            self._price_cache[symbol] = price
            self._last_update         = datetime.now()

    # ── 신선도 ────────────────────────────────────────────────────────────────

    def get_last(self, channel: str) -> Optional[dict]:
        return self._last_data.get(channel)

    def get_data_delay_seconds(self) -> Optional[float]:
        if self._last_update is None:
            return None
        return (datetime.now() - self._last_update).total_seconds()

    def is_data_fresh(self, max_delay_seconds: float = 60.0) -> bool:
        delay = self.get_data_delay_seconds()
        return delay is not None and delay <= max_delay_seconds

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._price_cache)


# ── 싱글톤 ────────────────────────────────────────────────────────────────────
_data_hub: Optional[DataHub] = None


def get_data_hub() -> DataHub:
    global _data_hub
    if _data_hub is None:
        _data_hub = DataHub()
    return _data_hub
