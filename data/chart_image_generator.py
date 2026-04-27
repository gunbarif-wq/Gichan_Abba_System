"""
Chart Image Generator
실시간 3분봉 → 차트 이미지 생성 (추론용)
"""
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
logger = logging.getLogger(__name__)

class ChartImageGenerator:
    """실시간 차트 이미지 생성 (추론용)"""

    def generate(self, df_3m: pd.DataFrame, symbol: str, output_dir: str = "storage/chart_images") -> Optional[str]:
        """60개 3분봉 → PNG 이미지 생성"""
        try:
            from training.make_chart_images import generate_chart_image
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = str(Path(output_dir) / f"{symbol}_{ts}.png")
            chunk = df_3m.tail(60)
            if len(chunk) < 60:
                return None
            success = generate_chart_image(chunk, out_path)
            return out_path if success else None
        except Exception as e:
            logger.error(f"이미지 생성 실패: {e}")
            return None

def get_chart_image_generator() -> ChartImageGenerator:
    return ChartImageGenerator()
