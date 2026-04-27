"""
Command Auth
텔레그램 명령 권한 관리
"""

import logging
import os
from typing import Set

logger = logging.getLogger(__name__)


class CommandAuth:
    """
    명령 권한 관리자
    - 허용된 Telegram user_id만 명령 가능
    - .env의 TELEGRAM_CHAT_ID 기반
    """

    def __init__(self):
        self._allowed_ids: Set[str] = set()
        self._load_allowed_ids()
        logger.info(f"[CommandAuth] 초기화: {len(self._allowed_ids)}개 허용 ID")

    def _load_allowed_ids(self) -> None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if chat_id:
            self._allowed_ids.add(str(chat_id))

        # 추가 허용 ID (콤마 구분)
        extra = os.getenv("TELEGRAM_ALLOWED_IDS", "")
        for uid in extra.split(","):
            uid = uid.strip()
            if uid:
                self._allowed_ids.add(uid)

    def is_authorized(self, user_id: str) -> bool:
        """권한 확인"""
        if not self._allowed_ids:
            # 허용 ID가 없으면 모두 차단
            logger.warning("[CommandAuth] 허용된 user_id 없음 - 모두 차단")
            return False
        return str(user_id) in self._allowed_ids

    def add_allowed_id(self, user_id: str) -> None:
        self._allowed_ids.add(str(user_id))

    def remove_allowed_id(self, user_id: str) -> None:
        self._allowed_ids.discard(str(user_id))
