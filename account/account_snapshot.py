"""Account Snapshot - 계좌 스냅샷 저장"""
import json
import logging
from datetime import datetime
from pathlib import Path
logger = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("datasets/daily_snapshots")

def save_snapshot() -> str:
    """현재 계좌 상태를 파일로 저장"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    from account.account_manager import get_account_manager
    account = get_account_manager().get_account()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "timestamp": ts,
        "mode": str(account.mode),
        "available_cash": account.available_cash,
        "total_asset": account.total_asset,
        "positions": {
            sym: {
                "quantity": pos.quantity,
                "avg_buy_price": pos.avg_buy_price,
                "total_buy_amount": pos.total_buy_amount,
            }
            for sym, pos in account.positions.items()
        },
    }
    path = SNAPSHOT_DIR / f"snapshot_{ts}.json"
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[AccountSnapshot] 저장: {path}")
    return str(path)
