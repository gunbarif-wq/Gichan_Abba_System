"""Universe Filter (Skeleton) - 거래 유니버스 필터링"""
import logging
from typing import List
logger = logging.getLogger(__name__)

class UniverseFilter:
    """
    종목 유니버스 필터링 (Skeleton)
    시총, 거래량, 가격 기준으로 필터링 - TODO
    """
    def filter(self, symbols: List[str]) -> List[str]:
        return symbols

def get_universe_filter() -> UniverseFilter:
    return UniverseFilter()
