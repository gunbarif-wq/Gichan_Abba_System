"""
Trade Summary
텔레그램 메시지 포맷 생성
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from shared.schemas import TradeResult

logger = logging.getLogger(__name__)


class TradeSummary:
    """매매 결과 텔레그램 포맷 생성"""

    @staticmethod
    def format_trade_result(result: TradeResult) -> str:
        """매매 결과 포맷"""
        holding_str = ""
        if result.buy_time and result.sell_time:
            diff = result.sell_time - result.buy_time
            holding_str = _format_duration(diff)

        pnl_emoji = "🟢" if result.pnl >= 0 else "🔴"
        mode_str = str(result.mode).upper() if hasattr(result.mode, 'upper') else str(result.mode).upper()

        msg = (
            f"[매매 완료] {pnl_emoji}\n"
            f"종목: {result.name} ({result.symbol})\n"
            f"모드: {mode_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"매수수량:   {result.buy_quantity:>6,}주\n"
            f"매도수량:   {result.sell_quantity:>6,}주\n"
            f"매수평균가: {result.buy_avg_price:>10,.0f}원\n"
            f"매도평균가: {result.sell_avg_price:>10,.0f}원\n"
            f"총 매수금액:{result.total_buy_amount:>12,.0f}원\n"
            f"총 매도금액:{result.total_sell_amount:>12,.0f}원\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"매수수수료: {result.buy_commission:>10,.0f}원\n"
            f"매도수수료: {result.sell_commission:>10,.0f}원\n"
            f"거래세:     {result.tax:>10,.0f}원\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"순손익금:   {result.pnl:>10,.0f}원\n"
            f"순손익률:   {result.pnl_ratio:>10.2f}%\n"
            f"실현손익:   {result.realized_pnl:>10,.0f}원\n"
            f"남은수량:   {result.remaining_quantity:>6,}주\n"
        )

        if holding_str:
            msg += f"보유시간:   {holding_str}\n"

        if result.sell_reason:
            msg += f"매도사유:   {result.sell_reason}\n"

        return msg

    @staticmethod
    def format_daily_summary(summary: dict) -> str:
        """일일 요약 포맷"""
        win = summary.get("win_count", 0)
        loss = summary.get("loss_count", 0)
        total = summary.get("trades", 0)
        total_pnl = summary.get("total_pnl", 0.0)
        win_rate = win / total * 100 if total > 0 else 0.0

        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        return (
            f"[일일 매매 요약] {pnl_emoji}\n"
            f"총 매매: {total}건\n"
            f"수익: {win}건 / 손실: {loss}건\n"
            f"승률: {win_rate:.1f}%\n"
            f"총 손익: {total_pnl:,.0f}원\n"
        )


def _format_duration(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes}분"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}시간 {minutes}분"


_trade_summary: Optional[TradeSummary] = None


def get_trade_summary() -> TradeSummary:
    global _trade_summary
    if _trade_summary is None:
        _trade_summary = TradeSummary()
    return _trade_summary
