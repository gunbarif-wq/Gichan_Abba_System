"""
Ops Agent — 운영 상태 종합 관리
시장 시간 + 토큰 + 헬스 체크 → OpsStatus
"""
import logging
from datetime import datetime
from typing import Optional

from shared.schemas import OpsStatus, Mode, SessionType

logger = logging.getLogger(__name__)


class OpsAgent:
    """
    운영 에이전트
    - 시장 시간 확인 (MarketClock)
    - 토큰 상태 (TokenMonitor)
    - 헬스 체크 (HealthChecker)
    - 종합 건강 상태 반환
    """

    def __init__(self, mode: Mode, kis_client=None):
        self.mode               = mode
        self._kis               = kis_client
        self._last_ops_status: Optional[OpsStatus] = None
        logger.info(f"[OpsAgent] 초기화: {mode.value}")

    def get_ops_status(self) -> OpsStatus:
        from ops.market_clock import get_market_clock
        from ops.health_checker import get_health_checker
        from ops.token_monitor  import get_token_monitor

        clock  = get_market_clock()
        health = get_health_checker(self._kis)
        token  = get_token_monitor(self._kis)

        health_map = health.check_all()
        token_ok   = health_map.get("token", False)
        api_ok     = health_map.get("api",   False)
        db_ok      = health_map.get("db",    False)

        if not token_ok:
            health_status   = "ERROR"
            system_message  = "토큰 만료 또는 없음"
        elif not api_ok:
            health_status   = "WARNING"
            system_message  = "KIS API 응답 없음"
        elif not db_ok:
            health_status   = "WARNING"
            system_message  = "storage 디렉토리 없음"
        else:
            health_status   = "OK"
            system_message  = token.status_str()

        status = OpsStatus(
            mode            = self.mode,
            is_market_open  = clock.is_market_open(),
            can_buy         = clock.can_buy(),
            can_sell        = clock.can_sell(),
            session         = clock.get_session(),
            current_time    = datetime.now(),
            health_status   = health_status,
            system_message  = system_message,
            metadata        = {
                "token_ok": token_ok,
                "api_ok":   api_ok,
                "db_ok":    db_ok,
            },
        )
        self._last_ops_status = status
        return status

    def is_system_healthy(self) -> bool:
        return self.get_ops_status().health_status == "OK"

    def status_summary(self) -> str:
        s = self.get_ops_status()
        return (
            f"[{s.mode.value}] {s.session.value} "
            f"매수={s.can_buy} 매도={s.can_sell} "
            f"상태={s.health_status} {s.system_message}"
        )


_ops_agent: Optional[OpsAgent] = None


def get_ops_agent(mode: Mode = Mode.PAPER, kis_client=None) -> OpsAgent:
    global _ops_agent
    if _ops_agent is None:
        _ops_agent = OpsAgent(mode, kis_client)
    return _ops_agent
