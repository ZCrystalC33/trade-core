#!/usr/bin/env python3
"""
signal_to_trade.py — 訊號橋接進場模組
Stephanie 量化系統：把 trade_signals 中的有前景訊號手動轉為實際進場 trades

使用方式：
  # 互動式（不給引數，會列出最近訊號並一步步引導）
  python3 signal_to_trade.py

  # 直接帶參數進場
  python3 signal_to_trade.py --signal-id 123 --entry-price 200 --shares 1000

  # 帶完整參數（含倉位類型、市場、備註）
  python3 signal_to_trade.py --signal-id 123 --entry-price 200 --shares 1000 \\
      --position-type 短線 --market TW --stop-loss-pct 7 --take-profit-pct 15 \\
      --notes "突破季線量縮"

  # 查看訊號列表（不進場）
  python3 signal_to_trade.py --list-signals [--days 7]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── cost_model 可能在同一目錄，動態 import ─────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cost_model import CostModel

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

# ── 預設停損停利設定 ────────────────────────────────────────────────
DEFAULT_STOP_LOSS_PCT   = 0.07   # 7%
DEFAULT_TAKE_PROFIT_PCT = 0.15   # 15%
POSITION_TYPES = ("短線", "波段", "中線")
VALID_MARKETS  = ("TW", "US", "CRYPTO")


# ══════════════════════════════════════════════════════════════════
# 資料庫工具
# ══════════════════════════════════════════════════════════════════

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    """
    確保 trades 表有 signal_id 外鍵欄位。
    init_database.py 已定義，但若舊版 DB 缺欄位則補上。
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trades)")
    cols = {row["name"] for row in cursor.fetchall()}
    if "signal_id" not in cols:
        cursor.execute("ALTER TABLE trades ADD COLUMN signal_id INTEGER DEFAULT NULL")
        conn.commit()
        print("⚠️  已自動補充 trades.signal_id 欄位（舊版資料庫相容）")
    conn.close()


