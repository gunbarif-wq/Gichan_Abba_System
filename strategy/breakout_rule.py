"""
Breakout Rule — 돌파 신호 생성
조건: 20봉 고점 돌파 + 거래량 2배 이상 + 등락률 1% 이상
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from shared.schemas import Signal, OrderSide

logger = logging.getLogger(__name__)

# 돌파 판정 기준
LOOKBACK       = 20   # 고점 참조 봉 수
VOL_MULTIPLIER = 2.0  # 거래량 기준 배수
MIN_CHANGE_PCT = 1.0  # 최소 등락률 (%)
MIN_BARS       = 25   # 최소 데이터 봉 수


class BreakoutRule:
    """
    20봉 고점 돌파 전략

    진입 조건:
    1. 현재 종가 > 직전 LOOKBACK봉 최고가
    2. 현재 거래량 >= 직전 20봉 평균 * VOL_MULTIPLIER
    3. 현재 등락률 >= MIN_CHANGE_PCT%
    """

    def check(self, symbol: str, name: str,
              df_3m: pd.DataFrame) -> Optional[Signal]:
        if len(df_3m) < MIN_BARS:
            return None

        closes  = df_3m["close"].values
        volumes = df_3m["volume"].values
        opens   = df_3m["open"].values

        current_close  = closes[-1]
        current_vol    = volumes[-1]
        current_open   = opens[-1]

        # ① 20봉 고점 (현재 봉 제외)
        prior_high = closes[-LOOKBACK - 1:-1].max()

        # ② 평균 거래량 (직전 20봉, 현재 봉 제외)
        avg_vol = volumes[-21:-1].mean()
        if avg_vol <= 0:
            return None

        # ③ 등락률 (현재 봉 시가 기준)
        change_pct = (current_close - current_open) / (current_open + 1e-9) * 100

        # 판정
        breakout     = current_close > prior_high
        vol_surge    = current_vol >= avg_vol * VOL_MULTIPLIER
        price_move   = change_pct >= MIN_CHANGE_PCT

        if not (breakout and vol_surge and price_move):
            return None

        vol_ratio = current_vol / avg_vol
        reason = (f"20봉고점돌파 "
                  f"(고점={prior_high:,.0f}→{current_close:,.0f} "
                  f"거래량={vol_ratio:.1f}배 "
                  f"등락={change_pct:+.1f}%)")

        logger.info(f"[Breakout] {symbol} {name}: {reason}")

        # 매수가 = 현재가, 수량은 상위에서 결정 (1주)
        return Signal(
            symbol=symbol,
            name=name,
            side=OrderSide.BUY,
            price=float(current_close),
            quantity=1,
            reason=reason,
            confidence=min(1.0, vol_ratio / 5.0),
            agent_source="breakout_rule",
            metadata={
                "prior_high":  prior_high,
                "vol_ratio":   round(vol_ratio, 2),
                "change_pct":  round(change_pct, 2),
            },
        )


_rule: Optional[BreakoutRule] = None


def get_breakout_rule() -> BreakoutRule:
    global _rule
    if _rule is None:
        _rule = BreakoutRule()
    return _rule
