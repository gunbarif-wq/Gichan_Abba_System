"""Watchlist Builder (Skeleton) - 감시 종목 목록 생성"""
import logging
from typing import List
logger = logging.getLogger(__name__)

class WatchlistBuilder:
    """감시 종목 목록 생성 (Skeleton) - TODO"""
    def build(self) -> List[str]:
        logger.debug("[WatchlistBuilder] 감시 목록 생성 TODO")
        return []

def get_watchlist_builder() -> WatchlistBuilder:
    return WatchlistBuilder()
