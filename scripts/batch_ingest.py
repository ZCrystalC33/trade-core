#!/usr/bin/env python3
"""
批次攝取腳本：一次攝取多檔股票的日K
用法：python3 batch_ingest.py 2330 2317 2454 3008 4967
"""

import os
import sys
import time
import sqlite3
import requests
import argparse
from pathlib import Path

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


def ingest_stock(stock_id: str, start_date: str, end_date: str, token: str) -> int:
    """單一股票日K攝取（寫入SQLite）"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        print(f"  ⚠️ {stock_id} API錯誤：{data.get('message')}")
        return 0

    records = data.get("data", [])
    if not records:
        print(f"  ⚠️ {stock_id} 無資料")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0

    for r in records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO daily_price
                (stock_id, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                r["stock_id"],
                r["date"],
                r["open"],
                r["max"],
                r["min"],
                r["close"],
                r["Trading_Volume"],
            ))
            inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批次日K攝取")
    parser.add_argument("--stocks", nargs="+", default=["2330","2317","2454","3008","4967"])
    parser.add_argument("--start", type=str, default="2025-01-01")
    parser.add_argument("--end", type=str, default="2026-04-20")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token，請設定 ~/.trade_core.env")
        sys.exit(1)

    print(f"📦 開始批次攝取 {len(args.stocks)} 檔股票...")
    print("=" * 50)

    total = 0
    for i, sid in enumerate(args.stocks, 1):
        try:
            cnt = ingest_stock(sid, args.start, args.end, token)
            print(f"  {i}. {sid} → {cnt} 筆 ✅")
            total += cnt
            if i < len(args.stocks):
                time.sleep(0.5)  # 避免API rate limit
        except Exception as e:
            print(f"  ⚠️ {sid} 錯誤：{e}")

    print("=" * 50)
    print(f"✅ 批次完成，共寫入 {total} 筆")
