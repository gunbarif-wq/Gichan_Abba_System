"""
Trade Reporter
매매 완료 후 종목별 리포트 생성
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from shared.schemas import Order, TradeResult

logger = logging.getLogger(__name__)


class TradeReporter:
    """
    매매 결과 기록 및 리포트 생성
    """

    def __init__(self, report_dir: str = "storage/feedback_reports"):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._trade_log: List[dict] = []
        logger.info("[TradeReporter] 초기화")

    def record(self, result: TradeResult) -> None:
        """매매 결과 기록"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": result.symbol,
            "name": result.name,
            "mode": str(result.mode),
            "buy_quantity": result.buy_quantity,
            "sell_quantity": result.sell_quantity,
            "buy_avg_price": result.buy_avg_price,
            "sell_avg_price": result.sell_avg_price,
            "total_buy_amount": result.total_buy_amount,
            "total_sell_amount": result.total_sell_amount,
            "buy_commission": result.buy_commission,
            "sell_commission": result.sell_commission,
            "tax": result.tax,
            "pnl": result.pnl,
            "pnl_ratio": result.pnl_ratio,
            "remaining_quantity": result.remaining_quantity,
            "sell_reason": result.sell_reason,
            "status": result.status,
        }
        self._trade_log.append(record)

        # 파일 저장
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trade_{result.symbol}_{ts}.json"
        with open(str(self.report_dir / filename), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # BlackBox 기록
        try:
            from hub.blackbox_logger import get_blackbox
            get_blackbox().log_system("TRADE_COMPLETE", f"{result.symbol} pnl={result.pnl:,.0f}")
        except Exception:
            pass

        logger.info(f"[TradeReporter] 기록: {result.symbol} pnl={result.pnl:,.0f}원")

    def get_daily_summary(self) -> dict:
        """일일 매매 요약"""
        if not self._trade_log:
            return {"trades": 0}

        pnls = [r["pnl"] for r in self._trade_log]
        return {
            "trades": len(self._trade_log),
            "total_pnl": sum(pnls),
            "win_count": sum(1 for p in pnls if p > 0),
            "loss_count": sum(1 for p in pnls if p < 0),
            "avg_pnl": sum(pnls) / len(pnls),
        }

    def get_all_records(self) -> List[dict]:
        return list(self._trade_log)


_trade_reporter: Optional[TradeReporter] = None


def get_trade_reporter() -> TradeReporter:
    global _trade_reporter
    if _trade_reporter is None:
        _trade_reporter = TradeReporter()
    return _trade_reporter
