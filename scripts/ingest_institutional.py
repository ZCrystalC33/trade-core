#!/usr/bin/env python3
"""
 資料攝取模組 ②：三大法人買賣（FinMind API）
 用法：python3 ingest_institutional.py --stock 4967 --start 2025-01-01 --end 2026-04-20
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

# 嘗試從環境變數讀取 token
FINMIND_TOKEN = os.environ.get(
    "FINMIND_TOKEN",
    os.environ.get("TRADE_CORE_FINMIND_TOKEN", "")
)


def get_token() -> str:
    if FINMIND_TOKEN:
        return FINMIND_TOKEN
    token_file = Path.home() / ".trade_core.env"
    if token_file.exists():
        for line in token_file.read_text().splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def fetch_institutional(stock_id: str, start_date: str, end_date: str, token: str) -> list:
    """從 FinMind 抓三大法人買賣資料"""
    url = f"{FINMIND_API}/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 抓取 {stock_id} 法人資料：{start_date} ~ {end_date}")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        raise RuntimeError(f"FinMind API 錯誤：{data.get('message')}")
    return data.get("data", [])


def save_institutional(records: list):
    """寫入 institutional 資料表"""
    if not records:
        print("⚠️  無法人資料可寫入")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 依日期分組合併（不同法人加總）
    from collections import defaultdict
    grouped = defaultdict(lambda: {
        "foreign_buy": 0, "foreign_sell": 0,
        "prop_buy": 0, "prop_sell": 0,
        "dealer_buy": 0, "dealer_sell": 0,
    })
    for r in records:
        date = r["date"]
        name = r.get("name", "")
        buy = int(r.get("buy") or 0)
        sell = int(r.get("sell") or 0)

        if "Foreign" in name:
            grouped[date]["foreign_buy"] += buy
            grouped[date]["foreign_sell"] += sell
        elif "Prop" in name:
            grouped[date]["prop_buy"] += buy
            grouped[date]["prop_sell"] += sell
        elif "Dealer" in name or "自營" in name:
            grouped[date]["dealer_buy"] += buy
            grouped[date]["dealer_sell"] += sell

    inserted = 0
    for date, vals in grouped.items():
        net = ((vals["foreign_buy"] - vals["foreign_sell"])
               + (vals["prop_buy"] - vals["prop_sell"])
               + (vals["dealer_buy"] - vals["dealer_sell"]))
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO institutional
                (stock_id, date, foreign_buy, foreign_sell, prop_buy, prop_sell,
                 dealer_buy, dealer_sell, net_buy)
                VALUES ('4967', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date,
                  vals["foreign_buy"], vals["foreign_sell"],
                  vals["prop_buy"], vals["prop_sell"],
                  vals["dealer_buy"], vals["dealer_sell"],
                  net))
            inserted += 1
        except Exception as e:
            pass

    conn.commit()
    conn.close()
    print(f"✅ 寫入 {inserted} 筆到 institutional")
    return inserted


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="三大法人資料攝取")
    parser.add_argument("--stock", type=str, default="4967")
    parser.add_argument("--start", type=str, default="2025-01-01")
    parser.add_argument("--end", type=str, default="2026-04-20")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("⚠️  無 FinMind Token，使用 --demo 模式需要環境變數或 ~/.trade_core.env")
        sys.exit(1)

    try:
        records = fetch_institutional(args.stock, args.start, args.end, token)
        save_institutional(records)
        log(f"institutional 完成：{args.stock}，共 {len(records)} 筆")
    except Exception as e:
        log(f"錯誤：{e}", "ERROR")
        sys.exit(1)
