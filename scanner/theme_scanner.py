"""
Theme Scanner — KIS API 기반 테마 순환매 스캔
전일/당일 상승 테마의 연속 흐름 종목 탐색
"""
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ThemeScanner:
    """
    KIS API get_theme_rank() 결과에서 종목 코드 추출
    PreMarketScanner와 달리 단독 사용 가능한 경량 스캐너
    """

    def __init__(self, kis_client=None):
        self._kis = kis_client
        logger.info("[ThemeScanner] 초기화")

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def scan(self, top_n: int = 20) -> List[str]:
        """테마 상위 종목 코드 목록 반환"""
        items = self.scan_items(top_n=top_n)
        return [item["symbol"] for item in items]

    def scan_items(self, top_n: int = 20) -> List[Dict]:
        """
        테마 순환매 스캔
        반환: [{"symbol": ..., "name": ..., "score": ..., "rank": ...}, ...]
        """
        kis = self._get_kis()
        if kis is None:
            logger.warning("[ThemeScanner] KIS 클라이언트 없음")
            return []

        try:
            raw = kis.get_theme_rank(top_n=top_n)
        except Exception as e:
            logger.warning(f"[ThemeScanner] 조회 실패: {e}")
            return []

        result = []
        for rank, item in enumerate(raw):
            symbol = item.get("mksc_shrn_iscd", "")
            name   = item.get("hts_kor_isnm", symbol)
            if not symbol:
                continue

            score = max(0, top_n - rank)
            result.append({
                "symbol": symbol,
                "name":   name,
                "rank":   rank + 1,
                "score":  score,
                "raw":    item,
            })

        logger.info(f"[ThemeScanner] 테마 종목 {len(result)}개 탐색")
        return result

    def get_top_symbols(self, top_n: int = 10) -> List[str]:
        """상위 N개 종목 코드만 반환 (간편 인터페이스)"""
        items = self.scan_items(top_n=top_n * 2)
        return [item["symbol"] for item in items[:top_n]]


_scanner: ThemeScanner = None


def get_theme_scanner(kis_client=None) -> ThemeScanner:
    global _scanner
    if _scanner is None:
        _scanner = ThemeScanner(kis_client)
    return _scanner
