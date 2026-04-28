"""
Health Checker — 서버/API/토큰/데이터 피드 상태 확인
"""
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

STORAGE_DIR = Path("storage")


class HealthChecker:
    """
    시스템 전반 건강 상태 확인
    check_all() 결과: {"api": bool, "token": bool, "db": bool, "data": bool}
    """

    def __init__(self, kis_client=None):
        self._kis = kis_client

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def check_all(self) -> Dict[str, bool]:
        return {
            "api":   self.check_api(),
            "token": self.check_token(),
            "db":    self.check_db(),
            "data":  self.check_data_feed(),
        }

    def check_api(self) -> bool:
        """KIS REST API 연결 상태 — 삼성전자 현재가 조회로 확인"""
        kis = self._get_kis()
        if kis is None:
            return False
        try:
            result = kis.get_current_price("005930")
            return bool(result)
        except Exception as e:
            logger.warning(f"[HealthChecker] API 체크 실패: {e}")
            return False

    def check_token(self) -> bool:
        """KIS 토큰 유효 여부"""
        try:
            from ops.token_monitor import get_token_monitor
            return get_token_monitor(self._kis).is_valid()
        except Exception:
            return False

    def check_db(self) -> bool:
        """storage 디렉토리 존재 여부"""
        return STORAGE_DIR.exists()

    def check_data_feed(self) -> bool:
        """WebSocket 데이터 피드 신선도 — DataHub 마지막 업데이트 기준"""
        try:
            from hub.data_hub import get_data_hub
            hub = get_data_hub()
            delay = hub.get_data_delay_seconds()
            if delay is None:
                return True   # 아직 데이터 없음 (초기 상태)
            return delay <= 120.0  # 2분 이내
        except Exception:
            return True

    def is_all_ok(self) -> bool:
        status = self.check_all()
        # api/token 이 핵심; db/data는 경고만
        return status.get("api", False) and status.get("token", False)

    def summary(self) -> str:
        s = self.check_all()
        parts = [f"{k}={'OK' if v else 'NG'}" for k, v in s.items()]
        return " | ".join(parts)


_health_checker: HealthChecker = None


def get_health_checker(kis_client=None) -> HealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker(kis_client)
    return _health_checker
