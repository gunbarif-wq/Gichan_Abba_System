"""
Watchlist Builder — 당일 감시 종목 목록 생성
PreMarketScanner 결과 + VolumeScanner + UniverseFilter 통합
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


class WatchlistBuilder:
    """
    감시 목록 생성기

    우선순위:
    1. PreMarketScanner 완료 결과 (장전 스캔 완료 후)
    2. VolumeScanner (거래량 상위) + UniverseFilter
    3. 중복 제거 후 상위 MAX개 반환
    """

    MAX_SYMBOLS = 30

    def __init__(self, kis_client=None):
        self._kis = kis_client

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def build(self) -> List[str]:
        """감시 종목 코드 리스트 반환"""
        return [item["symbol"] for item in self.build_items()]

    def build_items(self) -> List[dict]:
        """
        감시 종목 상세 반환
        [{"symbol": ..., "name": ..., "score": ..., "source": ...}]
        """
        seen:    set   = set()
        result:  list  = []

        # ① VolumeScanner (KOSPI + KOSDAQ 거래량 상위)
        kis = self._get_kis()
        if kis is not None:
            try:
                from scanner.universe_filter import get_universe_filter
                uf = get_universe_filter()

                for market in ("J", "Q"):
                    raw = kis.get_volume_rank(market=market, top_n=20)
                    filtered = uf.filter_by_volume_rank_items(raw)
                    for rank, item in enumerate(filtered):
                        symbol = item.get("mksc_shrn_iscd", "")
                        name   = item.get("hts_kor_isnm", symbol)
                        if not symbol or symbol in seen:
                            continue
                        seen.add(symbol)
                        result.append({
                            "symbol": symbol,
                            "name":   name,
                            "score":  max(0, 20 - rank),
                            "source": f"volume_{market}",
                        })
            except Exception as e:
                logger.warning(f"[WatchlistBuilder] 거래량 스캔 실패: {e}")

        # ② ThemeScanner
        try:
            from scanner.theme_scanner import get_theme_scanner
            ts = get_theme_scanner(kis)
            for item in ts.scan_items(top_n=10):
                sym = item["symbol"]
                if sym in seen:
                    continue
                seen.add(sym)
                result.append({
                    "symbol": sym,
                    "name":   item["name"],
                    "score":  item["score"],
                    "source": "theme",
                })
        except Exception as e:
            logger.warning(f"[WatchlistBuilder] 테마 스캔 실패: {e}")

        # 점수 내림차순, 상위 MAX_SYMBOLS
        result.sort(key=lambda x: x["score"], reverse=True)
        result = result[:self.MAX_SYMBOLS]

        logger.info(f"[WatchlistBuilder] 감시 목록 {len(result)}개 생성")
        return result


_builder: WatchlistBuilder = None


def get_watchlist_builder(kis_client=None) -> WatchlistBuilder:
    global _builder
    if _builder is None:
        _builder = WatchlistBuilder(kis_client)
    return _builder
