"""거래량 상위 종목 스캔 — KIS API 연동"""
import logging
from typing import List
from trade.kis_mock_client import get_kis_mock_client

logger = logging.getLogger(__name__)


class VolumeScanner:
    """
    KIS API 거래량 상위 조회로 급등 후보 종목 수집
    KOSPI + KOSDAQ 각각 top_n개 조회 후 합산
    """

    def __init__(self, top_n: int = 20):
        self.top_n  = top_n
        self.client = get_kis_mock_client()

    def scan(self) -> List[str]:
        symbols = []
        for market in ("J", "Q"):  # J=코스피, Q=코스닥
            try:
                results = self.client.get_volume_rank(market=market, top_n=self.top_n)
                for item in results:
                    code = item.get("mksc_shrn_iscd", "")
                    if code:
                        symbols.append(code)
            except Exception as e:
                logger.warning(f"[VolumeScanner] {market} 스캔 실패: {e}")

        symbols = list(dict.fromkeys(symbols))  # 중복 제거, 순서 유지
        logger.info(f"[VolumeScanner] 스캔 완료: {len(symbols)}개")
        return symbols


_scanner = None

def get_volume_scanner() -> VolumeScanner:
    global _scanner
    if _scanner is None:
        _scanner = VolumeScanner()
    return _scanner
