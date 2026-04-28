"""
Fill Checker — 주문 체결 확인
Paper 모드: 즉시 체결 가정
Mock/Live: KIS 당일 체결 조회 API (VTTC8001R / TTTC8001R)
"""

import logging
from datetime import datetime
from typing import Optional

from shared.schemas import Order, OrderState

logger = logging.getLogger(__name__)

# KIS 체결 조회 TR
TR_FILL_MOCK = "VTTC8001R"
TR_FILL_LIVE = "TTTC8001R"


class FillChecker:
    """
    체결 확인 처리기

    check_fill():
      - Paper 모드: Order를 그대로 FILLED 상태로 반환
      - Mock/Live: KIS inquire-daily-ccld API로 체결 내역 조회
    """

    def __init__(self, kis_client=None, is_mock: bool = True):
        self._kis     = kis_client
        self._is_mock = is_mock
        logger.info(f"[FillChecker] 초기화 (mock={is_mock})")

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def check_fill(self, order: Order) -> Order:
        """
        체결 상태 업데이트

        Paper 모드: 즉시 체결 처리
        Mock/Live:  KIS API 조회 후 상태 반영
        """
        if order.state in (OrderState.BUY_FILLED, OrderState.SELL_FILLED):
            return order

        kis = self._get_kis()
        if kis is None:
            # Paper 폴백: 즉시 체결
            return self._mark_filled(order)

        try:
            fills = self._query_fills(order.symbol)
            matched = [f for f in fills if f.get("orgn_odno") == order.order_id
                       or f.get("odno") == order.order_id]

            if matched:
                fill = matched[-1]
                filled_qty = int(fill.get("tot_ccld_qty", 0))
                avg_price  = float(fill.get("avg_prvs",    0))

                if filled_qty > 0:
                    order.filled_quantity   = filled_qty
                    order.avg_filled_price  = avg_price
                    order.filled_time       = datetime.now()
                    if filled_qty >= order.quantity:
                        if order.side.value == "BUY":
                            order.state = OrderState.BUY_FILLED
                        else:
                            order.state = OrderState.SELL_FILLED
                    else:
                        if order.side.value == "BUY":
                            order.state = OrderState.BUY_PARTIAL
                        else:
                            order.state = OrderState.SELL_PARTIAL
                    logger.info(
                        f"[FillChecker] 체결 확인: {order.symbol} "
                        f"{filled_qty}주 @ {avg_price:,.0f}원"
                    )
            else:
                # API 조회됐지만 매칭 없음 → Paper 폴백
                return self._mark_filled(order)

        except Exception as e:
            logger.warning(f"[FillChecker] API 조회 실패, 즉시 체결 처리: {e}")
            return self._mark_filled(order)

        return order

    def _query_fills(self, symbol: str) -> list:
        """KIS 당일 체결 조회"""
        kis = self._get_kis()
        tr_id = TR_FILL_MOCK if self._is_mock else TR_FILL_LIVE
        url   = f"{kis.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "CANO":          kis.cano,
            "ACNT_PRDT_CD":  kis.acnt_prdt_cd,
            "INQR_STRT_DT":  today,
            "INQR_END_DT":   today,
            "SLL_BUY_DVSN_CD": "00",   # 전체
            "INQR_DVSN":     "00",
            "PDNO":          symbol,
            "CCLD_DVSN":     "00",
            "ORD_GNO_BRNO":  "",
            "ODNO":          "",
            "INQR_DVSN_3":   "00",
            "INQR_DVSN_1":   "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        resp = kis._session.get(url, headers=kis._headers(tr_id),
                                params=params, timeout=5)
        resp.raise_for_status()
        return resp.json().get("output1", [])

    @staticmethod
    def _mark_filled(order: Order) -> Order:
        """즉시 체결 처리 (Paper 모드)"""
        order.filled_quantity  = order.quantity
        order.avg_filled_price = order.price
        order.filled_time      = datetime.now()
        if order.side.value == "BUY":
            order.state = OrderState.BUY_FILLED
        else:
            order.state = OrderState.SELL_FILLED
        return order

    def is_filled(self, order: Order) -> bool:
        return order.state in (OrderState.BUY_FILLED, OrderState.SELL_FILLED)

    def is_partial(self, order: Order) -> bool:
        return order.state in (OrderState.BUY_PARTIAL, OrderState.SELL_PARTIAL)


_fill_checker: Optional[FillChecker] = None


def get_fill_checker(kis_client=None, is_mock: bool = True) -> FillChecker:
    global _fill_checker
    if _fill_checker is None:
        _fill_checker = FillChecker(kis_client, is_mock)
    return _fill_checker
