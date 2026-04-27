"""
System Status
전체 시스템 상태 집계
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SystemStatus:
    """시스템 전반 상태 집계"""

    def __init__(self):
        self._start_time = datetime.now()
        logger.info("[SystemStatus] 초기화")

    def get_uptime_seconds(self) -> float:
        return (datetime.now() - self._start_time).total_seconds()

    def get_status(self) -> dict:
        from ops.health_checker import get_health_checker
        health = get_health_checker().check_all()
        return {
            "uptime_seconds": self.get_uptime_seconds(),
            "started_at": self._start_time.isoformat(),
            "health": health,
            "all_ok": all(health.values()),
        }

    def format_status_message(self) -> str:
        status = self.get_status()
        uptime = int(status["uptime_seconds"])
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        health_str = " ".join(f"{k}:{'✅' if v else '❌'}" for k, v in status["health"].items())
        return (
            f"[시스템 상태]\n"
            f"가동시간: {h:02d}:{m:02d}:{s:02d}\n"
            f"상태: {health_str}\n"
        )


_system_status: Optional[SystemStatus] = None


def get_system_status() -> SystemStatus:
    global _system_status
    if _system_status is None:
        _system_status = SystemStatus()
    return _system_status
