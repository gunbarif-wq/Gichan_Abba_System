"""
Command Router — 텔레그램 명령 실제 라우팅
/status /positions /buy /sell /stop /resume /cash 처리
"""
import logging
from datetime import datetime
from typing import Optional

from shared.schemas import CommandRequest, CommandResult

logger = logging.getLogger(__name__)


class CommandRouter:
    """
    지원 명령:
      /status    — 운영 상태 (시장 시간, 토큰, 헬스)
      /positions — 보유 종목 목록
      /cash      — 가용 현금
      /buy <종목코드> <수량> [가격]  — 수동 매수
      /sell <종목코드>              — 수동 매도 (전량)
      /stop      — 자동매수 일시 정지
      /resume    — 자동매수 재개
    """

    def __init__(self):
        logger.info("[CommandRouter] 초기화")

    def route_command(self, request: CommandRequest) -> CommandResult:
        cmd  = request.command.lstrip("/").lower()
        args = request.args
        rid  = str(request.timestamp)

        handlers = {
            "status":    self._handle_status,
            "positions": self._handle_positions,
            "cash":      self._handle_cash,
            "buy":       self._handle_buy,
            "sell":      self._handle_sell,
            "stop":      self._handle_stop,
            "resume":    self._handle_resume,
            "confirm":   self._handle_confirm,
            "help":      self._handle_help,
        }

        handler = handlers.get(cmd)
        if handler is None:
            return CommandResult(
                request_id=rid, success=False,
                message=f"알 수 없는 명령: /{cmd}\n/help 로 명령 목록 확인",
            )

        try:
            msg = handler(args)
            return CommandResult(request_id=rid, success=True, message=msg)
        except Exception as e:
            logger.error(f"[CommandRouter] /{cmd} 처리 오류: {e}")
            return CommandResult(request_id=rid, success=False,
                                 message=f"오류: {e}", error=str(e))

    # ── handlers ─────────────────────────────────────────────────────────────

    def _handle_status(self, args) -> str:
        from ops.ops_agent import get_ops_agent
        s = get_ops_agent().get_ops_status()
        now = datetime.now()
        return (
            f"📊 시스템 상태 {now:%H:%M:%S}\n"
            f"모드: {s.mode.value}\n"
            f"세션: {s.session.value}\n"
            f"매수가능: {'Y' if s.can_buy else 'N'}\n"
            f"매도가능: {'Y' if s.can_sell else 'N'}\n"
            f"헬스: {s.health_status}\n"
            f"{s.system_message}"
        )

    def _handle_positions(self, args) -> str:
        from account.account_manager import get_account_manager
        mgr  = get_account_manager()
        pos  = mgr.get_all_positions()
        cash = mgr.available_cash

        if not pos:
            return f"보유 종목 없음\n현금: {cash:,.0f}원"

        lines = [f"보유 종목 ({len(pos)}개)\n현금: {cash:,.0f}원\n"]
        for sym, p in pos.items():
            sign = "+" if p.unrealized_pnl_ratio >= 0 else ""
            lines.append(
                f"{p.name}({sym}) {p.quantity:,}주 "
                f"평균{p.avg_buy_price:,.0f}원 "
                f"{sign}{p.unrealized_pnl_ratio:.1f}%"
            )
        return "\n".join(lines)

    def _handle_cash(self, args) -> str:
        from account.account_manager import get_account_manager
        mgr   = get_account_manager()
        cash  = mgr.available_cash
        total = mgr.get_total_asset()
        return f"가용현금: {cash:,.0f}원\n총자산: {total:,.0f}원"

    def _handle_buy(self, args) -> str:
        """사용법: /buy 005930 10 [75000]"""
        if len(args) < 2:
            return "사용법: /buy <종목코드> <수량> [가격]"

        symbol   = args[0].strip()
        try:
            quantity = int(args[1])
        except ValueError:
            return f"수량 오류: {args[1]}"

        price = int(args[2]) if len(args) >= 3 else 0

        try:
            from run import get_shared_state
            state = get_shared_state()
            state.manual_buy_queue.put({
                "symbol": symbol, "quantity": quantity, "price": price,
                "source": "telegram",
            })
            return f"수동 매수 요청: {symbol} {quantity}주 @ {'시장가' if price == 0 else f'{price:,}원'}"
        except Exception as e:
            return f"매수 요청 실패: {e}"

    def _handle_sell(self, args) -> str:
        """사용법: /sell 005930"""
        if not args:
            return "사용법: /sell <종목코드>"

        symbol = args[0].strip()
        try:
            from run import get_shared_state
            state = get_shared_state()
            state.manual_sell_queue.put({
                "symbol": symbol, "source": "telegram",
            })
            return f"수동 매도 요청: {symbol}"
        except Exception as e:
            return f"매도 요청 실패: {e}"

    def _handle_stop(self, args) -> str:
        try:
            from run import get_shared_state
            state = get_shared_state()
            state.trading_paused = True
            return "자동 매수 일시 정지"
        except Exception as e:
            return f"정지 실패: {e}"

    def _handle_resume(self, args) -> str:
        try:
            from run import get_shared_state
            state = get_shared_state()
            state.trading_paused = False
            return "자동 매수 재개"
        except Exception as e:
            return f"재개 실패: {e}"

    def _handle_confirm(self, args) -> str:
        """Live 모드 2단계 확인: /confirm <confirm_id>"""
        if not args:
            return "사용법: /confirm <확인코드>"

        confirm_id = args[0].strip()
        try:
            from control.manual_trade_handler import get_manual_trade_handler
            handler = get_manual_trade_handler()
            pending = handler._pending_confirmations.pop(confirm_id, None)
            if pending is None:
                return f"확인 코드 없음 또는 만료: {confirm_id}"

            symbol = pending["symbol"]
            qty    = pending["qty"]
            price  = pending["price"]

            if pending["type"] == "BUY":
                result = handler._execute_buy(symbol, "", qty, price)
            else:
                result = handler._execute_sell(symbol, "", qty, price)

            return result.message
        except Exception as e:
            return f"확인 처리 실패: {e}"

    def _handle_help(self, args) -> str:
        return (
            "📋 사용 가능한 명령\n"
            "/status    — 시스템 상태\n"
            "/positions — 보유 종목\n"
            "/cash      — 가용 현금\n"
            "/buy <코드> <수량> [가격]\n"
            "/sell <코드>\n"
            "/stop      — 자동매수 정지\n"
            "/resume    — 자동매수 재개"
        )
