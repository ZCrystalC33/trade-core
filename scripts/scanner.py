#!/usr/bin/env python3
"""
 Stephanie 量化系統
 股票掃描器（Scanner）
 用途：根據技術指標條件，自動篩選候選股票

 三層防護（解決全資料庫掃描效能問題）：
  1. 白名單制度 — 只掃 watchlist 內的股票
  2. 指標快取 — indicator_cache 表，直接讀取不重算
  3. Jin10 宏觀情緒 — 前置檢查，幫 Scanner 過濾
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import indicators_lib as il

try:
    import jin10_client as jc
    JIN10_AVAILABLE = True
except ImportError:
    JIN10_AVAILABLE = False
    jc = None

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
CACHE_VALID_DAYS = 1  # 指標快取有效天數


# ── 工具─────────────────────────────────────────────────────────

def get_watchlist_stocks(market: str = "TW") -> list:
    """
    讀取白名單（watchlist）中的股票代碼清單。
    如果 watchlist 為空，自動 fallback 回原本的追蹤標的。
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_id, name FROM watchlist
        WHERE active = 1 AND market = ?
        ORDER BY added_at ASC
    """, (market,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        # Fallback：讀 stock_info 表當作追蹤標的
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT stock_id, name FROM stock_info WHERE market = ? LIMIT 20", (market,))
        rows = cur.fetchall()
        conn.close()

    return [(r[0], r[1]) for r in rows]


def get_stocks_with_new_data(days: int = 30) -> list:
    """只回傳近N天有新增日K資料的股票（來自 watchlist）"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT w.stock_id, w.name
        FROM watchlist w
        JOIN daily_price dp ON dp.stock_id = w.stock_id
        WHERE dp.date >= date('now', ?)
          AND w.active = 1
        ORDER BY w.stock_id
    """, (f"-{days} days",))
    rows = cur.fetchall()
    conn.close()
    return rows


def _get_price_data(stock_id: str, days: int = 120) -> pd.DataFrame:
    """從資料庫讀取日K（pandas DataFrame，由舊到新）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT date, open, high, low, close, volume
        FROM daily_price
        WHERE stock_id = ?
        ORDER BY date ASC
        LIMIT ?
    """, (stock_id, days))
    rows = cur.fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def _compute_indicators(stock_id: str) -> dict | None:
    """計算指標並寫入快取表，回傳 indicators dict"""
    df = _get_price_data(stock_id, 120)
    if len(df) < 60:
        return None

    df = il.add_all_indicators(df)
    ind = il.latest_indicators(df)

    # 寫入快取 — numpy type 全部轉成 Python 原生型別再 JSON serialize
    def _to_native(obj):
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"unserializable: {type(obj)}")
    indicators_json = json.dumps(ind, default=_to_native)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO indicator_cache
        (stock_id, cached_at, close_at_cache, indicators_json, score, score_label)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        stock_id,
        datetime.now().strftime("%Y-%m-%d"),
        ind.get("close"),
        indicators_json,
        None, None  # score/score_label 由呼叫者填
    ))
    conn.commit()
    conn.close()

    ind["stock_id"] = stock_id
    ind["date"] = df["date"].iloc[-1]
    return ind


def get_cached_indicators(stock_id: str) -> dict | None:
    """
    從快取讀取指標，若快取已過期或不存在則回傳 None。
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT cached_at, indicators_json, close_at_cache
        FROM indicator_cache
        WHERE stock_id = ?
    """, (stock_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    cached_at_str, indicators_json, close_at_cache = row
    cached_at = datetime.strptime(cached_at_str, "%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    # 當日快取仍有效
    if cached_at_str == today:
        ind = json.loads(indicators_json)
        ind["stock_id"] = stock_id
        ind["date"] = cached_at_str
        ind["close"] = close_at_cache
        return ind

    # 快取已過期
    return None


def get_indicators(stock_id: str) -> dict | None:
    """
    拿到乾淨指標（快取優先，沒有就算）。
    """
    ind = get_cached_indicators(stock_id)
    if ind is not None:
        return ind
    return _compute_indicators(stock_id)


# ── 訊號判定─────────────────────────────────────────────────────

def detect_signals(ind: dict) -> dict:
    """根據指標 dict 判斷訊號，回傳 {signal_type: description}"""
    signals = {}
    k, d = ind.get("K"), ind.get("D")
    dif, dea = ind.get("DIF"), ind.get("DEA")
    macd_bar = ind.get("MACD_Bar")
    ma5 = ind.get("MA5")
    ma20 = ind.get("MA20")
    ma60 = ind.get("MA60")
    close = ind.get("close")
    vol = ind.get("volume")
    vol5_ma = ind.get("Vol_MA5")

    if k is not None and d is not None:
        if k > d and k < 30:
            signals["KD_GOLD_CROSS_LOW"] = "KD低檔黃金交叉"
        elif k > d:
            signals["KD_GOLD_CROSS"] = "KD黃金交叉"
        elif k < d and k > 70:
            signals["KD_DEATH_CROSS_HIGH"] = "KD高檔死亡交叉"
        elif k < d:
            signals["KD_DEATH_CROSS"] = "KD死亡交叉"

    if dif is not None and dea is not None:
        if dif > dea:
            signals["MACD_BULL"] = "MACD多頭"
        else:
            signals["MACD_BEAR"] = "MACD空頭"

    if macd_bar is not None:
        if macd_bar > 0:
            signals["MACD_BAR_POS"] = "MACD柱狀圖正值"
        else:
            signals["MACD_BAR_NEG"] = "MACD柱狀圖負值"

    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            signals["MA_BULL"] = "均線多頭排列"
        elif ma5 < ma20 < ma60:
            signals["MA_BEAR"] = "均線空頭排列"

    if vol5_ma and vol and close and ma5:
        if vol > vol5_ma * 1.8 and close > ma5:
            signals["VOL_SPIKE"] = "量能暴增（>1.8倍均量）"

    return signals


# ── Scanner（白名單 + 快取導向）─────────────────────────────────

def scan_kd_gold_cross(market: str = "TW", min_k: float = 20, max_k: float = 80) -> list:
    """KD 低檔黃金交叉（只看 watchlist）"""
    watchlist = get_watchlist_stocks(market)
    candidates = []

    for sid, _ in watchlist:
        ind = get_indicators(sid)
        if ind is None:
            continue
        k, d = ind.get("K"), ind.get("D")
        if k is not None and d is not None and k > d and min_k < k < max_k:
            candidates.append({
                "stock_id": sid,
                "close": ind.get("close"),
                "K": round(k, 2),
                "D": round(d, 2),
                "date": ind.get("date"),
            })

    candidates.sort(key=lambda x: x["K"], reverse=True)
    return candidates


def scan_macd_bull(market: str = "TW") -> list:
    """MACD 多頭（只看 watchlist）"""
    watchlist = get_watchlist_stocks(market)
    candidates = []

    for sid, _ in watchlist:
        ind = get_indicators(sid)
        if ind is None:
            continue
        dif, dea = ind.get("DIF"), ind.get("DEA")
        macd_bar = ind.get("MACD_Bar")
        if dif is not None and dea is not None and macd_bar is not None:
            if dif > dea and macd_bar > 0:
                candidates.append({
                    "stock_id": sid,
                    "close": ind.get("close"),
                    "DIF": round(dif, 4),
                    "DEA": round(dea, 4),
                    "MACD_Bar": round(macd_bar, 4),
                    "date": ind.get("date"),
                })

    candidates.sort(key=lambda x: x["DIF"], reverse=True)
    return candidates


def scan_ma_bull(market: str = "TW") -> list:
    """均線多頭排列（只看 watchlist）"""
    watchlist = get_watchlist_stocks(market)
    candidates = []

    for sid, _ in watchlist:
        ind = get_indicators(sid)
        if ind is None:
            continue
        ma5, ma20, ma60 = ind.get("MA5"), ind.get("MA20"), ind.get("MA60")
        if all(x is not None for x in [ma5, ma20, ma60]):
            if ma5 > ma20 > ma60:
                candidates.append({
                    "stock_id": sid,
                    "close": ind.get("close"),
                    "MA5": round(ma5, 2),
                    "MA20": round(ma20, 2),
                    "MA60": round(ma60, 2),
                    "date": ind.get("date"),
                })

    candidates.sort(key=lambda x: x["close"], reverse=True)
    return candidates


def scan_vol_spike(market: str = "TW", threshold: float = 1.8) -> list:
    """量能暴增（只看 watchlist）"""
    watchlist = get_watchlist_stocks(market)
    candidates = []

    for sid, _ in watchlist:
        ind = get_indicators(sid)
        if ind is None:
            continue
        vol = ind.get("volume")
        vol5_ma = ind.get("Vol_MA5")
        if vol5_ma and vol and vol > vol5_ma * threshold:
            candidates.append({
                "stock_id": sid,
                "close": ind.get("close"),
                "volume": vol,
                "vol_5ma": round(vol5_ma, 0),
                "vol_ratio": round(vol / vol5_ma, 2),
                "date": ind.get("date"),
            })

    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return candidates


def run_all_scans(market: str = "TW") -> dict:
    """一口氣跑所有掃描（白名單版）"""
    watchlist = get_watchlist_stocks(market)
    print(f"🔍 Stephanie 掃描器（白名單模式）")
    print(f"   監控中：{len(watchlist)} 檔 | 市場：{market}")
    print("=" * 50)

    # ── 宏觀前置檢查 ────────────────────────────────────
    if JIN10_AVAILABLE:
        try:
            macro_score = jc.get_macro_sentiment()
            macro_flag = jc.check_macro_threshold(macro_score)
            print(f"\n🌐 宏觀情緒：{macro_score:.1f}/100  [{macro_flag}]")
            alert = jc.check_macro_alerts()
            if alert:
                print(f"  📢 {alert}")
        except Exception:
            macro_flag = "N/A"
            print("\n⚠️  宏觀數據取得失敗（使用預設值）")
    else:
        macro_flag = "N/A"
        print("\n⚠️  Jin10 未啟用")

    results = {}

    print("\n📌 KD 低檔黃金交叉")
    print("-" * 40)
    kd = scan_kd_gold_cross(market)
    results["kd_gold_cross"] = kd
    if kd:
        for i, c in enumerate(kd, 1):
            print(f"  {i}. {c['stock_id']} 收{c['close']} | K={c['K']:.1f} D={c['D']:.1f}")
    else:
        print("  （無）")

    print("\n📌 MACD 多頭")
    print("-" * 40)
    macd = scan_macd_bull(market)
    results["macd_bull"] = macd
    if macd:
        for i, c in enumerate(macd, 1):
            print(f"  {i}. {c['stock_id']} 收{c['close']} | DIF={c['DIF']:.4f} DEA={c['DEA']:.4f}")
    else:
        print("  （無）")

    print("\n📌 均線多頭排列")
    print("-" * 40)
    ma = scan_ma_bull(market)
    results["ma_bull"] = ma
    if ma:
        for i, c in enumerate(ma, 1):
            print(f"  {i}. {c['stock_id']} 收{c['close']} | {c['MA5']:.1f}>{c['MA20']:.1f}>{c['MA60']:.1f}")
    else:
        print("  （無）")

    print("\n📌 量能暴增（>1.8倍）")
    print("-" * 40)
    vol = scan_vol_spike(market)
    results["volume_surge"] = vol
    if vol:
        for i, c in enumerate(vol, 1):
            print(f"  {i}. {c['stock_id']} 收{c['close']} | 量比{c['vol_ratio']:.1f}x")
    else:
        print("  （無）")

    print(f"\n{'='*50}")
    print(f"✅ 完成 | 白名單 {len(watchlist)} 檔")
    return results


# ── Watchlist 管理───────────────────────────────────────────────

def add_to_watchlist(stock_id: str, name: str = None, market: str = "TW", notes: str = ""):
    """新增股票到白名單"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO watchlist (stock_id, name, market, notes, added_at, active)
        VALUES (?, ?, ?, ?, datetime('now'), 1)
    """, (stock_id, name or stock_id, market, notes))
    conn.commit()
    conn.close()


def remove_from_watchlist(stock_id: str):
    """從白名單移除（軟刪除）"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE watchlist SET active = 0 WHERE stock_id = ?", (stock_id,))
    conn.commit()
    conn.close()


