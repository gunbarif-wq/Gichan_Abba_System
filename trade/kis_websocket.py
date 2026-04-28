"""
KIS 웹소켓 실시간 클라이언트
현재가/체결량을 REST 호출 없이 실시간으로 수신
REST API 초당 호출 한도 소모 없음
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, Optional, Set

import websocket

logger = logging.getLogger(__name__)


# ── 웹소켓 URL ────────────────────────────────────────────────────────────────
WS_URL_MOCK = "ws://ops.koreainvestment.com:31000"
WS_URL_LIVE = "ws://ops.koreainvestment.com:21000"

# 실시간 체결가 TR
TR_REALTIME_PRICE = "H0STCNT0"


class RealtimeTick:
    """실시간 체결 데이터"""
    __slots__ = [
        "symbol", "price", "change_rate",
        "volume", "ask_qty", "bid_qty", "timestamp"
    ]

    def __init__(self, symbol: str, price: int, change_rate: float,
                 volume: int, ask_qty: int, bid_qty: int):
        self.symbol      = symbol
        self.price       = price
        self.change_rate = change_rate  # 전일대비율 (%)
        self.volume      = volume       # 누적 거래량
        self.ask_qty     = ask_qty      # 매도 체결 건수
        self.bid_qty     = bid_qty      # 매수 체결 건수

    def __repr__(self):
        return (f"Tick({self.symbol} {self.price:,}원 "
                f"{self.change_rate:+.2f}% vol={self.volume:,})")


class KisWebSocketClient:
    """
    KIS 실시간 웹소켓 클라이언트

    사용법:
        client = KisWebSocketClient(approval_key, is_mock=True)
        client.on_tick = lambda tick: print(tick)
        client.start()
        client.subscribe("005930")
        client.subscribe("000660")
        ...
        client.stop()
    """

    RECONNECT_DELAY = 5   # 재연결 대기 (초)
    MAX_RECONNECTS  = 10  # 최대 재연결 시도

    def __init__(self, approval_key: str, is_mock: bool = True):
        self.approval_key = approval_key
        self.ws_url       = WS_URL_MOCK if is_mock else WS_URL_LIVE

        self._ws:              Optional[websocket.WebSocketApp] = None
        self._thread:          Optional[threading.Thread]       = None
        self._running:         bool = False
        self._connected:       bool = False
        self._reconnect_count: int  = 0

        # 구독 목록 (재연결 시 자동 재구독)
        self._subscribed: Set[str] = set()
        self._lock = threading.Lock()

        # 콜백 — 외부에서 설정
        self.on_tick:       Optional[Callable[[RealtimeTick], None]] = None
        self.on_connect:    Optional[Callable[[], None]]             = None
        self.on_disconnect: Optional[Callable[[], None]]             = None

    # ── 시작/종료 ──────────────────────────────────────────────────────────────

    def start(self):
        """웹소켓 연결 시작 (백그라운드 스레드)"""
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop, name="KisWebSocket", daemon=True
        )
        self._thread.start()
        logger.info("[WS] 웹소켓 클라이언트 시작")

    def stop(self):
        """웹소켓 연결 종료"""
        self._running = False
        if self._ws:
            self._ws.close()
        logger.info("[WS] 웹소켓 클라이언트 종료")

    def is_connected(self) -> bool:
        return self._connected

    # ── 구독 관리 ──────────────────────────────────────────────────────────────

    def subscribe(self, symbol: str):
        """종목 실시간 체결가 구독"""
        with self._lock:
            if symbol in self._subscribed:
                return
            self._subscribed.add(symbol)

        if self._connected:
            self._send_subscribe(symbol)
            logger.info(f"[WS] 구독 추가: {symbol}")

    def unsubscribe(self, symbol: str):
        """구독 취소"""
        with self._lock:
            self._subscribed.discard(symbol)

        if self._connected:
            self._send_unsubscribe(symbol)
            logger.info(f"[WS] 구독 취소: {symbol}")

    def subscribe_list(self, symbols: list):
        """여러 종목 일괄 구독"""
        for symbol in symbols:
            self.subscribe(symbol)

    def get_subscribed(self) -> Set[str]:
        with self._lock:
            return set(self._subscribed)

    # ── 내부 연결 루프 ─────────────────────────────────────────────────────────

    def _run_loop(self):
        while self._running and self._reconnect_count < self.MAX_RECONNECTS:
            try:
                self._ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open    = self._on_open,
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.error(f"[WS] 연결 오류: {e}")

            if self._running:
                self._reconnect_count += 1
                logger.warning(
                    f"[WS] {self.RECONNECT_DELAY}초 후 재연결 "
                    f"({self._reconnect_count}/{self.MAX_RECONNECTS})"
                )
                time.sleep(self.RECONNECT_DELAY)

    # ── 웹소켓 이벤트 ─────────────────────────────────────────────────────────

    def _on_open(self, ws):
        self._connected       = True
        self._reconnect_count = 0
        logger.info("[WS] 연결 성공")

        # 기존 구독 목록 전체 재구독
        with self._lock:
            symbols = list(self._subscribed)
        for symbol in symbols:
            self._send_subscribe(symbol)
            time.sleep(0.05)  # 구독 요청 사이 짧은 대기

        if self.on_connect:
            self.on_connect()

    def _on_message(self, ws, message: str):
        try:
            # KIS 웹소켓 응답: JSON(제어) 또는 파이프구분(실시간 데이터)
            if message.startswith("{"):
                self._handle_control(message)
            else:
                self._handle_realtime(message)
        except Exception as e:
            logger.debug(f"[WS] 메시지 파싱 오류: {e}")

    def _on_error(self, ws, error):
        logger.error(f"[WS] 오류: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False
        logger.warning(f"[WS] 연결 종료: {close_status_code} {close_msg}")
        if self.on_disconnect:
            self.on_disconnect()

    # ── 구독 메시지 전송 ───────────────────────────────────────────────────────

    def _send_subscribe(self, symbol: str):
        self._send_tr(symbol, tr_type="1")

    def _send_unsubscribe(self, symbol: str):
        self._send_tr(symbol, tr_type="2")

    def _send_tr(self, symbol: str, tr_type: str):
        if not self._ws or not self._connected:
            return
        msg = {
            "header": {
                "approval_key": self.approval_key,
                "custtype":     "P",
                "tr_type":      tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id":  TR_REALTIME_PRICE,
                    "tr_key": symbol,
                }
            }
        }
        try:
            self._ws.send(json.dumps(msg))
        except Exception as e:
            logger.warning(f"[WS] 전송 실패 ({symbol}): {e}")

    # ── 데이터 파싱 ────────────────────────────────────────────────────────────

    def _handle_control(self, message: str):
        """JSON 제어 메시지 처리 (구독 응답, PINGPONG 등)"""
        data = json.loads(message)
        header = data.get("header", {})
        tr_id  = header.get("tr_id", "")

        if tr_id == "PINGPONG":
            self._ws.send(message)  # PONG 응답
            return

        body = data.get("body", {})
        rt_cd = body.get("rt_cd", "")
        if rt_cd == "0":
            msg1 = body.get("msg1", "")
            logger.debug(f"[WS] 구독 성공: {msg1}")
        elif rt_cd:
            logger.warning(f"[WS] 구독 오류: {body.get('msg1', '')}")

    def _handle_realtime(self, message: str):
        """
        파이프 구분 실시간 체결 데이터 파싱
        형식: TR_ID|암호화여부|데이터수|필드0|필드1|...
        """
        parts = message.split("|")
        if len(parts) < 4:
            return

        # tr_id = parts[0]  # H0STCNT0
        # encrypt = parts[1]
        # count = int(parts[2])
        fields = parts[3].split("^")

        if len(fields) < 13:
            return

        try:
            symbol      = fields[0]   # 종목코드
            price       = int(fields[2])    # 현재가
            change_rate = float(fields[5])  # 전일대비율
            volume      = int(fields[10])   # 누적거래량
            ask_qty     = int(fields[12])   # 매도체결건수
            bid_qty     = int(fields[13])   # 매수체결건수

            tick = RealtimeTick(
                symbol=symbol, price=price,
                change_rate=change_rate, volume=volume,
                ask_qty=ask_qty, bid_qty=bid_qty,
            )

            if self.on_tick:
                self.on_tick(tick)

        except (IndexError, ValueError) as e:
            logger.debug(f"[WS] 데이터 파싱 오류: {e}")
