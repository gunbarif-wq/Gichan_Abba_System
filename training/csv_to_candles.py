"""
CSV to 3분봉 변환기
1분봉 CSV → 3분봉 OHLCV + 미래 수익률 계산
"""

import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def load_1m_csv(csv_path: str) -> Optional[pd.DataFrame]:
    """1분봉 CSV 로드"""
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
        df.columns = df.columns.str.lower()

        time_col = None
        for col in ["date", "time", "datetime", "timestamp", "날짜", "시간"]:
            if col in df.columns:
                time_col = col
                break
        if time_col is None:
            time_col = df.columns[0]

        col_map = {}
        for target, patterns in {
            "Open": ["open", "o", "시가"],
            "High": ["high", "h", "고가"],
            "Low": ["low", "l", "저가"],
            "Close": ["close", "c", "종가"],
            "Volume": ["volume", "vol", "v", "거래량"],
        }.items():
            for p in patterns:
                if p in df.columns:
                    col_map[target] = p
                    break

        if len(col_map) < 5:
            logger.warning(f"필요 컬럼 부족: {csv_path}")
            return None

        data = pd.DataFrame(
            {
                "Open": pd.to_numeric(df[col_map["Open"]], errors="coerce"),
                "High": pd.to_numeric(df[col_map["High"]], errors="coerce"),
                "Low": pd.to_numeric(df[col_map["Low"]], errors="coerce"),
                "Close": pd.to_numeric(df[col_map["Close"]], errors="coerce"),
                "Volume": pd.to_numeric(df[col_map["Volume"]], errors="coerce"),
            }
        )
        data.index = pd.to_datetime(df[time_col])
        data = data.dropna().sort_index()
        return data

    except Exception as e:
        logger.error(f"CSV 로드 실패: {csv_path} -> {e}")
        return None


def resample_to_3m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """1분봉 → 3분봉 리샘플링"""
    df_3m = df_1m.resample("3min").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna()
    return df_3m


def calculate_future_return(df_3m: pd.DataFrame, forward_candles: int = 10) -> pd.DataFrame:
    """
    미래 수익률 계산
    forward_candles개 3분봉 이후 종가 기준 (기본 10개 = 30분)
    """
    df = df_3m.copy()
    df["future_close"] = df["Close"].shift(-forward_candles)
    df["future_return"] = (df["future_close"] - df["Close"]) / df["Close"]
    return df


def add_volume_features(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """거래량 특징 추가"""
    df = df.copy()
    df["vol_ma"] = df["Volume"].rolling(window).mean()
    df["vol_ratio"] = df["Volume"] / df["vol_ma"].replace(0, np.nan)
    return df


def convert_all_csvs(
    csv_dir: str = "data/csv",
    output_dir: str = "datasets/processed_candles",
    forward_candles: int = 10,
) -> dict:
    """
    모든 CSV 파일을 3분봉으로 변환
    Returns: {symbol: DataFrame}
    """
    csv_dir_path = Path(csv_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = list(csv_dir_path.glob("*_1m*.csv"))
    if not csv_files:
        csv_files = list(csv_dir_path.glob("*.csv"))

    results = {}
    logger.info(f"CSV 변환 시작: {len(csv_files)}개 파일")

    for csv_file in csv_files:
        symbol = csv_file.stem.split("_")[0]
        logger.info(f"  처리 중: {csv_file.name} -> symbol={symbol}")

        df_1m = load_1m_csv(str(csv_file))
        if df_1m is None or len(df_1m) < 60:
            logger.warning(f"  데이터 부족 건너뜀: {csv_file.name}")
            continue

        df_3m = resample_to_3m(df_1m)
        df_3m = calculate_future_return(df_3m, forward_candles)
        df_3m = add_volume_features(df_3m)

        out_file = output_path / f"{symbol}_3m.parquet"
        df_3m.to_parquet(str(out_file))
        results[symbol] = df_3m
        logger.info(f"  완료: {len(df_3m)}개 3분봉 -> {out_file.name}")

    logger.info(f"변환 완료: {len(results)}개 종목")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.chdir(Path(__file__).parent.parent)
    results = convert_all_csvs()
    print(f"\n완료: {len(results)}개 종목 변환됨")
    for sym, df in list(results.items())[:3]:
        print(f"  {sym}: {len(df)}개 3분봉, future_return 유효={df['future_return'].notna().sum()}")
