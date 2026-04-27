"""
KIS 실계좌 클라이언트 (Skeleton)
기본 비활성화 - live_trading=false 이면 절대 주문 불가

TODO: KIS 실계좌 API 연동 구현
"""

import logging
import os
from typing import Optional

from shared.schemas import Order
from shared.errors import LiveTradingDisabled, APIError

logger = logging.getLogger(__name__)


class KisLiveClient:
    """
    KIS 실계좌 API 클라이언트 (Skeleton)

    주의:
    - live_trading=false 이면 절대 주문 전송 불가
    - 모든 주문 전에 _safety_check() 실행 필수

    TODO: 실계좌 API 구현
    """

    BASE_URL = "https://openapi.koreainvestment.com:9443"
    LIVE_TRADING_ENABLED = False  # 기본 비활성화

    def __init__(self, app_key: str = "", app_secret: str = "", cano: str = "", acnt_prdt_cd: str = ""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.cano = cano
        self.acnt_prdt_cd = acnt_prdt_cd
        self._access_token: Optional[str] = None
        logger.warning("[KisLiveClient] 실계좌 클라이언트 초기화 - 기본 비활성화")

    def _safety_check(self) -> None:
        """실계좌 주문 안전 체크"""
        if not self.LIVE_TRADING_ENABLED:
            raise LiveTradingDisabled(
                "실계좌 거래 비활성화 상태 (live_trading=false). "
                "활성화하려면 config/live_config.yaml에서 live_trading: true로 변경 후 "
                "관리자 승인이 필요합니다."
            )

    def place_order(self, order: Order) -> Order:
        """주문 전송 (TODO)"""
        self._safety_check()
        raise APIError("KIS 실계좌 클라이언트 미구현 - TODO")

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (TODO)"""
        self._safety_check()
        raise APIError("KIS 실계좌 클라이언트 미구현 - TODO")

    def get_balance(self) -> dict:
        """잔고 조회 (TODO)"""
        raise APIError("KIS 실계좌 클라이언트 미구현 - TODO")


_kis_live_client: Optional[KisLiveClient] = None


def get_kis_live_client() -> KisLiveClient:
    global _kis_live_client
    if _kis_live_client is None:
        _kis_live_client = KisLiveClient(
            app_key=os.getenv("KIS_APP_KEY", ""),
            app_secret=os.getenv("KIS_APP_SECRET", ""),
            cano=os.getenv("KIS_CANO", ""),
            acnt_prdt_cd=os.getenv("KIS_ACNT_PRDT_CD", "01"),
        )
    return _kis_live_client
