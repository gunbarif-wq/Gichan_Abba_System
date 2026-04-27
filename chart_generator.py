import os
import pandas as pd
import mplfinance as mpf
from pathlib import Path
from datetime import datetime

# 설정
csv_folder = Path("data/csv")
output_folder = Path("storage/chart_images/raw")
output_folder.mkdir(parents=True, exist_ok=True)

# AI 학습용 스타일 (텍스트/축/그리드 모두 제거)
style = mpf.make_mpf_style(
    marketcolors=mpf.make_marketcolors(
        up='red', down='blue', edge='inherit', wick='inherit', volume='in', alpha=1.0
    ),
    gridcolor='white', gridstyle='',
    rc={
        'axes.edgecolor': 'white', 'axes.linewidth': 0,
        'figure.facecolor': 'white', 'axes.facecolor': 'white'
    }
)

print("="*70)
print("AI 학습용 3분봉 차트 이미지 생성 시작")
print("="*70)

csv_files = list(csv_folder.glob("*.csv"))
print(f"\n📁 발견: {len(csv_files)}개 CSV 파일")

total_images = 0

for i, csv_file in enumerate(csv_files, 1):
    print(f"\n[{i}/{len(csv_files)}] {csv_file.name}")
    
    try:
        # CSV 읽기
        df = pd.read_csv(csv_file, encoding='utf-8')
        
        # 컬럼명 소문자 변환
        df.columns = df.columns.str.lower()
        
        # 시간 컬럼 찾기
        time_col = None
        for col in ['date', 'time', 'datetime', 'timestamp', '날짜', '시간']:
            if col in df.columns:
                time_col = col
                break
        
        if not time_col:
            time_col = df.columns[0]  # 첫 번째 컬럼 사용
        
        # OHLCV 매핑
        col_map = {}
        for target, patterns in {
            'Open': ['open', 'o', '시가'],
            'High': ['high', 'h', '고가'],
            'Low': ['low', 'l', '저가'],
            'Close': ['close', 'c', '종가'],
            'Volume': ['volume', 'vol', 'v', '거래량']
        }.items():
            for p in patterns:
                if p in df.columns:
                    col_map[target] = p
                    break
        
        # DataFrame 생성
        data = pd.DataFrame({
            'Open': pd.to_numeric(df[col_map['Open']], errors='coerce'),
            'High': pd.to_numeric(df[col_map['High']], errors='coerce'),
            'Low': pd.to_numeric(df[col_map['Low']], errors='coerce'),
            'Close': pd.to_numeric(df[col_map['Close']], errors='coerce'),
            'Volume': pd.to_numeric(df[col_map['Volume']], errors='coerce')
        })
        data.index = pd.to_datetime(df[time_col])
        data = data.dropna()
        
        # 60개씩 슬라이딩 윈도우 (50% 오버랩)
        window = 60
        for j in range(0, len(data) - window + 1, window // 2):
            chunk = data.iloc[j:j+window]
            
            start = chunk.index[0].strftime('%Y%m%d_%H%M')
            end = chunk.index[-1].strftime('%H%M')
            filename = f"{csv_file.stem}_{start}_to_{end}.png"
            
            # 차트 생성
            mpf.plot(
                chunk, type='candle', style=style, volume=True,
                figsize=(10, 8),
                savefig=dict(fname=str(output_folder/filename), dpi=100, bbox_inches='tight'),
                axisoff=True, returnfig=False
            )
            
            total_images += 1
        
        print(f"  ✅ {total_images}개 이미지 생성 중...")
        
    except Exception as e:
        print(f"  ❌ 오류: {str(e)}")

print("\n" + "="*70)
print(f"✅ 완료! 총 {total_images}개 이미지 생성됨")
print(f"📂 저장 위치: {output_folder}")
print("="*70)