"""
Risk Manager (Risk Guard)
모든 주문을 검증하는 최종 게이트키퍼
어떤 에이전트나 명령도 우회할 수 없다.
"""

import logging
from datetime import datetime
from typing import Optional

import yaml

from shared.schemas import Order, OrderSide, RiskCheckResult, Mode
from shared.errors import (
    RiskException,
    InsufficientCash,
    PositionRatioExceeded,
    CashRatioExceeded,
    MaxPositionsExceeded,
    UnknownOrderState,
    LiveTradingDisabled,
    EmergencyStop,
)
from account.account_manager import get_account_manager
from trade.order_manager import get_order_manager
from trade.position_manager import get_position_manager

# 순환 임포트 방지: get_shared_state는 run.py에서 주입하거나 지연 임포트
def _get_shared_state():
    try:
        from run import get_shared_state
        return get_shared_state()
    except Exception:
        return None

logger = logging.getLogger(__name__)


class RiskManager:
    """
    리스크 관리자 (Risk Guard)
    
    규칙:
    1. 모든 주문은 먼저 Risk Guard를 통과해야 함
    2. AI는 Risk Guard를 우회할 수 없음
    3. Command Agent도 Risk Guard를 우회할 수 없음
    4. live_trading=false이면 실계좌 주문은 절대 불가
    5. 모든 거부는 기록됨
    """
    
    def __init__(self, config_path: str = "config/risk_rules.yaml"):
        """
        리스크 관리자 초기화
        
        Args:
            config_path: 리스크 규칙 설정 파일 경로
        """
        self.config_path = config_path
        self.rules = self._load_rules()
        self.rejections = []  # 거부 기록
        logger.info("[RiskManager] 초기화 완료")
    
    def _load_rules(self) -> dict:
        """리스크 규칙 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                rules = yaml.safe_load(f)
            logger.info(f"[RiskManager] 규칙 로드: {self.config_path}")
            return rules
        except FileNotFoundError:
            logger.warning(f"[RiskManager] 규칙 파일 없음: {self.config_path}")
            return self._default_rules()
    
    def _default_rules(self) -> dict:
        """기본 규칙"""
        return {
            'max_position_ratio_per_stock': 0.20,
            'min_cash_ratio': 0.20,
            'max_positions': 5,
            'max_daily_loss_ratio': 0.03,
            'allow_live_trading': False,
            'new_buy_allowed': True,
            'emergency_stop': False,
        }
    
    def check_order(self, order: Order, mode: Mode) -> RiskCheckResult:
        """
        주문 리스크 검사 (최종 게이트키퍼)
        
        Args:
            order: 주문 객체
            mode: 운영 모드
        
        Returns:
            리스크 검사 결과
        
        Raises:
            RiskException: 리스크 위반
        """
        logger.info(
            f"[RiskManager] 주문 검사 시작: {order.symbol} "
            f"{order.side.value} {order.quantity}주 @ {order.price:,}원"
        )
        
        checks = {}

        try:
            # 1. 긴급 중단 — SharedState 실시간 참조, 최우선 처리
            self._check_emergency_stop_realtime()

            # 2. 실계좌 거래 여부 확인
            checks['live_trading'] = self._check_live_trading(mode)

            # 3. 긴급 중단 확인 (legacy rules 기반 — SharedState 없는 환경 대비)
            checks['emergency_stop'] = self._check_emergency_stop()
            
            # 3. UNKNOWN 상태 확인
            checks['unknown_state'] = self._check_unknown_order_state(order.symbol)
            
            # 4. 매수 주문 검사
            if order.side == OrderSide.BUY:
                checks['new_buy_allowed'] = self._check_new_buy_allowed()
                checks['duplicate_buy'] = self._check_duplicate_buy(order.symbol)
                checks['insufficient_cash'] = self._check_cash(
                    order.quantity,
                    order.price
                )
                checks['position_ratio'] = self._check_position_ratio(
                    order.symbol,
                    order.amount
                )
                checks['cash_ratio'] = self._check_min_cash_ratio(
                    order.quantity,
                    order.price
                )
                checks['max_positions'] = self._check_max_positions(order.symbol)
            
            # 5. 매도 주문 검사
            elif order.side == OrderSide.SELL:
                checks['holdings'] = self._check_holdings(
                    order.symbol,
                    order.quantity
                )
                checks['duplicate_sell'] = self._check_duplicate_sell(order.symbol)
            
            # 모든 검사 통과
            passed = all(checks.values())
            
            result = RiskCheckResult(
                passed=passed,
                reason="" if passed else "일부 검사 실패",
                checks=checks,
            )
            
            if passed:
                logger.info(f"[RiskManager] 주문 승인: {order.order_id}")
            else:
                logger.warning(
                    f"[RiskManager] 주문 거부: {order.order_id} "
                    f"실패 항목: {[k for k, v in checks.items() if not v]}"
                )
                self._record_rejection(order, checks)
                raise RiskException(f"리스크 검사 실패: {result.checks}")
            
            return result
            
        except RiskException as e:
            logger.error(f"[RiskManager] 리스크 위반: {str(e)}")
            raise
    
    def _check_live_trading(self, mode: Mode) -> bool:
        """실계좌 거래 가능 여부"""
        if mode == Mode.LIVE and not self.rules.get('allow_live_trading', False):
            logger.warning("[RiskManager] LIVE 모드에서 실계좌 거래 비활성화됨")
            return False
        return True
    
    def _check_emergency_stop_realtime(self) -> None:
        """SharedState.emergency_stop 실시간 참조 — True이면 즉시 예외"""
        state = _get_shared_state()
        if state is not None and state.emergency_stop:
            logger.warning("[RiskManager] Emergency Stop ACTIVE — 모든 주문 차단")
            raise EmergencyStop("Emergency Stop ACTIVE")

    def _check_emergency_stop(self) -> bool:
        """rules 기반 긴급 중단 (SharedState 없는 환경 대비)"""
        if self.rules.get('emergency_stop', False):
            logger.warning("[RiskManager] Emergency Stop ACTIVE (rules)")
            return False
        return True
    
    def _check_unknown_order_state(self, symbol: str) -> bool:
        """UNKNOWN 상태의 주문 존재 여부"""
        order_manager = get_order_manager()
        pending = order_manager.get_pending_orders(symbol)
        
        from shared.schemas import OrderState
        for order in pending:
            if order.state == OrderState.UNKNOWN:
                logger.warning(f"[RiskManager] UNKNOWN 상태 주문 존재: {symbol}")
                return False
        
        return True
    
    def _check_new_buy_allowed(self) -> bool:
        """신규 매수 허용 여부"""
        if not self.rules.get('new_buy_allowed', True):
            logger.warning("[RiskManager] 신규 매수 중단됨")
            return False
        return True
    
    def _check_duplicate_buy(self, symbol: str) -> bool:
        """중복 매수 방지"""
        account_manager = get_account_manager()
        order_manager = get_order_manager()
        
        # 이미 보유 중
        if account_manager.get_position(symbol):
            logger.warning(f"[RiskManager] {symbol} 이미 보유 중")
            return False
        
        # 미체결 매수 주문
        if order_manager.has_pending_buy(symbol):
            logger.warning(f"[RiskManager] {symbol} 미체결 매수 주문 존재")
            return False
        
        return True
    
    def _check_cash(self, quantity: int, price: float) -> bool:
        """현금 충분 여부"""
        account_manager = get_account_manager()
        
        if not account_manager.can_buy(symbol="", quantity=quantity, price=price):
            logger.warning(
                "[RiskManager] 주문가능금액 부족"
            )
            return False
        
        return True
    
    def _check_position_ratio(self, symbol: str, amount: float) -> bool:
        """종목당 최대 비중 확인"""
        account_manager = get_account_manager()
        account = account_manager.get_account()
        
        new_position_amount = amount
        total_asset = account.total_asset or 1
        
        ratio = new_position_amount / total_asset
        max_ratio = self.rules.get('max_position_ratio_per_stock', 0.20)
        
        if ratio > max_ratio:
            logger.warning(
                f"[RiskManager] {symbol} 최대 비중 초과: "
                f"{ratio:.1%} > {max_ratio:.1%}"
            )
            return False
        
        return True
    
    def _check_min_cash_ratio(self, quantity: int, price: float) -> bool:
        """최소 현금 비율 확인"""
        account_manager = get_account_manager()
        account = account_manager.get_account()
        
        order_amount = quantity * price
        commission = order_amount * 0.00015
        total_deduct = order_amount + commission
        
        remaining_cash = account.available_cash - total_deduct
        total_asset = account.total_asset or 1
        
        min_ratio = self.rules.get('min_cash_ratio', 0.20)
        
        if remaining_cash / total_asset < min_ratio:
            logger.warning(
                f"[RiskManager] 최소 현금 비율 미달: "
                f"{(remaining_cash/total_asset):.1%} < {min_ratio:.1%}"
            )
            return False
        
        return True
    
    def _check_max_positions(self, symbol: str) -> bool:
        """최대 보유 종목 수 확인"""
        account_manager = get_account_manager()
        positions = account_manager.get_all_positions()
        
        max_positions = self.rules.get('max_positions', 5)
        
        # 이미 보유 중이면 카운트 제외
        current_count = len([p for p in positions.values() if p.symbol != symbol and p.quantity > 0])
        
        if current_count >= max_positions:
            logger.warning(
                f"[RiskManager] 최대 종목 수 초과: "
                f"{current_count} >= {max_positions}"
            )
            return False
        
        return True
    
    def _check_holdings(self, symbol: str, quantity: int) -> bool:
        """보유 수량 확인"""
        account_manager = get_account_manager()
        
        if not account_manager.can_sell(symbol, quantity):
            logger.warning(f"[RiskManager] {symbol} 매도 수량 부족")
            return False
        
        return True
    
    def _check_duplicate_sell(self, symbol: str) -> bool:
        """중복 매도 방지"""
        order_manager = get_order_manager()
        
        if order_manager.has_pending_sell(symbol):
            logger.warning(f"[RiskManager] {symbol} 미체결 매도 주문 존재")
            return False
        
        return True
    
    def _record_rejection(self, order: Order, checks: dict) -> None:
        """거부 기록"""
        rejection = {
            'timestamp': datetime.now(),
            'symbol': order.symbol,
            'side': order.side.value,
            'quantity': order.quantity,
            'price': order.price,
            'failed_checks': [k for k, v in checks.items() if not v],
        }
        self.rejections.append(rejection)
        logger.info(f"[RiskManager] 거부 기록: {len(self.rejections)}건")
    
    def set_emergency_stop(self, enabled: bool) -> None:
        """긴급 중단 설정 — rules + SharedState 동시 반영"""
        self.rules['emergency_stop'] = enabled
        shared = _get_shared_state()
        if shared is not None:
            shared.emergency_stop = enabled
        state = "활성화" if enabled else "해제"
        logger.warning(f"[RiskManager] Emergency Stop {state}")
    
    def set_new_buy_allowed(self, allowed: bool) -> None:
        """신규 매수 허용 설정"""
        self.rules['new_buy_allowed'] = allowed
        state = "허용" if allowed else "중단"
        logger.warning(f"[RiskManager] 신규 매수 {state}")
    
    def get_rejections(self) -> list:
        """거부 기록 조회"""
        return self.rejections.copy()
    
    def clear_rejections(self) -> None:
        """거부 기록 초기화"""
        self.rejections.clear()


# 전역 리스크 관리자 인스턴스
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    """리스크 관리자 싱글톤 반환"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager


def init_risk_manager(config_path: str = "config/risk_rules.yaml") -> RiskManager:
    """리스크 관리자 초기화"""
    global _risk_manager
    _risk_manager = RiskManager(config_path)
    return _risk_manager
