"""Breakout Rule (Skeleton) - 돌파 신호 생성"""
import logging
from typing import Optional
import pandas as pd
from shared.schemas import Signal, OrderSide
logger = logging.getLogger(__name__)

class BreakoutRule:
    """돌파 전략 (Skeleton) - TODO: 실제 돌파 로직"""
    def check(self, symbol: str, name: str, df_3m: pd.DataFrame) -> Optional[Signal]:
        """돌파 신호 생성"""
        if len(df_3m) < 20:
            return None
        # TODO: 실제 돌파 판정 로직
        return None

def get_breakout_rule() -> BreakoutRule:
    return BreakoutRule()
