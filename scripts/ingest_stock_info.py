#!/usr/bin/env python3
"""
 資料攝取模組 ⑤：個股基本資料（FinMind API）
 用法：python3 ingest_stock_info.py --stock 4967
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


def fetch_stock_info(stock_id: str, token: str) -> list:
    """從 FinMind 抓個股基本資料"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockInfo",
        "data_id": stock_id,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 抓取 {stock_id} 基本資料")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data.get('message')}")
    return data.get("data", [])


def fetch_per_pbr(stock_id: str, start_date: str, end_date: str, token: str) -> list:
    """抓 PER / PBR / 股息率"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockPER",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 抓取 {stock_id} PER/PBR")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        return []
    return data.get("data", [])


def save_stock_info(stock_id: str, info_records: list, per_records: list):
    """寫入 stock_info 資料表"""
    if not info_records:
        print("⚠️  無基本資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 取最新一筆基本資料
    latest = info_records[-1] if info_records else {}

    # 取最新一筆 PER/PBR
    latest_per = per_records[-1] if per_records else {}

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO stock_info
            (stock_id, name, industry, listed_date, capital, shares,
             par_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stock_id,
            latest.get("stock_name", ""),
            latest.get("industry_category", ""),
            latest.get("date", ""),           # 上市日期
            None,                              # 實收資本額（需另查）
            None,                              # 流通在外股數（需另查）
            10.0,                              # 面值預設10元
            updated_at,
        ))
        inserted = 1
    except Exception as e:
        print(f"⚠️ 寫入錯誤：{e}")
        inserted = 0

    conn.commit()
    conn.close()

    print(f"✅ 寫入 1 筆到 stock_info（{stock_id}）")
    if latest_per:
        print(f"   最新 PER={latest_per.get('PER')} | PBR={latest_per.get('PBR')} | 殖利率={latest_per.get('dividend_yield')}%")

    return inserted


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="個股基本資料攝取")
    parser.add_argument("--stock", type=str, default="4967")
    parser.add_argument("--start", type=str, default="2026-04-01")  # PER起始日
    parser.add_argument("--end", type=str, default="2026-04-20")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token，請設定 ~/.trade_core.env")
        sys.exit(1)

    try:
        info = fetch_stock_info(args.stock, token)
        per = fetch_per_pbr(args.stock, args.start, args.end, token)
        save_stock_info(args.stock, info, per)
        log(f"stock_info 完成：{args.stock}")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
