#!/usr/bin/env python3
"""
 K線圖視覺化腳本
 用途：產出個股日K圖（mplfinance），標示均線、訊號

 使用方式：
   python3 chart.py --stock 4967 --days 120
   python3 chart.py --stock 2330 --output ~/stock_quant/output/2330_kline.png
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    import mplfinance as mpf
    import pandas as pd
except ImportError:
    print("❌ 需先安裝：pip3 install mplfinance pandas --break-system-packages")
    sys.exit(1)

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_data(stock_id: str, days: int = 120) -> pd.DataFrame:
    """從資料庫讀取日K（優先還原價格）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 優先用還原價格
    cursor.execute("""
        SELECT date, open, high, low,
               adj_close as close, volume
        FROM adjusted_daily_price
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, days))
    rows = cursor.fetchall()

    if not rows:
        # 沒有還原價格，用原始
        cursor.execute("""
            SELECT date, open, high, low, close, volume
            FROM daily_price
            WHERE stock_id = ?
            ORDER BY date DESC
            LIMIT ?
        """, (stock_id, days))
        rows = cursor.fetchall()

    conn.close()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df.set_index("date", inplace=True)
    return df


def compute_ma(df: pd.DataFrame) -> dict:
    """計算均線"""
    closes = df["close"]
    mas = {}
    for period in [5, 10, 20, 60]:
        if len(closes) >= period:
            mas[f"MA{period}"] = closes.rolling(period).mean()
    return mas


def chart(stock_id: str, days: int = 120, output_path: str = None):
    """產出 K線圖"""
    df = load_data(stock_id, days)
    if df.empty:
        print(f"❌ 無 {stock_id} 資料")
        return

    stock_name = stock_id  # 可從 stock_info 查，這裡簡化
    title = f"{stock_id} Daily Candlestick (Adjusted) — Last {days} Trading Days"

    # 均線
    mas = compute_ma(df)
    apds = []

    colors = ["y", "b", "r", "g"]  # 對應 MA5/10/20/60
    for i, (name, ma_series) in enumerate(sorted(mas.items())):
        color = colors[i] if i < len(colors) else "gray"
        apds.append(mpf.make_addplot(ma_series, color=color, width=0.8, linestyle="-"))

    # 圖表設定
    mc = mpf.make_marketcolors(
        up="#26A69A", down="#EF5350",  # 漲綠跌紅
        edge="inherit",
        volume="in",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle="-",
        gridcolor="#E0E0E0",
        facecolor="#FAFAFA",
        figcolor="#FFFFFF",
        rc={"font.size": 9},
    )

    # 輸出
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        output_path = OUTPUT_DIR / f"{stock_id}_kline.png"

    mpf.plot(
        df,
        type="candle",
        style=style,
        title=title,
        ylabel="價格（元）",
        volume=True,
        addplot=apds,
        savefig=dict(fname=str(output_path), dpi=150, bbox_inches="tight"),
        figsize=(14, 8),
        datetime_format="%Y-%m",
        xrotation=45,
    )

    print(f"✅ 已產出：{output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K線圖視覺化")
    parser.add_argument("--stock", type=str, default="4967")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    chart(args.stock, args.days, args.output)
