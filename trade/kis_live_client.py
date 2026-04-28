"""KIS 실투자 클라이언트 — live_trading=False 이면 주문 불가"""
import logging
import os
from typing import Optional
from trade.kis_base_client import KisBaseClient
from shared.errors import LiveTradingDisabled

logger = logging.getLogger(__name__)

class KisLiveClient(KisBaseClient):
    BASE_URL          = "https://openapi.koreainvestment.com:9443"
    IS_MOCK           = False
    LIVE_TRADING_ENABLED = False  # config에서 명시적으로 활성화해야 함

    def place_buy_order(self, symbol, quantity, price, order_type="00"):
        if not self.LIVE_TRADING_ENABLED:
            raise LiveTradingDisabled("실계좌 거래 비활성화 상태")
        return super().place_buy_order(symbol, quantity, price, order_type)

    def place_sell_order(self, symbol, quantity, price, order_type="00"):
        if not self.LIVE_TRADING_ENABLED:
            raise LiveTradingDisabled("실계좌 거래 비활성화 상태")
        return super().place_sell_order(symbol, quantity, price, order_type)

_kis_live_client: Optional[KisLiveClient] = None

def get_kis_live_client() -> KisLiveClient:
    global _kis_live_client
    if _kis_live_client is None:
        _kis_live_client = KisLiveClient(
            app_key      = os.getenv("KIS_APP_KEY", ""),
            app_secret   = os.getenv("KIS_APP_SECRET", ""),
            cano         = os.getenv("KIS_CANO", ""),
            acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD", "01"),
        )
    return _kis_live_client
