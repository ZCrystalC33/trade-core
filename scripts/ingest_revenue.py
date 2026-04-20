#!/usr/bin/env python3
"""
 資料攝取模組 ③：月營收資料（FinMind API）
 用法：python3 ingest_revenue.py --stock 4967 --start 2025-01
"""

import sys
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
FINMIND_API = "https://api.finmindtrade.com/api/v4"
LOG_FILE = Path(__file__).parent.parent / "logs" / "data_ingest.log"


def fetch_monthly_revenue(stock_id: str, start_month: str) -> list:
    """從 FinMind 抓月營收資料"""
    payload = {
        "dataset": "TaiwanStockMonthRevenue",
        "data": {
            "stock_id": stock_id,
            "start_date": start_month,
        },
        "token": "",
    }

    print(f"📡 抓取 {stock_id} 月營收：{start_month} ~")
    resp = requests.post(FINMIND_API, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data}")

    return data.get("data", [])


def save_revenue(records: list):
    """寫入 monthly_revenue 資料表"""
    if not records:
        print("⚠️  無營收資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    inserted = 0
    for r in records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO monthly_revenue
                (stock_id, revenue_month, revenue, yoy_change, mom_change)
                VALUES (?, ?, ?, ?, ?)
            """, (
                r["stock_id"],
                r["date"],          # 格式：YYYY-MM
                r["revenue"],        # 營收（千元 or 萬元，視API回傳）
                r.get("yoy_ratio"),  # 年增率（%）
                r.get("mom_ratio"),  # 月增率（%）
            ))
            inserted += 1
        except Exception as e:
            print(f"⚠️ 寫入錯誤：{e}")

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 monthly_revenue")
    return inserted


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="月營收資料攝取")
    parser.add_argument("--stock", type=str, default="4967")
    parser.add_argument("--start", type=str, default="2024-01")  # YYYY-MM
    args = parser.parse_args()

    try:
        records = fetch_monthly_revenue(args.stock, args.start)
        save_revenue(records)
        log(f"monthly_revenue 完成：{args.stock}，共 {len(records)} 筆")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
