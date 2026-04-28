"""
Exchange Validator — NXT 적격 종목 판별 및 SOR 라우팅 결정

NXT(넥스트레이드) 거래 가능 종목: KOSPI 200 + KOSDAQ 150 구성 종목
목록은 매일 07:00 KIS API로 갱신, storage/watchlist/nxt_eligible.json 저장
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR      = Path(__file__).resolve().parent.parent
ELIGIBLE_PATH = BASE_DIR / "storage" / "watchlist" / "nxt_eligible.json"

# KIS TR_ID: 지수 구성종목 조회
_KIS_INDEX_TR = "FHPUP02100000"


def _fetch_index_members(kis, index_code: str) -> list[str]:
    """
    KIS API로 지수 구성종목 조회
    index_code: "0001"=KOSPI200, "1001"=KOSDAQ150
    """
    import requests

    try:
        token = kis.get_access_token()
        import os
        hdrs = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey":        os.getenv("KIS_APP_KEY", ""),
            "appsecret":     os.getenv("KIS_APP_SECRET", ""),
            "tr_id":         _KIS_INDEX_TR,
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD":         index_code,
        }
        url = f"{kis.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-member"
        r   = requests.get(url, headers=hdrs, params=params, timeout=10)
        items = r.json().get("output2", [])
        return [it.get("mksc_shrn_iscd", "") for it in items if it.get("mksc_shrn_iscd")]
    except Exception as e:
        logger.warning(f"[ExchangeValidator] 지수 구성종목 조회 실패 ({index_code}): {e}")
        return []


def refresh_eligible_list(kis=None) -> set[str]:
    """
    KOSPI 200 + KOSDAQ 150 구성종목 조회 후 파일 저장.
    kis=None 이면 파일에서만 로드.
    """
    symbols: set[str] = set()

    if kis is not None:
        kospi200  = _fetch_index_members(kis, "0001")
        kosdaq150 = _fetch_index_members(kis, "1001")
        symbols   = set(kospi200) | set(kosdaq150)

        if symbols:
            ELIGIBLE_PATH.parent.mkdir(parents=True, exist_ok=True)
            ELIGIBLE_PATH.write_text(
                json.dumps({
                    "symbols":    sorted(symbols),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "kospi200_count":  len(kospi200),
                    "kosdaq150_count": len(kosdaq150),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                f"[ExchangeValidator] NXT 적격 목록 갱신: "
                f"KOSPI200 {len(kospi200)}개 + KOSDAQ150 {len(kosdaq150)}개 = {len(symbols)}개"
            )
        else:
            logger.warning("[ExchangeValidator] API 조회 결과 없음 — 기존 파일 유지")

    # 파일 로드 (API 실패 시 fallback)
    if not symbols and ELIGIBLE_PATH.exists():
        try:
            data    = json.loads(ELIGIBLE_PATH.read_text(encoding="utf-8"))
            symbols = set(data.get("symbols", []))
            logger.info(f"[ExchangeValidator] 캐시 로드: {len(symbols)}개")
        except Exception as e:
            logger.warning(f"[ExchangeValidator] 캐시 로드 실패: {e}")

    return symbols


# ── 싱글톤 캐시 ────────────────────────────────────────────────────────────────
_eligible: Optional[set] = None


def _get_eligible() -> set[str]:
    global _eligible
    if _eligible is None:
        _eligible = refresh_eligible_list()
    return _eligible


def is_nxt_eligible(symbol: str) -> bool:
    """NXT 거래 가능 종목 여부 (KOSPI200 or KOSDAQ150)"""
    return symbol in _get_eligible()


def get_exchange_label(symbol: str) -> str:
    """종목의 거래소 레이블 반환: 'NXT' | 'KRX'"""
    return "NXT" if is_nxt_eligible(symbol) else "KRX"
