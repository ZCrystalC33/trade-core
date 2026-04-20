#!/usr/bin/env python3
"""
 價格還原引擎
 用途：將未還原的日K價格，還原為可比價（去除除權息的價格斷層）

 邏輯：
  從 FinMind 取得個股除權除息記錄（TaiwanStockDividend），
  計算每日「還原因子」，對歷史價格進行後視還原。

 使用方式：
   python3 adjust_prices.py --stock 4967        # 還原單一股票
   python3 adjust_prices.py --all                # 還原資料庫中所有股票
"""

import os
import sys
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
FINMIND_API = "https://api.finmindtrade.com/api/v4"


def get_token() -> str:
    token = os.environ.get("FINMIND_TOKEN", "")
    if token:
        return token
    tf = Path.home() / ".trade_core.env"
    if tf.exists():
        for line in tf.read_text().splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def fetch_dividends(stock_id: str, token: str) -> list:
    """取得除權除息資料"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockDividend",
        "data_id": stock_id,
        "start_date": "2010-01-01",  # 盡量拉長，確保完整
        "end_date": "2030-12-31",
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        return []
    return data.get("data", [])


def build_adjustment_factors(dividend_records: list, price_records: list) -> dict:
    """
    根據除權除息記錄，建立「還原因子」對照表。

    邏輯：
      現金股利還原：今日收盤應 = 昨日收盤 - 現金股利
                    調整後收盤 = 原始收盤 + 累積股利
                    因子 = 調整後收盤 / 原始收盤

      因此：因子 = 1 + (今日之前所有現金股利之和) / 今日收盤
           還原收盤 = 原始收盤 * 因子

    實作方式（後視還原）：
      從最新價格往回走，維護一個累積調整因子。
      每經過一次除權息日，因子就往上跳一階。
    """
    if not dividend_records or not price_records:
        return {}

    # 建立 {date: cash_per_share} 的對照
    # 注意：台灣股利 = CashEarningsDistribution（盈餘配股/配息）
    #                  + CashStatutorySurplus（法定公積紅利）
    ex_dates = {}  # {ex_dividend_date: total_cash_per_share}
    for rec in dividend_records:
        cash_div    = rec.get("CashEarningsDistribution", 0) or 0
        stat_surp   = rec.get("CashStatutorySurplus", 0) or 0
        stock_div   = rec.get("StockEarningsDistribution", 0) or 0
        ex_date     = rec.get("CashExDividendTradingDate", "")  # 除權息交易日

        total_cash = (cash_div or 0) + (stat_surp or 0)

        if not ex_date or total_cash == 0:
            continue

        ex_dates[ex_date] = ex_dates.get(ex_date, 0.0) + total_cash

    # 從新到舊排列價格
    sorted_prices = sorted(price_records, key=lambda x: x["date"], reverse=True)

    # 由新到舊跑，維護累積已發股利
    cumulative_div = 0.0
    prev_date = None
    factors = {}  # {date: cumulative_div_at_that_date}

    for rec in sorted_prices:
        date = rec["date"]
        close = rec["close"]

        # 如果今日是除權息日，則從累積中扣除（因為股價已反應）
        if date in ex_dates:
            cumulative_div = cumulative_div + ex_dates[date]

        factors[date] = cumulative_div
        prev_date = date

    return factors, ex_dates


def compute_adjusted_prices(price_records: list, factors: dict) -> list:
    """
    根據還原因子，計算調整後價格。
    adjusted_close = raw_close + cumulative_dividend_at_date
    factor = 1 + cumulative_dividend / raw_close
    adjusted_close = raw_close * factor
    """
    adjusted = []
    for rec in price_records:
        date = rec["date"]
        raw_close = rec["close"]
        cumulative_div = factors.get(date, 0.0)

        if raw_close > 0:
            adj_close = raw_close + cumulative_div
            adj_factor = adj_close / raw_close
        else:
            adj_close = raw_close
            adj_factor = 1.0

        adjusted.append({
            "stock_id": rec["stock_id"],
            "date": date,
            "open": rec["open"],
            "high": rec["high"],
            "low": rec["low"],
            "close": raw_close,
            "adj_close": round(adj_close, 2),
            "adj_factor": round(adj_factor, 6),
            "volume": rec["volume"],
        })
    return adjusted


def save_adjusted_prices(stock_id: str, adjusted_records: list):
    """
    寫入 SQLite 的 adjusted_daily_price 資料表
    （若不存在則建立）
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 建立還原日K表（如果不存在）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adjusted_daily_price (
            stock_id      TEXT    NOT NULL,
            date          TEXT    NOT NULL,
            open          REAL    NOT NULL,
            high          REAL    NOT NULL,
            low           REAL    NOT NULL,
            close         REAL    NOT NULL,
            adj_close     REAL    NOT NULL,
            adj_factor    REAL    NOT NULL,
            volume        INTEGER NOT NULL,
            PRIMARY KEY (stock_id, date)
        )
    """)

    inserted = 0
    for r in adjusted_records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO adjusted_daily_price
                (stock_id, date, open, high, low, close, adj_close, adj_factor, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"], r["date"],
                r["open"], r["high"], r["low"],
                r["close"], r["adj_close"], r["adj_factor"], r["volume"],
            ))
            inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return inserted


def process_stock(stock_id: str, token: str) -> dict:
    """對單一股票進行還原處理"""
    # 抓除權息資料
    dividends = fetch_dividends(stock_id, token)
    if not dividends:
        print(f"  ⚠️ {stock_id} 無除權息資料")

    # 從資料庫讀取原始價格
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_id, date, open, high, low, close, volume
        FROM daily_price
        WHERE stock_id = ?
        ORDER BY date ASC
    """, (stock_id,))
    raw_prices = [dict(zip(["stock_id","date","open","high","low","close","volume"], r))
                  for r in cursor.fetchall()]
    conn.close()

    if not raw_prices:
        print(f"  ⚠️ {stock_id} 資料庫中無日K資料")
        return {"stock_id": stock_id, "status": "no_data"}

    # 建立還原因子
    factors, ex_dates = build_adjustment_factors(dividends, raw_prices)

    # 計算還原價格
    adjusted = compute_adjusted_prices(raw_prices, factors)

    # 寫入資料庫
    inserted = save_adjusted_prices(stock_id, adjusted)

    return {
        "stock_id": stock_id,
        "status": "ok",
        "dividend_events": len(ex_dates),
        "adjusted_count": inserted,
    }


def main():
    parser = argparse.ArgumentParser(description="價格還原引擎")
    parser.add_argument("--stock", type=str, help="股票代碼")
    parser.add_argument("--all", action="store_true", help="還原資料庫中所有股票")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token")
        sys.exit(1)

    if args.all:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT stock_id FROM daily_price")
        stocks = [r[0] for r in cursor.fetchall()]
        conn.close()
        print(f"📦 還原 {len(stocks)} 檔股票...")
    elif args.stock:
        stocks = [args.stock]
    else:
        print("用法：--stock 4967 或 --all")
        sys.exit(1)

    import time
    for i, sid in enumerate(stocks, 1):
        print(f"\n[{i}/{len(stocks)}] 處理 {sid}...")
        try:
            result = process_stock(sid, token)
            if result["status"] == "ok":
                print(f"  ✅ 完成：{result['dividend_events']} 筆除權息事件，{result['adjusted_count']} 筆還原價格入庫")
            else:
                print(f"  ⚠️ {result['status']}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ 錯誤：{e}")


if __name__ == "__main__":
    main()
