#!/usr/bin/env python3
"""
 倉位管理模組
 用途：追蹤即時持倉、計算浮動損益、檢查風控條件、產出持倉報告

 使用方式：
   python3 portfolio.py --add 4967 --cost 200 --shares 1000 --type 波段
   python3 portfolio.py --report
   python3 portfolio.py --check-risk
   python3 portfolio.py --remove 4967
"""

import os
import sys
import os
import sqlite3
import json
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 持倉資料表（若不存在則建立）────────────────────────

def ensure_portfolio_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id    TEXT    NOT NULL UNIQUE,
            entry_date  TEXT,
            cost        REAL    NOT NULL,
            shares      INTEGER NOT NULL,
            position_type TEXT NOT NULL,  -- 短線/波段/中線
            status      TEXT    DEFAULT 'OPEN',  -- OPEN / CLOSED
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


# ── 持倉操作 ─────────────────────────────────────────────

def add_position(stock_id: str, cost: float, shares: int, position_type: str):
    """新增一筆持倉"""
    ensure_portfolio_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        cursor.execute("""
            INSERT INTO portfolio (stock_id, entry_date, cost, shares, position_type, status)
            VALUES (?, ?, ?, ?, ?, 'OPEN')
        """, (stock_id, today, cost, shares, position_type))
        conn.commit()
        msg = f"✅ 新增持倉：{stock_id} {shares}股 成本${cost}"
    except Exception as e:
        msg = f"❌ 錯誤：{e}（可能已存在）"
    conn.close()
    return msg


def remove_position(stock_id: str):
    """平倉（STATUS改為CLOSED）"""
    ensure_portfolio_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE portfolio SET status='CLOSED' WHERE stock_id=? AND status='OPEN'
    """, (stock_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected:
        return f"✅ {stock_id} 已平倉"
    return f"⚠️  {stock_id} 無有效持倉"


# ── 即時報價查詢（FinMind） ──────────────────────────────

def get_latest_price(stock_id: str) -> float:
    """取最新收盤價"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT close FROM daily_price
        WHERE stock_id=? ORDER BY date DESC LIMIT 1
    """, (stock_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0


# ── 風控檢查 ─────────────────────────────────────────────

def check_risk() -> list:
    """
    檢查所有風控條件，回傳需警告的項目
    """
    ensure_portfolio_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT stock_id, cost, shares, position_type FROM portfolio WHERE status='OPEN'")
    positions = cursor.fetchall()
    conn.close()

    if not positions:
        return ["（目前無持倉）"]

    # 假設總資金 100萬（需改為動態讀取真實帳務）
    TOTAL_CAPITAL = float(os.environ.get("PORTFOLIO_CAPITAL", "1000000"))
    SINGLE_MAX_PCT = 0.05       # 單筆不超過5%
    DAILY_LOSS_STOP = 0.03      # 單日虧損>3%停止
    TOTAL_POS_MAX   = 0.70      # 總持倉不超過70%

    warnings = []
    total_cost = 0.0

    lines = []
    lines.append(f"\n{'='*55}")
    lines.append("【Stephanie 持倉風控報告】")
    lines.append(f"{'='*55}")
    lines.append(f"  {'股票':<6} {'成本':>8} {'現價':>8} {'股數':>6} {'市值':>10} {'浮盈':>8} {'報酬%':>7} {'Type':<4}")
    lines.append("  " + "-" * 65)

    for (stock_id, cost, shares, ptype) in positions:
        current = get_latest_price(stock_id)
        market_value = current * shares
        cost_total = cost * shares
        unrealized = market_value - cost_total
        pnl_pct = (current - cost) / cost * 100 if cost > 0 else 0
        total_cost += market_value

        lines.append(f"  {stock_id:<6} {cost:>8.2f} {current:>8.2f} {shares:>6} {market_value:>10.0f} {unrealized:>+8.0f} {pnl_pct:>+7.2f}% {ptype:<4}")

        # 風控檢查
        position_pct = market_value / TOTAL_CAPITAL
        if position_pct > SINGLE_MAX_PCT:
            warnings.append(f"⚠️ {stock_id} 倉位過重：{position_pct*100:.1f}%（上限5%）")

        if pnl_pct <= -7:
            warnings.append(f"🔴 {stock_id} 觸發停損：報酬{pnl_pct:.1f}%")

        if pnl_pct >= 15:
            warnings.append(f"🟢 {stock_id} 達到停利目標：{pnl_pct:.1f}%")

    total_pct = total_cost / TOTAL_CAPITAL
    lines.append(f"\n  總持倉市值：{total_cost:,.0f} / 總資金{TOTAL_CAPITAL:,.0f}（{total_pct*100:.1f}%）")

    if total_pct > TOTAL_POS_MAX:
        warnings.append(f"⚠️ 總持倉過高：{total_pct*100:.1f}%（上限70%）")

    # 總資金報酬
    total_unrealized = sum(
        get_latest_price(sid) * sh - cost * sh
        for sid, cost, sh, _ in positions
    )
    total_pnl_pct = total_unrealized / TOTAL_CAPITAL * 100
    lines.append(f"  浮動損益：{total_unrealized:+,.0f}（{total_pnl_pct:+.2f}%）")
    lines.append("=" * 55)

    if warnings:
        lines.append("\n▍風控警示：")
        for w in warnings:
            lines.append(f"  {w}")

    return lines


# ── 產出持倉報告 ─────────────────────────────────────────

def generate_portfolio_report() -> str:
    """產出完整持倉報告"""
    ensure_portfolio_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT stock_id, cost, shares, position_type, entry_date, created_at FROM portfolio ORDER BY created_at DESC")
    positions = cursor.fetchall()
    conn.close()

    if not positions:
        return "📭 目前沒有任何持倉"

    lines = [
        f"\n📊 **Stephanie 持倉報告** — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    lines.append(f"{'股票':<6} {'成本':>8} {'現價':>8} {'股數':>6} {'市值':>10} {'浮盈':>8} {'報酬%':>7} {'類型'}")
    lines.append("-" * 65)

    for (stock_id, cost, shares, ptype, entry_date, _) in positions:
        current = get_latest_price(stock_id)
        mv = current * shares
        unreal = mv - cost * shares
        pnl_pct = (current - cost) / cost * 100 if cost > 0 else 0
        lines.append(f"{stock_id:<6} {cost:>8.2f} {current:>8.2f} {shares:>6} {mv:>10.0f} {unreal:>+8.0f} {pnl_pct:>+7.2f}% {ptype}")

    lines.extend(["", "_由 Trade Core 倉位管理模組產生_"])

    # 加上風控檢查
    risk_lines = check_risk()
    for line in risk_lines:
        lines.append(line)

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="倉位管理")
    parser.add_argument("--add", type=str, help="新增持倉")
    parser.add_argument("--remove", type=str, help="平倉")
    parser.add_argument("--cost", type=float, help="成本價格")
    parser.add_argument("--shares", type=int, help="股數")
    parser.add_argument("--type", type=str, default="波段", help="短線/波段/中線")
    parser.add_argument("--report", action="store_true", help="產出持倉報告")
    parser.add_argument("--check-risk", action="store_true", help="風控檢查")
    args = parser.parse_args()

    if args.add and args.cost and args.shares:
        print(add_position(args.add, args.cost, args.shares, args.type))
    elif args.remove:
        print(remove_position(args.remove))
    elif args.report:
        print(generate_portfolio_report())
    elif args.check_risk or ("--check-risk" in sys.argv):
        lines = check_risk()
        for l in lines:
            print(l)
    else:
        parser.print_help()