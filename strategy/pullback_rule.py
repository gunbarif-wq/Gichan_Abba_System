"""
Pullback Rule — 눌림목 진입 신호
조건: 단기 고점에서 1~3% 하락 + 단기 상승 추세 유지 + 거래량 감소 (건강한 눌림)
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from shared.schemas import Signal, OrderSide

logger = logging.getLogger(__name__)

# 눌림목 기준
HIGH_LOOKBACK   = 10   # 최근 고점 참조 봉 수
PULLBACK_MIN    = 1.0  # 최소 하락률 (%)
PULLBACK_MAX    = 5.0  # 최대 하락률 (%, 초과시 하락 전환 의심)
VOL_DECLINE_MIN = 0.4  # 눌림 구간 거래량 ≤ 평균의 이 배수 (건강한 눌림)
MA_LOOKBACK     = 20   # 추세 확인 이동평균
MIN_BARS        = 25


class PullbackRule:
    """
    눌림목 진입 전략

    진입 조건:
    1. 최근 10봉 최고가 대비 현재가가 1~5% 하락 (눌림 구간)
    2. 5봉 MA > 20봉 MA (단기 상승 추세 유지)
    3. 현재 거래량 <= 직전 20봉 평균 * VOL_DECLINE_MIN (거래량 감소 = 매도 압력 없음)
    4. 최근 고점이 그 이전 20봉 평균 대비 +3% 이상 (급등 후 눌림)
    """

    def check(self, symbol: str, name: str,
              df_3m: pd.DataFrame) -> Optional[Signal]:
        if len(df_3m) < MIN_BARS:
            return None

        closes  = df_3m["close"].values
        volumes = df_3m["volume"].values

        current_close = closes[-1]
        current_vol   = volumes[-1]

        # ① 최근 고점
        recent_high = closes[-HIGH_LOOKBACK - 1:-1].max()
        pullback_pct = (recent_high - current_close) / (recent_high + 1e-9) * 100
        in_pullback  = PULLBACK_MIN <= pullback_pct <= PULLBACK_MAX

        # ② 추세: MA5 > MA20
        ma5  = closes[-5:].mean()
        ma20 = closes[-20:].mean()
        uptrend = ma5 > ma20

        # ③ 거래량 감소 (건강한 눌림)
        avg_vol   = volumes[-21:-1].mean()
        vol_quiet = current_vol <= avg_vol * VOL_DECLINE_MIN if avg_vol > 0 else False

        # ④ 고점이 충분히 높았는지 (급등 확인)
        base_avg    = closes[-HIGH_LOOKBACK - 20:-HIGH_LOOKBACK].mean() if len(closes) >= HIGH_LOOKBACK + 20 else closes[:-HIGH_LOOKBACK].mean()
        surge_exist = recent_high > base_avg * 1.03 if base_avg > 0 else False

        if not (in_pullback and uptrend):
            return None

        # vol_quiet or surge_exist 중 하나만 충족해도 진입 (약한 조건)
        if not (vol_quiet or surge_exist):
            return None

        reason = (f"눌림목 "
                  f"(고점={recent_high:,.0f} 현재={current_close:,.0f} "
                  f"눌림={pullback_pct:.1f}% "
                  f"MA5>MA20={'Y' if uptrend else 'N'})")

        logger.info(f"[Pullback] {symbol} {name}: {reason}")

        confidence = max(0.3, 1.0 - pullback_pct / (PULLBACK_MAX * 2))

        return Signal(
            symbol=symbol,
            name=name,
            side=OrderSide.BUY,
            price=float(current_close),
            quantity=1,
            reason=reason,
            confidence=round(confidence, 2),
            agent_source="pullback_rule",
            metadata={
                "recent_high":   recent_high,
                "pullback_pct":  round(pullback_pct, 2),
                "ma5":           round(ma5, 2),
                "ma20":          round(ma20, 2),
            },
        )


_rule: Optional[PullbackRule] = None


def get_pullback_rule() -> PullbackRule:
    global _rule
    if _rule is None:
        _rule = PullbackRule()
    return _rule
