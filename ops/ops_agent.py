"""
Ops Agent
운영 상태 관리 (Skeleton)
"""

import logging
from datetime import datetime
from typing import Optional

from shared.schemas import OpsStatus, Mode, SessionType

logger = logging.getLogger(__name__)


class OpsAgent:
    """
    운영 에이전트 (Skeleton)

    역할:
    - 시장 시간 확인
    - 토큰 상태 확인
    - 서버 상태 확인
    - 데이터 지연 확인
    - 에이전트 생존 상태 확인
    - 주문 가능 상태 판단

    주문 금지 - 에이전트는 분석만 한다.

    TODO: 실제 상태 모니터링 구현
    """

    def __init__(self, mode: Mode):
        self.mode = mode
        self._last_ops_status: Optional[OpsStatus] = None
        logger.info(f"[OpsAgent] 초기화: {mode.value}")

    def get_ops_status(self) -> OpsStatus:
        """운영 상태 조회"""
        from ops.market_clock import get_market_clock
        clock = get_market_clock()

        status = OpsStatus(
            mode=self.mode,
            is_market_open=clock.is_market_open(),
            can_buy=clock.can_buy(),
            can_sell=clock.can_sell(),
            session=clock.get_session(),
            current_time=datetime.now(),
            health_status="OK",
            system_message="",
        )
        self._last_ops_status = status
        return status

    def is_system_healthy(self) -> bool:
        """시스템 전반 건강 상태"""
        status = self.get_ops_status()
        return status.health_status == "OK"


_ops_agent: Optional[OpsAgent] = None


def get_ops_agent(mode: Mode = Mode.PAPER) -> OpsAgent:
    global _ops_agent
    if _ops_agent is None:
        _ops_agent = OpsAgent(mode)
    return _ops_agent
