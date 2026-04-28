"""
매수/매도 실행 최적화
Vision 점수 + ATR 기반 주문 전략 및 손익 계산
"""

from typing import Optional


def calc_atr(price_history: list[dict], period: int = 14) -> float:
    """
    ATR(Average True Range) 계산 — 14일 기본.

    price_history: [{'high': float, 'low': float, 'close': float}, ...]
                   최신 데이터가 마지막 인덱스. 최소 period+1개 필요.
    """
    if len(price_history) < 2:
        return 0.0

    data = price_history[-(period + 1):]
    true_ranges = []
    for i in range(1, len(data)):
        high  = data[i]["high"]
        low   = data[i]["low"]
        prev_close = data[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0
    return sum(true_ranges[-period:]) / min(len(true_ranges), period)


def get_tick_size(price: float) -> int:
    """KRX 호가 단위 반환."""
    if price < 1_000:      return 1
    if price < 5_000:      return 5
    if price < 10_000:     return 10
    if price < 50_000:     return 50
    if price < 100_000:    return 100
    if price < 500_000:    return 500
    return 1_000


def optimize(
    vision_score: float,
    current_price: float,
    price_history: list[dict],
    atr_multiplier_profit: float = 2.0,
    atr_multiplier_loss: float   = 1.5,
) -> dict:
    """
    Vision 점수 + ATR 기반 주문 전략 계산.

    Args:
        vision_score:           Vision 모델 점수 (0~100)
        current_price:          현재가 (원)
        price_history:          OHLC 딕셔너리 리스트 (최소 15개 권장)
        atr_multiplier_profit:  익절 ATR 배수 (기본 2.0)
        atr_multiplier_loss:    손절 ATR 배수 (기본 1.5)

    Returns:
        {
            'action':        'buy_market' | 'buy_limit' | 'hold',
            'order_price':   주문가 (buy_limit 일 때만 유효, 나머지 None),
            'profit_target': 익절 목표가 (원),
            'stop_loss':     손절가 (원),
            'atr':           ATR 값,
            'reason':        판단 근거 문자열,
        }
    """
    atr = calc_atr(price_history)

    # ATR 계산 불가 시 현재가의 1.5% 폴백
    if atr <= 0:
        atr = current_price * 0.015

    profit_target = round(current_price + atr * atr_multiplier_profit)
    stop_loss     = round(current_price - atr * atr_multiplier_loss)

    # ── Vision 점수별 주문 전략 ────────────────────────────────────────────────
    if vision_score >= 90:
        action      = "buy_market"
        order_price = None
        reason      = f"Vision {vision_score:.0f}점 → 즉시 시장가 매수"

    elif vision_score >= 80:
        tick        = get_tick_size(current_price)
        order_price = current_price - tick          # 호가 -1틱
        action      = "buy_limit"
        reason      = f"Vision {vision_score:.0f}점 → 호가 -1틱 지정가 ({order_price:,}원)"

    else:
        action      = "hold"
        order_price = None
        reason      = f"Vision {vision_score:.0f}점 → 관망 (기준 미달)"

    return {
        "action":        action,
        "order_price":   order_price,
        "profit_target": profit_target,
        "stop_loss":     stop_loss,
        "atr":           round(atr, 1),
        "reason":        reason,
    }


# ── 테스트 ────────────────────────────────────────────────────────────────────
def _make_dummy_history(base_price: float, n: int = 20) -> list[dict]:
    """테스트용 더미 OHLC 데이터 생성."""
    import random
    random.seed(42)
    history = []
    price = base_price
    for _ in range(n):
        change = random.uniform(-0.02, 0.02)
        close  = price * (1 + change)
        high   = close * random.uniform(1.001, 1.015)
        low    = close * random.uniform(0.985, 0.999)
        history.append({"high": high, "low": low, "close": close})
        price = close
    return history


def run_tests():
    print("=" * 55)
    print("  execution_optimizer 테스트")
    print("=" * 55)

    cases = [
        ("시장가 매수 (90+)", 92.5, 45_000),
        ("지정가 매수 (80-90)", 85.0, 12_500),
        ("관망 (70-80)", 75.0, 8_200),
        ("관망 (70 미만)", 65.0, 3_300),
    ]

    for name, score, price in cases:
        history = _make_dummy_history(price)
        result  = optimize(score, price, history)
        print(f"\n[{name}]")
        print(f"  Vision 점수: {score}")
        print(f"  현재가:      {price:,}원")
        print(f"  ATR:         {result['atr']:,.1f}원")
        print(f"  action:      {result['action']}")
        if result["order_price"]:
            print(f"  주문가:      {result['order_price']:,}원")
        print(f"  익절가:      {result['profit_target']:,}원")
        print(f"  손절가:      {result['stop_loss']:,}원")
        print(f"  근거:        {result['reason']}")

    # ATR 계산 검증
    print("\n[ATR 계산 검증]")
    h = [
        {"high": 10500, "low": 9800, "close": 10200},
        {"high": 10800, "low": 10100, "close": 10600},
        {"high": 11000, "low": 10300, "close": 10700},
    ]
    atr = calc_atr(h, period=2)
    print(f"  3개 봉, period=2 → ATR={atr:.1f} (예상 ~500~700)")

    print("\n테스트 완료.")


if __name__ == "__main__":
    run_tests()
