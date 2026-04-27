"""
Token Monitor (Skeleton)
KIS API 토큰 상태 모니터링 및 자동 갱신
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TokenMonitor:
    """KIS 토큰 모니터링 (Skeleton)"""

    def __init__(self):
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        logger.info("[TokenMonitor] 초기화")

    def is_valid(self) -> bool:
        """토큰 유효 여부"""
        if self._token is None:
            return False
        if self._expires_at and datetime.now() >= self._expires_at:
            return False
        return True

    def refresh(self) -> bool:
        """토큰 갱신 (TODO)"""
        logger.info("[TokenMonitor] 토큰 갱신 TODO")
        return False

    def get_token(self) -> Optional[str]:
        if not self.is_valid():
            self.refresh()
        return self._token


_token_monitor: Optional[TokenMonitor] = None


def get_token_monitor() -> TokenMonitor:
    global _token_monitor
    if _token_monitor is None:
        _token_monitor = TokenMonitor()
    return _token_monitor
