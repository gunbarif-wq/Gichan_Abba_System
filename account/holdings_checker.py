"""
Holdings Checker — 보유 종목 조회
1순위: KIS API
2순위: AccountManager (Paper 모드 / fallback)
KIS → AccountManager 양방향 동기화
"""
import logging
from typing import Dict, Optional

from shared.schemas import Position

logger = logging.getLogger(__name__)


class HoldingsChecker:
    """
    보유 종목 조회 및 AccountManager 동기화
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

    def get_holdings(self) -> Dict[str, Position]:
        """보유 종목 전체 조회"""
        kis = self._get_kis()
        if kis is not None:
            try:
                raw = kis.get_holdings()
                if raw:
                    positions = self._parse_holdings(raw)
                    self._sync_account_holdings(positions)
                    return positions
            except Exception as e:
                logger.warning(f"[HoldingsChecker] KIS API 실패, fallback: {e}")

        # Fallback: AccountManager
        try:
            from account.account_manager import get_account_manager
            return get_account_manager().get_all_positions()
        except Exception:
            return {}

    def get_holding(self, symbol: str) -> Optional[Position]:
        """특정 종목 보유 조회"""
        return self.get_holdings().get(symbol)

    def _parse_holdings(self, raw: list) -> Dict[str, Position]:
        """KIS inquire-balance output1 → Position dict"""
        positions = {}
        for item in raw:
            symbol = item.get("pdno", "")
            if not symbol:
                continue
            try:
                qty     = int(  item.get("hldg_qty",    0))
                avg_prc = float(item.get("pchs_avg_prc", 0))
                cur_prc = float(item.get("prpr",         0))
                name    = item.get("prdt_name", symbol)

                if qty <= 0:
                    continue

                total_buy = avg_prc * qty
                cur_val   = cur_prc * qty
                pnl       = cur_val - total_buy
                pnl_ratio = pnl / total_buy * 100 if total_buy > 0 else 0.0

                positions[symbol] = Position(
                    symbol             = symbol,
                    name               = name,
                    quantity           = qty,
                    avg_buy_price      = avg_prc,
                    total_buy_amount   = total_buy,
                    current_price      = cur_prc,
                    unrealized_pnl     = pnl,
                    unrealized_pnl_ratio = pnl_ratio,
                )
            except (ValueError, TypeError) as e:
                logger.warning(f"[HoldingsChecker] 파싱 오류 {symbol}: {e}")
        return positions

    def _sync_account_holdings(self, positions: Dict[str, Position]) -> None:
        """KIS 보유 종목을 AccountManager에 동기화"""
        try:
            from account.account_manager import get_account_manager
            from trade.position_manager  import get_position_manager
            mgr = get_position_manager()
            for sym, pos in positions.items():
                mgr.update_position_price(sym, pos.current_price)
        except Exception:
            pass

    def summary(self) -> str:
        pos = self.get_holdings()
        if not pos:
            return "보유 종목 없음"
        lines = []
        for sym, p in pos.items():
            sign = "+" if p.unrealized_pnl_ratio >= 0 else ""
            lines.append(
                f"{p.name}({sym}) {p.quantity:,}주 "
                f"평균{p.avg_buy_price:,.0f}원 "
                f"{sign}{p.unrealized_pnl_ratio:.1f}%"
            )
        return "\n".join(lines)


_checker: Optional[HoldingsChecker] = None


def get_holdings_checker(kis_client=None) -> HoldingsChecker:
    global _checker
    if _checker is None:
        _checker = HoldingsChecker(kis_client)
    return _checker
