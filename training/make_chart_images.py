"""
라벨링된 차트 이미지 생성기
3분봉 OHLCV → 60개 캔들 + 거래량 PNG
라벨(Success/Fail/Sideways)별 폴더에 저장
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import mplfinance as mpf
    import matplotlib
    matplotlib.use("Agg")
    MPF_AVAILABLE = True
except ImportError:
    MPF_AVAILABLE = False
    logger.warning("mplfinance 미설치 - pip install mplfinance")


CHART_STYLE = None


def _get_style():
    global CHART_STYLE
    if CHART_STYLE is None and MPF_AVAILABLE:
        CHART_STYLE = mpf.make_mpf_style(
            marketcolors=mpf.make_marketcolors(
                up="red", down="blue",
                edge="inherit", wick="inherit",
                volume="in", alpha=1.0,
            ),
            gridcolor="white",
            gridstyle="",
            rc={
                "axes.edgecolor": "white",
                "axes.linewidth": 0,
                "figure.facecolor": "white",
                "axes.facecolor": "white",
            },
        )
    return CHART_STYLE


def generate_chart_image(
    chunk: pd.DataFrame,
    output_path: str,
    figsize: tuple = (10, 8),
    dpi: int = 100,
) -> bool:
    """60개 3분봉 캔들 + 거래량 이미지 저장"""
    if not MPF_AVAILABLE:
        return False

    try:
        style = _get_style()
        mpf.plot(
            chunk[["Open", "High", "Low", "Close", "Volume"]],
            type="candle",
            style=style,
            volume=True,
            figsize=figsize,
            savefig=dict(fname=output_path, dpi=dpi, bbox_inches="tight"),
            axisoff=True,
            returnfig=False,
        )
        return True
    except Exception as e:
        logger.error(f"이미지 생성 실패: {output_path} -> {e}")
        return False


def make_images_for_symbol(
    df_3m: pd.DataFrame,
    symbol: str,
    labels_df: pd.DataFrame,
    output_base: str = "datasets/chart_images",
    split_ratios: tuple = (0.7, 0.15, 0.15),
    window: int = 60,
    step: int = 30,
) -> dict:
    """
    종목의 3분봉 + 라벨 → 이미지 생성 및 train/val/test 분할
    Returns: {label: count}
    """
    output_path = Path(output_base)
    counts = {"Success": 0, "Fail": 0, "Sideways": 0}

    # 해당 종목의 라벨만 추출
    sym_labels = labels_df[labels_df["symbol"] == symbol].copy()
    if sym_labels.empty:
        return counts

    valid_df = df_3m.dropna(subset=["future_return"])
    positions = list(range(0, len(valid_df) - window + 1, step))

    total = len(positions)
    n_train = int(total * split_ratios[0])
    n_val = int(total * split_ratios[1])

    for idx, pos in enumerate(positions):
        chunk = valid_df.iloc[pos: pos + window]
        end_time = str(chunk.index[-1])

        row = sym_labels[sym_labels["end_time"] == end_time]
        if row.empty:
            continue

        label = row.iloc[0]["label"]
        future_return = row.iloc[0]["future_return_pct"]

        # train/val/test 분할
        if idx < n_train:
            split = "train"
        elif idx < n_train + n_val:
            split = "val"
        else:
            split = "test"

        label_dir = output_path / split / label
        label_dir.mkdir(parents=True, exist_ok=True)

        ts = chunk.index[-1].strftime("%Y%m%d_%H%M")
        ret_str = f"{future_return:+.2f}pct".replace(".", "p")
        filename = f"{label}_{symbol}_{ts}_{ret_str}.png"
        out_file = str(label_dir / filename)

        if generate_chart_image(chunk, out_file):
            counts[label] = counts.get(label, 0) + 1

    return counts


def build_all_images(
    processed_dir: str = "datasets/processed_candles",
    labels_csv: str = "datasets/labels.csv",
    output_base: str = "datasets/chart_images",
) -> dict:
    """모든 종목의 이미지 생성"""
    if not MPF_AVAILABLE:
        logger.error("mplfinance 미설치. pip install mplfinance 후 재실행")
        return {}

    labels_path = Path(labels_csv)
    if not labels_path.exists():
        logger.error(f"labels.csv 없음: {labels_csv}")
        return {}

    labels_df = pd.read_csv(str(labels_path))
    processed_path = Path(processed_dir)
    parquet_files = list(processed_path.glob("*_3m.parquet"))

    total_counts = {"Success": 0, "Fail": 0, "Sideways": 0}
    logger.info(f"이미지 생성 시작: {len(parquet_files)}개 종목")

    for pq in parquet_files:
        symbol = pq.stem.replace("_3m", "")
        try:
            df = pd.read_parquet(str(pq))
            counts = make_images_for_symbol(df, symbol, labels_df, output_base)
            for k, v in counts.items():
                total_counts[k] = total_counts.get(k, 0) + v
            logger.info(f"  {symbol}: {counts}")
        except Exception as e:
            logger.error(f"  {symbol} 실패: {e}")

    logger.info(f"\n최종 이미지 수: {total_counts}")
    return total_counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.chdir(Path(__file__).parent.parent)

    counts = build_all_images()
    print(f"\n생성 완료:")
    for label, cnt in counts.items():
        print(f"  {label}: {cnt}개")
