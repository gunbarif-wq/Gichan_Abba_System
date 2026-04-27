"""Theme Scanner (Skeleton) - 테마 종목 스캔"""
import logging
from typing import List
logger = logging.getLogger(__name__)

class ThemeScanner:
    """테마 종목 탐색 (Skeleton) - TODO"""
    def scan(self) -> List[str]:
        logger.debug("[ThemeScanner] 스캔 TODO")
        return []

def get_theme_scanner() -> ThemeScanner:
    return ThemeScanner()
