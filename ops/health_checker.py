"""
Health Checker (Skeleton)
서버/API/DB 상태 확인
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HealthChecker:
    """시스템 건강 상태 확인 (Skeleton)"""

    def check_all(self) -> dict:
        """전체 시스템 상태 확인"""
        return {
            "api": self.check_api(),
            "db": self.check_db(),
            "data": self.check_data_feed(),
        }

    def check_api(self) -> bool:
        """KIS API 연결 상태 (TODO)"""
        return True  # Paper 모드: 항상 정상

    def check_db(self) -> bool:
        """DB 연결 상태"""
        try:
            from pathlib import Path
            return Path("storage").exists()
        except Exception:
            return False

    def check_data_feed(self) -> bool:
        """데이터 피드 상태 (TODO)"""
        return True  # Paper 모드: 항상 정상


_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker
