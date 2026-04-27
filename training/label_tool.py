"""
자동 라벨링 도구
3분봉 데이터 + 미래 수익률 → Success/Fail/Sideways + 패턴 태그
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


SUCCESS_THRESHOLD = 0.03   # 3% 이상 상승 = Success
FAIL_THRESHOLD = -0.02     # 2% 이상 하락 = Fail
VOLUME_SURGE_RATIO = 3.0   # 거래량 평균 대비 3배 = 급등 판정
BREAKOUT_CANDLES = 5       # 돌파 판정 기준 캔들 수


@dataclass
class WindowLabel:
    symbol: str
    start_time: str
    end_time: str
    label: str              # Success, Fail, Sideways
    pattern_tags: List[str] = field(default_factory=list)
    future_return: float = 0.0
    entry_price: float = 0.0
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


def classify_label(future_return: float) -> str:
    if future_return >= SUCCESS_THRESHOLD:
        return "Success"
    elif future_return <= FAIL_THRESHOLD:
        return "Fail"
    else:
        return "Sideways"


def detect_pattern_tags(chunk: pd.DataFrame) -> List[str]:
    """60개 3분봉 구간의 패턴 태그 감지"""
    tags = []

    if len(chunk) < 10:
        return tags

    # ── Breakout 판정: 마지막 캔들 거래량이 앞 5개 평균의 VOLUME_SURGE_RATIO배 이상
    if "vol_ratio" in chunk.columns:
        last_vol_ratio = chunk["vol_ratio"].iloc[-1]
        if pd.notna(last_vol_ratio) and last_vol_ratio >= VOLUME_SURGE_RATIO:
            tags.append("Breakout")
    else:
        recent_vol = chunk["Volume"].iloc[-BREAKOUT_CANDLES:]
        prior_vol_mean = chunk["Volume"].iloc[:-BREAKOUT_CANDLES].mean()
        if prior_vol_mean > 0 and recent_vol.mean() >= VOLUME_SURGE_RATIO * prior_vol_mean:
            tags.append("Breakout")

    # ── Dip (풀백) 판정: 최근 고점 대비 하락 후 반등
    mid = len(chunk) // 2
    high_first = chunk["High"].iloc[:mid].max()
    low_second = chunk["Low"].iloc[mid:].min()
    last_close = chunk["Close"].iloc[-1]
    if high_first > 0:
        dip_ratio = (high_first - low_second) / high_first
        recovery = (last_close - low_second) / max(high_first - low_second, 1)
        if dip_ratio >= 0.02 and recovery >= 0.5:
            tags.append("Dip")

    # ── Volatility 판정: 최고-최저 범위가 시작가의 5% 이상
    start_price = chunk["Close"].iloc[0]
    price_range = chunk["High"].max() - chunk["Low"].min()
    if start_price > 0 and price_range / start_price >= 0.05:
        tags.append("Volatility")

    # ── Sideways_Tight: 변동성 1% 미만
    if start_price > 0 and price_range / start_price < 0.01:
        tags.append("Sideways_Tight")

    return tags


def label_windows(
    df_3m: pd.DataFrame,
    symbol: str,
    window: int = 60,
    step: int = 30,
) -> List[WindowLabel]:
    """
    3분봉 DataFrame에서 슬라이딩 윈도우로 라벨 생성
    future_return이 없는 구간(마지막 10캔들)은 제외
    """
    labels: List[WindowLabel] = []

    valid_df = df_3m.dropna(subset=["future_return"])
    if len(valid_df) < window:
        logger.warning(f"{symbol}: 유효 데이터 부족 ({len(valid_df)} < {window})")
        return labels

    # 슬라이딩 윈도우 (valid_df 인덱스 기준)
    positions = list(range(0, len(valid_df) - window + 1, step))
    for pos in positions:
        chunk = valid_df.iloc[pos: pos + window]

        future_return = float(chunk["future_return"].iloc[-1])
        entry_price = float(chunk["Close"].iloc[-1])

        label_str = classify_label(future_return)
        tags = detect_pattern_tags(chunk)

        wl = WindowLabel(
            symbol=symbol,
            start_time=str(chunk.index[0]),
            end_time=str(chunk.index[-1]),
            label=label_str,
            pattern_tags=tags,
            future_return=round(future_return * 100, 4),  # %
            entry_price=entry_price,
        )
        labels.append(wl)

    return labels


def build_labels_csv(
    processed_dir: str = "datasets/processed_candles",
    output_csv: str = "datasets/labels.csv",
) -> pd.DataFrame:
    """
    모든 parquet 파일에서 라벨 생성 후 labels.csv 저장
    """
    processed_path = Path(processed_dir)
    parquet_files = list(processed_path.glob("*_3m.parquet"))

    all_labels = []
    for pq in parquet_files:
        symbol = pq.stem.replace("_3m", "")
        try:
            df = pd.read_parquet(str(pq))
            window_labels = label_windows(df, symbol)
            for wl in window_labels:
                all_labels.append(
                    {
                        "symbol": wl.symbol,
                        "start_time": wl.start_time,
                        "end_time": wl.end_time,
                        "label": wl.label,
                        "pattern_tags": ",".join(wl.pattern_tags),
                        "future_return_pct": wl.future_return,
                        "entry_price": wl.entry_price,
                    }
                )
            logger.info(f"  {symbol}: {len(window_labels)}개 라벨")
        except Exception as e:
            logger.error(f"  {symbol} 라벨링 실패: {e}")

    if not all_labels:
        logger.warning("생성된 라벨 없음")
        return pd.DataFrame()

    df_labels = pd.DataFrame(all_labels)
    df_labels.to_csv(output_csv, index=False, encoding="utf-8-sig")

    counts = df_labels["label"].value_counts()
    logger.info(f"라벨 분포: {dict(counts)}")
    logger.info(f"labels.csv 저장: {output_csv}")

    return df_labels


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.chdir(Path(__file__).parent.parent)

    from training.csv_to_candles import convert_all_csvs

    print("1. CSV → 3분봉 변환...")
    convert_all_csvs()

    print("\n2. 라벨 생성...")
    df = build_labels_csv()
    if len(df):
        print(f"\n라벨 분포:")
        print(df["label"].value_counts())
        print(f"\n패턴 태그 샘플:")
        print(df[df["pattern_tags"] != ""][["symbol", "label", "pattern_tags"]].head(10))