def list_watchlist(market: str = "TW") -> list:
    """列出白名單"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_id, name, market, notes, added_at
        FROM watchlist WHERE active = 1 AND market = ?
        ORDER BY added_at
    """, (market,))
    rows = cur.fetchall()
    conn.close()
    cols = ["stock_id","name","market","notes","added_at"]
    return [dict(zip(cols, r)) for r in rows]


def init_default_watchlist():
    """寫入預設追蹤標的"""
    defaults = [
        ("4967", "十銓",   "TW", "記憶體模組"),
        ("2330", "台積電", "TW", "晶圓代工"),
        ("2317", "鴻海",   "TW", "代工/AI供應鏈"),
        ("2454", "聯發科", "TW", "IC設計"),
        ("3008", "大立光", "TW", "光學鏡頭"),
    ]
    for sid, name, market, notes in defaults:
        add_to_watchlist(sid, name, market, notes)
    print(f"✅ 預設白名單寫入完成（{len(defaults)} 檔）")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--add":
            add_to_watchlist(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        elif cmd == "--remove":
            remove_from_watchlist(sys.argv[2])
        elif cmd == "--list":
            for w in list_watchlist():
                print(f"  {w['stock_id']} {w['name']} ({w['notes']})")
        elif cmd == "--init-watchlist":
            init_default_watchlist()
        elif cmd == "--scan":
            run_all_scans(sys.argv[2] if len(sys.argv) > 2 else "TW")
        else:
            print(f"未知指令：{cmd}")
    else:
        run_all_scans()
