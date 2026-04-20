#!/usr/bin/env python3
"""
 資料攝取模組 ③：月營收資料（FinMind API）
 用法：python3 ingest_revenue.py --stock 4967 --start 2024-01
"""

import os
import sys
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
LOG_FILE = Path(__file__).parent.parent / "logs" / "data_ingest.log"
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


def fetch_monthly_revenue(stock_id: str, start_date: str, token: str) -> list:
    """從 FinMind 抓月營收資料"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": stock_id,
        "start_date": start_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 抓取 {stock_id} 月營收：{start_date} ~")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data.get('message')}")
    return data.get("data", [])


def save_revenue(records: list, stock_id: str):
    """寫入 monthly_revenue 資料表"""
    if not records:
        print("⚠️  無營收資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0

    for r in records:
        # revenue_month 格式：YYYY-MM（由 date 欄位而來）
        rev_date = r.get("date", "")  # 格式：2025-01-01
        revenue_month = rev_date[:7] if len(rev_date) >= 7 else rev_date
        revenue = r.get("revenue", 0) or 0
        # 年月重疊於 revenue_year / revenue_month 欄位
        yoy = r.get("yoy_ratio")  # FinMind 可能有的年增率欄位
        mom = r.get("mom_ratio")  # FinMind 可能有的月增率欄位

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO monthly_revenue
                (stock_id, revenue_month, revenue, yoy_change, mom_change)
                VALUES (?, ?, ?, ?, ?)
            """, (stock_id, revenue_month, revenue, yoy, mom))
            inserted += 1
        except Exception as e:
            pass

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
    parser.add_argument("--start", type=str, default="2024-01-01")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token，請設定環境變數或 ~/.trade_core.env")
        sys.exit(1)

    try:
        records = fetch_monthly_revenue(args.stock, args.start, token)
        save_revenue(records, args.stock)
        log(f"monthly_revenue 完成：{args.stock}，共 {len(records)} 筆")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
