"""Daily Report - 일일 리포트 생성 및 발송"""
import logging
from typing import Optional
logger = logging.getLogger(__name__)

class DailyReport:
    """일일 매매 리포트 생성 및 발송"""

    def send_daily_summary(self) -> bool:
        """일일 요약 텔레그램 발송"""
        try:
            from report.trade_reporter import get_trade_reporter
            from report.trade_summary import get_trade_summary
            from notify.telegram import get_telegram_notifier

            summary = get_trade_reporter().get_daily_summary()
            msg = get_trade_summary().format_daily_summary(summary)
            return get_telegram_notifier().send(msg)
        except Exception as e:
            logger.error(f"[DailyReport] 실패: {e}")
            return False

_daily_report: Optional[DailyReport] = None

def get_daily_report() -> DailyReport:
    global _daily_report
    if _daily_report is None:
        _daily_report = DailyReport()
    return _daily_report
