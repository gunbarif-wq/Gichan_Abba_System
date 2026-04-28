#!/usr/bin/env python3
"""
Gichan Abba System - 멀티스레딩 메인 엔트리포인트

스레드 우선순위:
  Thread 0: PreMarketThread     - 07:00~08:00:10 장전 스캔 + 실시간 버퍼
  Thread 1: SellMonitorThread   - 1초 주기, 손절/익절/수동매도 (최우선)
  Thread 2: BuyExecutorThread   - 후보 큐에서 매수 실행 (08:00:10~15:20)
  Thread 3: StrategyThread      - 종목 스캔/분석 (CPU 쓰로틀링 적용)
  Thread 4: MonitorReportThread - 30분마다 텔레그램 리포트 (08:00~20:00)
  Thread 5: CommandThread       - 수동 명령 수신
"""

import logging
import queue
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Optional

import yaml

from shared.schemas import Mode, OrderSide, Signal, OrderType
from shared.constants import DEFAULT_MODE, DEFAULT_INITIAL_CASH
from shared.errors import RiskException, OrderException, InsufficientCash

from account.account_manager import init_account_manager, get_account_manager
from ops.market_clock import init_market_clock, get_market_clock
from risk.risk_manager import init_risk_manager, get_risk_manager
from trade.order_manager import get_order_manager
from trade.position_manager import get_position_manager
from strategy.signal_engine import get_signal_engine
from report.pnl_calculator import get_pnl_calculator
from agents.agents import VisionAgent, SupplyAgent, NewsAgent, CouncilAgent
from scanner.volume_scanner import get_volume_scanner
from scanner.premarket_scanner import PreMarketScanner
from trade.kis_websocket import KisWebSocketClient
from trade.kis_mock_client import get_kis_mock_client
from notify.telegram import get_telegram_notifier
from hub.data_hub import get_data_hub
from control.command_agent import get_command_agent


# ── 로깅 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(threadName)-14s %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('storage/logs/gichan_abba.log'),
    ]
)
logger = logging.getLogger(__name__)


# ── 설정 ──────────────────────────────────────────────────────────────────────
STOP_LOSS_PCT    = -5.0   # 손절선 -5%
TAKE_PROFIT_PCT  =  8.0   # 익절선 +8%
SELL_CHECK_SEC   =  1.0   # 매도 감시 주기 (초)
BUY_CHECK_SEC    =  0.5   # 매수 실행 주기 (초)
SCAN_INTERVAL    = 60.0   # 종목 스캔 주기 (초)
CPU_THROTTLE     =  0.15  # 분석 루프 내 sleep (CPU 점유율 억제)
CANDIDATE_QUEUE_SIZE = 20


