"""KIS 모의투자 클라이언트"""
import os
from typing import Optional
from trade.kis_base_client import KisBaseClient

class KisMockClient(KisBaseClient):
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    IS_MOCK  = True

_kis_mock_client: Optional[KisMockClient] = None

def get_kis_mock_client() -> KisMockClient:
    global _kis_mock_client
    if _kis_mock_client is None:
        _kis_mock_client = KisMockClient(
            app_key      = os.getenv("KIS_MOCK_APP_KEY", ""),
            app_secret   = os.getenv("KIS_MOCK_APP_SECRET", ""),
            cano         = os.getenv("KIS_MOCK_CANO", ""),
            acnt_prdt_cd = os.getenv("KIS_MOCK_ACNT_PRDT_CD", "01"),
        )
    return _kis_mock_client
