"""
Telegram 알림 (Skeleton)
TODO: python-telegram-bot 연동
"""
import logging
import os
from typing import Optional
logger = logging.getLogger(__name__)

class TelegramNotifier:
    """텔레그램 알림 발송 (Skeleton)"""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._available = bool(self.token and self.chat_id)
        logger.info(f"[TelegramNotifier] 초기화 available={self._available}")

    def send(self, message: str) -> bool:
        """메시지 발송 (TODO: 실제 API 호출)"""
        if not self._available:
            logger.debug(f"[TelegramNotifier] 토큰/채팅ID 없음 - 콘솔 출력: {message[:50]}...")
            return False
        # TODO: requests.post to Telegram API
        logger.info(f"[TelegramNotifier] 발송 TODO: {message[:50]}...")
        return True

    def send_trade_result(self, result_message: str) -> bool:
        return self.send(f"[거래 결과]\n{result_message}")

    def send_error(self, error_message: str) -> bool:
        return self.send(f"⚠️ [오류]\n{error_message}")

_notifier: Optional[TelegramNotifier] = None

def get_telegram_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
