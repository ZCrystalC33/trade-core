#!/usr/bin/env python3
"""
 加密貨幣資料攝取模組
 資料來源：CoinGecko API（免費，無需 API Key）

 支援：
  - 主流幣種現貨日K（比特幣、以太坊、Solana、XRP等）
  - 即時報價 + 24h 漲跌
  - 歷史走勢

 使用方式：
   python3 ingest_crypto.py --add bitcoin ethereum solana
   python3 ingest_crypto.py --add ALL         # 抓所有支援的主流幣
   python3 ingest_crypto.py --price            # 抓最新報價
"""

import os
import sys
import sqlite3
import requests
import argparse
import time
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
CG_BASE = "https://api.coingecko.com/api/v3"

# 常用幣種對照表（id → symbol）
SUPPORTED_COINS = {
    "bitcoin":          "BTC",
    "ethereum":         "ETH",
    "solana":           "SOL",
    "ripple":           "XRP",
    "cardano":          "ADA",
    "dogecoin":         "DOGE",
    "polkadot":         "DOT",
    "chainlink":        "LINK",
    "polygon":          "MATIC",
    "avalanche-2":      "AVAX",
    "uniswap":          "UNI",
    "litecoin":         "LTC",
    "cosmos":           "ATOM",
    "stellar":          "XLM",
    "near":             "NEAR",
    "aptos":            "APT",
    "arbitrum":         "ARB",
    "optimism":         "OP",
    "sui":              "SUI",
    "solana":           "SOL",
}


# ── 資料表設定 ─────────────────────────────────────────

CRYPTO_TABLES = {
    "crypto_daily_price": """
        CREATE TABLE IF NOT EXISTS crypto_daily_price (
            coin_id     TEXT    NOT NULL,
            symbol      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            market_cap  REAL,
            PRIMARY KEY (coin_id, date)
        )
    """,
    "crypto_realtime": """
        CREATE TABLE IF NOT EXISTS crypto_realtime (
            coin_id     TEXT    PRIMARY KEY,
            symbol      TEXT,
            name        TEXT,
            price_usd   REAL,
            price_btc   REAL,
            change_24h  REAL,
            change_7d  REAL,
            volume_24h  INTEGER,
            market_cap  INTEGER,
            updated_at  TEXT
        )
    """,
}


def ensure_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for sql in CRYPTO_TABLES.values():
        cursor.execute(sql)
    conn.commit()
    conn.close()


# ── CoinGecko API 工具 ─────────────────────────────────

