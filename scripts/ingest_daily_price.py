#!/usr/bin/env python3
"""
 Stephanie 量化系統
 資料攝取模組 ①：日K資料（FinMind API）
 
 用法：
   python3 ingest_daily_price.py --stock 4967 --start 2025-01-01 --end 2026-04-20
   python3 ingest_daily_price.py --stock 4967 --demo   # 使用模擬資料示範
"""

import os
import sys
import json
import sqlite3
import requests
import argparse
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
LOG_FILE = Path(__file__).parent.parent / "logs" / "data_ingest.log"

# FinMind API 設定
FINMIND_BASE = "https://api.finmindtrade.com/api/v4"


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


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_daily_price_api(stock_id: str, start_date: str, end_date: str, token: str) -> list:
    """從 FinMind API 抓取日K（GET 方式）"""
    url = f"{FINMIND_BASE}/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = {}

    print(f"📡 抓取 {stock_id} 日K：{start_date} ~ {end_date}")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data.get('message', data)}")

    return data.get("data", [])


def generate_demo_data(stock_id: str, start_date: str, end_date: str) -> list:
    """
    產生模擬日K資料（用於示範，無API key時）
    模擬十銓科技的價格走勢
    """
    print(f"⚠️  使用模擬資料模式（無API token）")

    # 解析日期
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # 模擬參數
    base_price = 150.0
    records = []
    current_price = base_price

    day = start
    while day <= end:
        if day.weekday() >= 5:  # 週末跳過
            day += timedelta(days=1)
            continue

        # 模擬波動
        change_pct = (hash(str(day.date())) % 100 - 50) / 500  # -10% ~ +10%
        open_price = current_price * (1 + change_pct)
        high_price = open_price * (1 + abs(change_pct) * 1.5)
        low_price = open_price * (1 - abs(change_pct) * 0.8)
        close_price = open_price * (1 + change_pct * 0.8)
        volume = 5000000 + hash(str(day.date())) % 10000000

        records.append({
            "stock_id": stock_id,
            "date": day.strftime("%Y-%m-%d"),
            "open": round(open_price, 2),
            "max": round(high_price, 2),
            "min": round(low_price, 2),
            "close": round(close_price, 2),
            "Trading_Volume": int(volume),
        })

        current_price = close_price
        day += timedelta(days=1)

    return records


def save_to_db(records: list) -> int:
    """寫入 SQLite daily_price"""
    if not records:
        print("⚠️  無資料可寫入")
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
                r["max"],     # high
                r["min"],     # low
                r["close"],
                r["Trading_Volume"],
            ))
            inserted += 1
        except Exception as e:
            pass  # 已存在就替換

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 daily_price")
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="日K資料攝取")
    parser.add_argument("--stock", type=str, help="股票代碼", default="4967")
    parser.add_argument("--start", type=str, help="起始日期 YYYY-MM-DD", default="2025-01-01")
    parser.add_argument("--end", type=str, help="結束日期 YYYY-MM-DD", default="2026-04-20")
    parser.add_argument("--token", type=str, help="FinMind API Token", default="")
    parser.add_argument("--demo", action="store_true", help="使用模擬資料（無需token）")
    args = parser.parse_args()

    try:
        if args.demo:
            records = generate_demo_data(args.stock, args.start, args.end)
        else:
            records = fetch_daily_price_api(args.stock, args.start, args.end, args.token)

        save_to_db(records)
        log(f"daily_price 完成：{args.stock}，共 {len(records)} 筆")

    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        print(f"\n提示：若無 FinMind API token，可加 --demo 參數使用模擬資料")
        print(f"  python3 ingest_daily_price.py --stock 4967 --demo")
        sys.exit(1)
