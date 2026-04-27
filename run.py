#!/usr/bin/env python3
"""
Gichan Abba System - 멀티스레딩 메인 엔트리포인트

스레드 우선순위:
  Thread 1: SellMonitorThread  - 1초 주기, 손절/익절/수동매도 (최우선)
  Thread 2: BuyExecutorThread  - 후보 큐에서 매수 실행
  Thread 3: StrategyThread     - 종목 스캔/분석 (CPU 쓰로틀링 적용)
  Thread 4: CommandThread      - 수동 명령 수신 (텔레그램/콘솔)
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
from shared.errors import RiskException, OrderException

from account.account_manager import init_account_manager, get_account_manager
from ops.market_clock import init_market_clock, get_market_clock
from risk.risk_manager import init_risk_manager, get_risk_manager
from trade.order_manager import get_order_manager
from trade.position_manager import get_position_manager
from strategy.signal_engine import get_signal_engine
from report.pnl_calculator import get_pnl_calculator
from agents.agents import VisionAgent, SupplyAgent, NewsAgent, CouncilAgent
from scanner.volume_scanner import get_volume_scanner


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


# ── Thread 1: SellMonitorThread (최우선) ──────────────────────────────────────
class SellMonitorThread(threading.Thread):
    """
    1초마다 보유 포지션을 감시하여 손절/익절/수동매도를 즉시 실행.
    StrategyThread의 CPU 사용량과 완전히 분리됨.
    """

    def __init__(self, state: SharedState, account_mgr, order_mgr,
                 position_mgr, risk_mgr, pnl_calc, mode: Mode):
        super().__init__(name="SellMonitor", daemon=True)
        self.state = state
        self.account_mgr  = account_mgr
        self.order_mgr    = order_mgr
        self.position_mgr = position_mgr
        self.risk_mgr     = risk_mgr
        self.pnl_calc     = pnl_calc
        self.mode         = mode

    def run(self):
        logger.info("[SellMonitor] 매도 감시 시작")
        while self.state.is_running():
            try:
                # ① 수동 매도 명령 즉시 처리
                self._process_manual_sells()

                # ② 자동 손절/익절 체크
                self._check_auto_exit()

            except Exception as e:
                logger.error(f"[SellMonitor] 오류: {e}", exc_info=True)

            time.sleep(SELL_CHECK_SEC)

        logger.info("[SellMonitor] 종료")

    def _process_manual_sells(self):
        while not self.state.manual_sell_queue.empty():
            try:
                symbol = self.state.manual_sell_queue.get_nowait()
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

            tax = self.pnl_calc.calculate_tax(executed.amount)
            self.account_mgr.add_for_sell(
                symbol=symbol,
                quantity=executed.filled_quantity,
                price=executed.avg_filled_price,
                commission=executed.commission,
                tax=tax,
            )
            self.account_mgr.remove_position(symbol, executed.filled_quantity)

            account = self.account_mgr.get_account()
            logger.info(
                f"[SellMonitor] 매도 완료: {symbol} | "
                f"현금: {account.available_cash:,}원"
            )

        except (OrderException, RiskException) as e:
            logger.error(f"[SellMonitor] {symbol} 매도 실패: {e}")
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

    def run(self):
        logger.info("[BuyExecutor] 매수 실행기 시작")
        while self.state.is_running():
            try:
                # ① 수동 매수 명령
                self._process_manual_buys()

                # ② 후보 큐에서 자동 매수
                if not self.state.is_emergency_stop():
                    self._process_candidate_queue()

            except Exception as e:
                logger.error(f"[BuyExecutor] 오류: {e}", exc_info=True)

            time.sleep(BUY_CHECK_SEC)

        logger.info("[BuyExecutor] 종료")

    def _process_manual_buys(self):
        while not self.state.manual_buy_queue.empty():
            try:
                item = self.state.manual_buy_queue.get_nowait()
                symbol, name, price, quantity = item
                self._execute_buy(symbol, name, price, quantity, reason="수동 매수 명령")
            except queue.Empty:
                break

    def _process_candidate_queue(self):
        try:
            symbol, name, price, quantity, reason = \
                self.state.candidate_queue.get_nowait()
            self._execute_buy(symbol, name, price, quantity, reason=reason)
        except queue.Empty:
            pass

    def _execute_buy(self, symbol: str, name: str, price: float,
                     quantity: int, reason: str):
        from uuid import uuid4
        from shared.schemas import Order, OrderType

        buy_signal = Signal(
            symbol=symbol, name=name,
            side=OrderSide.BUY, price=price,
            quantity=quantity, reason=reason,
        )

        order_obj = Order(
            order_id=str(uuid4()),
            symbol=symbol, name=name,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity, price=price,
            amount=quantity * price,
            reason=reason,
        )

        try:
            self.risk_mgr.check_order(order_obj, self.mode)
            executed = self.order_mgr.create_order(
                signal=buy_signal, price=price, quantity=quantity
            )
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
            logger.info(
                f"[BuyExecutor] 매수 완료: {symbol} {executed.filled_quantity}주 "
                f"@ {executed.avg_filled_price:,}원 | {reason}"
            )
        except (RiskException, OrderException) as e:
            logger.warning(f"[BuyExecutor] {symbol} 매수 거부: {e}")


# ── Thread 3: StrategyThread (CPU 쓰로틀링 적용) ─────────────────────────────
class StrategyThread(threading.Thread):
    """
    종목 스캔 → AI 분석 → 후보 큐 적재.
    CPU 점유율을 억제하기 위해 개별 분석 사이에 sleep을 삽입.
    이 스레드가 느려져도 SellMonitorThread는 영향받지 않음.
    """

    def __init__(self, state: SharedState, scanner,
                 vision_agent, supply_agent, news_agent, council_agent):
        super().__init__(name="Strategy", daemon=True)
        self.state         = state
        self.scanner       = scanner
        self.vision_agent  = vision_agent
        self.supply_agent  = supply_agent
        self.news_agent    = news_agent
        self.council_agent = council_agent

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

            # 개별 종목 분석
            try:
                vision_score  = self.vision_agent.analyze(symbol)
                time.sleep(CPU_THROTTLE)  # CPU 점유율 억제

                supply_score  = self.supply_agent.analyze(symbol)
                time.sleep(CPU_THROTTLE)

                news_score    = self.news_agent.analyze(symbol)
                time.sleep(CPU_THROTTLE)

                decision = self.council_agent.make_decision(
                    scores=[vision_score, supply_score, news_score],
                    symbol=symbol, name=symbol,
                )

                if decision.recommendation == "BUY":
                    logger.info(
                        f"[Strategy] 매수 후보: {symbol} "
                        f"점수={decision.avg_score:.1f}"
                    )
                    try:
                        # 가격/수량은 실제 구현 시 시세 조회로 대체
                        self.state.candidate_queue.put_nowait(
                            (symbol, symbol, 0.0, 0, f"AI점수 {decision.avg_score:.1f}")
                        )
                    except queue.Full:
                        logger.debug("[Strategy] 후보 큐 가득 참, 건너뜀")

            except Exception as e:
                logger.warning(f"[Strategy] {symbol} 분석 오류: {e}")
                time.sleep(CPU_THROTTLE)

    def _interruptible_sleep(self, total_sec: float, chunk: float = 1.0):
        """running 플래그를 확인하며 쪼개서 sleep — 즉시 종료 가능"""
        elapsed = 0.0
        while elapsed < total_sec and self.state.is_running():
            time.sleep(min(chunk, total_sec - elapsed))
            elapsed += chunk


# ── Thread 4: CommandThread ───────────────────────────────────────────────────
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


# ── 메인 오케스트레이터 ────────────────────────────────────────────────────────
class GichanAbbaSystem:

    def __init__(self):
        config = self._load_config()
        mode            = Mode(config.get('mode', DEFAULT_MODE))
        initial_cash    = config.get('initial_cash', DEFAULT_INITIAL_CASH)
        commission_rate = config.get('commission_rate', 0.00015)
        tax_rate        = config.get('tax_rate', 0.0018)

        # 싱글톤 초기화
        account_mgr  = init_account_manager(mode, initial_cash)
        market_clock = init_market_clock(mode, time_check_enabled=False)
        risk_mgr     = init_risk_manager()
        order_mgr    = get_order_manager()
        position_mgr = get_position_manager()
        pnl_calc     = get_pnl_calculator(commission_rate, tax_rate)

        self.state = SharedState()

        # 에이전트
        vision_agent  = VisionAgent()
        supply_agent  = SupplyAgent()
        news_agent    = NewsAgent()
        council_agent = CouncilAgent()
        scanner       = get_volume_scanner()

        # 스레드 생성
        self.threads = [
            SellMonitorThread(self.state, account_mgr, order_mgr,
                              position_mgr, risk_mgr, pnl_calc, mode),
            BuyExecutorThread(self.state, account_mgr, order_mgr,
                              risk_mgr, pnl_calc, mode, commission_rate),
            StrategyThread(self.state, scanner,
                           vision_agent, supply_agent, news_agent, council_agent),
            CommandThread(self.state, account_mgr, position_mgr),
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

    def _on_signal(self, signum, frame):
        logger.warning(f"[System] 시그널 수신({signum}), 종료 요청")
        self.state.stop()

    def run(self):
        logger.info("=" * 60)
        logger.info("Gichan Abba System 시작 (멀티스레딩)")
        logger.info(f"  손절선: {STOP_LOSS_PCT}%  익절선: {TAKE_PROFIT_PCT}%")
        logger.info(f"  매도 감시 주기: {SELL_CHECK_SEC}초")
        logger.info(f"  스캔 주기: {SCAN_INTERVAL}초")
        logger.info("=" * 60)

        for t in self.threads:
            t.start()
            logger.info(f"  스레드 시작: {t.name}")

        # 메인 스레드는 종료 신호만 대기
        try:
            while self.state.is_running():
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.state.stop()

        logger.info("[System] 모든 스레드 종료 대기 중...")
        for t in self.threads:
            t.join(timeout=5.0)
        logger.info("[System] 정상 종료")


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    GichanAbbaSystem().run()
