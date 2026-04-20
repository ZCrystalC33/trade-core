#!/usr/bin/env python3
"""
 進化學習框架
 用途：追蹤訊號勝率、記錄成功/失敗案例、更新選股模板

 執行方式：
   python3 evolution.py --report        # 產出進化報告
   python3 evolution.py --record --stock 4967 --result WIN --gain 18.5
   python3 evolution.py --init          # 初始化進化資料庫
"""

import os
import sys
import sqlite3
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


# ── 勝率統計 ─────────────────────────────────────────────

def compute_signal_stats():
    """
    計算每種訊號的勝率與平均報酬
    從 trade_signals + trades 交叉比對
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 找出所有有結果的交易
    cursor.execute("""
        SELECT ts.stock_id, ts.signal_type, ts.signal_date, ts.price_at_signal,
               t.exit_price, t.pnl_pct, t.exit_reason, t.hold_days
        FROM trade_signals ts
        LEFT JOIN trades t ON t.stock_id = ts.stock_id
               AND t.signal_id IS NOT NULL
        WHERE ts.signal_source = 'SCANNER'
        ORDER BY ts.signal_date DESC
    """)

    # 按訊號類型分組
    by_signal = defaultdict(list)
    by_stock = defaultdict(list)

    for r in cursor.fetchall():
        stock_id = r[0]
        signal_type = r[1]
        pnl = r[5]
        if pnl is not None:
            by_signal[signal_type].append(pnl)
            by_stock[stock_id].append(pnl)

    conn.close()

    stats = {}
    for sig, pnls in sorted(by_signal.items()):
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        stats[sig] = {
            "count": len(pnls),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        }

    return stats, dict(by_stock)


def compute_stock_stats():
    """計算各檔股票的勝率"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_id, COUNT(*) as cnt,
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
               AVG(pnl_pct) as avg_pnl,
               SUM(pnl_pct) as total_pnl
        FROM trades
        GROUP BY stock_id
    """)
    rows = cursor.fetchall()
    conn.close()

    result = {}
    for sid, cnt, wins, avg_pnl, total_pnl in rows:
        result[sid] = {
            "trades": cnt,
            "wins": wins or 0,
            "win_rate": round((wins or 0) / cnt * 100, 1),
            "avg_pnl": round(avg_pnl or 0, 2),
            "total_pnl": round(total_pnl or 0, 2),
        }
    return result


# ── 進化規則工廠 ─────────────────────────────────────────

def generate_evolution_insights(signal_stats: dict, stock_stats: dict) -> list:
    """根據統計結果自動生成進化洞察"""
    insights = []

    # 找出最好和最差的訊號
    if signal_stats:
        sorted_by_wr = sorted(signal_stats.items(), key=lambda x: x[1]["win_rate"], reverse=True)
        sorted_by_pnl = sorted(signal_stats.items(), key=lambda x: x[1]["avg_pnl"], reverse=True)

        best_sig = sorted_by_wr[0]
        best_pnl_sig = sorted_by_pnl[0]

        insights.append(f"🟢 勝率最高訊號：{best_sig[0]}（{best_sig[1]['win_rate']}% / {best_sig[1]['count']}筆）")
        insights.append(f"📈 報酬最高訊號：{best_pnl_sig[0]}（平均{best_pnl_sig[1]['avg_pnl']}%）")

        # 最差訊號
        worst_sig = sorted_by_wr[-1]
        if worst_sig[1]["win_rate"] < 40 and worst_sig[1]["count"] >= 3:
            insights.append(f"🔴 勝率過低訊號：{worst_sig[0]}（{worst_sig[1]['win_rate']}%），建議降低權重")

        # 胜率低於 45% 的訊號要警愒
        for sig, st in signal_stats.items():
            if st["win_rate"] < 45 and st["count"] >= 5:
                insights.append(f"⚠️ {sig} 勝率{st['win_rate']}%（{st['count']}筆），注意策略失效風險")

    # 個股表現
    if stock_stats:
        best_stock = max(stock_stats.items(), key=lambda x: x[1]["total_pnl"])
        insights.append(f"📊 個股總報酬最高：{best_stock[0]}（{best_stock[1]['total_pnl']}% / {best_stock[1]['trades']}筆）")

    return insights


# ── 選股模板更新 ─────────────────────────────────────────

def update_success_template(signal_stats: dict, stock_stats: dict) -> str:
    """
    根據勝率統計，自動產出新的選股模板規則
    """
    if not signal_stats:
        return "（尚無足夠資料產生模板）"

    # 高勝率訊號（>55%且樣本數>=3）
    high_win = [
        (sig, st["win_rate"], st["count"], st["avg_pnl"])
        for sig, st in signal_stats.items()
        if st["win_rate"] >= 55 and st["count"] >= 3
    ]
    # 高報酬訊號（平均報酬>8%且樣本數>=3）
    high_pnl = [
        (sig, st["avg_pnl"], st["count"], st["win_rate"])
        for sig, st in signal_stats.items()
        if st["avg_pnl"] >= 8 and st["count"] >= 3
    ]

    template = []
    template.append("【Stephanie 選股模板 — 自動更新】")
    template.append(f"更新時間：{datetime.now().strftime('%Y-%m-%d')}")
    template.append("")
    template.append("▶ 高勝率訊號（勝率≥55%，樣本≥3筆）：")
    if high_win:
        for sig, wr, cnt, pnl in sorted(high_win, key=lambda x: -x[1]):
            template.append(f"  ✅ {sig}：勝率{wr}%（{cnt}筆）/ 平均報酬{pnl}%")
    else:
        template.append("  （目前無符合條件的訊號）")

    template.append("")
    template.append("▶ 高報酬訊號（平均報酬≥8%，樣本≥3筆）：")
    if high_pnl:
        for sig, pnl, cnt, wr in sorted(high_pnl, key=lambda x: -x[1]):
            template.append(f"  ✅ {sig}：平均報酬{pnl}%（{cnt}筆）/ 勝率{wr}%")
    else:
        template.append("  （目前無符合條件的訊號）")

    return "\n".join(template)


# ── 產出進化報告 ─────────────────────────────────────────

def generate_evolution_report() -> str:
    """產出完整的進化報告"""
    signal_stats, stock_stats = compute_signal_stats()
    stock_stats2 = compute_stock_stats()
    insights = generate_evolution_insights(signal_stats, stock_stats2)
    template = update_success_template(signal_stats, stock_stats2)

    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"🧬 **Stephanie 進化學習報告**",
        f"📅 {today}",
        "",
        "───",
        "▍訊號勝率統計",
        "",
    ]

    if signal_stats:
        lines.append(f"  {'訊號':<25} {'筆數':>5} {'勝率':>6} {'平均報酬':>8} {'平均獲利':>8} {'平均虧損':>8}")
        lines.append("  " + "-" * 65)
        for sig, st in sorted(signal_stats.items(), key=lambda x: -x[1]["win_rate"]):
            lines.append(f"  {sig:<25} {st['count']:>5} {st['win_rate']:>6}% {st['avg_pnl']:>+7.2f}% {st['avg_win']:>+7.2f}% {st['avg_loss']:>+7.2f}%")
    else:
        lines.append("  （尚無訊號記錄）")

    lines.extend(["", "───", "▍個股勝率統計", ""])

    if stock_stats2:
        lines.append(f"  {'股票':>6} {'交易筆數':>8} {'勝率':>6} {'平均報酬':>8} {'總報酬':>8}")
        lines.append("  " + "-" * 45)
        for sid, st in sorted(stock_stats2.items(), key=lambda x: -x[1]["total_pnl"]):
            lines.append(f"  {sid:>6} {st['trades']:>8} {st['win_rate']:>6}% {st['avg_pnl']:>+7.2f}% {st['total_pnl']:>+7.2f}%")
    else:
        lines.append("  （尚無交易記錄）")

    lines.extend(["", "───", "▍進化洞察", ""])
    for ins in insights:
        lines.append(f"  {ins}")

    lines.extend(["", "───", "▍選股模板更新", "", template])

    lines.extend(["", "───", f"_由 Trade Core 進化學習引擎產生_"])

    return "\n".join(lines)


# ── 手動記錄交易結果 ─────────────────────────────────────

def record_trade(stock_id: str, signal_type: str, result: str, gain_pct: float,
                 entry_price: float, exit_price: float, hold_days: int):
    """手動記錄一筆交易結果（用於還沒辦法自動串券商的情況）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO trades
        (stock_id, entry_date, entry_price, exit_date, exit_price,
         shares, position_type, realized_pnl, realized_pnl_pct,
         status, notes)
        VALUES (?, ?, ?, ?, ?, 0, '波段', ?, ?, 'CLOSED',
                '手動記錄')
    """, (
        stock_id,
        datetime.now().strftime("%Y-%m-%d"),  # 簡化，先塞今天
        entry_price,
        datetime.now().strftime("%Y-%m-%d"),
        exit_price,
        round(exit_price - entry_price, 2),
        round(gain_pct, 2),
    ))

    conn.commit()
    conn.close()
    return f"已記錄 {stock_id} {result} {gain_pct:+.2f}%"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="進化學習框架")
    parser.add_argument("--report", action="store_true", help="產出進化報告")
    parser.add_argument("--record", action="store_true", help="手動記錄交易")
    parser.add_argument("--stock", type=str, help="股票代碼")
    parser.add_argument("--result", type=str, choices=["WIN","LOSS"], help="結果")
    parser.add_argument("--gain", type=float, help="報酬率%")
    parser.add_argument("--entry", type=float, help="進場價格")
    parser.add_argument("--exit", type=float, help="出場價格")
    parser.add_argument("--hold", type=int, default=0, help="持有天數")
    args = parser.parse_args()

    if args.report or len(sys.argv) == 1:
        report = generate_evolution_report()
        print(report)
    elif args.record and args.stock and args.result and args.gain is not None:
        msg = record_trade(
            args.stock, "MANUAL", args.result, args.gain,
            args.entry or 0, args.exit or 0, args.hold
        )
        print(f"✅ {msg}")
    else:
        parser.print_help()