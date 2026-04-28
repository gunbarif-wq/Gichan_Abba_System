"""
Telegram Commander — 자연어 종목명 기반 양방향 제어
지원 명령:
  [종목명]          — 감시 목록 추가
  [종목명] 중지     — 감시 목록 제거
  [종목명] 매수     — 확인 버튼 후 시장가 매수
  [종목명] 매도     — 확인 버튼 후 시장가 매도
  전량매도          — 전체 포지션 즉시 시장가 매도
  감시              — 현재 감시 목록
  종목선정          — Top200 선정 트리거
  보유              — 잔고 + 보유 포지션 + 손익
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

BASE_DIR     = Path(__file__).resolve().parent.parent
WATCHLIST_DB = BASE_DIR / "storage" / "watchlist" / "commander_watchlist.json"

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"
POLL_TIMEOUT = 30
CONFIRM_TTL  = 60   # 확인 버튼 유효 시간(초)


# ── 퍼지 종목명 매칭 ──────────────────────────────────────────────────────────

def _load_symbol_master() -> dict:
    path = BASE_DIR / "storage" / "watchlist" / "symbol_master.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def fuzzy_match(query: str, master: dict) -> list:
    q = query.strip().lower()
    results = []
    for symbol, info in master.items():
        name = info.get("name", "")
        if q in name.lower() or name.lower() in q:
            results.append({"symbol": symbol, "name": name})
    results.sort(key=lambda x: (0 if x["name"].lower() == q else 1, len(x["name"])))
    return results


# ── 감시 목록 관리 ────────────────────────────────────────────────────────────

def _load_watchlist() -> dict:
    if WATCHLIST_DB.exists():
        try:
            return json.loads(WATCHLIST_DB.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_watchlist(data: dict):
    WATCHLIST_DB.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Commander ─────────────────────────────────────────────────────────────────

class Commander:

    def __init__(self):
        self.token    = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id  = os.getenv("TELEGRAM_CHAT_ID", "")
        self._offset  = 0
        self._ok      = bool(self.token and self.chat_id)
        self._pending: dict = {}   # confirm_id → {action, symbol, name, expires_at, ...}
        self._daily_report_started = False
        logger.info(f"[Commander] 초기화 (bot={'OK' if self._ok else 'NO TOKEN'})")

    # ── Telegram API ──────────────────────────────────────────────────────────

    def _api(self, method: str, **params) -> Optional[dict]:
        url = f"{TELEGRAM_API.format(token=self.token)}/{method}"
        try:
            resp = requests.post(url, json=params, timeout=POLL_TIMEOUT + 5)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            logger.warning(f"[Commander] API 오류: {data.get('description')}")
        except requests.RequestException as e:
            logger.warning(f"[Commander] 연결 오류: {e}")
        return None

    def send(self, text: str, reply_markup: Optional[dict] = None) -> Optional[int]:
        params = dict(chat_id=self.chat_id, text=text, parse_mode="HTML")
        if reply_markup:
            params["reply_markup"] = reply_markup
        result = self._api("sendMessage", **params)
        return result.get("message_id") if result else None

    def _edit_reply_markup(self, message_id: int, markup: Optional[dict]):
        self._api("editMessageReplyMarkup",
                  chat_id=self.chat_id,
                  message_id=message_id,
                  reply_markup=markup or {})

    def _answer_callback(self, callback_id: str, text: str = ""):
        self._api("answerCallbackQuery", callback_query_id=callback_id, text=text)

    # ── 확인 버튼 ─────────────────────────────────────────────────────────────

    def _send_confirm(self, action: str, symbol: str, name: str,
                      price: int, quantity: int, amount: int,
                      extra: dict = None) -> str:
        """확인/취소 인라인 버튼 메시지 발송. confirm_id 반환."""
        cid = uuid.uuid4().hex[:8]
        self._pending[cid] = {
            "action":     action,   # "buy" | "sell"
            "symbol":     symbol,
            "name":       name,
            "price":      price,
            "quantity":   quantity,
            "amount":     amount,
            "extra":      extra or {},
            "expires_at": datetime.now().timestamp() + CONFIRM_TTL,
            "msg_id":     None,
        }
        sign = "매수" if action == "buy" else "매도"
        msg = (
            f"주문 확인\n"
            f"종목: {name}({symbol})\n"
            f"구분: {sign}\n"
            f"가격: {price:,}원\n"
            f"수량: {quantity:,}주\n"
            f"금액: {amount:,}원\n"
            f"\n확인하시겠습니까? ({CONFIRM_TTL}초 내)"
        )
        markup = {
            "inline_keyboard": [[
                {"text": "확인", "callback_data": f"confirm:{cid}"},
                {"text": "취소", "callback_data": f"cancel:{cid}"},
            ]]
        }
        mid = self.send(msg, reply_markup=markup)
        if mid:
            self._pending[cid]["msg_id"] = mid
        return cid

    # ── 주문 실행 (확인 후) ───────────────────────────────────────────────────

    def _execute_buy(self, symbol: str, name: str,
                     price: int, quantity: int) -> str:
        try:
            from trade.kis_live_client import get_kis_live_client
            kis = get_kis_live_client()
            kis.place_buy_order(symbol, quantity, price, order_type="01")
            amount = price * quantity
            return (
                f"매수 체결\n"
                f"종목: {name}({symbol})\n"
                f"가격: {price:,}원\n"
                f"수량: {quantity:,}주\n"
                f"금액: {amount:,}원"
            )
        except Exception as e:
            return f"매수 실패: {e}"

    def _execute_sell(self, symbol: str, name: str,
                      price: int, quantity: int, avg_price: int) -> str:
        try:
            from trade.kis_live_client import get_kis_live_client
            kis    = get_kis_live_client()
            kis.place_sell_order(symbol, quantity, price, order_type="01")
            amount = price * quantity
            profit = (price - avg_price) * quantity
            pct    = (price - avg_price) / avg_price * 100 if avg_price > 0 else 0.0
            sign   = "+" if profit >= 0 else ""
            return (
                f"매도 체결\n"
                f"종목: {name}({symbol})\n"
                f"가격: {price:,}원\n"
                f"수량: {quantity:,}주\n"
                f"금액: {amount:,}원\n"
                f"손익: {sign}{profit:,}원 ({sign}{pct:.2f}%)"
            )
        except Exception as e:
            return f"매도 실패: {e}"

    # ── callback_query 처리 ───────────────────────────────────────────────────

    def _handle_callback(self, callback: dict):
        cid_str     = callback.get("data", "")
        callback_id = callback.get("id", "")
        chat_id     = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        msg_id      = callback.get("message", {}).get("message_id")

        if chat_id != self.chat_id:
            return

        if ":" not in cid_str:
            return
        action_type, cid = cid_str.split(":", 1)

        pending = self._pending.pop(cid, None)
        if pending is None:
            self._answer_callback(callback_id, "만료된 요청입니다.")
            return

        if datetime.now().timestamp() > pending["expires_at"]:
            self._answer_callback(callback_id, "시간 초과.")
            if msg_id:
                self._edit_reply_markup(msg_id, None)
            return

        # 버튼 제거
        if msg_id:
            self._edit_reply_markup(msg_id, None)

        if action_type == "cancel":
            self._answer_callback(callback_id, "취소됨")
            self.send("주문이 취소되었습니다.")
            return

        # 확인 → 실제 주문
        self._answer_callback(callback_id, "처리 중...")
        if pending["action"] == "buy":
            result = self._execute_buy(
                pending["symbol"], pending["name"],
                pending["price"], pending["quantity"],
            )
        else:
            result = self._execute_sell(
                pending["symbol"], pending["name"],
                pending["price"], pending["quantity"],
                pending["extra"].get("avg_price", 0),
            )
        self.send(result)

    # ── 명령 핸들러 ───────────────────────────────────────────────────────────

    def _handle_add_watch(self, symbol: str, name: str) -> str:
        wl = _load_watchlist()
        if symbol in wl:
            return f"{name}({symbol}) 이미 감시 중"
        wl[symbol] = {"name": name, "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        _save_watchlist(wl)
        return f"감시 추가: {name}({symbol})"

    def _handle_remove_watch(self, symbol: str, name: str) -> str:
        wl = _load_watchlist()
        if symbol not in wl:
            return f"{name}({symbol}) 감시 목록에 없음"
        wl.pop(symbol)
        _save_watchlist(wl)
        return f"감시 제거: {name}({symbol})"

    def _prepare_buy(self, symbol: str, name: str) -> str:
        try:
            from account.account_manager import get_account_manager
            mgr     = get_account_manager()
            balance = mgr.available_cash
        except Exception:
            balance = 0.0

        if balance < 100_000:
            return f"매수 불가: 잔고 부족 ({balance:,.0f}원)"

        try:
            from risk.money_manager import evaluate
            risk = evaluate({
                "balance":            balance,
                "win_rate":           0.6,
                "avg_win":            8.0,
                "avg_loss":           5.0,
                "consecutive_losses": 0,
            })
            if not risk["can_trade"]:
                return f"매수 불가: 리스크 제한 ({risk['reason']})"
            position_size = risk["position_size"]
        except Exception as e:
            return f"리스크 확인 실패: {e}"

        try:
            from trade.kis_live_client import get_kis_live_client
            kis   = get_kis_live_client()
            data  = kis.get_current_price(symbol)
            price = int(data.get("stck_prpr", 0))
            if price <= 0:
                return f"{name} 현재가 조회 실패"
        except Exception as e:
            return f"현재가 조회 실패: {e}"

        quantity = max(1, int(position_size / price))
        self._send_confirm("buy", symbol, name, price, quantity, price * quantity)
        return ""

    def _prepare_sell(self, symbol: str, name: str) -> str:
        try:
            from account.account_manager import get_account_manager
            mgr = get_account_manager()
            pos = mgr.get_all_positions().get(symbol)
            if not pos or pos.quantity <= 0:
                return f"{name}({symbol}) 보유 없음"
            quantity  = pos.quantity
            avg_price = int(pos.avg_buy_price)
        except Exception as e:
            return f"포지션 확인 실패: {e}"

        try:
            from trade.kis_live_client import get_kis_live_client
            kis   = get_kis_live_client()
            data  = kis.get_current_price(symbol)
            price = int(data.get("stck_prpr", 0))
            if price <= 0:
                return f"{name} 현재가 조회 실패"
        except Exception as e:
            return f"현재가 조회 실패: {e}"

        self._send_confirm("sell", symbol, name, price, quantity, price * quantity,
                           extra={"avg_price": avg_price})
        return ""

    def _handle_panic_sell(self) -> str:
        """전량매도 — 모든 보유 포지션 즉시 시장가 매도."""
        try:
            from account.account_manager import get_account_manager
            from trade.kis_live_client import get_kis_live_client
            mgr       = get_account_manager()
            positions = mgr.get_all_positions()
        except Exception as e:
            return f"전량매도 실패: {e}"

        if not positions:
            return "보유 종목 없음"

        self.send(f"전량매도 시작 — {len(positions)}개 종목")
        kis     = get_kis_live_client()
        results = []

        for symbol, pos in positions.items():
            if pos.quantity <= 0:
                continue
            try:
                data  = kis.get_current_price(symbol)
                price = int(data.get("stck_prpr", 0)) or int(pos.avg_buy_price)
                kis.place_sell_order(symbol, pos.quantity, price, order_type="01")
                amount = price * pos.quantity
                profit = (price - pos.avg_buy_price) * pos.quantity
                pct    = (price - pos.avg_buy_price) / pos.avg_buy_price * 100
                sign   = "+" if profit >= 0 else ""
                results.append(
                    f"{pos.name}({symbol}) {pos.quantity:,}주 "
                    f"@ {price:,}원 {sign}{pct:.1f}%"
                )
            except Exception as e:
                results.append(f"{symbol} 매도 실패: {e}")

        self.send("\n".join(results))
        return "모든 보유 종목의 매도가 완료되었습니다."

    def _handle_watchlist(self) -> str:
        wl = _load_watchlist()
        if not wl:
            return "감시 목록 없음"
        lines = [f"감시 목록 ({len(wl)}개)"]
        for sym, info in wl.items():
            lines.append(f"  {info.get('name', sym)}({sym})")
        return "\n".join(lines)

    def _handle_select(self) -> str:
        def _run():
            try:
                from trade.kis_live_client import get_kis_live_client
                from scanner.premarket_scanner import PreMarketScanner, WatchCandidate
                from exchange.validator import is_nxt_eligible

                kis = get_kis_live_client()

                # ── Top50 실시간 스캔 ─────────────────────────────────────────
                top50: dict[str, WatchCandidate] = {}
                for market in ("J", "Q"):
                    try:
                        items = kis.get_volume_rank(market=market, top_n=25)
                        for rank, item in enumerate(items):
                            symbol = item.get("mksc_shrn_iscd", "")
                            name   = item.get("hts_kor_isnm", symbol)
                            if not symbol:
                                continue
                            exchange = "NXT" if is_nxt_eligible(symbol) else "KRX"
                            c = top50.setdefault(
                                symbol,
                                WatchCandidate(symbol=symbol, name=name, exchange=exchange)
                            )
                            c.score += max(0, 25 - rank)
                            c.reasons.append(f"실시간거래량{rank+1}위")
                    except Exception:
                        pass

                # ── 기존 감시목록 로드 ────────────────────────────────────────
                # run.py PreMarketThread가 오늘 선정한 목록 (없으면 빈 dict)
                try:
                    from run import get_shared_state
                    state    = get_shared_state()
                    existing = getattr(state, "watchlist_candidates", {})
                except Exception:
                    existing = {}

                # ── 비교 및 점수 합산 ─────────────────────────────────────────
                # 기존 목록에 있으면 점수 보너스, Top50에만 있으면 그대로 포함
                merged: dict[str, WatchCandidate] = {}

                for symbol, c in top50.items():
                    merged[symbol] = c
                    if symbol in existing:
                        merged[symbol].score += existing[symbol].score * 0.5
                        merged[symbol].reasons.append("기존선정")

                # 기존 목록에는 있지만 Top50에 없는 종목 (점수 감점 후 포함)
                for symbol, c in existing.items():
                    if symbol not in merged:
                        c.score *= 0.3   # Top50 미진입 시 감점
                        c.reasons.append("기존유지")
                        merged[symbol] = c

                # 점수 기준 상위 30개
                ranked = sorted(merged.values(), key=lambda x: x.score, reverse=True)[:30]

                # ── 결과 전송 ─────────────────────────────────────────────────
                now_str = datetime.now().strftime("%H:%M")
                lines   = [
                    f"<b>수동 종목선정 완료</b> {now_str}",
                    f"Top50 스캔 {len(top50)}개 / 기존목록 {len(existing)}개 → 최종 {len(ranked)}개",
                    "",
                ]
                for i, c in enumerate(ranked[:15], 1):
                    tag = "[NXT]" if c.exchange == "NXT" else "[KRX]"
                    lines.append(
                        f"{i:2d}. {tag} {c.name}({c.symbol}) "
                        f"점수={c.score:.0f} {', '.join(c.reasons[:2])}"
                    )
                if len(ranked) > 15:
                    lines.append(f"... 외 {len(ranked)-15}개")

                self.send("\n".join(lines))

            except Exception as e:
                self.send(f"종목 선정 실패: {e}")

        threading.Thread(target=_run, daemon=True).start()
        return "종목 선정 시작\nTop50 스캔 + 기존목록 비교 중... (완료 시 결과 전송)"

    def _handle_holdings(self) -> str:
        try:
            from account.account_manager import get_account_manager
            mgr   = get_account_manager()
            cash  = mgr.available_cash
            total = mgr.get_total_asset()
            pos   = mgr.get_all_positions()
        except Exception as e:
            return f"계좌 조회 실패: {e}"

        lines = [
            f"계좌 현황 {datetime.now():%H:%M}",
            f"현금: {cash:,.0f}원",
            f"총자산: {total:,.0f}원",
        ]
        if pos:
            lines.append(f"\n보유 종목 ({len(pos)}개)")
            for sym, p in pos.items():
                sign = "+" if p.unrealized_pnl_ratio >= 0 else ""
                lines.append(
                    f"  {p.name}({sym}) {p.quantity:,}주 "
                    f"평균{p.avg_buy_price:,.0f}원 "
                    f"{sign}{p.unrealized_pnl_ratio:.1f}%"
                )
        else:
            lines.append("\n보유 종목 없음")
        return "\n".join(lines)

    # ── 20:00 일일 리포트 ─────────────────────────────────────────────────────

    def _send_daily_report(self):
        try:
            from account.account_manager import get_account_manager
            from report.pnl_calculator import get_pnl_calculator
            mgr      = get_account_manager()
            cash     = mgr.available_cash
            total    = mgr.get_total_asset()
            pnl_calc = get_pnl_calculator()
            today    = pnl_calc.get_daily_summary() if hasattr(pnl_calc, "get_daily_summary") else {}

            daily_pnl   = today.get("total_profit", 0)
            daily_yield = today.get("total_yield",  0.0)
            trade_count = today.get("trade_count",  0)
            sign        = "+" if daily_pnl >= 0 else ""

            msg = (
                f"📊 <b>일일 리포트</b> {datetime.now():%Y-%m-%d}\n"
                f"─────────────────────\n"
                f"당일 손익:  {sign}{daily_pnl:,.0f}원\n"
                f"수익률:     {sign}{daily_yield:.2f}%\n"
                f"거래 횟수:  {trade_count}회\n"
                f"현금:       {cash:,.0f}원\n"
                f"총자산:     {total:,.0f}원"
            )
        except Exception as e:
            msg = f"일일 리포트 생성 실패: {e}"

        self.send(msg)

    def _start_daily_report_scheduler(self):
        """20:00 KST 일일 리포트 스케줄러 — 별도 스레드."""
        if self._daily_report_started:
            return
        self._daily_report_started = True

        def _scheduler():
            while True:
                now    = datetime.now()
                target = now.replace(hour=20, minute=0, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                wait = (target - datetime.now()).total_seconds()
                time.sleep(wait)
                self._send_daily_report()

        threading.Thread(target=_scheduler, daemon=True, name="DailyReport").start()
        logger.info("[Commander] 20:00 일일 리포트 스케줄러 시작")

    # ── 메시지 라우팅 ─────────────────────────────────────────────────────────

    def process(self, text: str) -> str:
        text = text.strip()
        if not text or text.startswith("/"):
            return ""

        if text == "감시":      return self._handle_watchlist()
        if text == "종목선정":  return self._handle_select()
        if text == "보유":      return self._handle_holdings()
        if text == "전량매도":  return self._handle_panic_sell()

        stock_query, action = self._parse(text)
        if not stock_query:
            return ""

        master  = _load_symbol_master()
        matches = fuzzy_match(stock_query, master)

        if not matches:
            return f"'{stock_query}' 종목을 찾을 수 없습니다."

        if len(matches) > 1:
            names = ", ".join(f"{m['name']}({m['symbol']})" for m in matches[:5])
            return f"여러 종목이 검색됩니다: {names}\n정확한 종목명을 입력해주세요."

        symbol = matches[0]["symbol"]
        name   = matches[0]["name"]

        if action == "매수":
            return self._prepare_buy(symbol, name)
        elif action == "매도":
            return self._prepare_sell(symbol, name)
        elif action == "중지":
            return self._handle_remove_watch(symbol, name)
        else:
            return self._handle_add_watch(symbol, name)

    def _parse(self, text: str) -> tuple:
        text  = text.strip()
        if text.startswith("/"):
            return "", ""
        parts   = text.split()
        actions = {"중지", "매수", "매도"}
        if len(parts) > 1 and parts[-1] in actions:
            return " ".join(parts[:-1]), parts[-1]
        return text, ""

    # ── 폴링 루프 ─────────────────────────────────────────────────────────────

    def run(self):
        if not self._ok:
            logger.error("[Commander] TELEGRAM_BOT_TOKEN/CHAT_ID 없음")
            return

        self._start_daily_report_scheduler()
        logger.info("[Commander] 폴링 시작")

        while True:
            try:
                updates = self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=POLL_TIMEOUT,
                    allowed_updates=["message", "callback_query"],
                )
                if not updates:
                    continue

                for upd in updates:
                    self._offset = upd["update_id"] + 1

                    # 인라인 버튼 콜백
                    if "callback_query" in upd:
                        cb      = upd["callback_query"]
                        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                        if chat_id == self.chat_id:
                            self._handle_callback(cb)
                        continue

                    msg     = upd.get("message", {})
                    text    = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if not text:
                        continue
                    if chat_id != self.chat_id:
                        logger.warning(f"[Commander] 미인가 chat_id 무시: {chat_id}")
                        continue

                    response = self.process(text)
                    if response:
                        self.send(response)

                # 만료된 pending 정리
                now = datetime.now().timestamp()
                self._pending = {k: v for k, v in self._pending.items()
                                 if v["expires_at"] > now}

            except Exception as e:
                logger.error(f"[Commander] 폴링 오류: {e}")
                time.sleep(2)


_commander: Optional[Commander] = None


def get_commander() -> Commander:
    global _commander
    if _commander is None:
        _commander = Commander()
    return _commander


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(message)s")
    get_commander().run()
