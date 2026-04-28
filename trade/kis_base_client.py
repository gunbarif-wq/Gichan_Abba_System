"""
KIS API 베이스 클라이언트
REST (토큰/주문/잔고) + 웹소켓 접속키 발급
모의투자 / 실투자 공통 로직
"""

import logging
import threading
import time
from datetime import datetime, timedelta, date
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class KisBaseClient:
    """
    KIS REST API 공통 클라이언트

    모의투자: BASE_URL = https://openapivts.koreainvestment.com:29443
    실투자:   BASE_URL = https://openapi.koreainvestment.com:9443
    """

    # 서브클래스에서 오버라이드
    BASE_URL: str = ""
    IS_MOCK: bool = True

    # 토큰 만료 여유 시간 (만료 10분 전에 갱신)
    TOKEN_REFRESH_MARGIN = 600

    def __init__(self, app_key: str, app_secret: str,
                 cano: str, acnt_prdt_cd: str = "01"):
        self.app_key      = app_key
        self.app_secret   = app_secret
        self.cano         = cano
        self.acnt_prdt_cd = acnt_prdt_cd

        self._access_token:    Optional[str]      = None
        self._token_expire_at: Optional[datetime] = None
        self._approval_key:    Optional[str]      = None  # 웹소켓 접속키

        self._token_lock = threading.Lock()  # 동시 갱신 방지

        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ── 토큰 관리 ──────────────────────────────────────────────────────────────

    def get_access_token(self) -> str:
        """
        액세스 토큰 발급/갱신 (스레드 안전)
        - 만료 10분 전 자동 갱신
        - Lock으로 동시 갱신 방지 (두 스레드가 동시에 재발급 요청하는 문제 차단)
        """
        # Lock 없이 먼저 체크 (대부분 유효한 경우 빠른 반환)
        if self._is_token_valid():
            return self._access_token

        # 만료됐을 때만 Lock 획득 후 재확인 (double-checked locking)
        with self._token_lock:
            if self._is_token_valid():  # 다른 스레드가 이미 갱신했을 수 있음
                return self._access_token

            url  = f"{self.BASE_URL}/oauth2/tokenP"
            body = {
                "grant_type": "client_credentials",
                "appkey":     self.app_key,
                "appsecret":  self.app_secret,
            }

            resp = self._session.post(url, json=body, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            self._access_token    = data["access_token"]
            expires_in            = int(data.get("expires_in", 86400))
            self._token_expire_at = datetime.now() + timedelta(seconds=expires_in)

            logger.info(f"[KIS] 토큰 갱신 완료 (만료: {self._token_expire_at:%H:%M:%S})")
            return self._access_token

    def _is_token_valid(self) -> bool:
        if not self._access_token or not self._token_expire_at:
            return False
        return datetime.now() < self._token_expire_at - timedelta(
            seconds=self.TOKEN_REFRESH_MARGIN
        )

    def get_approval_key(self) -> str:
        """웹소켓 접속키 발급 (웹소켓 연결 시 1회만 호출)"""
        if self._approval_key:
            return self._approval_key

        url  = f"{self.BASE_URL}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey":     self.app_key,
            "secretkey":  self.app_secret,
        }

        resp = self._session.post(url, json=body, timeout=10)
        resp.raise_for_status()
        self._approval_key = resp.json()["approval_key"]
        logger.info("[KIS] 웹소켓 접속키 발급 완료")
        return self._approval_key

    # ── 공통 헤더 ──────────────────────────────────────────────────────────────

    def _headers(self, tr_id: str) -> dict:
        return {
            "Content-Type":  "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey":        self.app_key,
            "appsecret":     self.app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",
        }

    # ── 현재가 조회 (REST, 필요시만 사용) ─────────────────────────────────────

    def get_current_price(self, symbol: str) -> dict:
        """현재가 조회 (웹소켓 불가 시 fallback용)"""
        tr_id = "FHKST01010100"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd":         symbol,
        }

        resp = self._session.get(url, headers=self._headers(tr_id),
                                 params=params, timeout=5)
        resp.raise_for_status()
        return resp.json().get("output", {})

    # ── 3분봉 조회 ────────────────────────────────────────────────────────────

    def get_minute_candles(self, symbol: str, timeframe: int = 3,
                           count: int = 80) -> list:
        """
        당일 분봉 조회 (FHKST03010200)
        timeframe: 1 | 3 | 5 | 10 | 15 | 30 | 60
        count:     최대 조회 봉 수 (최신순 정렬 → 오래된 순으로 반전해서 반환)
        반환: [{"time": "HHMMss", "open":, "high":, "low":, "close":, "volume":}, ...]
              오래된 봉 → 최신 봉 순서
        """
        tr_id = "FHKST03010200"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        from datetime import datetime
        params = {
            "FID_ETC_CLS_CODE":      "",
            "FID_COND_MRK_DIV_CODE": "J",
            "FID_INPUT_ISCD":        symbol,
            "FID_INPUT_HOUR_1":      datetime.now().strftime("%H%M%S"),
            "FID_PW_DATA_INCU_YN":   "Y",  # 과거 데이터 포함
        }

        resp = self._session.get(url, headers=self._headers(tr_id),
                                 params=params, timeout=5)
        resp.raise_for_status()
        raw = resp.json().get("output2", [])

        candles = []
        for row in raw[:count]:
            try:
                candles.append({
                    "time":   row.get("stck_bsop_date", "") + row.get("stck_cntg_hour", ""),
                    "open":   float(row.get("stck_oprc", 0)),
                    "high":   float(row.get("stck_hgpr", 0)),
                    "low":    float(row.get("stck_lwpr", 0)),
                    "close":  float(row.get("stck_prpr", 0)),
                    "volume": int(  row.get("cntg_vol",  0)),
                })
            except (ValueError, TypeError):
                continue

        # KIS는 최신→과거 순 반환 → 역순으로 뒤집어 오래된 순으로
        candles.reverse()
        return candles

    def _get_candles_at_time(self, symbol: str, timeframe: int,
                             count: int, hour_str: str) -> list:
        """특정 시각 기준 분봉 조회 (내부 헬퍼)"""
        tr_id = "FHKST03010200"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        params = {
            "FID_ETC_CLS_CODE":      "",
            "FID_COND_MRK_DIV_CODE": "J",
            "FID_INPUT_ISCD":        symbol,
            "FID_INPUT_HOUR_1":      hour_str,
            "FID_PW_DATA_INCU_YN":   "Y",
        }
        try:
            resp = self._session.get(url, headers=self._headers(tr_id),
                                     params=params, timeout=5)
            resp.raise_for_status()
            raw = resp.json().get("output2", [])
        except Exception as e:
            logger.warning(f"[KIS] 분봉 조회 실패 ({hour_str}): {e}")
            return []

        candles = []
        for row in raw[:count]:
            try:
                candles.append({
                    "time":   row.get("stck_bsop_date", "") + row.get("stck_cntg_hour", ""),
                    "open":   float(row.get("stck_oprc", 0)),
                    "high":   float(row.get("stck_hgpr", 0)),
                    "low":    float(row.get("stck_lwpr", 0)),
                    "close":  float(row.get("stck_prpr", 0)),
                    "volume": int(  row.get("cntg_vol",  0)),
                })
            except (ValueError, TypeError):
                continue
        candles.reverse()
        return candles

    def get_minute_candles_df(self, symbol: str, timeframe: int = 3,
                              count: int = 80, min_bars: int = 20):
        """분봉 DataFrame 반환. 당일 봉이 min_bars 미만이면 전 거래일 보완"""
        import pandas as pd

        today_rows = self.get_minute_candles(symbol, timeframe, count)

        # 당일 분봉 부족 → 전 거래일 15:30 기준으로 추가 조회
        if len(today_rows) < min_bars:
            prev_rows = self._get_candles_at_time(symbol, timeframe, count, "153000")
            # 전일 봉 중 당일 날짜 중복 제거
            today_dates = {r["time"][:8] for r in today_rows}
            prev_rows = [r for r in prev_rows if r["time"][:8] not in today_dates]
            rows = prev_rows + today_rows
            logger.debug(
                f"[KIS] {symbol} 당일봉 {len(today_rows)}개 부족 → 전일 {len(prev_rows)}개 보완"
            )
        else:
            rows = today_rows

        if not rows:
            return None
        df = pd.DataFrame(rows)
        try:
            df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S",
                                            errors="coerce")
            df.set_index("datetime", inplace=True)
        except Exception:
            pass
        df = df[["open","high","low","close","volume"]].copy()
        df = df[df["close"] > 0].copy()
        return df if len(df) >= 1 else None

    # ── 주문 ───────────────────────────────────────────────────────────────────

    def place_buy_order(self, symbol: str, quantity: int,
                        price: int, order_type: str = "00") -> dict:
        """
        매수 주문
        order_type: "00"=지정가, "01"=시장가
        """
        tr_id = "VTTC0802U" if self.IS_MOCK else "TTTC0802U"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        body  = {
            "CANO":          self.cano,
            "ACNT_PRDT_CD":  self.acnt_prdt_cd,
            "PDNO":          symbol,
            "ORD_DVSN":      order_type,
            "ORD_QTY":       str(quantity),
            "ORD_UNPR":      str(price),
        }

        resp = self._session.post(url, headers=self._headers(tr_id),
                                  json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            raise RuntimeError(
                f"매수 주문 실패: {data.get('msg1', '')} [{data.get('msg_cd', '')}]"
            )

        logger.info(f"[KIS] 매수 주문 완료: {symbol} {quantity}주 @ {price:,}원")
        return data.get("output", {})

    def place_sell_order(self, symbol: str, quantity: int,
                         price: int, order_type: str = "00") -> dict:
        """매도 주문"""
        tr_id = "VTTC0801U" if self.IS_MOCK else "TTTC0801U"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        body  = {
            "CANO":          self.cano,
            "ACNT_PRDT_CD":  self.acnt_prdt_cd,
            "PDNO":          symbol,
            "ORD_DVSN":      order_type,
            "ORD_QTY":       str(quantity),
            "ORD_UNPR":      str(price),
        }

        resp = self._session.post(url, headers=self._headers(tr_id),
                                  json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            raise RuntimeError(
                f"매도 주문 실패: {data.get('msg1', '')} [{data.get('msg_cd', '')}]"
            )

        logger.info(f"[KIS] 매도 주문 완료: {symbol} {quantity}주 @ {price:,}원")
        return data.get("output", {})

    # ── 잔고/보유 조회 ─────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """예수금 잔고 조회"""
        tr_id = "VTTC8908R" if self.IS_MOCK else "TTTC8908R"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        params = {
            "CANO":          self.cano,
            "ACNT_PRDT_CD":  self.acnt_prdt_cd,
            "PDNO":          "005930",
            "ORD_UNPR":      "0",
            "ORD_DVSN":      "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN":         "Y",
        }

        resp = self._session.get(url, headers=self._headers(tr_id),
                                 params=params, timeout=5)
        resp.raise_for_status()
        return resp.json().get("output", {})

    def get_holdings(self) -> list:
        """보유 종목 조회"""
        tr_id = "VTTC8434R" if self.IS_MOCK else "TTTC8434R"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO":              self.cano,
            "ACNT_PRDT_CD":      self.acnt_prdt_cd,
            "AFHR_FLPR_YN":      "N",
            "OFL_YN":            "",
            "INQR_DVSN":         "02",
            "UNPR_DVSN":         "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN":         "01",
            "CTX_AREA_FK100":    "",
            "CTX_AREA_NK100":    "",
        }

        resp = self._session.get(url, headers=self._headers(tr_id),
                                 params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("output1", [])

    # ── 거래량 상위 조회 (종목선정용) ─────────────────────────────────────────

    def get_volume_rank(self, market: str = "J", top_n: int = 30) -> list:
        """
        거래량 상위 종목 조회
        market: J=코스피, Q=코스닥
        """
        tr_id = "FHPST01710000"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/volume-rank"
        params = {
            "FID_COND_MRK_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD":        "0000",
            "FID_DIV_CLS_CODE":      "0",
            "FID_BLNG_CLS_CODE":     "0",
            "FID_TRGT_CLS_CODE":     "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1":     "1000",
            "FID_INPUT_PRICE_2":     "500000",
            "FID_VOL_CNT":           "100000",
            "FID_INPUT_DATE_1":      "",
        }

        resp = self._session.get(url, headers=self._headers(tr_id),
                                 params=params, timeout=5)
        resp.raise_for_status()
        output = resp.json().get("output", [])
        return output[:top_n]

    # ── 뉴스/공시 조회 (장전 스캔용) ──────────────────────────────────────────

    def get_news_list(self, top_n: int = 20) -> list:
        """당일 뉴스/공시 목록 조회"""
        tr_id = "FHKST01010900"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/news-title"
        params = {
            "FID_NEWS_OFER_ENTP_CODE": "",
            "FID_COND_MRK_DIV_CODE":   "V",
            "FID_INPUT_ISCD":          "0000000",
            "FID_INPUT_DATE_1":        datetime.now().strftime("%Y%m%d"),
            "FID_INPUT_HOUR_1":        "000000",
        }
        try:
            resp = self._session.get(url, headers=self._headers(tr_id),
                                     params=params, timeout=5)
            resp.raise_for_status()
            return resp.json().get("output", [])[:top_n]
        except Exception as e:
            logger.warning(f"[KIS] 뉴스 조회 실패: {e}")
            return []

    # ── 테마 상위 조회 (장전 스캔용) ──────────────────────────────────────────

    def get_theme_rank(self, top_n: int = 20) -> list:
        """등락률 상위 테마 종목 조회"""
        tr_id = "FHKST01710200"
        url   = f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-theme-list"
        params = {
            "FID_COND_MRK_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20172",
            "FID_DIV_CLS_CODE":      "1",
        }
        try:
            resp = self._session.get(url, headers=self._headers(tr_id),
                                     params=params, timeout=5)
            resp.raise_for_status()
            return resp.json().get("output", [])[:top_n]
        except Exception as e:
            logger.warning(f"[KIS] 테마 조회 실패: {e}")
            return []
