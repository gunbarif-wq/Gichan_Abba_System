"""
Data Hub
시장 데이터 배포 허브 (Skeleton)
실시간 데이터를 에이전트에게 배포한다.
"""

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DataHub:
    """
    데이터 허브 (Skeleton)

    역할:
    - 실시간 시세 데이터 수신 및 배포
    - 에이전트에게 구독 인터페이스 제공
    - 데이터 지연 모니터링

    TODO: WebSocket 기반 실시간 데이터 연동
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._last_data: Dict[str, dict] = {}
        self._last_update: Optional[datetime] = None
        logger.info("[DataHub] 초기화")

    def subscribe(self, channel: str, callback: Callable) -> None:
        """채널 구독"""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
        logger.debug(f"[DataHub] 구독: {channel}")

    def publish(self, channel: str, data: dict) -> None:
        """데이터 발행"""
        self._last_data[channel] = data
        self._last_update = datetime.now()

        for callback in self._subscribers.get(channel, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"[DataHub] 콜백 오류: {channel} -> {e}")

    def get_last(self, channel: str) -> Optional[dict]:
        """마지막 데이터 조회"""
        return self._last_data.get(channel)

    def get_data_delay_seconds(self) -> Optional[float]:
        """데이터 지연 시간 (초)"""
        if self._last_update is None:
            return None
        return (datetime.now() - self._last_update).total_seconds()

    def is_data_fresh(self, max_delay_seconds: float = 60.0) -> bool:
        """데이터가 신선한지 여부"""
        delay = self.get_data_delay_seconds()
        if delay is None:
            return False
        return delay <= max_delay_seconds

    def get_current_price(self, symbol: str) -> Optional[float]:
        """현재가 조회 (TODO: 실제 시세 연동)"""
        # Paper 모드: 마지막 데이터에서 가격 반환
        data = self._last_data.get(f"price_{symbol}")
        if data:
            return data.get("price")
        return None


# 싱글톤
_data_hub: Optional[DataHub] = None


def get_data_hub() -> DataHub:
    global _data_hub
    if _data_hub is None:
        _data_hub = DataHub()
    return _data_hub