def fetch_signal(signal_id: int) -> Optional[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM trade_signals WHERE id = ?",
        (signal_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_recent_signals(days: int = 14, limit: int = 30) -> list[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ts.*,
               (SELECT COUNT(*) FROM trades t WHERE t.signal_id = ts.id) AS linked_trades
        FROM trade_signals ts
        WHERE ts.signal_date >= date('now', ?)
        ORDER BY ts.signal_date DESC, ts.id DESC
        LIMIT ?
        """,
        (f"-{days} days", limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_trade(
    stock_id: str,
    entry_date: str,
    entry_price: float,
    shares: int,
    position_type: str,
    signal_id: Optional[int],
    stop_loss_price: float,
    take_profit_price: float,
    cost_basis: float,
    notes: Optional[str],
) -> int:
    """寫入 trades 表，回傳新 trade id"""
    conn = get_db()
    cursor = conn.cursor()
    full_notes = (
        f"停損:{stop_loss_price:.2f} 停利:{take_profit_price:.2f} "
        f"成本價:{cost_basis:.2f}"
        + (f" | {notes}" if notes else "")
    )
    cursor.execute(
        """
        INSERT INTO trades
            (stock_id, entry_date, entry_price, shares,
             position_type, signal_id, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """,
        (stock_id, entry_date, entry_price, shares,
         position_type, signal_id, full_notes)
    )
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def log_system(module: str, level: str, message: str, details: str = ""):
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO system_log (module, level, message, details)
               VALUES (?, ?, ?, ?)""",
            (module, level, message, details)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # 日誌失敗不影響主流程


# ══════════════════════════════════════════════════════════════════
# 顯示工具
# ══════════════════════════════════════════════════════════════════

def fmt_price(v) -> str:
    return f"{v:.2f}" if v is not None else "—"


def print_signal_table(signals: list[dict]):
    if not signals:
        print("  （最近無訊號記錄）")
        return

    header = f"{'ID':>5}  {'股票':>6}  {'日期':>10}  {'訊號類型':<22}  {'方向':>5}  {'訊號價':>8}  {'已進場':>4}"
    print("\n" + "─" * len(header))
    print(header)
    print("─" * len(header))
    for s in signals:
        linked = "✓" if s.get("linked_trades", 0) > 0 else "·"
        direction_cn = "多▲" if s["expected_direction"] == "LONG" else "空▼"
        print(
            f"{s['id']:>5}  {s['stock_id']:>6}  {s['signal_date']:>10}  "
            f"{s['signal_type']:<22}  {direction_cn:>5}  "
            f"{fmt_price(s['price_at_signal']):>8}  {linked:>4}"
        )
    print("─" * len(header))


def print_signal_detail(sig: dict):
    print(f"\n┌──────────────────────────────────────────────────")
    print(f"│ 訊號 #{sig['id']}  {sig['stock_id']}  {sig['signal_date']}")
    print(f"│ 類型：{sig['signal_type']}  方向：{sig['expected_direction']}")
    print(f"│ 訊號時股價：{fmt_price(sig['price_at_signal'])}")
    if sig.get("notes"):
        print(f"│ 備註：{sig['notes']}")
    if sig.get("indicators_json"):
        try:
            ind = json.loads(sig["indicators_json"])
            parts = []
            for k in ("K", "D", "DIF", "DEA", "MACD_Bar", "MA5", "MA20", "MA60", "RSI"):
                v = ind.get(k)
                if v is not None:
                    parts.append(f"{k}={v:.2f}")
            if parts:
                print(f"│ 指標：{', '.join(parts)}")
        except Exception:
            pass
    print(f"└──────────────────────────────────────────────────")


def print_trade_summary(
    sig: dict,
    entry_price: float,
    shares: int,
    position_type: str,
    market: str,
    stop_loss_pct: float,
    take_profit_pct: float,
):
    cm = CostModel(market)
    cost_basis      = cm.cost_basis(entry_price)
    sl_price        = entry_price * (1 - cm.adjusted_stop_loss_pct(stop_loss_pct))
    tp_price        = entry_price * (1 + cm.adjusted_take_profit_pct(take_profit_pct))
    breakeven_price = cm.min_profit_exit(entry_price)
    total_cost      = entry_price * shares

    print(f"\n{'═'*52}")
    print(f"  📋 進場確認單 — {sig['stock_id']}  #{sig['id']}")
    print(f"{'─'*52}")
    print(f"  進場價         : {fmt_price(entry_price)}")
    print(f"  股數           : {shares:,} 股")
    print(f"  倉位類型       : {position_type}")
    print(f"  市場           : {market}（{cm}）")
    print(f"  總投入金額     : {total_cost:,.0f}")
    print(f"{'─'*52}")
    print(f"  真實成本價     : {fmt_price(cost_basis)}  （含買入手續費）")
    print(f"  損益兩平出場   : {fmt_price(breakeven_price)}")
    print(f"{'─'*52}")
    sl_pct_raw = stop_loss_pct * 100
    tp_pct_raw = take_profit_pct * 100
    sl_trigger = cm.adjusted_stop_loss_pct(stop_loss_pct) * 100
    tp_trigger = cm.adjusted_take_profit_pct(take_profit_pct) * 100
    print(f"  停損設定       : -{sl_pct_raw:.1f}%  → 觸發價 {fmt_price(sl_price)}")
    print(f"                   （股價跌 {sl_trigger:.1f}% 時觸發）")
    print(f"  停利設定       : +{tp_pct_raw:.1f}%  → 觸發價 {fmt_price(tp_price)}")
    print(f"                   （毛利達 {tp_trigger:.1f}% 時觸發）")
    sl_loss_amt = (entry_price - sl_price) * shares
    tp_gain_amt = (tp_price - entry_price) * shares
    print(f"{'─'*52}")
    print(f"  最大損失金額   : -{sl_loss_amt:,.0f}（停損觸發）")
    print(f"  目標獲利金額   : +{tp_gain_amt:,.0f}（停利觸發）")
    print(f"  風報比         : 1 : {tp_gain_amt/sl_loss_amt:.2f}")
    print(f"{'═'*52}")

    return cost_basis, sl_price, tp_price


# ══════════════════════════════════════════════════════════════════
# 互動式流程
# ══════════════════════════════════════════════════════════════════

def interactive_mode():
    print("\n🟢 Stephanie 訊號橋接模組 — 互動式進場")
    print("   （此工具會將訊號轉為真實進場記錄，請謹慎確認）\n")

    # 1. 列出最近訊號
    days_input = input("  查詢最近幾天的訊號？[預設 14]：").strip()
    days = int(days_input) if days_input.isdigit() else 14
    signals = fetch_recent_signals(days=days)
    print_signal_table(signals)

    # 2. 選擇 signal_id
    while True:
        sid_input = input("\n  請輸入訊號 ID（輸入 q 離開）：").strip()
        if sid_input.lower() == "q":
            print("  已取消。")
            return
        if sid_input.isdigit():
            break
        print("  ⚠️  請輸入數字 ID")

    signal_id = int(sid_input)
    sig = fetch_signal(signal_id)
    if not sig:
        print(f"  ❌ 找不到訊號 ID={signal_id}")
        sys.exit(1)
    print_signal_detail(sig)

    # 3. 進場價
    price_input = input(f"\n  進場價格（訊號時為 {fmt_price(sig['price_at_signal'])}）：").strip()
    try:
        entry_price = float(price_input)
    except ValueError:
        print("  ❌ 無效價格")
        sys.exit(1)

    # 4. 股數
    shares_input = input("  股數（張數 × 1000）：").strip()
    try:
        shares = int(shares_input)
        if shares <= 0:
            raise ValueError
    except ValueError:
        print("  ❌ 無效股數")
        sys.exit(1)

    # 5. 倉位類型
    print(f"  倉位類型：{' / '.join(f'[{i+1}]{t}' for i,t in enumerate(POSITION_TYPES))}")
    pt_input = input("  選擇（數字或直接輸入）[預設 1 短線]：").strip()
    if pt_input.isdigit() and 1 <= int(pt_input) <= len(POSITION_TYPES):
        position_type = POSITION_TYPES[int(pt_input) - 1]
    elif pt_input in POSITION_TYPES:
        position_type = pt_input
    else:
        position_type = "短線"

    # 6. 市場
    mkt_input = input(f"  市場（{'/'.join(VALID_MARKETS)}）[預設 TW]：").strip().upper()
    market = mkt_input if mkt_input in VALID_MARKETS else "TW"

    # 7. 停損停利
    sl_input = input(f"  停損 %（跌幾 % 觸發，如 7）[預設 {DEFAULT_STOP_LOSS_PCT*100:.0f}]：").strip()
    tp_input = input(f"  停利 %（漲幾 % 觸發，如 15）[預設 {DEFAULT_TAKE_PROFIT_PCT*100:.0f}]：").strip()
    try:
        stop_loss_pct   = float(sl_input) / 100 if sl_input else DEFAULT_STOP_LOSS_PCT
        take_profit_pct = float(tp_input) / 100 if tp_input else DEFAULT_TAKE_PROFIT_PCT
    except ValueError:
        stop_loss_pct, take_profit_pct = DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT

    # 8. 備註
    notes = input("  備註（選填，直接 Enter 跳過）：").strip() or None

    # 9. 顯示確認單並請求最終確認
    cost_basis, sl_price, tp_price = print_trade_summary(
        sig, entry_price, shares, position_type, market,
        stop_loss_pct, take_profit_pct
    )

    confirm = input("\n  ✅ 確認進場？輸入 YES 執行，其他取消：").strip()
    if confirm != "YES":
        print("  ⏹  已取消，未寫入資料庫。")
        return

    # 10. 寫入
    _execute_entry(
        sig=sig,
        entry_price=entry_price,
        shares=shares,
        position_type=position_type,
        cost_basis=cost_basis,
        sl_price=sl_price,
        tp_price=tp_price,
        notes=notes,
    )


# ══════════════════════════════════════════════════════════════════
# 引數式流程
# ══════════════════════════════════════════════════════════════════

def args_mode(args):
    sig = fetch_signal(args.signal_id)
    if not sig:
        print(f"❌ 找不到訊號 ID={args.signal_id}")
        sys.exit(1)

    print_signal_detail(sig)

    market          = (args.market or "TW").upper()
    stop_loss_pct   = args.stop_loss_pct / 100
    take_profit_pct = args.take_profit_pct / 100
    position_type   = args.position_type or "短線"

    cost_basis, sl_price, tp_price = print_trade_summary(
        sig, args.entry_price, args.shares, position_type, market,
        stop_loss_pct, take_profit_pct
    )

    if not args.yes:
        confirm = input("\n  ✅ 確認進場？輸入 YES 執行，其他取消：").strip()
        if confirm != "YES":
            print("  ⏹  已取消，未寫入資料庫。")
            return
    else:
        print("\n  （--yes 旗標：略過確認，直接寫入）")

    _execute_entry(
        sig=sig,
        entry_price=args.entry_price,
        shares=args.shares,
        position_type=position_type,
        cost_basis=cost_basis,
        sl_price=sl_price,
        tp_price=tp_price,
        notes=args.notes,
    )


# ══════════════════════════════════════════════════════════════════
# 共用寫入邏輯
# ══════════════════════════════════════════════════════════════════

def _execute_entry(
    sig: dict,
    entry_price: float,
    shares: int,
    position_type: str,
    cost_basis: float,
    sl_price: float,
    tp_price: float,
    notes: Optional[str],
):
    entry_date = date.today().isoformat()

    trade_id = insert_trade(
        stock_id       = sig["stock_id"],
        entry_date     = entry_date,
        entry_price    = entry_price,
        shares         = shares,
        position_type  = position_type,
        signal_id      = sig["id"],
        stop_loss_price  = sl_price,
        take_profit_price = tp_price,
        cost_basis     = cost_basis,
        notes          = notes,
    )

    log_system(
        module  = "signal_to_trade",
        level   = "INFO",
        message = f"進場：{sig['stock_id']} @ {entry_price}，{shares}股，trade_id={trade_id}",
        details = json.dumps({
            "signal_id": sig["id"],
            "trade_id":  trade_id,
            "entry_price": entry_price,
            "shares": shares,
            "stop_loss":   sl_price,
            "take_profit": tp_price,
        }, ensure_ascii=False),
    )

    print(f"\n  🎯 進場成功！")
    print(f"     trades.id      = {trade_id}")
    print(f"     trade_signals.id = {sig['id']}  （signal_id 橋接完成）")
    print(f"     {sig['stock_id']}  進場 {entry_price}  ×  {shares:,} 股  [{position_type}]")
    print(f"     停損 {sl_price:.2f}  /  停利 {tp_price:.2f}\n")


# ══════════════════════════════════════════════════════════════════
# 列表訊號模式
# ══════════════════════════════════════════════════════════════════

def list_signals_mode(days: int):
    print(f"\n🔍 最近 {days} 天的交易訊號")
    signals = fetch_recent_signals(days=days, limit=50)
    print_signal_table(signals)
    linked = sum(1 for s in signals if s.get("linked_trades", 0) > 0)
    print(f"\n  共 {len(signals)} 筆，其中 {linked} 筆已關聯進場\n")


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Stephanie 訊號橋接模組：把 trade_signals 轉為實際 trades",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python3 signal_to_trade.py                                 # 互動式
  python3 signal_to_trade.py --list-signals                  # 查看近 14 天訊號
  python3 signal_to_trade.py --list-signals --days 30        # 查看近 30 天
  python3 signal_to_trade.py --signal-id 5 --entry-price 185.5 --shares 2000
  python3 signal_to_trade.py --signal-id 5 --entry-price 185.5 --shares 2000 \\
      --position-type 波段 --stop-loss-pct 7 --take-profit-pct 20 --yes
""",
    )

    # 模式旗標
    p.add_argument("--list-signals", action="store_true",
                   help="列出最近訊號後離開")
    p.add_argument("--days", type=int, default=14,
                   help="--list-signals 查詢天數（預設 14）")

    # 進場必填
    p.add_argument("--signal-id",    type=int,   help="訊號 ID（trade_signals.id）")
    p.add_argument("--entry-price",  type=float, help="進場價格")
    p.add_argument("--shares",       type=int,   help="股數（如 1000 = 1 張）")

    # 進場選填
    p.add_argument("--position-type", type=str, choices=POSITION_TYPES,
                   default="短線", help="倉位類型（預設：短線）")
    p.add_argument("--market", type=str, choices=VALID_MARKETS,
                   default="TW", help="市場（預設：TW）")
    p.add_argument("--stop-loss-pct", type=float, default=DEFAULT_STOP_LOSS_PCT * 100,
                   metavar="PCT", help="停損百分比（如 7 表示 7%%，預設 7）")
    p.add_argument("--take-profit-pct", type=float, default=DEFAULT_TAKE_PROFIT_PCT * 100,
                   metavar="PCT", help="停利百分比（如 15 表示 15%%，預設 15）")
    p.add_argument("--notes", type=str, default=None, help="備註")
    p.add_argument("--yes", "-y", action="store_true",
                   help="略過最終確認提示，直接寫入（謹慎使用）")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 確保 DB schema 完整
    ensure_schema()

    # ── 模式路由 ─────────────────────────────────────────────
    if args.list_signals:
        list_signals_mode(args.days)
        return

    # 若有 signal-id 表示引數模式
    if args.signal_id is not None:
        required = [("--entry-price", args.entry_price), ("--shares", args.shares)]
        missing = [name for name, val in required if val is None]
        if missing:
            parser.error(f"引數模式缺少必填參數：{', '.join(missing)}")
        args_mode(args)
        return

    # 無引數 → 互動式
    interactive_mode()


if __name__ == "__main__":
    main()
