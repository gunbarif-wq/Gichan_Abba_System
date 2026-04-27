"""
KIS 모의투자 클라이언트 (Skeleton)
실제 KIS 모의투자 API 호출 구조

TODO: KIS API 연동 구현
"""

import logging
from typing import Optional

from shared.schemas import Order, OrderState
from shared.errors import APIError, TokenExpired

logger = logging.getLogger(__name__)


class KisMockClient:
    """
    KIS 모의투자 API 클라이언트 (Skeleton)

    TODO:
    - 토큰 발급/갱신
    - 주문 전송
    - 체결 조회
    - 잔고 조회
    - 보유 종목 조회
    """

    BASE_URL = "https://openapivts.koreainvestment.com:29443"

    def __init__(self, app_key: str = "", app_secret: str = "", cano: str = "", acnt_prdt_cd: str = ""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.cano = cano
        self.acnt_prdt_cd = acnt_prdt_cd
        self._access_token: Optional[str] = None
        logger.info("[KisMockClient] 초기화 (API 연동 TODO)")

    def get_token(self) -> Optional[str]:
        """액세스 토큰 발급 (TODO)"""
        logger.warning("[KisMockClient] 토큰 발급 TODO")
        return None

    def place_order(self, order: Order) -> Order:
        """주문 전송 (TODO)"""
        raise APIError("KIS Mock 클라이언트 미구현 - TODO")

    def get_order_status(self, order_id: str) -> Optional[Order]:
        """주문 상태 조회 (TODO)"""
        raise APIError("KIS Mock 클라이언트 미구현 - TODO")

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (TODO)"""
        raise APIError("KIS Mock 클라이언트 미구현 - TODO")

    def get_balance(self) -> dict:
        """잔고 조회 (TODO)"""
        raise APIError("KIS Mock 클라이언트 미구현 - TODO")

    def get_holdings(self) -> list:
        """보유 종목 조회 (TODO)"""
        raise APIError("KIS Mock 클라이언트 미구현 - TODO")


_kis_mock_client: Optional[KisMockClient] = None


def get_kis_mock_client() -> KisMockClient:
    global _kis_mock_client
    if _kis_mock_client is None:
        import os
        _kis_mock_client = KisMockClient(
            app_key=os.getenv("KIS_APP_KEY", ""),
            app_secret=os.getenv("KIS_APP_SECRET", ""),
            cano=os.getenv("KIS_CANO", ""),
            acnt_prdt_cd=os.getenv("KIS_ACNT_PRDT_CD", "01"),
        )
    return _kis_mock_client
