"""
Manual Trade Handler
텔레그램 수동 매수/매도 처리

흐름:
command_agent → manual_trade_handler → risk_guard → order_manager → broker

주의:
- Risk Guard 우회 금지
- broker/kis_client 직접 호출 금지
- live 모드에서 2단계 확인 필요
"""

import logging
from typing import Optional

from shared.schemas import Signal, OrderSide, Mode, CommandResult
from shared.errors import RiskException

logger = logging.getLogger(__name__)


class ManualTradeHandler:
    """
    수동 매매 처리기

    지원:
    /buy SYMBOL qty QTY
    /buy SYMBOL amount AMOUNT
    /sell SYMBOL qty QTY
    /sell SYMBOL amount AMOUNT
    /sell_all SYMBOL
    """

    def __init__(self, mode: Mode = Mode.PAPER):
        self.mode = mode
        self._pending_confirmations: dict = {}  # live 2단계 확인용
        logger.info(f"[ManualTradeHandler] 초기화: {mode.value}")

    def handle_buy(
        self,
        symbol: str,
        qty: Optional[int] = None,
        amount: Optional[float] = None,
        price: Optional[float] = None,
        name: str = "",
    ) -> CommandResult:
        """
        수동 매수 처리

        Args:
            symbol: 종목 코드
            qty: 수량 (qty/amount 중 하나)
            amount: 금액
            price: 현재가 (amount 기준 주문 시 필요)
            name: 종목명
        """
        from uuid import uuid4

        logger.info(f"[ManualTradeHandler] 매수 요청: {symbol} qty={qty} amount={amount}")

        # 수량 계산
        if qty is None and amount is not None:
            if price is None or price <= 0:
                return CommandResult(
                    request_id=str(uuid4()),
                    success=False,
                    message="현재가를 알 수 없어 수량 계산 불가",
                )
            commission_rate = 0.00015
            qty = int(amount / (price * (1 + commission_rate)))
            if qty < 1:
                return CommandResult(
                    request_id=str(uuid4()),
                    success=False,
                    message=f"주문 가능 수량 부족 (금액={amount:,.0f}원, 현재가={price:,.0f}원)",
                )

        if qty is None or qty < 1:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message="유효하지 않은 수량",
            )

        effective_price = price or 0.0

        # Live 모드: 2단계 확인 (거래소 정보 포함)
        if self.mode == Mode.LIVE:
            from exchange.validator import is_nxt_eligible
            nxt_ok     = is_nxt_eligible(symbol)
            exch_msg   = (
                "NXT 거래 가능 종목입니다. 최적가(SOR)로 매수를 진행할까요?"
                if nxt_ok else
                "KRX 전용 종목입니다. 정규소 매수를 진행할까요?"
            )
            confirm_id = str(uuid4())[:8]
            self._pending_confirmations[confirm_id] = {
                "type": "BUY", "symbol": symbol, "qty": qty,
                "price": effective_price, "use_sor": nxt_ok,
            }
            return CommandResult(
                request_id=confirm_id,
                success=True,
                message=(
                    f"{exch_msg}\n"
                    f"종목: {name or symbol} ({symbol})\n"
                    f"수량: {qty}주 @ {effective_price:,.0f}원\n"
                    f"확인 코드: {confirm_id}\n"
                    f"/confirm {confirm_id} 로 실행"
                ),
            )

        # Risk Guard → Order Manager
        return self._execute_buy(symbol, name, qty, effective_price)

    def handle_sell(
        self,
        symbol: str,
        qty: Optional[int] = None,
        amount: Optional[float] = None,
        price: Optional[float] = None,
        name: str = "",
        sell_all: bool = False,
    ) -> CommandResult:
        """수동 매도 처리"""
        from uuid import uuid4

        logger.info(f"[ManualTradeHandler] 매도 요청: {symbol} qty={qty} amount={amount} sell_all={sell_all}")

        # sell_all: 보유 수량 전량 매도
        if sell_all:
            try:
                from account.account_manager import get_account_manager
                pos = get_account_manager().get_position(symbol)
                if pos is None or pos.quantity == 0:
                    return CommandResult(
                        request_id=str(uuid4()),
                        success=False,
                        message=f"{symbol} 보유 수량 없음",
                    )
                qty = pos.quantity
            except Exception as e:
                return CommandResult(
                    request_id=str(uuid4()),
                    success=False,
                    message=f"보유 수량 조회 실패: {e}",
                )

        # 금액 기준 수량 계산
        if qty is None and amount is not None and price:
            qty = int(amount / price)

        if qty is None or qty < 1:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message="유효하지 않은 수량",
            )

        effective_price = price or 0.0

        # Live 모드: 2단계 확인 (거래소 정보 포함)
        if self.mode == Mode.LIVE:
            from exchange.validator import is_nxt_eligible
            nxt_ok   = is_nxt_eligible(symbol)
            exch_msg = (
                "NXT 거래 가능 종목입니다. 최적가(SOR)로 매도를 진행할까요?"
                if nxt_ok else
                "KRX 전용 종목입니다. 정규소 매도를 진행할까요?"
            )
            confirm_id = str(uuid4())[:8]
            self._pending_confirmations[confirm_id] = {
                "type": "SELL", "symbol": symbol, "qty": qty,
                "price": effective_price, "use_sor": nxt_ok,
            }
            return CommandResult(
                request_id=confirm_id,
                success=True,
                message=(
                    f"{exch_msg}\n"
                    f"종목: {name or symbol} ({symbol})\n"
                    f"수량: {qty}주 @ {effective_price:,.0f}원\n"
                    f"확인 코드: {confirm_id}\n"
                    f"/confirm {confirm_id} 로 실행"
                ),
            )

        return self._execute_sell(symbol, name, qty, effective_price)

    def _execute_buy(self, symbol: str, name: str, qty: int, price: float,
                     use_sor: bool = False) -> CommandResult:
        """실제 매수 실행 (Risk Guard → Order Manager)"""
        from uuid import uuid4
        from shared.schemas import Order, OrderType, Mode as ModeEnum
        from risk.risk_manager import get_risk_manager
        from trade.order_manager import get_order_manager

        try:
            if price <= 0:
                try:
                    from hub.data_hub import get_data_hub
                    price = float(get_data_hub().get_current_price(symbol) or 0)
                except Exception:
                    price = 0
                if price <= 0:
                    return CommandResult(
                        request_id=str(uuid4()),
                        success=False,
                        message=f"매수 실패: {symbol} 현재가 확인 불가",
                    )

            signal = Signal(
                symbol=symbol,
                name=name or symbol,
                side=OrderSide.BUY,
                price=price,
                quantity=qty,
                reason="manual_buy",
            )

            order_type = OrderType.MARKET if price <= 0 else OrderType.LIMIT
            order = Order(
                order_id=str(uuid4()),
                symbol=symbol,
                name=name or symbol,
                side=OrderSide.BUY,
                order_type=order_type,
                quantity=qty,
                price=price,
                amount=qty * price,
                reason="manual_buy",
            )

            get_risk_manager().check_order(order, self.mode)
            executed = get_order_manager().create_order(
                signal, price, qty, order_type=order_type, use_sor=use_sor
            )

            route = "SOR(NXT)" if use_sor else "KRX"
            if executed.filled_quantity <= 0:
                return CommandResult(
                    request_id=executed.order_id,
                    success=True,
                    message=f"매수 주문 제출 [{route}]: {symbol} 상태={executed.state.value}",
                )
            return CommandResult(
                request_id=executed.order_id,
                success=True,
                message=f"매수 완료 [{route}]: {symbol} {executed.filled_quantity}주 @ {executed.avg_filled_price:,.0f}원",
            )
        except RiskException as e:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message=f"리스크 차단: {e}",
            )
        except Exception as e:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message=f"매수 실패: {e}",
            )

    def _execute_sell(self, symbol: str, name: str, qty: int, price: float,
                      use_sor: bool = False) -> CommandResult:
        """실제 매도 실행 (Risk Guard → Order Manager)"""
        from uuid import uuid4
        from shared.schemas import Order, OrderType
        from risk.risk_manager import get_risk_manager
        from trade.order_manager import get_order_manager

        try:
            if price <= 0:
                try:
                    from account.account_manager import get_account_manager
                    pos = get_account_manager().get_position(symbol)
                    price = float((pos.current_price or pos.avg_buy_price) if pos else 0)
                except Exception:
                    price = 0
                if price <= 0:
                    return CommandResult(
                        request_id=str(uuid4()),
                        success=False,
                        message=f"매도 실패: {symbol} 현재가 확인 불가",
                    )

            signal = Signal(
                symbol=symbol,
                name=name or symbol,
                side=OrderSide.SELL,
                price=price,
                quantity=qty,
                reason="manual_sell",
            )

            order_type = OrderType.MARKET if price <= 0 else OrderType.LIMIT
            order = Order(
                order_id=str(uuid4()),
                symbol=symbol,
                name=name or symbol,
                side=OrderSide.SELL,
                order_type=order_type,
                quantity=qty,
                price=price,
                amount=qty * price,
                reason="manual_sell",
            )

            get_risk_manager().check_order(order, self.mode)
            executed = get_order_manager().create_order(
                signal, price, qty, order_type=order_type, use_sor=use_sor
            )

            route = "SOR(NXT)" if use_sor else "KRX"
            if executed.filled_quantity <= 0:
                return CommandResult(
                    request_id=executed.order_id,
                    success=True,
                    message=f"매도 주문 제출 [{route}]: {symbol} 상태={executed.state.value}",
                )
            return CommandResult(
                request_id=executed.order_id,
                success=True,
                message=f"매도 완료 [{route}]: {symbol} {executed.filled_quantity}주 @ {executed.avg_filled_price:,.0f}원",
            )
        except RiskException as e:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message=f"리스크 차단: {e}",
            )
        except Exception as e:
            return CommandResult(
                request_id=str(uuid4()),
                success=False,
                message=f"매도 실패: {e}",
            )


_manual_trade_handler: Optional[ManualTradeHandler] = None


def get_manual_trade_handler(mode: Mode = Mode.PAPER) -> ManualTradeHandler:
    global _manual_trade_handler
    if _manual_trade_handler is None or _manual_trade_handler.mode != mode:
        _manual_trade_handler = ManualTradeHandler(mode)
    return _manual_trade_handler
