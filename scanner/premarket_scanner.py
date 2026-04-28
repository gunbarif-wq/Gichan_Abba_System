"""
장전 스캐너 (07:00~08:00)
뉴스/공시, 테마 순환매, 거래량 급증 종목을 종합해 당일 감시 목록 생성
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_WATCHLIST = 30  # 최대 감시 종목 수


@dataclass
class WatchCandidate:
    """감시 후보 종목"""
    symbol:       str
    name:         str
    score:        float = 0.0          # 종합 점수 (높을수록 우선)
    reasons:      List[str] = field(default_factory=list)

    # 08:00~08:02 실시간 버퍼 (웹소켓 수신 후 채워짐)
    open_volume:     int   = 0         # 08:00~08:02 누적 거래량
    open_change_pct: float = 0.0       # 08:02 기준 등락률
    buy_ratio:       float = 0.0       # 매수체결 / (매수+매도) 체결 비율
    last_price:      int   = 0

    def add_tick(self, price: int, change_rate: float,
                 volume: int, ask_qty: int, bid_qty: int):
        self.last_price      = price
        self.open_change_pct = change_rate
        self.open_volume     = volume
        total_qty = ask_qty + bid_qty
        self.buy_ratio = bid_qty / total_qty if total_qty > 0 else 0.5

    def is_buy_ready(self) -> bool:
        """08:02 매수 진입 조건"""
        return (
            self.open_change_pct >= 1.0   # +1% 이상 상승
            and self.buy_ratio   >= 0.55  # 매수 우위
            and self.open_volume >= 5000  # 최소 거래량
        )


class PreMarketScanner:
    """
    장전 분석기

    단계:
      1) 07:00~08:00  뉴스/테마/거래량 스캔 → 후보 목록
      2) 08:00~08:02  웹소켓 실시간 데이터 버퍼링
      3) 08:02        매수 준비 완료 신호
    """

    def __init__(self, kis_client):
        self.kis        = kis_client
        self._watchlist: Dict[str, WatchCandidate] = {}  # symbol → candidate

    # ── 1단계: 장전 스캔 (07:00~08:00) ────────────────────────────────────────

    def run_premarket_scan(self) -> List[WatchCandidate]:
        """뉴스/테마/거래량 종합 스캔"""
        logger.info("[PreMarket] 장전 스캔 시작")
        candidates: Dict[str, WatchCandidate] = {}

        # ① 거래량 상위 (KOSPI + KOSDAQ)
        self._scan_volume(candidates)
        time.sleep(0.5)

        # ② 뉴스/공시 관련 종목
        self._scan_news(candidates)
        time.sleep(0.5)

        # ③ 테마 순환매
        self._scan_theme(candidates)

        # 점수 기준 정렬 후 상위 MAX_WATCHLIST개 확정
        ranked = sorted(candidates.values(),
                        key=lambda c: c.score, reverse=True)[:MAX_WATCHLIST]

        self._watchlist = {c.symbol: c for c in ranked}

        logger.info(
            f"[PreMarket] 감시 목록 확정: {len(self._watchlist)}개\n"
            + "\n".join(
                f"  {c.symbol} {c.name} 점수={c.score:.1f} ({', '.join(c.reasons)})"
                for c in ranked[:10]
            )
        )
        return ranked

    def _scan_volume(self, candidates: Dict[str, WatchCandidate]):
        """거래량 상위 종목 스캔"""
        for market in ("J", "Q"):
            try:
                items = self.kis.get_volume_rank(market=market, top_n=20)
                for rank, item in enumerate(items):
                    symbol = item.get("mksc_shrn_iscd", "")
                    name   = item.get("hts_kor_isnm", symbol)
                    if not symbol:
                        continue

                    c = candidates.setdefault(
                        symbol, WatchCandidate(symbol=symbol, name=name)
                    )
                    # 순위가 높을수록 높은 점수 (1위=20점, 20위=1점)
                    score = max(0, 20 - rank)
                    c.score += score
                    c.reasons.append(f"거래량{rank+1}위")

            except Exception as e:
                logger.warning(f"[PreMarket] 거래량 스캔 실패({market}): {e}")

    def _scan_news(self, candidates: Dict[str, WatchCandidate]):
        """뉴스/공시 관련 종목 (KIS 공시 API)"""
        try:
            items = self.kis.get_news_list()
            for item in items[:20]:
                symbol = item.get("mksc_shrn_iscd", "")
                name   = item.get("hts_kor_isnm", symbol)
                if not symbol:
                    continue
                c = candidates.setdefault(
                    symbol, WatchCandidate(symbol=symbol, name=name)
                )
                c.score += 15
                c.reasons.append("뉴스/공시")
        except Exception as e:
            logger.warning(f"[PreMarket] 뉴스 스캔 실패: {e}")

    def _scan_theme(self, candidates: Dict[str, WatchCandidate]):
        """테마 순환매 — 전일 상승 테마의 연속 흐름"""
        try:
            items = self.kis.get_theme_rank()
            for rank, item in enumerate(items[:10]):
                symbol = item.get("mksc_shrn_iscd", "")
                name   = item.get("hts_kor_isnm", symbol)
                if not symbol:
                    continue
                c = candidates.setdefault(
                    symbol, WatchCandidate(symbol=symbol, name=name)
                )
                score = max(0, 10 - rank)
                c.score += score
                c.reasons.append(f"테마{rank+1}위")
        except Exception as e:
            logger.warning(f"[PreMarket] 테마 스캔 실패: {e}")

    # ── 2단계: 실시간 틱 버퍼링 (08:00~08:02) ─────────────────────────────────

    def on_tick(self, tick):
        """웹소켓 콜백 — 감시 종목의 틱 데이터 버퍼링"""
        c = self._watchlist.get(tick.symbol)
        if c:
            c.add_tick(
                price=tick.price,
                change_rate=tick.change_rate,
                volume=tick.volume,
                ask_qty=tick.ask_qty,
                bid_qty=tick.bid_qty,
            )

    # ── 3단계: 08:02 매수 후보 반환 ───────────────────────────────────────────

    def get_buy_candidates(self) -> List[WatchCandidate]:
        """08:02 기준 매수 진입 조건을 충족한 종목 반환"""
        ready = [c for c in self._watchlist.values() if c.is_buy_ready()]
        ready.sort(key=lambda c: c.score, reverse=True)
        logger.info(f"[PreMarket] 매수 준비 완료: {len(ready)}개")
        return ready

    def get_watchlist(self) -> List[WatchCandidate]:
        return list(self._watchlist.values())

    def get_symbols(self) -> List[str]:
        return list(self._watchlist.keys())