# ── 공유 상태 ─────────────────────────────────────────────────────────────────
class SharedState:
    """
    스레드 간 공유 상태. 모든 접근은 lock을 통해야 한다.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.running: bool = True
        self.emergency_stop: bool = False
        self.new_buy_allowed: bool = True

        # 수동 명령 큐 (즉시 처리 보장)
        self.manual_sell_queue: queue.Queue = queue.Queue()
        self.manual_buy_queue: queue.Queue = queue.Queue()

        # 스캐너 → 매수 실행기 후보 큐
        self.candidate_queue: queue.Queue = queue.Queue(maxsize=CANDIDATE_QUEUE_SIZE)

        # 매도 중복 방지 플래그 {symbol: True}
        self._sell_in_progress: dict = {}

        # Telegram /stop /resume 제어
        self.trading_paused: bool = False

        # 오늘 장전 선정 결과 (수동 종목선정 비교용)
        self.watchlist_candidates: dict = {}

    # ── running 플래그 ─────────────────────────────────────────────────────────
    def stop(self):
        with self._lock:
            self.running = False

    def is_running(self) -> bool:
        with self._lock:
            return self.running

    # ── 긴급 중단 ──────────────────────────────────────────────────────────────
    def set_emergency_stop(self, flag: bool):
        with self._lock:
            self.emergency_stop = flag
        logger.warning(f"[SharedState] 긴급중단={'ON' if flag else 'OFF'}")

    def is_emergency_stop(self) -> bool:
        with self._lock:
            return self.emergency_stop

    # ── 매도 중복 방지 ─────────────────────────────────────────────────────────
    def mark_sell_in_progress(self, symbol: str) -> bool:
        """True 반환 시 이미 매도 진행 중 → 건너뜀"""
        with self._lock:
            if self._sell_in_progress.get(symbol):
                return True
            self._sell_in_progress[symbol] = True
            return False

    def clear_sell_in_progress(self, symbol: str):
        with self._lock:
            self._sell_in_progress.pop(symbol, None)


# ── SharedState 싱글톤 (CommandRouter 에서 접근) ─────────────────────────────
_shared_state: Optional[SharedState] = None


def get_shared_state() -> SharedState:
    global _shared_state
    if _shared_state is None:
        _shared_state = SharedState()
    return _shared_state


# ── Thread 0: PreMarketThread ────────────────────────────────────────────────
class PreMarketThread(threading.Thread):
    """
    07:00        뉴스/테마/거래량 스캔 시작
    07:00:10     NXT 적격 종목 선정 확정 (주문 대기)
    07:30:10     KRX 종목 선정 확정 (주문 대기)
    08:00        NXT 정규장 시작 → 선정된 NXT 종목 시장가 주문
    09:00        KRX 정규장 시작 → 선정된 KRX 종목 시장가 주문
    """

    SCAN_START   = (7,  0,  0)   # 07:00 스캔 시작
    NXT_SELECT   = (7,  0, 10)   # 07:00:10 NXT 종목 선정
    KRX_SELECT   = (7, 30, 10)   # 07:30:10 KRX 종목 선정
    NXT_OPEN     = (8,  0,  0)   # 08:00 NXT 정규장 → 주문 실행
    KRX_OPEN     = (9,  0,  0)   # 09:00 KRX 정규장 → 주문 실행

    def __init__(self, state: SharedState, scanner: PreMarketScanner,
                 ws: KisWebSocketClient, telegram):
        super().__init__(name="PreMarket", daemon=True)
        self.state    = state
        self.scanner  = scanner
        self.ws       = ws
        self.telegram = telegram

    def run(self):
        logger.info("[PreMarket] 장전 스레드 시작")
        while self.state.is_running():

            # 07:00까지 대기
            self._sleep_until(*self.SCAN_START)

            # ── 07:00: 장전 스캔 ─────────────────────────────────────────────
            logger.info("[PreMarket] 07:00 장전 스캔 시작")
            self.telegram.send_system("장전 분석 시작 (뉴스/테마/거래량)")

            try:
                candidates = self.scanner.run_premarket_scan()
                symbols    = self.scanner.get_symbols()
                # 수동 종목선정 비교용으로 공유 상태에 저장
                self.state.watchlist_candidates = {
                    c.symbol: c for c in candidates
                }
            except Exception as e:
                logger.error(f"[PreMarket] 스캔 오류: {e}")
                self.telegram.send_error(f"장전 스캔 실패: {e}")
                self._sleep_until(7, 0, 0, next_day=True)
                continue

            # 웹소켓 구독 (포지션 실시간 업데이트용)
            original_on_tick = self.ws.on_tick
            def combined_tick(tick):
                self.scanner.on_tick(tick)
                if original_on_tick:
                    original_on_tick(tick)
            self.ws.on_tick = combined_tick
            self.ws.subscribe_list(symbols)

            # ── 07:00:10: NXT 종목 선정 ──────────────────────────────────────
            self._sleep_until(*self.NXT_SELECT)
            nxt_selected = [c for c in candidates
                            if c.exchange == "NXT" and c.is_buy_ready()]
            logger.info(f"[PreMarket] 07:00:10 NXT 선정: {len(nxt_selected)}개")
            self.telegram.send(
                f"<b>NXT 선정 완료 {len(nxt_selected)}개</b> (08:00 정규장 시장가 주문 예정)\n"
                + "\n".join(f"  {c.symbol} {c.name} 점수={c.score:.0f}"
                            for c in nxt_selected)
            )

            # ── 07:30:10: KRX 종목 선정 ──────────────────────────────────────
            self._sleep_until(*self.KRX_SELECT)
            krx_selected = [c for c in candidates
                            if c.exchange == "KRX" and c.is_buy_ready()]
            logger.info(f"[PreMarket] 07:30:10 KRX 선정: {len(krx_selected)}개")
            self.telegram.send(
                f"<b>KRX 선정 완료 {len(krx_selected)}개</b> (09:00 정규장 시장가 주문 예정)\n"
                + "\n".join(f"  {c.symbol} {c.name} 점수={c.score:.0f}"
                            for c in krx_selected)
            )

            # ── 08:00: NXT 정규장 → 시장가 주문 ─────────────────────────────
            self._sleep_until(*self.NXT_OPEN)
            self._enqueue_candidates(nxt_selected, "NXT 정규장")
            logger.info(f"[PreMarket] 08:00 NXT 시장가 주문: {len(nxt_selected)}개")

            # ── 09:00: KRX 정규장 → 시장가 주문 ─────────────────────────────
            self._sleep_until(*self.KRX_OPEN)
            self._enqueue_candidates(krx_selected, "KRX 정규장")
            logger.info(f"[PreMarket] 09:00 KRX 시장가 주문: {len(krx_selected)}개")

            self.telegram.send_system(
                f"정규장 주문 완료\n"
                f"NXT {len(nxt_selected)}개 (08:00) / KRX {len(krx_selected)}개 (09:00)"
            )

            # 하루 1회 — 다음날 07:00까지 대기
            self._sleep_until(7, 0, 0, next_day=True)

    def _enqueue_candidates(self, candidates, label: str):
        for c in candidates:
            if not self.state.is_running():
                break
            try:
                self.state.candidate_queue.put_nowait(
                    (c.symbol, c.name, c.last_price, 0,
                     f"{label} 점수={c.score:.0f}",
                     c.exchange)
                )
            except queue.Full:
                logger.warning("[PreMarket] 후보 큐 가득 참")
                break

        logger.info("[PreMarket] 종료")

    def _sleep_until(self, hour: int, minute: int, second: int = 0, next_day: bool = False):
        """특정 시각까지 1초씩 대기"""
        from datetime import timedelta
        now    = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if next_day or target <= now:
            target += timedelta(days=1)

        wait = (target - datetime.now()).total_seconds()
        logger.info(
            f"[PreMarket] {target:%H:%M:%S}까지 대기 "
            f"({wait/60:.0f}분 {wait%60:.0f}초)"
        )
        for _ in range(int(wait)):
            if not self.state.is_running():
                return
            time.sleep(1)


# ── Thread 1: SellMonitorThread (최우선) ──────────────────────────────────────
class SellMonitorThread(threading.Thread):
    """
    1초마다 보유 포지션을 감시하여 손절/익절/수동매도를 즉시 실행.
    StrategyThread의 CPU 사용량과 완전히 분리됨.
    """

    def __init__(self, state: SharedState, account_mgr, order_mgr,
                 position_mgr, risk_mgr, pnl_calc, mode: Mode):
        super().__init__(name="SellMonitor", daemon=True)
        self.state        = state
        self.account_mgr  = account_mgr
        self.order_mgr    = order_mgr
        self.position_mgr = position_mgr
        self.risk_mgr     = risk_mgr
        self.pnl_calc     = pnl_calc
        self.mode         = mode
        self.telegram     = get_telegram_notifier()
        self.market_clock = get_market_clock()

    def run(self):
        logger.info("[SellMonitor] 매도 감시 시작")
        while self.state.is_running():
            try:
                # 매도는 운영 시간(08:00~20:00) 내에만
                if self.market_clock.can_sell():
                    self._process_manual_sells()
                    self._check_auto_exit()
            except Exception as e:
                logger.error(f"[SellMonitor] 오류: {e}", exc_info=True)

            time.sleep(SELL_CHECK_SEC)

        logger.info("[SellMonitor] 종료")

    def _process_manual_sells(self):
        while not self.state.manual_sell_queue.empty():
            try:
                item = self.state.manual_sell_queue.get_nowait()
                # item은 str(symbol) 또는 dict
                symbol = item["symbol"] if isinstance(item, dict) else str(item)
                self._execute_sell(symbol, reason="수동 매도 명령")
            except queue.Empty:
                break

    def _check_auto_exit(self):
        positions = self.position_mgr.get_all_positions()
        for symbol, pos in positions.items():
            pnl_pct = pos.unrealized_pnl_ratio  # % 단위

            if pnl_pct <= STOP_LOSS_PCT:
                self._execute_sell(symbol, reason=f"손절 {pnl_pct:.2f}%")
            elif pnl_pct >= TAKE_PROFIT_PCT:
                self._execute_sell(symbol, reason=f"익절 {pnl_pct:.2f}%")

    def _execute_sell(self, symbol: str, reason: str):
        if self.state.mark_sell_in_progress(symbol):
            return  # 이미 매도 진행 중

        try:
            pos = self.position_mgr.get_position(symbol)
            if not pos or pos.quantity <= 0:
                return

            current_price = pos.current_price or pos.avg_buy_price
            quantity = pos.quantity

            sell_signal = Signal(
                symbol=symbol,
                name=pos.name,
                side=OrderSide.SELL,
                price=current_price,
                quantity=quantity,
                reason=reason,
            )

            logger.warning(
                f"[SellMonitor] 매도 실행: {symbol} {quantity}주 "
                f"@ {current_price:,}원 | 사유: {reason}"
            )

            executed = self.order_mgr.create_order(
                signal=sell_signal,
                price=current_price,
                quantity=quantity,
            )
            if executed.filled_quantity <= 0:
                logger.warning(
                    f"[SellMonitor] 매도 제출됨/미체결: {symbol} state={executed.state.value}"
                )
                self.telegram.send_system(
                    f"매도 주문 제출됨\n종목: {symbol}\n상태: {executed.state.value}\n"
                    "체결 확인 후 계좌에 반영됩니다."
                )
                return

            tax = self.pnl_calc.calculate_tax(executed.amount)
            self.account_mgr.add_for_sell(
                symbol=symbol,
                quantity=executed.filled_quantity,
                price=executed.avg_filled_price,
                commission=executed.commission,
                tax=tax,
            )
            self.account_mgr.remove_position(
                symbol, executed.filled_quantity,
                sell_price=executed.avg_filled_price,
                commission=executed.commission,
                tax=tax,
            )

            account = self.account_mgr.get_account()
            sell_amount = int(executed.filled_quantity * executed.avg_filled_price)
            profit      = int(executed.avg_filled_price - pos.avg_buy_price) * executed.filled_quantity
            profit_rate = (executed.avg_filled_price - pos.avg_buy_price) / pos.avg_buy_price * 100

            logger.info(
                f"[SellMonitor] 매도 완료: {symbol} | "
                f"현금: {account.available_cash:,}원"
            )

            # 텔레그램: 매도 체결 알림
            self.telegram.send_sell(
                symbol=symbol, name=pos.name,
                price=int(executed.avg_filled_price),
                quantity=executed.filled_quantity,
                amount=sell_amount,
            )

            # 텔레그램: 수익 결과 알림
            self.telegram.send_profit(
                symbol=symbol, name=pos.name,
                buy_price=int(pos.avg_buy_price),
                sell_price=int(executed.avg_filled_price),
                quantity=executed.filled_quantity,
                profit=profit, profit_rate=profit_rate,
                reason=reason,
            )

        except (OrderException, RiskException) as e:
            logger.error(f"[SellMonitor] {symbol} 매도 실패: {e}")
            self.telegram.send_error(f"{symbol} 매도 실패: {e}")
        finally:
            self.state.clear_sell_in_progress(symbol)


# ── Thread 2: BuyExecutorThread ───────────────────────────────────────────────
class BuyExecutorThread(threading.Thread):
    """
    StrategyThread가 후보 큐에 넣은 종목을 꺼내 매수 실행.
    손절/익절 매도와는 독립적으로 동작.
    """

    def __init__(self, state: SharedState, account_mgr, order_mgr,
                 risk_mgr, pnl_calc, mode: Mode,
                 commission_rate: float = 0.00015):
        super().__init__(name="BuyExecutor", daemon=True)
        self.state           = state
        self.account_mgr     = account_mgr
        self.order_mgr       = order_mgr
        self.risk_mgr        = risk_mgr
        self.pnl_calc        = pnl_calc
        self.mode            = mode
        self.commission_rate = commission_rate
        self.telegram        = get_telegram_notifier()
        self.market_clock    = get_market_clock()

    def run(self):
        logger.info("[BuyExecutor] 매수 실행기 시작")
        while self.state.is_running():
            try:
                # ① 수동 매수 명령
                self._process_manual_buys()

                # ② 후보 큐에서 자동 매수 (trading_paused 아닐 때 — 시간은 종목별 체크)
                if (not self.state.is_emergency_stop()
                        and not self.state.trading_paused):
                    self._process_candidate_queue()

            except Exception as e:
                logger.error(f"[BuyExecutor] 오류: {e}", exc_info=True)

            time.sleep(BUY_CHECK_SEC)

        logger.info("[BuyExecutor] 종료")

    def _process_manual_buys(self):
        while not self.state.manual_buy_queue.empty():
            try:
                item = self.state.manual_buy_queue.get_nowait()
                # item은 tuple(symbol, name, price, qty) 또는 dict
                if isinstance(item, dict):
                    symbol   = item["symbol"]
                    name     = item.get("name", symbol)
                    price    = float(item.get("price", 0))
                    quantity = int(item.get("quantity", 1))
                else:
                    symbol, name, price, quantity = item
                self._execute_buy(symbol, name, price, quantity, reason="수동 매수 명령")
            except queue.Empty:
                break

    def _process_candidate_queue(self):
        try:
            item = self.state.candidate_queue.get_nowait()
            # exchange 필드는 선택적 (6번째 원소)
            symbol, name, price, quantity, reason = item[:5]
            exchange = item[5] if len(item) > 5 else "KRX"

            # 거래소별 매수 가능 시간 체크
            if not self.market_clock.can_buy(exchange):
                # 아직 해당 거래소 매수 시간 아님 → 큐에 다시 넣기
                self.state.candidate_queue.put_nowait(item)
                return

            self._execute_buy(symbol, name, price, quantity,
                              reason=reason, exchange=exchange)
        except queue.Full:
            pass
        except queue.Empty:
            pass

    def _execute_buy(self, symbol: str, name: str, price: float,
                     quantity: int, reason: str, exchange: str = "KRX"):
        from uuid import uuid4
        from shared.schemas import Order, OrderType
        from exchange.validator import is_nxt_eligible

        # 주문 타입: 장전 시간외=단일가(지정가), 정규장=시장가
        order_kind   = self.market_clock.buy_order_type(exchange)
        use_sor      = (exchange == "NXT" or is_nxt_eligible(symbol))
        order_type   = OrderType.MARKET if order_kind == "market" else OrderType.LIMIT

        buy_signal = Signal(
            symbol=symbol, name=name,
            side=OrderSide.BUY, price=price,
            quantity=quantity, reason=reason,
        )

        order_obj = Order(
            order_id=str(uuid4()),
            symbol=symbol, name=name,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=quantity, price=price,
            amount=quantity * price,
            reason=reason,
        )

        try:
            self.risk_mgr.check_order(order_obj, self.mode)
            executed = self.order_mgr.create_order(
                signal=buy_signal, price=price, quantity=quantity,
                order_type=order_type,
                use_sor=use_sor,
            )
            if executed.filled_quantity <= 0:
                logger.warning(
                    f"[BuyExecutor] 매수 제출됨/미체결: {symbol} state={executed.state.value}"
                )
                self.telegram.send_system(
                    f"매수 주문 제출됨\n종목: {symbol}\n상태: {executed.state.value}\n"
                    "체결 확인 후 계좌에 반영됩니다."
                )
                return
            self.account_mgr.deduct_for_buy(
                symbol=symbol, quantity=executed.filled_quantity,
                price=executed.avg_filled_price,
                commission=executed.commission,
            )
            self.account_mgr.update_position(
                symbol=symbol, name=name,
                quantity=executed.filled_quantity,
                price=executed.avg_filled_price,
                commission=executed.commission,
            )
            buy_amount = int(executed.filled_quantity * executed.avg_filled_price)
            route = "SOR(NXT)" if use_sor else exchange
            logger.info(
                f"[BuyExecutor] 매수 완료 [{route}]: {symbol} {executed.filled_quantity}주 "
                f"@ {executed.avg_filled_price:,}원 | {reason}"
            )

            # 텔레그램: 매수 체결 알림
            self.telegram.send_buy(
                symbol=symbol, name=name,
                price=int(executed.avg_filled_price),
                quantity=executed.filled_quantity,
                amount=buy_amount,
            )

        except InsufficientCash as e:
            logger.error(f"[BuyExecutor] {symbol} 잔고 부족: {e}")
            self.telegram.send_error(f"잔고 부족으로 매수 불가\n종목: {symbol}\n{e}")
        except (RiskException, OrderException) as e:
            logger.warning(f"[BuyExecutor] {symbol} 매수 거부: {e}")


# ── Thread 3: StrategyThread (CPU 쓰로틀링 적용) ─────────────────────────────
class StrategyThread(threading.Thread):
    """
    종목 스캔 → AI 분석 → 후보 큐 적재.
    CPU 점유율을 억제하기 위해 개별 분석 사이에 sleep을 삽입.
    이 스레드가 느려져도 SellMonitorThread는 영향받지 않음.
    """

    MIN_BARS_RULES  = 20   # 규칙만 적용 가능한 최소 봉 수
    MIN_BARS_AI     = 60   # 풀 AI 분석 최소 봉 수
    ORDER_AMOUNT    = 500_000  # 1회 주문 금액 (원)

    def __init__(self, state: SharedState, scanner,
                 vision_agent, supply_agent, news_agent, council_agent):
        super().__init__(name="Strategy", daemon=True)
        self.state         = state
        self.scanner       = scanner
        self.vision_agent  = vision_agent
        self.supply_agent  = supply_agent
        self.news_agent    = news_agent
        self.council_agent = council_agent
        self._kis          = get_kis_mock_client()
        self._data_hub     = get_data_hub()

        from strategy.breakout_rule import get_breakout_rule
        from strategy.pullback_rule import get_pullback_rule
        self._breakout_rule = get_breakout_rule()
        self._pullback_rule = get_pullback_rule()

    def run(self):
        logger.info("[Strategy] 전략 스레드 시작")
        while self.state.is_running():
            try:
                if not self.state.is_emergency_stop():
                    self._scan_and_analyze()
            except Exception as e:
                logger.error(f"[Strategy] 오류: {e}", exc_info=True)

            # 스캔 사이 대기 — CPU 점유 억제 + 매도 스레드에 제어권 양보
            self._interruptible_sleep(SCAN_INTERVAL)

        logger.info("[Strategy] 종료")

    def _scan_and_analyze(self):
        candidates = self.scanner.scan()

        if not candidates:
            logger.debug("[Strategy] 스캔 후보 없음")
            return

        logger.info(f"[Strategy] 스캔 완료: {len(candidates)}개 후보")

        for symbol in candidates:
            if not self.state.is_running() or self.state.is_emergency_stop():
                break

            try:
                self._analyze_symbol(symbol)
            except Exception as e:
                logger.warning(f"[Strategy] {symbol} 분석 오류: {e}")
            time.sleep(CPU_THROTTLE)

    def _analyze_symbol(self, symbol: str):
        # 3분봉 조회 (당일 부족 시 전 거래일 자동 보완)
        df_3m = None
        try:
            df_3m = self._kis.get_minute_candles_df(symbol, timeframe=3, count=80)
        except Exception as e:
            logger.debug(f"[Strategy] {symbol} 분봉 조회 실패: {e}")

        bar_count = len(df_3m) if df_3m is not None else 0

        # 봉 수 부족 → 분석 불가
        if bar_count < self.MIN_BARS_RULES:
            logger.debug(f"[Strategy] {symbol} 봉 수 부족({bar_count}개), 건너뜀")
            return

        # 현재가 조회
        price = self._data_hub.get_current_price(symbol)
        if not price or price <= 0:
            logger.debug(f"[Strategy] {symbol} 현재가 조회 실패")
            return

        # 거래량 비율 (최근 3봉 평균 / 직전 20봉 평균)
        volume_ratio = 1.0
        if df_3m is not None and bar_count >= 5:
            vols = df_3m["volume"].values
            recent_avg = vols[-3:].mean()
            base_avg   = vols[:-3].mean() if len(vols) > 3 else recent_avg
            volume_ratio = recent_avg / (base_avg + 1e-9)

        # ── 기술적 규칙 먼저 적용 (봉 수 20~59: 규칙 우선) ──────────────────
        rule_signal = None
        if df_3m is not None:
            rule_signal = (
                self._breakout_rule.check(symbol, symbol, df_3m)
                or self._pullback_rule.check(symbol, symbol, df_3m)
            )

        # 봉 수 미달 시 규칙 신호만으로 판단
        if bar_count < self.MIN_BARS_AI:
            if rule_signal is None:
                return  # 규칙 신호 없으면 패스
            reason = f"규칙신호({rule_signal.reason}) 봉{bar_count}개"
            quantity = int(self.ORDER_AMOUNT / (price * 1.00015))
            if quantity < 1:
                return
            logger.info(f"[Strategy] 매수 후보(규칙): {symbol} {reason}")
            try:
                self.state.candidate_queue.put_nowait(
                    (symbol, symbol, price, quantity, reason)
                )
            except queue.Full:
                pass
            return

        # ── 풀 AI 분석 (봉 수 60 이상) ───────────────────────────────────────
        vision_score = self.vision_agent.analyze(symbol, df_3m=df_3m)
        time.sleep(CPU_THROTTLE)

        supply_score = self.supply_agent.analyze(
            symbol, df_3m=df_3m, volume_ratio=volume_ratio
        )
        time.sleep(CPU_THROTTLE)

        news_score = self.news_agent.analyze(symbol)
        time.sleep(CPU_THROTTLE)

        decision = self.council_agent.make_decision(
            scores=[vision_score, supply_score, news_score],
            symbol=symbol, name=symbol,
            df_3m=df_3m,
        )

        # 규칙 신호 있으면 CouncilAgent 점수 threshold를 10점 낮춰 적용
        threshold_bonus = 10.0 if rule_signal is not None else 0.0

        if decision.avg_score + threshold_bonus >= self.council_agent.BUY_THRESHOLD:
            commission_rate = 0.00015
            quantity = int(self.ORDER_AMOUNT / (price * (1 + commission_rate)))
            if quantity < 1:
                logger.debug(f"[Strategy] {symbol} 주문 가능 수량 없음 (현재가={price:,}원)")
                return

            reason_tag = f"AI{decision.avg_score:.0f}" + ("+규칙" if rule_signal else "")
            logger.info(
                f"[Strategy] 매수 후보: {symbol} 점수={decision.avg_score:.1f} "
                f"봉={bar_count}개 가격={price:,}원 수량={quantity}주"
            )
            try:
                self.state.candidate_queue.put_nowait(
                    (symbol, symbol, price, quantity,
                     f"{reason_tag} 봉{bar_count}개")
                )
            except queue.Full:
                logger.debug("[Strategy] 후보 큐 가득 참, 건너뜀")

    def _interruptible_sleep(self, total_sec: float, chunk: float = 1.0):
        """running 플래그를 확인하며 쪼개서 sleep — 즉시 종료 가능"""
        elapsed = 0.0
        while elapsed < total_sec and self.state.is_running():
            time.sleep(min(chunk, total_sec - elapsed))
            elapsed += chunk


# ── Thread 4: MonitorReportThread ────────────────────────────────────────────
class MonitorReportThread(threading.Thread):
    """
    08:00~20:00 사이 30분마다 텔레그램으로 포지션 현황 리포트
    정각/30분에 맞춰 발송
    """

    REPORT_INTERVAL = 1800  # 30분

    def __init__(self, state: SharedState, account_mgr, position_mgr):
        super().__init__(name="MonitorReport", daemon=True)
        self.state        = state
        self.account_mgr  = account_mgr
        self.position_mgr = position_mgr
        self.telegram     = get_telegram_notifier()
        self.market_clock = get_market_clock()

    def run(self):
        logger.info("[MonitorReport] 30분 리포트 스레드 시작")

        # 다음 정각/30분까지 대기 후 시작
        self._wait_until_next_slot()

        while self.state.is_running():
            try:
                if self.market_clock.is_monitoring():
                    self._send_report()
            except Exception as e:
                logger.error(f"[MonitorReport] 오류: {e}")

            # 30분 대기 (1초씩 쪼개서 종료 신호 즉시 반응)
            for _ in range(self.REPORT_INTERVAL):
                if not self.state.is_running():
                    break
                time.sleep(1)

        logger.info("[MonitorReport] 종료")

    def _wait_until_next_slot(self):
        """다음 정각 또는 30분에 맞춰 시작"""
        from datetime import datetime
        now     = datetime.now()
        minutes = now.minute
        seconds = now.second
        if minutes < 30:
            wait = (30 - minutes) * 60 - seconds
        else:
            wait = (60 - minutes) * 60 - seconds
        logger.info(f"[MonitorReport] 첫 리포트까지 {wait//60}분 {wait%60}초 대기")
        for _ in range(wait):
            if not self.state.is_running():
                return
            time.sleep(1)

    def _send_report(self):
        positions   = self.position_mgr.get_all_positions()
        account     = self.account_mgr.get_account()
        self.telegram.send_monitor_report(
            positions=positions,
            available_cash=account.available_cash,
            total_asset=account.total_asset,
        )
        logger.info("[MonitorReport] 리포트 발송 완료")


# ── Thread 5: CommandThread ───────────────────────────────────────────────────
class CommandThread(threading.Thread):
    """
    콘솔(또는 텔레그램) 명령 수신.
    수동 매도/매수/긴급중단 등을 SharedState 큐에 적재.
    """

    COMMANDS = {
        "/sell":    "종목코드 입력 후 즉시 매도",
        "/buy":     "종목코드 가격 수량 즉시 매수",
        "/stop":    "긴급 중단 (매수 중지, 매도는 유지)",
        "/resume":  "긴급 중단 해제",
        "/status":  "현재 포지션 출력",
        "/quit":    "시스템 종료",
    }

    def __init__(self, state: SharedState, account_mgr, position_mgr):
        super().__init__(name="Command", daemon=True)
        self.state        = state
        self.account_mgr  = account_mgr
        self.position_mgr = position_mgr

    def run(self):
        logger.info("[Command] 명령 수신 대기 (콘솔)")
        print("\n명령어 목록:")
        for cmd, desc in self.COMMANDS.items():
            print(f"  {cmd:10s} - {desc}")
        print()

        while self.state.is_running():
            try:
                line = input().strip()
                if not line:
                    continue
                self._handle(line)
            except EOFError:
                break
            except Exception as e:
                logger.error(f"[Command] 오류: {e}")

    def _handle(self, line: str):
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "/sell" and len(parts) >= 2:
            symbol = parts[1].upper()
            self.state.manual_sell_queue.put(symbol)
            print(f"[Command] 수동 매도 요청: {symbol}")

        elif cmd == "/buy" and len(parts) >= 4:
            symbol = parts[1].upper()
            price = float(parts[2])
            qty = int(parts[3])
            name = parts[4] if len(parts) >= 5 else symbol
            self.state.manual_buy_queue.put((symbol, name, price, qty))
            print(f"[Command] 수동 매수 요청: {symbol} {qty}주 @ {price:,}원")

        elif cmd == "/stop":
            self.state.set_emergency_stop(True)
            print("[Command] 긴급 중단 활성화 — 신규 매수 중지")

        elif cmd == "/resume":
            self.state.set_emergency_stop(False)
            print("[Command] 긴급 중단 해제")

        elif cmd == "/status":
            self._print_status()

        elif cmd == "/quit":
            print("[Command] 시스템 종료 요청")
            self.state.stop()

        else:
            print(f"[Command] 알 수 없는 명령: {line}")
            print(f"  사용 가능: {', '.join(self.COMMANDS)}")

    def _print_status(self):
        positions = self.position_mgr.get_all_positions()
        account   = self.account_mgr.get_account()
        print("\n" + "=" * 50)
        print(f"  현금: {account.available_cash:>15,.0f}원")
        print(f"  총자산: {account.total_asset:>13,.0f}원")
        if positions:
            print(f"  보유 종목 ({len(positions)}개):")
            for sym, pos in positions.items():
                print(
                    f"    {sym} {pos.quantity}주 | 평균가 {pos.avg_buy_price:,.0f}원 "
                    f"| 손익 {pos.unrealized_pnl_ratio:+.2f}%"
                )
        else:
            print("  보유 종목 없음")
        print("=" * 50 + "\n")


# ── Thread 6: TelegramBotThread ──────────────────────────────────────────────
class _TelegramBotThread(threading.Thread):
    """Telegram CommandAgent + Commander 동시 폴링"""

    def __init__(self, state: SharedState):
        super().__init__(name="TelegramBot", daemon=True)
        self.state = state

    def run(self):
        logger.info("[TelegramBot] 봇 스레드 시작")
        # Commander를 별도 스레드로 분리 실행
        try:
            from telegram.commander import get_commander
            cmd_thread = threading.Thread(
                target=get_commander().run,
                name="TelegramCommander", daemon=True
            )
            cmd_thread.start()
        except Exception as e:
            logger.warning(f"[TelegramBot] Commander 시작 실패: {e}")

        try:
            agent = get_command_agent()
            agent.run()  # 내부 무한 루프 — 토큰 없으면 즉시 반환
        except Exception as e:
            logger.error(f"[TelegramBot] 오류: {e}")
        logger.info("[TelegramBot] 종료")


# ── 메인 오케스트레이터 ────────────────────────────────────────────────────────
class GichanAbbaSystem:

    def __init__(self):
        config = self._load_config()
        mode            = Mode(config.get('mode', DEFAULT_MODE))
        initial_cash    = config.get('initial_cash', DEFAULT_INITIAL_CASH)
        commission_rate = config.get('commission_rate', 0.00015)
        tax_rate        = config.get('tax_rate', 0.0018)
        if mode == Mode.LIVE:
            from trade.kis_live_client import KisLiveClient
            KisLiveClient.LIVE_TRADING_ENABLED = bool(config.get('live_trading', False))

        # 싱글톤 초기화
        account_mgr  = init_account_manager(mode, initial_cash)
        market_clock = init_market_clock(mode, time_check_enabled=False)
        risk_mgr     = init_risk_manager()
        order_mgr    = get_order_manager(mode=mode)
        position_mgr = get_position_manager()
        pnl_calc     = get_pnl_calculator(commission_rate, tax_rate)

        self.state = SharedState()
        global _shared_state
        _shared_state = self.state

        # 웹소켓 + 장전 스캐너 초기화
        kis_client      = get_kis_mock_client()
        approval_key    = kis_client.get_approval_key()
        self.ws         = KisWebSocketClient(approval_key, is_mock=True)
        self.ws.on_tick = self._on_realtime_tick
        premarket_scanner = PreMarketScanner(kis_client)
        telegram          = get_telegram_notifier()

        # 에이전트
        vision_agent  = VisionAgent()
        supply_agent  = SupplyAgent()
        news_agent    = NewsAgent()
        council_agent = CouncilAgent()
        scanner       = get_volume_scanner()

        # 스레드 생성
        self.threads = [
            PreMarketThread(self.state, premarket_scanner, self.ws, telegram),
            SellMonitorThread(self.state, account_mgr, order_mgr,
                              position_mgr, risk_mgr, pnl_calc, mode),
            BuyExecutorThread(self.state, account_mgr, order_mgr,
                              risk_mgr, pnl_calc, mode, commission_rate),
            StrategyThread(self.state, scanner,
                           vision_agent, supply_agent, news_agent, council_agent),
            MonitorReportThread(self.state, account_mgr, position_mgr),
            CommandThread(self.state, account_mgr, position_mgr),
            _TelegramBotThread(self.state),
        ]

        # SIGINT / SIGTERM 핸들러
        signal.signal(signal.SIGINT,  self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    def _load_config(self) -> dict:
        try:
            with open(f"config/{DEFAULT_MODE}_config.yaml", 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            return {}

    def _on_realtime_tick(self, tick):
        """웹소켓 실시간 체결 → 포지션 현재가 업데이트 + DataHub 배포"""
        pos_mgr = get_position_manager()
        pos_mgr.update_position_price(tick.symbol, tick.price)
        get_data_hub().on_tick(tick)

    def _on_signal(self, signum, frame):
        logger.warning(f"[System] 시그널 수신({signum}), 종료 요청")
        self.state.stop()

    def run(self):
        logger.info("=" * 60)
        logger.info("Gichan Abba System 시작 (멀티스레딩)")
        logger.info(f"  매수: 08:00:10~15:20  감시: 08:00~20:00")
        logger.info(f"  손절선: {STOP_LOSS_PCT}%  익절선: {TAKE_PROFIT_PCT}%")
        logger.info(f"  매도 감시 주기: {SELL_CHECK_SEC}초  스캔 주기: {SCAN_INTERVAL}초")
        logger.info("=" * 60)

        get_telegram_notifier().send_system(
            f"시스템 시작\n"
            f"매수: 08:00:10~15:20 | 감시: 08:00~20:00\n"
            f"손절: {STOP_LOSS_PCT}% | 익절: {TAKE_PROFIT_PCT}%"
        )

        # 웹소켓 먼저 시작
        self.ws.start()
        logger.info("  웹소켓 클라이언트 시작")

        for t in self.threads:
            t.start()
            logger.info(f"  스레드 시작: {t.name}")

        # 메인 스레드는 종료 신호만 대기
        try:
            while self.state.is_running():
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.state.stop()

        self.ws.stop()
        logger.info("[System] 모든 스레드 종료 대기 중...")
        for t in self.threads:
            t.join(timeout=5.0)
        logger.info("[System] 정상 종료")


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    GichanAbbaSystem().run()
