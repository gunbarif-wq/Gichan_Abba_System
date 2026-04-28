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
    exchange:     str  = "KRX"         # 상장 거래소: KRX(코스피/코스닥) | NXT(넥스트레이드)

    # 08:00~08:00:10 실시간 버퍼 (웹소켓 수신 후 채워짐)
    open_volume:     int   = 0         # 08:00~08:00:10 누적 거래량
    open_change_pct: float = 0.0       # 08:00:10 기준 등락률
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
        """
        장전 단일가 매수 진입 조건.
        웹소켓 틱 없이 스캔 점수만으로 판단 (단일가는 실시간 틱 없음).
        """
        return self.score >= 5.0  # 거래량 상위 진입 점수 이상


class PreMarketScanner:
    """
    장전 분석기

    단계:
      1) 07:00~08:00  뉴스/테마/거래량 스캔 → 후보 목록
      2) 08:00~08:00:10  웹소켓 실시간 데이터 버퍼링 (10초)
      3) 08:00:10        최종 선정 → 장전 시간외 매수
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
        from exchange.validator import is_nxt_eligible
        for market in ("J", "Q"):
            try:
                items = self.kis.get_volume_rank(market=market, top_n=20)
                for rank, item in enumerate(items):
                    symbol = item.get("mksc_shrn_iscd", "")
                    name   = item.get("hts_kor_isnm", symbol)
                    if not symbol:
                        continue

                    exchange = "NXT" if is_nxt_eligible(symbol) else "KRX"
                    c = candidates.setdefault(
                        symbol, WatchCandidate(symbol=symbol, name=name,
                                              exchange=exchange)
                    )
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

    # ── 시뮬레이션: 현재가로 틱 데이터 채우기 ────────────────────────────────────

    def fill_from_current_price(self):
        """시뮬레이션/테스트용 — 현재가 API로 on_tick 대체"""
        import time as _time
        for symbol, c in list(self._watchlist.items()):
            try:
                data = self.kis.get_current_price(symbol)
                price      = int(float(data.get("stck_prpr", 0) or 0))
                change_pct = float(data.get("prdy_ctrt", 0) or 0)
                volume     = int(float(data.get("acml_vol", 0) or 0))
                # 호가잔량으로 buy_ratio 근사
                ask_qty = int(float(data.get("askp_rsqn1", 1) or 1))
                bid_qty = int(float(data.get("bidp_rsqn1", 1) or 1))
                c.last_price      = price
                c.open_change_pct = change_pct
                c.open_volume     = volume
                total = ask_qty + bid_qty
                c.buy_ratio = bid_qty / total if total > 0 else 0.5
                _time.sleep(0.05)
            except Exception as e:
                logger.debug(f"[PreMarket] {symbol} 현재가 조회 실패: {e}")

    # ── 2단계: 실시간 틱 버퍼링 (08:00~08:00:10) ──────────────────────────────

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

    # ── 3단계: 08:00:10 최종 선정 ─────────────────────────────────────────────

    def get_buy_candidates(self) -> List[WatchCandidate]:
        """08:00:10 기준 매수 진입 조건을 충족한 종목 반환"""
        ready = [c for c in self._watchlist.values() if c.is_buy_ready()]
        ready.sort(key=lambda c: c.score, reverse=True)
        logger.info(f"[PreMarket] 매수 준비 완료: {len(ready)}개")
        return ready

    def get_watchlist(self) -> List[WatchCandidate]:
        return list(self._watchlist.values())

    def get_symbols(self) -> List[str]:
        return list(self._watchlist.keys())
