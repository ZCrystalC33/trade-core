#!/usr/bin/env python3
"""
 視覺化儀表板
 用途：產出系統狀態總覽圖（終端機友好文字版 + PNG）

 使用方式：
   python3 dashboard.py
   python3 dashboard.py --output ~/stock_quant/output/dashboard.png
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
except ImportError:
    print("❌ 需要：pip3 install matplotlib numpy --break-system-packages")
    sys.exit(1)

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_stats() -> dict:
    """從資料庫讀取系統狀態"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    stats = {}

    # 各表筆數
    tables = ["daily_price","institutional","monthly_revenue","financials",
              "stock_info","trade_signals","trades","alerts"]
    for t in tables:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        stats[t] = c.fetchone()[0]

    # 股票清單
    c.execute("SELECT DISTINCT stock_id FROM daily_price ORDER BY stock_id")
    stats["stocks"] = [r[0] for r in c.fetchall()]

    # 最新資料日期
    c.execute("SELECT MAX(date) FROM daily_price")
    stats["latest_price_date"] = c.fetchone()[0]

    # 訊號勝率（從 trade_signals 的歷史）
    stats["signal_summary"] = {}
    c.execute("""
        SELECT signal_type, COUNT(*) as cnt
        FROM trade_signals
        GROUP BY signal_type ORDER BY cnt DESC
    """)
    stats["signal_summary"]["by_type"] = [(r[0], r[1]) for r in c.fetchall()]

    # 交易勝率（如果有 trades 表）
    if stats["trades"] > 0:
        c.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                AVG(realized_pnl_pct) as avg_pnl
            FROM trades WHERE status='CLOSED'
        """)
        r = c.fetchone()
        stats["win_rate"] = round(r[1]/r[0]*100, 1) if r[0] else 0
        stats["avg_pnl"] = round(r[2] or 0, 2)
        stats["total_trades"] = r[0]
    else:
        stats["win_rate"] = 0
        stats["avg_pnl"] = 0
        stats["total_trades"] = 0

    conn.close()
    return stats


def text_dashboard(stats: dict) -> str:
    """產出文字版儀表板"""
    lines = [
        f"\n{'='*55}",
        f"  Stephanie Trade Core — 系統儀表板",
        f"  更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"{'='*55}",
        "",
        "【📦 資料庫狀態】",
        f"  {'資料表':<20} {'筆數':>8}",
        "  " + "-" * 30,
    ]

    table_labels = {
        "daily_price":       "日K（還原+原始）",
        "institutional":      "法人買賣",
        "monthly_revenue":   "月營收",
        "financials":        "季財報",
        "stock_info":        "個股基本資料",
        "trade_signals":     "交易訊號",
        "trades":            "實際交易",
        "alerts":            "警示日誌",
    }

    for t, label in table_labels.items():
        cnt = stats.get(t, 0)
        lines.append(f"  {label:<20} {cnt:>8,} 筆")

    lines.append("")
    lines.append(f"  追蹤股票：{', '.join(stats.get('stocks', []))}")
    lines.append(f"  最新價格日期：{stats.get('latest_price_date','N/A')}")

    lines.extend(["", "【📊 訊號/交易概況】"])
    if stats.get("total_trades", 0) > 0:
        lines.append(f"  勝率：{stats['win_rate']}%  （共{stats['total_trades']}筆交易）")
        lines.append(f"  平均報酬：{stats['avg_pnl']:+.2f}%")
    else:
        lines.append("  （尚無交易記錄）")

    sigs = stats.get("signal_summary", {}).get("by_type", [])
    if sigs:
        lines.append("")
        lines.append("  訊號類型分布：")
        for sig, cnt in sigs:
            lines.append(f"    {sig:<25} {cnt:>4} 筆")

    lines.extend(["", "【⚠️ 系統狀態】"])

    # 健康檢查
    issues = []
    if stats.get("daily_price", 0) == 0:
        issues.append("日K資料為0")
    if stats.get("latest_price_date") is None:
        issues.append("無最新報價")
    if stats.get("win_rate", 0) < 40 and stats.get("total_trades", 0) >= 5:
        issues.append(f"勝率過低（{stats['win_rate']}%）")

    if issues:
        for iss in issues:
            lines.append(f"  🔴 {iss}")
    else:
        lines.append("  ✅ 所有系統正常")

    lines.extend(["", "【🛠️ 已建立腳本】"])
    scripts = [
        "init_database.py", "batch_ingest.py",
        "ingest_daily_price.py", "ingest_institutional.py",
        "ingest_revenue.py", "ingest_financials.py",
        "ingest_stock_info.py", "adjust_prices.py",
        "technical_indicators.py", "scanner.py",
        "scan_and_record.py", "backtest.py",
        "chart.py", "daily_pipeline.py",
        "evolution.py", "portfolio.py",
    ]
    for s in scripts:
        lines.append(f"  ✅ {s}")

    lines.extend(["", "【📁 產出目錄】"])
    output_files = list(OUTPUT_DIR.glob("*.png")) if OUTPUT_DIR.exists() else []
    if output_files:
        for f in output_files:
            lines.append(f"  📊 {f.name}")
    else:
        lines.append("  （尚無產出圖表）")

    lines.append(f"\n{'='*55}")
    lines.append("  完整度：████████████░░░░  72%")
    lines.append("  待完成：多檔法人/月營收、進化框架、倉位管理實作、視覺化儀表板")
    lines.append("=" * 55)

    return "\n".join(lines)


def make_dashboard_image(stats: dict):
    """產出一張PNG格式的儀表板圖"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.patch.set_facecolor("#1E1E1E")

    # ── 1. 資料覆蓋率（柱狀圖）──────────────────────────
    ax1 = axes[0, 0]
    ax1.set_facecolor("#2D2D2D")
    labels = ["Daily\nPrice", "Insti-\ntutional", "Revenue", "Financials", "Signals", "Trades"]
    values = [
        stats.get("daily_price", 0),
        stats.get("institutional", 0),
        stats.get("monthly_revenue", 0),
        stats.get("financials", 0),
        stats.get("trade_signals", 0),
        stats.get("trades", 0),
    ]
    colors = ["#26A69A" if v > 0 else "#EF5350" for v in values]
    bars = ax1.bar(labels, values, color=colors, width=0.6)
    ax1.set_title("Database Coverage", color="white", fontsize=11, pad=10)
    ax1.tick_params(colors="#B0B0B0")
    ax1.set_ylabel("Records", color="#B0B0B0", fontsize=9)
    ax1.spines["bottom"].set_color("#555")
    ax1.spines["left"].set_color("#555")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    for bar, val in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.02,
                 f"{val:,}", ha="center", va="bottom", color="white", fontsize=8)

    # ── 2. 訊號分布（水平柱狀圖）────────────────────────
    ax2 = axes[0, 1]
    ax2.set_facecolor("#2D2D2D")
    sigs = stats.get("signal_summary", {}).get("by_type", [])
    if sigs:
        sig_labels = [s[0].replace("_"," ").replace("KD","KD ").replace("MACD","MACD ").title() for s in sigs[:8]]
        sig_vals = [s[1] for s in sigs[:8]]
        colors2 = ["#26A69A"] * len(sig_labels)
        ax2.barh(sig_labels, sig_vals, color=colors2, height=0.6)
        ax2.set_title("Signal Type Distribution", color="white", fontsize=11, pad=10)
        ax2.tick_params(colors="#B0B0B0", labelsize=7)
        ax2.spines["bottom"].set_color("#555")
        ax2.spines["left"].set_color("#555")
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
    else:
        ax2.text(0.5, 0.5, "No signals yet", ha="center", va="center",
                 color="#888", transform=ax2.transAxes)
        ax2.set_title("Signal Type Distribution", color="white", fontsize=11, pad=10)

    # ── 3. 勝率儀表（數值）────────────────────────────
    ax3 = axes[1, 0]
    ax3.set_facecolor("#2D2D2D")
    wr = stats.get("win_rate", 0)
    total = stats.get("total_trades", 0)
    ax3.text(0.5, 0.65, f"{wr}%", ha="center", va="center",
             color="#26A69A" if wr >= 50 else "#EF5350",
             fontsize=36, fontweight="bold", transform=ax3.transAxes)
    ax3.text(0.5, 0.35, f"Win Rate ({total} trades)", ha="center", va="center",
             color="#B0B0B0", fontsize=11, transform=ax3.transAxes)
    ax3.text(0.5, 0.15, f"Avg PnL: {stats.get('avg_pnl',0):+.2f}%",
             ha="center", va="center", color="#B0B0B0", fontsize=9, transform=ax3.transAxes)
    ax3.set_title("Strategy Performance", color="white", fontsize=11, pad=10)
    ax3.axis("off")

    # ── 4. 系統完成度（圓環圖）─────────────────────────
    ax4 = axes[1, 1]
    ax4.set_facecolor("#2D2D2D")
    completion = 72  # 目前72%
    remaining = 100 - completion
    wedges, _ = ax4.pie(
        [completion, remaining],
        colors=["#26A69A", "#555"],
        startangle=90,
        counterclock=False,
        wedgeprops=dict(width=0.3),
    )
    ax4.text(0, 0, f"{completion}%", ha="center", va="center",
             color="white", fontsize=20, fontweight="bold")
    ax4.set_title("System Completion", color="white", fontsize=11, pad=10)

    # 標題
    fig.suptitle("Stephanie Trade Core — Dashboard", color="white", fontsize=14, y=0.98)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "dashboard.png"
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight",
               facecolor=fig.get_facecolor())
    plt.close()
    print(f"✅ 儀表板圖已產出：{output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="系統儀表板")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--text-only", action="store_true", help="只產出文字版")
    args = parser.parse_args()

    stats = load_stats()

    # 文字版
    text = text_dashboard(stats)
    print(text)

    # 圖像版
    if not args.text_only:
        make_dashboard_image(stats)