"""
Universe Filter — 거래 유니버스 필터링
가격·거래량·시총 기준으로 분석 대상 종목을 사전에 걸러낸다.
"""
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# 필터 기준값
PRICE_MIN    = 1_000     # 최소 주가 (원) — 동전주 제외
PRICE_MAX    = 300_000   # 최대 주가 (원) — 초고가주 유동성 부족
VOLUME_MIN   = 100_000   # 최소 거래량 (주)
CHANGE_MAX   = 29.0      # 최대 등락률 (%) — 상한가 근접 제외 (슬리피지)
CHANGE_MIN   = -29.0     # 최소 등락률 (%) — 하한가 근접 제외


class UniverseFilter:
    """
    종목 유니버스 필터링

    입력:
        symbols: KIS volume_rank 등에서 수집된 종목 코드 목록

    출력:
        가격·거래량·등락률 조건을 모두 만족하는 종목 코드 목록

    kwargs로 종목별 시세 dict를 받으면 실제 필터링, 없으면 패스스루
    """

    def filter(self, symbols: List[str],
               price_map:  Dict[str, float] = None,
               volume_map: Dict[str, int]   = None,
               change_map: Dict[str, float] = None) -> List[str]:
        """
        symbols: 종목 코드 리스트
        price_map:  {symbol: current_price}
        volume_map: {symbol: today_volume}
        change_map: {symbol: change_pct}
        """
        if not (price_map or volume_map or change_map):
            # 시세 데이터 없으면 패스스루 (PreMarket 스캔 전)
            return symbols

        result = []
        for sym in symbols:
            price  = (price_map  or {}).get(sym)
            volume = (volume_map or {}).get(sym)
            change = (change_map or {}).get(sym)

            if price is not None:
                if not (PRICE_MIN <= price <= PRICE_MAX):
                    logger.debug(f"[UniverseFilter] {sym} 제외: 가격 {price:,.0f}원")
                    continue

            if volume is not None:
                if volume < VOLUME_MIN:
                    logger.debug(f"[UniverseFilter] {sym} 제외: 거래량 {volume:,}")
                    continue

            if change is not None:
                if not (CHANGE_MIN <= change <= CHANGE_MAX):
                    logger.debug(f"[UniverseFilter] {sym} 제외: 등락률 {change:.1f}%")
                    continue

            result.append(sym)

        logger.info(f"[UniverseFilter] {len(symbols)} → {len(result)}개 필터링 완료")
        return result

    def filter_by_volume_rank_items(self, items: List[dict]) -> List[dict]:
        """
        KIS volume_rank API 결과 리스트를 직접 필터링
        item 키: mksc_shrn_iscd, stck_prpr, acml_vol, prdy_ctrt
        """
        result = []
        for item in items:
            try:
                price  = float(item.get("stck_prpr",  0))
                volume = int(  item.get("acml_vol",    0))
                change = float(item.get("prdy_ctrt",   0))

                if not (PRICE_MIN <= price <= PRICE_MAX):
                    continue
                if volume < VOLUME_MIN:
                    continue
                if not (CHANGE_MIN <= change <= CHANGE_MAX):
                    continue
                result.append(item)
            except (ValueError, TypeError):
                continue

        logger.info(f"[UniverseFilter] items {len(items)} → {len(result)} 필터링")
        return result


_filter: UniverseFilter = None


def get_universe_filter() -> UniverseFilter:
    global _filter
    if _filter is None:
        _filter = UniverseFilter()
    return _filter