def cg_get(endpoint: str, params: dict = None) -> dict:
    """發送 CoinGecko GET 請求"""
    url = f"{CG_BASE}/{endpoint}"
    r = requests.get(url, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_coin_list() -> dict:
    """取得所有可用幣種 ID 清單"""
    cache_file = Path(DB_PATH).parent / "crypto_coin_list.json"
    if cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age.days < 7:  # 7天內cache有效
            import json
            return json.loads(cache_file.read_text())

    coins = cg_get("coins/list")
    result = {}
    for c in coins:
        result[c["id"]] = {"symbol": c["symbol"].upper(), "name": c.get("name", "")}

    import json
    cache_file.write_text(json.dumps(result))
    return result


# ── 即時報價 ─────────────────────────────────────────────

def fetch_realtime_prices(coin_ids: list) -> list:
    """一次抓多幣即時報價"""
    if not coin_ids:
        return []
    ids_str = ",".join(coin_ids)
    data = cg_get("coins/markets", {
        "vs_currency": "usd",
        "ids": ids_str,
        "order": "market_cap_desc",
        "per_page": 100,
        "sparkline": "false",
        "price_change_percentage": "24h,7d",
    })
    return data


def save_realtime_prices(data: list):
    """寫入 crypto_realtime 表"""
    if not data:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    for coin in data:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO crypto_realtime
                (coin_id, symbol, name, price_usd, price_btc, change_24h,
                 change_7d, volume_24h, market_cap, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                coin.get("id"),
                coin.get("symbol", "").upper(),
                coin.get("name", ""),
                coin.get("current_price"),
                None,  # price_btc（可另外抓）
                coin.get("price_change_percentage_24h"),
                coin.get("price_change_percentage_7d"),
                coin.get("total_volume"),
                coin.get("market_cap"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
            inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return inserted


# ── 歷史日K ─────────────────────────────────────────────

def fetch_coin_history(coin_id: str, days: int = 365) -> list:
    """抓取幣種歷史日K"""
    try:
        data = cg_get(f"coins/{coin_id}/market_chart", {
            "vs_currency": "usd",
            "days": days,
        })
        prices = data.get("prices", [])
        volumes = {v[0]: v[1] for v in data.get("volumes", [])}

        records = []
        for price in prices:
            ts_ms, price_val = price
            dt = datetime.fromtimestamp(ts_ms / 1000)
            records.append({
                "coin_id":  coin_id,
                "date":     dt.strftime("%Y-%m-%d"),
                "price":    price_val,
                "volume":   volumes.get(ts_ms, 0),
            })
        return records
    except Exception as e:
        print(f"  ⚠️ {coin_id} history error: {e}")
        return []


def compute_ohlc(records: list) -> list:
    """把每日的價格陣列轉成 OHLC"""
    from collections import defaultdict
    by_date = defaultdict(list)
    for r in records:
        by_date[r["date"]].append(r["price"])

    ohlc = []
    for date in sorted(by_date.keys()):
        prices = by_date[date]
        ohlc.append({
            "date":   date,
            "open":   prices[0],
            "high":   max(prices),
            "low":    min(prices),
            "close":  prices[-1],
            "volume": 0,  # CoinGecko 日K無精確成交量，用總量代替
        })
    return ohlc


def save_crypto_daily(coin_id: str, symbol: str, ohlc_records: list) -> int:
    if not ohlc_records:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    for r in ohlc_records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO crypto_daily_price
                (coin_id, symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (coin_id, symbol, r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
            inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return inserted


# ── 主程式 ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="加密貨幣資料攝取")
    parser.add_argument("--add", nargs="+", help="新增幣種（如：bitcoin ethereum solana）")
    parser.add_argument("--add-all", action="store_true", help="新增所有主流幣")
    parser.add_argument("--price", action="store_true", help="只抓最新報價")
    parser.add_argument("--days", type=int, default=365, help="歷史天數（預設365）")
    args = parser.parse_args()

    ensure_tables()

    # ── 只抓即時報價 ─────────────────────────────────
    if args.price:
        coins = list(SUPPORTED_COINS.keys())
        print(f"📡 抓取 {len(coins)} 種加密幣即時報價...")
        data = fetch_realtime_prices(coins)
        saved = save_realtime_prices(data)
        print(f"✅ 寫入 {saved} 筆即時報價")
        for coin in (data or [])[:10]:
            chg = coin.get("price_change_percentage_24h", 0) or 0
            print(f"  {coin.get('symbol'):<6} ${coin.get('current_price'):>12,.2f}  24h {chg:+.2f}%")
        return

    # ── 處理新增幣種 ─────────────────────────────────
    if args.add_all:
        coin_ids = list(SUPPORTED_COINS.keys())
    elif args.add:
        coin_ids = args.add
    else:
        print("用法：")
        print("  --price              抓即時報價")
        print("  --add bitcoin ethereum solana   新增特定幣種")
        print("  --add-all            新增所有主流幣")
        sys.exit(0)

    print(f"📦 攝取 {len(coin_ids)} 種加密幣...")

    # 先抓即時報價
    print("📡 更新即時報價...")
    rt_data = fetch_realtime_prices(coin_ids)
    saved_rt = save_realtime_prices(rt_data)
    print(f"  ✅ 即時報價 {saved_rt} 筆")

    # 再抓歷史日K
    total_ohlc = 0
    for i, cid in enumerate(coin_ids, 1):
        print(f"\n[{i}/{len(coin_ids)}] {cid}：抓取歷史日K（{args.days}天）...")
        raw = fetch_coin_history(cid, args.days)
        if not raw:
            print(f"  ⚠️ 無歷史資料")
            continue
        ohlc = compute_ohlc(raw)
        symbol = SUPPORTED_COINS.get(cid, cid.upper())
        saved = save_crypto_daily(cid, symbol, ohlc)
        print(f"  ✅ {len(ohlc)} 筆 OHLC 寫入")
        total_ohlc += saved
        time.sleep(0.5)  # CoinGecko 免費方案有 rate limit

    print(f"\n✅ 完成：即時報價 {saved_rt} 筆 / 日K {total_ohlc} 筆")


if __name__ == "__main__":
    main()
