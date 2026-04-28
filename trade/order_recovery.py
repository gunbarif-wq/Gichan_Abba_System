"""
Order Recovery — UNKNOWN 상태 주문 복구
KIS 미체결 조회 (VTTC8036R) + 체결 조회로 최종 상태 확정
"""

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

TR_PENDING_MOCK = "VTTC8036R"
TR_PENDING_LIVE = "TTTC8036R"


class OrderRecovery:
    """
    UNKNOWN 상태 주문 복구

    흐름:
    1. KIS 미체결 조회 → 주문번호 있으면 → 아직 미체결(PENDING)
    2. KIS 체결 조회   → 매칭 있으면     → 체결 완료(FILLED)
    3. 둘 다 없으면    → 취소 가정(CANCELLED) 또는 STILL_UNKNOWN
    텔레그램 경보는 호출자(OrderManager)가 담당
    """

    def __init__(self, kis_client=None, is_mock: bool = True):
        self._kis              = kis_client
        self._is_mock          = is_mock
        self._lock             = threading.Lock()
        self._recovery_history: list = []
        logger.info("[OrderRecovery] 초기화")

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def recover_unknown_order(self, order_id: str, symbol: str) -> str:
        """
        Returns: 'FILLED' | 'PENDING' | 'CANCELLED' | 'STILL_UNKNOWN'
        """
        logger.warning(f"[OrderRecovery] UNKNOWN 복구 시도: {order_id} {symbol}")
        result = "STILL_UNKNOWN"

        kis = self._get_kis()
        if kis is None:
            self._record(order_id, symbol, result)
            return result

        try:
            # ① 미체결 조회
            pending = self._query_pending(symbol)
            if any(p.get("odno") == order_id or
                   p.get("orgn_odno") == order_id
                   for p in pending):
                result = "PENDING"
                logger.info(f"[OrderRecovery] {order_id} → 미체결 확인")
                self._record(order_id, symbol, result)
                return result

            # ② 체결 조회
            from trade.fill_checker import FillChecker
            fills = FillChecker(kis, self._is_mock)._query_fills(symbol)
            if any(f.get("odno") == order_id or
                   f.get("orgn_odno") == order_id
                   for f in fills):
                result = "FILLED"
                logger.info(f"[OrderRecovery] {order_id} → 체결 확인")
                self._record(order_id, symbol, result)
                return result

            # ③ 둘 다 없으면 취소 가정
            result = "CANCELLED"
            logger.info(f"[OrderRecovery] {order_id} → 취소 가정")

        except Exception as e:
            logger.error(f"[OrderRecovery] API 오류: {e}")

        self._record(order_id, symbol, result)
        return result

    def _query_pending(self, symbol: str) -> list:
        """KIS 미체결 조회"""
        kis   = self._get_kis()
        tr_id = TR_PENDING_MOCK if self._is_mock else TR_PENDING_LIVE
        url   = f"{kis.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO":          kis.cano,
            "ACNT_PRDT_CD":  kis.acnt_prdt_cd,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1":   "0",
            "INQR_DVSN_2":   "0",
        }
        resp = kis._session.get(url, headers=kis._headers(tr_id),
                                params=params, timeout=5)
        resp.raise_for_status()
        output = resp.json().get("output", [])
        # symbol 필터링
        return [o for o in output if o.get("pdno", "") == symbol]

    def _record(self, order_id: str, symbol: str, result: str) -> None:
        with self._lock:
            self._recovery_history.append({
                "order_id":  order_id,
                "symbol":    symbol,
                "result":    result,
                "timestamp": datetime.now().isoformat(),
            })

    def get_history(self) -> list:
        with self._lock:
            return list(self._recovery_history)


_order_recovery: Optional[OrderRecovery] = None


def get_order_recovery(kis_client=None, is_mock: bool = True) -> OrderRecovery:
    global _order_recovery
    if _order_recovery is None:
        _order_recovery = OrderRecovery(kis_client, is_mock)
    return _order_recovery
