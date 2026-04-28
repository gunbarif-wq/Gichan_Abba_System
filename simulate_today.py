"""오늘 시스템 실행 시뮬레이션 — 텔레그램 전송"""
import os, sys, time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

from trade.kis_live_client import get_kis_live_client
from notify.telegram import get_telegram_notifier
from scanner.premarket_scanner import PreMarketScanner

def main():
    kis = get_kis_live_client()
    tg  = get_telegram_notifier()

    print("[1] 거래량 상위 스캔 중...", flush=True)
    scanner = PreMarketScanner(kis)
    watchlist = scanner.run_premarket_scan()
    print(f"    감시 후보: {len(watchlist)}개", flush=True)

    print("[2] 현재가 조회 중 (on_tick 대체)...", flush=True)
    scanner.fill_from_current_price()

    candidates = scanner.get_buy_candidates()
    print(f"    매수 준비 종목: {len(candidates)}개", flush=True)

    # 전체 감시 목록 (점수 상위 10)
    top10 = sorted(watchlist, key=lambda c: c.score, reverse=True)[:10]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"<b>[기찬 아빠 시스템] 오늘 시뮬레이션 결과</b>",
        f"기준시각: {now_str}",
        "",
        f"<b>장전 감시 후보 {len(watchlist)}개 (상위 10)</b>",
    ]
    for i, c in enumerate(top10, 1):
        chg = f"{c.open_change_pct:+.1f}%" if c.open_change_pct != 0 else "-"
        vol = f"{c.open_volume:,}" if c.open_volume > 0 else "-"
        lines.append(
            f"  {i:2d}. {c.name}({c.symbol}) "
            f"점수={c.score:.0f} 등락={chg} 거래량={vol}"
        )

    lines.append("")
    if candidates:
        lines.append(f"<b>매수 진입 조건 충족 {len(candidates)}개</b>")
        for c in candidates[:5]:
            lines.append(
                f"  {c.name}({c.symbol}) "
                f"{c.open_change_pct:+.1f}% 매수비율={c.buy_ratio:.0%}"
            )
    else:
        lines.append("<b>매수 진입 조건 충족 종목: 없음</b>")
        lines.append("(장 마감 후 시뮬레이션 - 실시간 조건 미충족)")

    lines += [
        "",
        f"감시 기준: 등락+1% 이상 / 매수비율 55% 이상 / 거래량 5000주 이상",
    ]

    msg = "\n".join(lines)
    print("\n" + msg, flush=True)
    print("\n[3] 텔레그램 전송...", flush=True)
    tg.send(msg)
    print("    전송 완료!", flush=True)

if __name__ == "__main__":
    main()
