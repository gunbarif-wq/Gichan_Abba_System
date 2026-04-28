"""
고급 피처 추출 모듈 (독립 스크립트)
15개 피처: 체결강도, 호가비율, 지수상관, 섹터모멘텀, RSI, MACD(3), BB(3), 거래량(3), 변동성
학습 파이프라인과 통합 전 단독 검증용
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# ── 피처 이름 정의 ─────────────────────────────────────────────────────────────
FEATURE_NAMES = [
    "transaction_strength",   # 1.  체결강도 (매수체결/전체체결)
    "orderbook_ratio",        # 2.  호가잔량비율 (매수잔량/매도잔량)
    "index_correlation",      # 3.  코스피 지수 상관계수 (20봉)
    "sector_momentum",        # 4.  섹터 모멘텀 (5일 수익률)
    "rsi_14",                 # 5.  RSI 14
    "macd_line",              # 6.  MACD 라인
    "macd_signal",            # 7.  MACD 시그널
    "macd_hist",              # 8.  MACD 히스토그램
    "bb_upper_pct",           # 9.  현재가의 볼린저 상단 대비 위치 (%)
    "bb_lower_pct",           # 10. 현재가의 볼린저 하단 대비 위치 (%)
    "bb_width",               # 11. 볼린저 밴드 폭 (변동성 지표)
    "volume_ratio_5",         # 12. 거래량비율 (현재봉/5봉 평균)
    "volume_ratio_20",        # 13. 거래량비율 (현재봉/20봉 평균)
    "volume_surge",           # 14. 거래량 급증 여부 (ratio_5 > 2.0 → 1.0)
    "price_volatility",       # 15. 가격 변동성 (20봉 수익률 표준편차)
]


# ── 기술 지표 계산 ─────────────────────────────────────────────────────────────

def _rsi(close: np.ndarray, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    deltas = np.diff(close[-(period + 1):])
    gains  = deltas[deltas > 0].mean() if (deltas > 0).any() else 0.0
    losses = (-deltas[deltas < 0]).mean() if (deltas < 0).any() else 1e-9
    rs = gains / losses
    return round(100 - 100 / (1 + rs), 4)


def _ema(close: np.ndarray, period: int) -> np.ndarray:
    alpha = 2 / (period + 1)
    ema = np.zeros_like(close, dtype=float)
    ema[0] = close[0]
    for i in range(1, len(close)):
        ema[i] = alpha * close[i] + (1 - alpha) * ema[i - 1]
    return ema


def _macd(close: np.ndarray, fast=12, slow=26, signal=9) -> tuple[float, float, float]:
    if len(close) < slow + signal:
        return 0.0, 0.0, 0.0
    ema_fast   = _ema(close, fast)
    ema_slow   = _ema(close, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist       = macd_line[-1] - signal_line[-1]
    return round(float(macd_line[-1]), 4), round(float(signal_line[-1]), 4), round(float(hist), 4)


def _bollinger(close: np.ndarray, period: int = 20, std_mult: float = 2.0) -> tuple[float, float, float, float]:
    """(upper, middle, lower, width) 반환. 현재가는 close[-1]."""
    if len(close) < period:
        c = float(close[-1])
        return c, c, c, 0.0
    window = close[-period:]
    mid    = window.mean()
    std    = window.std(ddof=0)
    upper  = mid + std_mult * std
    lower  = mid - std_mult * std
    width  = (upper - lower) / (mid + 1e-9) * 100
    return round(float(upper), 2), round(float(mid), 2), round(float(lower), 2), round(float(width), 4)


# ── API 데이터 수집 ────────────────────────────────────────────────────────────

def _get_kis():
    from trade.kis_mock_client import get_kis_mock_client
    return get_kis_mock_client()


def _fetch_candles(symbol: str, timeframe: int = 3, count: int = 80) -> Optional[pd.DataFrame]:
    try:
        return _get_kis().get_minute_candles_df(symbol, timeframe=timeframe, count=count)
    except Exception as e:
        print(f"  [경고] 분봉 조회 실패 ({symbol}): {e}")
        return None


def _fetch_orderbook(symbol: str) -> dict:
    """호가 잔량 조회. 실패 시 기본값 반환."""
    try:
        kis = _get_kis()
        url = f"{kis.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        params = {
            "FID_COND_MRK_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }
        resp = kis._session.get(url, headers=kis._headers("FHKST01010200"),
                                params=params, timeout=5)
        resp.raise_for_status()
        output = resp.json().get("output1", {})
        buy_qty  = sum(int(output.get(f"bidp_rsqn{i}", 0)) for i in range(1, 6))
        sell_qty = sum(int(output.get(f"askp_rsqn{i}", 0)) for i in range(1, 6))
        return {"buy_qty": buy_qty, "sell_qty": sell_qty}
    except Exception:
        return {"buy_qty": 0, "sell_qty": 0}


def _fetch_index_candles(count: int = 80) -> Optional[pd.DataFrame]:
    """코스피 지수 분봉 조회 (종목코드 0001)."""
    try:
        return _fetch_candles("0001", timeframe=3, count=count)
    except Exception:
        return None


def _fetch_transaction_strength(symbol: str) -> float:
    """체결강도 = 매수체결량 / (매수+매도체결량). 현재가 output에서 추출."""
    try:
        kis    = _get_kis()
        output = kis.get_current_price(symbol)
        buy_vol  = float(output.get("seln_cntg_csnu", 0) or 0)
        sell_vol = float(output.get("shnu_cntg_csnu", 0) or 0)
        total    = buy_vol + sell_vol
        return round(buy_vol / total, 4) if total > 0 else 0.5
    except Exception:
        return 0.5


# ── 피처 추출 메인 함수 ────────────────────────────────────────────────────────

def extract(symbol: str) -> pd.DataFrame:
    """
    15개 고급 피처 추출.

    Args:
        symbol: 종목코드 (예: '005930')

    Returns:
        단일 행 DataFrame (컬럼 = FEATURE_NAMES)
    """
    print(f"[AdvancedFeatures] {symbol} 피처 추출 중...", flush=True)

    feat = {k: 0.0 for k in FEATURE_NAMES}

    # ── 1. 체결강도 ────────────────────────────────────────────────────────────
    feat["transaction_strength"] = _fetch_transaction_strength(symbol)

    # ── 2. 호가잔량비율 ────────────────────────────────────────────────────────
    ob = _fetch_orderbook(symbol)
    buy_qty, sell_qty = ob["buy_qty"], ob["sell_qty"]
    feat["orderbook_ratio"] = round(buy_qty / (sell_qty + 1e-9), 4) if sell_qty > 0 else 1.0

    # ── 분봉 데이터 ────────────────────────────────────────────────────────────
    df = _fetch_candles(symbol, timeframe=3, count=80)
    if df is None or len(df) < 5:
        print(f"  [경고] 분봉 데이터 부족 — 나머지 피처 0으로 설정", flush=True)
        df_result = pd.DataFrame([feat], columns=FEATURE_NAMES)
        df_result.insert(0, "symbol", symbol)
        df_result.insert(1, "extracted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return df_result

    close  = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)

    # ── 3. 코스피 지수 상관계수 ────────────────────────────────────────────────
    idx_df = _fetch_index_candles(count=80)
    if idx_df is not None and len(idx_df) >= 5:
        n      = min(20, len(close), len(idx_df))
        s_ret  = np.diff(close[-n:]) / (close[-n:-1] + 1e-9)
        i_ret  = np.diff(idx_df["close"].values[-n:].astype(float))
        i_base = idx_df["close"].values[-n:-1].astype(float)
        i_ret  = i_ret / (i_base + 1e-9)
        if len(s_ret) > 1 and np.std(s_ret) > 0 and np.std(i_ret) > 0:
            feat["index_correlation"] = round(float(np.corrcoef(s_ret, i_ret)[0, 1]), 4)

    # ── 4. 섹터 모멘텀 (5봉 수익률로 근사) ────────────────────────────────────
    if len(close) >= 6:
        feat["sector_momentum"] = round(float((close[-1] - close[-6]) / (close[-6] + 1e-9) * 100), 4)

    # ── 5. RSI ─────────────────────────────────────────────────────────────────
    feat["rsi_14"] = _rsi(close, 14)

    # ── 6~8. MACD ──────────────────────────────────────────────────────────────
    feat["macd_line"], feat["macd_signal"], feat["macd_hist"] = _macd(close)

    # ── 9~11. 볼린저 밴드 ──────────────────────────────────────────────────────
    upper, mid, lower, width = _bollinger(close, 20)
    cur = close[-1]
    feat["bb_upper_pct"] = round((cur - upper) / (upper + 1e-9) * 100, 4)
    feat["bb_lower_pct"] = round((cur - lower) / (lower + 1e-9) * 100, 4)
    feat["bb_width"]     = width

    # ── 12~14. 거래량 ──────────────────────────────────────────────────────────
    avg_5  = volume[-5:].mean()  if len(volume) >= 5  else volume.mean()
    avg_20 = volume[-20:].mean() if len(volume) >= 20 else volume.mean()
    cur_vol = volume[-1]
    feat["volume_ratio_5"]  = round(float(cur_vol / (avg_5  + 1e-9)), 4)
    feat["volume_ratio_20"] = round(float(cur_vol / (avg_20 + 1e-9)), 4)
    feat["volume_surge"]    = 1.0 if feat["volume_ratio_5"] > 2.0 else 0.0

    # ── 15. 가격 변동성 ────────────────────────────────────────────────────────
    if len(close) >= 3:
        returns = np.diff(close[-20:]) / (close[-20:-1] + 1e-9)
        feat["price_volatility"] = round(float(np.std(returns) * 100), 6)

    df_result = pd.DataFrame([feat], columns=FEATURE_NAMES)
    df_result.insert(0, "symbol", symbol)
    df_result.insert(1, "extracted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return df_result


# ── 테스트 / 메인 ──────────────────────────────────────────────────────────────

def main(symbol: str = "005930"):
    print("=" * 60)
    print(f"  Advanced Features 추출 — {symbol}")
    print("=" * 60)

    df = extract(symbol)

    # 피처 테이블 출력
    feature_df = df[FEATURE_NAMES].T.reset_index()
    feature_df.columns = ["feature", "value"]
    feature_df.insert(0, "no", range(1, len(feature_df) + 1))

    print(f"\n{'No':>3}  {'Feature':<25}  {'Value':>12}")
    print("-" * 45)
    for _, row in feature_df.iterrows():
        print(f"{int(row['no']):>3}  {row['feature']:<25}  {row['value']:>12.4f}")

    print("-" * 45)
    print(f"총 {len(FEATURE_NAMES)}개 피처 추출 완료")
    print(f"\nDataFrame shape: {df.shape}")
    print(f"컬럼: {list(df.columns)}")
    return df


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    main(ticker)
