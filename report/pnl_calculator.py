"""
PnL Calculator
손익 계산
"""

import logging
from typing import Optional

from shared.schemas import TradeResult, Order, OrderSide

logger = logging.getLogger(__name__)


class PnlCalculator:
    """
    손익 계산기
    - 매수/매도 금액 계산
    - 수수료 계산
    - 거래세 계산
    - 순손익 계산
    """
    
    def __init__(self, commission_rate: float = 0.00015, tax_rate: float = 0.0018):
        """
        손익 계산기 초기화
        
        Args:
            commission_rate: 수수료율 (기본 0.015%)
            tax_rate: 거래세율 (기본 0.18%)
        """
        self.commission_rate = commission_rate
        self.tax_rate = tax_rate
        logger.info(
            f"[PnlCalculator] 초기화: "
            f"수수료={commission_rate:.4%} 거래세={tax_rate:.2%}"
        )
    
    def calculate_commission(self, amount: float) -> float:
        """
        수수료 계산
        
        Args:
            amount: 거래금액
        
        Returns:
            수수료
        """
        return amount * self.commission_rate
    
    def calculate_tax(self, sell_amount: float) -> float:
        """
        거래세 계산 (매도 금액 기준)
        
        Args:
            sell_amount: 매도금액
        
        Returns:
            거래세
        """
        return sell_amount * self.tax_rate
    
    def calculate_trade_result(
        self,
        symbol: str,
        name: str,
        buy_quantity: int,
        buy_price: float,
        buy_commission: float,
        sell_quantity: int,
        sell_price: float,
        sell_commission: float,
        mode: str,
    ) -> TradeResult:
        """
        매매 결과 계산
        
        Args:
            symbol: 종목 코드
            name: 종목명
            buy_quantity: 매수 수량
            buy_price: 매수 평균가
            buy_commission: 매수 수수료
            sell_quantity: 매도 수량
            sell_price: 매도 평균가
            sell_commission: 매도 수수료
            mode: 운영 모드
        
        Returns:
            매매 결과
        """
        # 매수금액
        total_buy_amount = buy_quantity * buy_price
        
        # 매도금액
        total_sell_amount = sell_quantity * sell_price
        
        # 거래세 (매도금액 기준)
        tax = self.calculate_tax(total_sell_amount)
        
        # 순손익 = 매도금액 - 매수금액 - 수수료 - 거래세
        pnl = total_sell_amount - total_buy_amount - buy_commission - sell_commission - tax
        
        # 순손익률 = 순손익 / 매수금액 * 100
        if total_buy_amount > 0:
            pnl_ratio = (pnl / total_buy_amount) * 100
        else:
            pnl_ratio = 0.0
        
        # 실현손익 = 매도 수량 기준
        if sell_quantity > 0:
            sell_ratio = sell_quantity / buy_quantity if buy_quantity > 0 else 0
            realized_pnl = pnl * sell_ratio
        else:
            realized_pnl = 0.0
        
        # 남은 보유수량
        remaining_quantity = buy_quantity - sell_quantity
        
        result = TradeResult(
            symbol=symbol,
            name=name,
            mode=mode,
            buy_quantity=buy_quantity,
            sell_quantity=sell_quantity,
            buy_avg_price=buy_price,
            sell_avg_price=sell_price,
            total_buy_amount=total_buy_amount,
            total_sell_amount=total_sell_amount,
            buy_commission=buy_commission,
            sell_commission=sell_commission,
            tax=tax,
            pnl=pnl,
            pnl_ratio=pnl_ratio,
            realized_pnl=realized_pnl,
            remaining_quantity=remaining_quantity,
        )
        
        logger.info(
            f"[PnlCalculator] {symbol} 손익 계산: "
            f"손익금={pnl:,}원 손익률={pnl_ratio:.2f}%"
        )
        
        return result
    
    def get_summary_message(self, result: TradeResult) -> str:
        """
        매매 결과 요약 메시지
        
        Args:
            result: 매매 결과
        
        Returns:
            포맷된 메시지
        """
        message = f"""
📊 매매 결과
═══════════════════════════
종목: {result.name} ({result.symbol})
모드: {result.mode.upper()}

매입 정보
───────────────────────────
수량: {result.buy_quantity:,}주
평균가: {result.buy_avg_price:,}원
총금액: {result.total_buy_amount:,}원

매도 정보
───────────────────────────
수량: {result.sell_quantity:,}주
평균가: {result.sell_avg_price:,}원
총금액: {result.total_sell_amount:,}원

손익 계산
───────────────────────────
매수금액:     {result.total_buy_amount:>12,}원
매도금액:     {result.total_sell_amount:>12,}원
매수수수료:   {result.buy_commission:>12,.0f}원
매도수수료:   {result.sell_commission:>12,.0f}원
거래세:       {result.tax:>12,.0f}원
───────────────────────────
순손익금:     {result.pnl:>12,.0f}원
순손익률:     {result.pnl_ratio:>12.2f}%

잔여 정보
───────────────────────────
남은수량:     {result.remaining_quantity:,}주
실현손익:     {result.realized_pnl:,}원
═══════════════════════════
""".strip()
        
        return message


# 전역 손익 계산기 인스턴스
_pnl_calculator: Optional[PnlCalculator] = None


def get_pnl_calculator(
    commission_rate: float = 0.00015,
    tax_rate: float = 0.0018
) -> PnlCalculator:
    """손익 계산기 싱글톤 반환"""
    global _pnl_calculator
    if _pnl_calculator is None:
        _pnl_calculator = PnlCalculator(commission_rate, tax_rate)
    return _pnl_calculator
