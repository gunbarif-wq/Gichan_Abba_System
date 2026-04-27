"""Volume Scanner (Skeleton) - 거래량 급증 종목 스캔"""
import logging
from typing import List
logger = logging.getLogger(__name__)

class VolumeScanner:
    """거래량 급증 종목 탐색 (Skeleton) - TODO: 실시간 데이터 연동"""
    def scan(self) -> List[str]:
        logger.debug("[VolumeScanner] 스캔 TODO")
        return []

def get_volume_scanner() -> VolumeScanner:
    return VolumeScanner()
