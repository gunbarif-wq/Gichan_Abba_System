"""Previous Day Loader (Skeleton) - 전일 데이터 로드"""
import logging
from typing import Optional
import pandas as pd
logger = logging.getLogger(__name__)

class PreviousDayLoader:
    """전일 OHLCV 데이터 로드 (Skeleton) - TODO: KIS API 연동"""
    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        logger.debug(f"[PreviousDayLoader] {symbol} 전일 데이터 TODO")
        return None

def get_previous_day_loader() -> PreviousDayLoader:
    return PreviousDayLoader()
