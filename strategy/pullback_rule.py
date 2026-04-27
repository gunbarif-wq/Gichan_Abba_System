"""Pullback Rule (Skeleton) - 풀백 신호 생성"""
import logging
from typing import Optional
import pandas as pd
from shared.schemas import Signal
logger = logging.getLogger(__name__)

class PullbackRule:
    """풀백 전략 (Skeleton) - TODO"""
    def check(self, symbol: str, name: str, df_3m: pd.DataFrame) -> Optional[Signal]:
        if len(df_3m) < 20:
            return None
        # TODO: 실제 풀백 판정 로직
        return None

def get_pullback_rule() -> PullbackRule:
    return PullbackRule()
