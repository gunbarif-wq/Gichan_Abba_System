"""
종목 정보 업데이터 — 매일 07:00 KST 실행
1. KIS API로 전체 종목 목록 조회
2. 종목명 변경 감지 및 업데이트
3. 상폐/거래정지 종목 제거
4. storage/watchlist/symbol_master.json 갱신
5. 텔레그램 변경사항 리포트
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).resolve().parent.parent
MASTER_PATH  = BASE_DIR / "storage" / "watchlist" / "symbol_master.json"


# ── KIS 전체 종목 조회 ────────────────────────────────────────────────────────

def _fetch_all_symbols(kis) -> dict:
    """
    KIS API로 코스피+코스닥 전체 종목 조회.
    반환: {symbol: {"name": str, "market": str, "updated_at": str}}
    """
    result = {}
    for market in ("J", "Q"):
        market_name = "KOSPI" if market == "J" else "KOSDAQ"
        try:
            items = kis.get_volume_rank(market=market, top_n=200)
            for item in items:
                symbol = item.get("mksc_shrn_iscd") or item.get("stck_shrn_iscd", "")
                name   = item.get("hts_kor_isnm", "")
                if not symbol:
                    continue
                result[symbol] = {
                    "name":       name,
                    "market":     market_name,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
        except Exception as e:
            logger.warning(f"[SymbolUpdater] {market_name} 조회 실패: {e}")
    return result


def _is_delisted(kis, symbol: str) -> bool:
    """현재가 조회 실패 or 거래정지 여부로 상폐 판단."""
    try:
        data   = kis.get_current_price(symbol)
        status = data.get("iscd_stat_cls_code", "")
        price  = float(data.get("stck_prpr", 0) or 0)
        # 거래정지(55), 관리종목(33), 투자위험(65) 등
        if status in ("55", "33", "65", "99"):
            return True
        if price <= 0:
            return True
        return False
    except Exception:
        return True


# ── 마스터 로드/저장 ──────────────────────────────────────────────────────────

def load_master() -> dict:
    if MASTER_PATH.exists():
        try:
            return json.loads(MASTER_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_master(master: dict):
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_PATH.write_text(
        json.dumps(master, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ── 메인 업데이트 로직 ────────────────────────────────────────────────────────

def run_update(notify: bool = True) -> dict:
    """
    종목 마스터 업데이트 실행.
    반환: {"renamed": [...], "delisted": [...], "added": [...], "total": int}
    """
    from dotenv import load_dotenv
    load_dotenv()

    from trade.kis_live_client import get_kis_live_client
    from notify.telegram import get_telegram_notifier

    kis = get_kis_live_client()
    tg  = get_telegram_notifier()

    logger.info("[SymbolUpdater] 종목 마스터 업데이트 시작")

    # NXT 적격 목록 갱신 (KOSPI200 + KOSDAQ150)
    try:
        from exchange.validator import refresh_eligible_list
        eligible = refresh_eligible_list(kis)
        logger.info(f"[SymbolUpdater] NXT 적격 목록 갱신: {len(eligible)}개")
    except Exception as e:
        logger.warning(f"[SymbolUpdater] NXT 목록 갱신 실패: {e}")

    prev    = load_master()
    current = _fetch_all_symbols(kis)

    renamed  = []
    delisted = []
    added    = []

    # ── 기존 종목 변경 감지 ───────────────────────────────────────────────────
    for symbol, prev_info in list(prev.items()):
        if symbol not in current:
            # 거래량 상위 200위 밖으로 빠진 경우 상폐 여부 추가 확인
            if _is_delisted(kis, symbol):
                delisted.append({
                    "symbol": symbol,
                    "name":   prev_info.get("name", ""),
                })
                prev.pop(symbol)
                logger.info(f"[SymbolUpdater] 상폐/정지 제거: {symbol} {prev_info.get('name')}")
            continue

        # 종목명 변경 감지
        new_name  = current[symbol]["name"]
        prev_name = prev_info.get("name", "")
        if new_name and new_name != prev_name:
            renamed.append({
                "symbol":   symbol,
                "old_name": prev_name,
                "new_name": new_name,
            })
            prev[symbol]["name"]       = new_name
            prev[symbol]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            logger.info(f"[SymbolUpdater] 종목명 변경: {symbol} {prev_name} → {new_name}")

    # ── 신규 종목 추가 ─────────────────────────────────────────────────────────
    for symbol, info in current.items():
        if symbol not in prev:
            prev[symbol] = info
            added.append({"symbol": symbol, "name": info["name"]})

    # 저장
    save_master(prev)
    total = len(prev)
    logger.info(f"[SymbolUpdater] 완료 — 총 {total}개 | 변경명 {len(renamed)} | 상폐 {len(delisted)} | 신규 {len(added)}")

    result = {
        "renamed":  renamed,
        "delisted": delisted,
        "added":    added,
        "total":    total,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 텔레그램 리포트 (변경사항 있을 때만)
    if notify and (renamed or delisted):
        _send_report(tg, result)

    return result


def _send_report(tg, result: dict):
    lines = [
        f"📋 <b>종목 마스터 업데이트</b> {result['updated_at']}",
        f"총 {result['total']}개 종목",
    ]
    if result["renamed"]:
        lines.append(f"\n<b>종목명 변경 {len(result['renamed'])}건</b>")
        for r in result["renamed"][:10]:
            lines.append(f"  {r['symbol']} {r['old_name']} → {r['new_name']}")
        if len(result["renamed"]) > 10:
            lines.append(f"  ... 외 {len(result['renamed'])-10}건")

    if result["delisted"]:
        lines.append(f"\n<b>상폐/거래정지 {len(result['delisted'])}건</b>")
        for d in result["delisted"][:10]:
            lines.append(f"  {d['symbol']} {d['name']}")

    tg.send("\n".join(lines))


# ── 공개 조회 함수 (다른 모듈에서 사용) ──────────────────────────────────────

def get_symbol_name(symbol: str, fallback: str = "") -> str:
    """마스터에서 종목명 조회. 없으면 fallback 반환."""
    master = load_master()
    return master.get(symbol, {}).get("name", fallback or symbol)


def is_valid_symbol(symbol: str) -> bool:
    """마스터에 존재하는 유효 종목인지 확인."""
    return symbol in load_master()


# ── 스케줄러 ──────────────────────────────────────────────────────────────────

def run_scheduler():
    """매일 07:00 KST 자동 실행."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                BASE_DIR / "storage" / "logs" / "symbol_updater.log",
                encoding="utf-8"
            ),
        ]
    )
    logger.info("[SymbolUpdater] 스케줄러 시작 — 매일 07:00 KST")
    while True:
        now    = datetime.now()
        target = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = (target - datetime.now()).total_seconds()
        logger.info(f"[SymbolUpdater] 07:00까지 대기 ({wait/3600:.1f}시간)")
        time.sleep(wait)
        run_update(notify=True)


if __name__ == "__main__":
    import sys
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--now",       action="store_true", help="즉시 1회 실행")
    parser.add_argument("--schedule",  action="store_true", help="스케줄러 실행")
    args = parser.parse_args()

    if args.schedule:
        run_scheduler()
    else:
        result = run_update(notify=False)
        print(f"\n총 종목: {result['total']}개")
        print(f"종목명 변경: {len(result['renamed'])}건")
        print(f"상폐/정지:   {len(result['delisted'])}건")
        print(f"신규 추가:   {len(result['added'])}건")
        if result["renamed"]:
            print("\n[변경명]")
            for r in result["renamed"]:
                print(f"  {r['symbol']} {r['old_name']} → {r['new_name']}")
        if result["delisted"]:
            print("\n[상폐/정지]")
            for d in result["delisted"]:
                print(f"  {d['symbol']} {d['name']}")
