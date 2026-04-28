"""
텔레그램 알림 — requests 기반 동기 발송
매수/매도/수익/30분 모니터링 리포트
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:

    RETRY_COUNT = 3
    RETRY_DELAY = 2

    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._ok     = bool(self.token and self.chat_id)
        self._lock   = threading.Lock()  # 동시 발송 순서 보장

        if self._ok:
            logger.info("[Telegram] 초기화 완료")
        else:
            logger.warning("[Telegram] 토큰/채팅ID 없음 — 콘솔 출력 모드")

    # ── 기본 발송 ──────────────────────────────────────────────────────────────

    def send(self, message: str) -> bool:
        if not self._ok:
            print(f"[Telegram 미설정] {message}")
            return False

        url  = TELEGRAM_API.format(token=self.token)
        data = {
            "chat_id":    self.chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }

        with self._lock:
            for attempt in range(self.RETRY_COUNT):
                try:
                    resp = requests.post(url, data=data, timeout=10)
                    if resp.status_code == 200:
                        return True
                    logger.warning(
                        f"[Telegram] 발송 실패 {resp.status_code}: {resp.text[:100]}"
                    )
                except requests.RequestException as e:
                    logger.warning(f"[Telegram] 연결 오류 ({attempt+1}/{self.RETRY_COUNT}): {e}")
                    if attempt < self.RETRY_COUNT - 1:
                        time.sleep(self.RETRY_DELAY)

        return False

    # ── 매수 알림 ──────────────────────────────────────────────────────────────

    def send_buy(self, symbol: str, name: str, price: int,
                 quantity: int, amount: int):
        msg = (
            f"🟢 <b>매수 체결</b>\n"
            f"종목: {name} ({symbol})\n"
            f"매수가: {price:,}원\n"
            f"수량: {quantity:,}주\n"
            f"매수금액: {amount:,}원\n"
            f"시각: {datetime.now():%H:%M:%S}"
        )
        self.send(msg)

    # ── 매도 알림 ──────────────────────────────────────────────────────────────

    def send_sell(self, symbol: str, name: str, price: int,
                  quantity: int, amount: int):
        msg = (
            f"🔴 <b>매도 체결</b>\n"
            f"종목: {name} ({symbol})\n"
            f"매도가: {price:,}원\n"
            f"수량: {quantity:,}주\n"
            f"매도금액: {amount:,}원\n"
            f"시각: {datetime.now():%H:%M:%S}"
        )
        self.send(msg)

    # ── 매도 완료 수익 알림 ────────────────────────────────────────────────────

    def send_profit(self, symbol: str, name: str,
                    buy_price: int, sell_price: int,
                    quantity: int, profit: int, profit_rate: float,
                    reason: str = ""):
        emoji = "📈" if profit >= 0 else "📉"
        sign  = "+" if profit >= 0 else ""
        msg = (
            f"{emoji} <b>매매 완료</b>\n"
            f"종목: {name} ({symbol})\n"
            f"매수가: {buy_price:,}원  →  매도가: {sell_price:,}원\n"
            f"수량: {quantity:,}주\n"
            f"수익금: {sign}{profit:,}원\n"
            f"수익률: {sign}{profit_rate:.2f}%\n"
        )
        if reason:
            msg += f"사유: {reason}\n"
        msg += f"시각: {datetime.now():%H:%M:%S}"
        self.send(msg)

    # ── 30분 모니터링 리포트 ──────────────────────────────────────────────────

    def send_monitor_report(self, positions: dict, available_cash: float,
                             total_asset: float):
        now = datetime.now()
        lines = [
            f"📊 <b>모니터링 리포트</b> {now:%H:%M}",
            f"현금: {available_cash:,.0f}원",
            f"총자산: {total_asset:,.0f}원",
            "",
        ]

        if positions:
            lines.append(f"<b>보유 종목 ({len(positions)}개)</b>")
            for sym, pos in positions.items():
                sign  = "+" if pos.unrealized_pnl_ratio >= 0 else ""
                emoji = "🔺" if pos.unrealized_pnl_ratio >= 0 else "🔻"
                lines.append(
                    f"{emoji} {pos.name}({sym}) "
                    f"{pos.quantity:,}주 | "
                    f"평균가 {pos.avg_buy_price:,.0f}원 | "
                    f"{sign}{pos.unrealized_pnl_ratio:.2f}%"
                )
        else:
            lines.append("보유 종목 없음")

        self.send("\n".join(lines))

    def send_status(self, mode: str, session: str, can_buy: bool,
                    can_sell: bool, health: str, message: str = ""):
        flag_buy  = "Y" if can_buy  else "N"
        flag_sell = "Y" if can_sell else "N"
        msg = (
            f"📊 <b>시스템 상태</b> {datetime.now():%H:%M:%S}\n"
            f"모드: {mode}\n"
            f"세션: {session}\n"
            f"매수가능: {flag_buy}  매도가능: {flag_sell}\n"
            f"헬스: {health}"
        )
        if message:
            msg += f"\n{message}"
        self.send(msg)

    def send_error(self, message: str):
        self.send(f"⚠️ <b>오류</b>\n{message}")

    def send_system(self, message: str):
        self.send(f"🤖 <b>시스템</b>\n{message}")


# ── 싱글톤 ────────────────────────────────────────────────────────────────────
_notifier: Optional[TelegramNotifier] = None

def get_telegram_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
