"""
Token Monitor — KIS 액세스 토큰 상태 모니터링
KisBaseClient의 토큰 관리에 위임하는 얇은 래퍼
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TokenMonitor:
    """
    KIS 토큰 상태 확인 및 갱신
    실제 토큰 관리는 KisBaseClient._token_lock 기반으로 처리
    이 클래스는 현재 상태 조회 인터페이스만 제공
    """

    def __init__(self, kis_client=None):
        self._kis = kis_client
        logger.info("[TokenMonitor] 초기화")

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def is_valid(self) -> bool:
        """토큰 유효 여부 (KisBaseClient 기준)"""
        kis = self._get_kis()
        if kis is None:
            return False
        return kis._is_token_valid()

    def get_expires_at(self) -> Optional[datetime]:
        """토큰 만료 시각"""
        kis = self._get_kis()
        if kis is None:
            return None
        return kis._token_expire_at

    def refresh(self) -> bool:
        """토큰 강제 갱신"""
        kis = self._get_kis()
        if kis is None:
            return False
        try:
            # _access_token 초기화 → get_access_token 호출 시 자동 재발급
            kis._access_token    = None
            kis._token_expire_at = None
            kis.get_access_token()
            logger.info("[TokenMonitor] 토큰 강제 갱신 완료")
            return True
        except Exception as e:
            logger.error(f"[TokenMonitor] 토큰 갱신 실패: {e}")
            return False

    def get_token(self) -> Optional[str]:
        """유효한 토큰 반환 (만료 시 자동 갱신)"""
        kis = self._get_kis()
        if kis is None:
            return None
        try:
            return kis.get_access_token()
        except Exception as e:
            logger.error(f"[TokenMonitor] 토큰 조회 실패: {e}")
            return None

    def status_str(self) -> str:
        """토큰 상태 문자열"""
        if not self.is_valid():
            return "만료/없음"
        exp = self.get_expires_at()
        if exp:
            remaining = (exp - datetime.now()).total_seconds() / 60
            return f"유효 (만료까지 {remaining:.0f}분)"
        return "유효"


_token_monitor: Optional[TokenMonitor] = None


def get_token_monitor(kis_client=None) -> TokenMonitor:
    global _token_monitor
    if _token_monitor is None:
        _token_monitor = TokenMonitor(kis_client)
    return _token_monitor
