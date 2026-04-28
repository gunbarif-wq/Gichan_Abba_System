"""
자금 관리 시스템
Kelly Criterion 포지션 크기 + 연속 손실 감지 + 비중 제한
"""

MAX_POSITIONS    = 5      # 최대 동시 보유 종목 수
MAX_WEIGHT_PCT   = 25.0   # 종목당 최대 비중 (%)
KELLY_FRACTION   = 0.25   # 풀 켈리의 25% (과도한 베팅 방지)
MIN_POSITION     = 100_000  # 최소 주문 금액 (원)


def calc_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Kelly Criterion f* = (bp - q) / b
    b = avg_win / avg_loss, p = win_rate, q = 1 - win_rate
    반환값: 0.0 ~ 1.0 (투자 비율)
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    p = win_rate
    q = 1.0 - win_rate
    kelly = (b * p - q) / b
    return max(0.0, min(kelly, 1.0))


def calc_position_size(
    balance: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    consecutive_losses: int,
    current_positions: int = 0,
    current_weight_pct: float = 0.0,
) -> dict:
    """
    포지션 크기 및 매매 가능 여부 계산.

    Args:
        balance:             총 가용 자금 (원)
        win_rate:            과거 승률 (0~1)
        avg_win:             평균 수익률 (%, 예: 8.0)
        avg_loss:            평균 손실률 (%, 예: 5.0)
        consecutive_losses:  현재 연속 손실 횟수
        current_positions:   현재 보유 종목 수
        current_weight_pct:  해당 종목 현재 비중 (%)

    Returns:
        {
            'position_size':  주문 금액 (원),
            'kelly_f':        켈리 비율,
            'can_trade':      매매 가능 여부,
            'reason':         'ok' | 'loss_limit' | 'position_limit' | 'weight_limit' | 'no_edge',
        }
    """
    # ── 연속 손실 체크 ────────────────────────────────────────────────────────
    if consecutive_losses >= 3:
        return {
            "position_size": 0,
            "kelly_f":       0.0,
            "can_trade":     False,
            "reason":        "loss_limit",
        }

    # ── 최대 보유 종목 수 체크 ────────────────────────────────────────────────
    if current_positions >= MAX_POSITIONS:
        return {
            "position_size": 0,
            "kelly_f":       0.0,
            "can_trade":     False,
            "reason":        "position_limit",
        }

    # ── 종목당 최대 비중 체크 ──────────────────────────────────────────────────
    if current_weight_pct >= MAX_WEIGHT_PCT:
        return {
            "position_size": 0,
            "kelly_f":       0.0,
            "can_trade":     False,
            "reason":        "weight_limit",
        }

    # ── Kelly 포지션 크기 계산 ────────────────────────────────────────────────
    kelly_f = calc_kelly(win_rate, avg_win, avg_loss)

    if kelly_f <= 0:
        return {
            "position_size": 0,
            "kelly_f":       0.0,
            "can_trade":     False,
            "reason":        "no_edge",
        }

    # 풀 켈리의 KELLY_FRACTION 적용
    adjusted_f = kelly_f * KELLY_FRACTION

    # 종목당 최대 비중 캡
    max_f = MAX_WEIGHT_PCT / 100.0
    adjusted_f = min(adjusted_f, max_f)

    position_size = balance * adjusted_f

    # 2연패 시 50% 축소
    if consecutive_losses == 2:
        position_size *= 0.5

    position_size = int(position_size)

    if position_size < MIN_POSITION:
        position_size = 0
        can_trade = False
        reason = "no_edge"
    else:
        can_trade = True
        reason = "ok"

    return {
        "position_size": position_size,
        "kelly_f":       round(adjusted_f, 4),
        "can_trade":     can_trade,
        "reason":        reason,
    }


def evaluate(params: dict) -> dict:
    """딕셔너리 입력 인터페이스."""
    return calc_position_size(
        balance             = params["balance"],
        win_rate            = params["win_rate"],
        avg_win             = params["avg_win"],
        avg_loss            = params["avg_loss"],
        consecutive_losses  = params.get("consecutive_losses", 0),
        current_positions   = params.get("current_positions", 0),
        current_weight_pct  = params.get("current_weight_pct", 0.0),
    )


# ── 테스트 ────────────────────────────────────────────────────────────────────
def run_tests():
    print("=" * 55)
    print("  money_manager 테스트")
    print("=" * 55)

    cases = [
        ("정상 매매",           {"balance": 10_000_000, "win_rate": 0.8, "avg_win": 8.0, "avg_loss": 5.0, "consecutive_losses": 0}),
        ("2연패 → 50% 축소",    {"balance": 10_000_000, "win_rate": 0.8, "avg_win": 8.0, "avg_loss": 5.0, "consecutive_losses": 2}),
        ("3연패 → 중단",        {"balance": 10_000_000, "win_rate": 0.8, "avg_win": 8.0, "avg_loss": 5.0, "consecutive_losses": 3}),
        ("종목 5개 초과",       {"balance": 10_000_000, "win_rate": 0.7, "avg_win": 6.0, "avg_loss": 4.0, "consecutive_losses": 0, "current_positions": 5}),
        ("비중 25% 초과",       {"balance": 10_000_000, "win_rate": 0.7, "avg_win": 6.0, "avg_loss": 4.0, "consecutive_losses": 0, "current_weight_pct": 25.0}),
        ("승률 낮아 엣지 없음", {"balance": 10_000_000, "win_rate": 0.3, "avg_win": 3.0, "avg_loss": 8.0, "consecutive_losses": 0}),
    ]

    for name, params in cases:
        result = evaluate(params)
        status = "O" if result["can_trade"] else "X"
        print(f"\n[{name}]")
        print(f"  {status} can_trade:     {result['can_trade']}")
        print(f"     reason:        {result['reason']}")
        print(f"     kelly_f:       {result['kelly_f']:.4f}")
        print(f"     position_size: {result['position_size']:,}원")

    print("\n테스트 완료.")


if __name__ == "__main__":
    run_tests()
