"""
Previous Day Loader — KIS 전일 OHLCV + 거래량 조회
FHKST03010100 (inquire-daily-price)
3분봉 빌드를 위한 기준 데이터 및 수급 분석에 활용
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TR_DAILY = "FHKST03010100"


class PreviousDayLoader:
    """
    KIS 일봉 조회 → 전일 OHLCV + 거래량

    반환 DataFrame 컬럼:
        date, open, high, low, close, volume, change_pct
    """

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

    def load(self, symbol: str, days: int = 20) -> Optional[pd.DataFrame]:
        """
        최근 days일 일봉 데이터 반환
        전일 데이터만 필요하면 df.iloc[-1] 사용
        """
        kis = self._get_kis()
        if kis is None:
            logger.warning(f"[PreviousDayLoader] KIS 클라이언트 없음")
            return None

        try:
            end_dt   = datetime.now().strftime("%Y%m%d")
            start_dt = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")

            url    = f"{kis.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
            params = {
                "FID_COND_MRK_DIV_CODE": "J",
                "FID_INPUT_ISCD":        symbol,
                "FID_PERIOD_DIV_CODE":   "D",   # D=일봉
                "FID_ORG_ADJ_PRC":       "1",   # 수정주가 적용
            }

            resp = kis._session.get(
                url,
                headers=kis._headers(TR_DAILY),
                params=params,
                timeout=5,
            )
            resp.raise_for_status()
            output = resp.json().get("output2", [])

            if not output:
                logger.debug(f"[PreviousDayLoader] {symbol} 일봉 없음")
                return None

            records = []
            for row in output[:days]:
                try:
                    records.append({
                        "date":       row.get("stck_bsop_date", ""),
                        "open":       float(row.get("stck_oprc",  0)),
                        "high":       float(row.get("stck_hgpr",  0)),
                        "low":        float(row.get("stck_lwpr",  0)),
                        "close":      float(row.get("stck_clpr",  0)),
                        "volume":     int(  row.get("acml_vol",   0)),
                        "change_pct": float(row.get("prdy_ctrt",  0)),
                    })
                except (ValueError, TypeError):
                    continue

            if not records:
                return None

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            df.sort_values("date", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df

        except Exception as e:
            logger.warning(f"[PreviousDayLoader] {symbol} 조회 실패: {e}")
            return None

    def get_prev_close(self, symbol: str) -> Optional[float]:
        """전일 종가만 반환"""
        df = self.load(symbol, days=2)
        if df is None or len(df) < 1:
            return None
        return float(df.iloc[-1]["close"])

    def get_prev_volume(self, symbol: str) -> Optional[int]:
        """전일 거래량만 반환"""
        df = self.load(symbol, days=2)
        if df is None or len(df) < 1:
            return None
        return int(df.iloc[-1]["volume"])


_loader: Optional[PreviousDayLoader] = None


def get_previous_day_loader(kis_client=None) -> PreviousDayLoader:
    global _loader
    if _loader is None:
        _loader = PreviousDayLoader(kis_client)
    return _loader
