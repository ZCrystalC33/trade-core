#!/usr/bin/env python3
"""
daily_top30.py - 每日 Top30 推薦評分系統

維度設計（已移除不可靠的 PE/PB 和 YoY）：
  動能     25%：近20日價格漲幅 Percentile
  技術面   25%：KD + MACD 黃金交叉比率（近20日）
  資金流   20%：三大法人買賣超 Percentile（近5日）
  流動性   10%：日均成交量 Percentile
  穩健性    5%：20日價格波動率（越低越好）
  槓桿      5%：融資餘額/成交金額（越低越好）
  產業      5%：vs 產業平均動能

DB: /home/snow/trade-core/data/stock_quant.db
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

# ── 維度權重 ───────────────────────────────────────────
WEIGHTS = {
    "momentum":   0.25,
    "technical":  0.25,
    "fund_flow":  0.20,
    "liquidity":  0.10,
    "volatility": 0.05,
    "leverage":   0.05,
    "industry":   0.05,
}

# ── DB helper ────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_stocks():
    """取真實股票（排除類指數）"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT d.stock_id
        FROM daily_price d
        JOIN stock_info s ON d.stock_id = s.stock_id
        WHERE s.name NOT LIKE '%類指數'
          AND s.name NOT LIKE '%類ETF%'
          AND d.stock_id NOT IN ('ChemicalBiotechnologyMedicalCare', 'TradingConsumersGoods')
        ORDER BY d.stock_id
    """)
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_price_data(stock_id, days=30):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, close, volume
        FROM daily_price
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, days))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    rows.reverse()  # 舊→新
    return rows


def fetch_adjusted_price_data(stock_id, days=60):
    """取近 N 日還原價格（adj_close），用於動能和技術面計算
    Note: 預設取 60 天，確保有足夠 warmup 資料（MACD 需要 ~35 天）"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, adj_close as close, volume
        FROM adjusted_daily_price
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, days))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if rows:
        rows.reverse()  # 舊→新
        return rows
    # 無還原價格時 fallback 到原始價格（不建議用於動能計算）
    import logging
    logging.warning(f"No adjusted price for {stock_id}, using raw close")
    return fetch_price_data(stock_id, days)


def fetch_monthly_revenue(stock_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT revenue_month, revenue, yoy_change
        FROM monthly_revenue
        WHERE stock_id = ?
        ORDER BY revenue_month DESC
        LIMIT 2
    """, (stock_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_institutional(stock_id, days=5):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, net_buy
        FROM institutional
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, days))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    rows.reverse()
    return rows


# ── 技術指標 helper（純 Python） ─────────────────────

def _calc_kd(closes, n=9):
    """計算 KD 值（RSV → K → D）"""
    if len(closes) < n + 1:
        return []
    k_vals, d_vals = [], []
    for i in range(n - 1, len(closes)):
        low_n = min(closes[max(0, i - n + 1):i + 1])
        high_n = max(closes[max(0, i - n + 1):i + 1])
        rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if high_n > low_n else 50
        k = 0.5 * (k_vals[-1] if k_vals else 50) + 0.5 * rsv
        d = 0.5 * (d_vals[-1] if d_vals else 50) + 0.5 * k
        k_vals.append(k)
        d_vals.append(d)
    return list(zip(k_vals, d_vals))


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """計算 MACD（DIF, DEA, Bar）"""
    if len(closes) < slow + signal:
        return []
    # EMA
    def ema(arr, period):
        k = 2 / (period + 1)
        result = [arr[0]]
        for v in arr[1:]:
            result.append(result[-1] * (1 - k) + v * k)
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    bar = [2 * (d - de) for d, de in zip(dif, dea)]
    return list(zip(dif[len(dif) - len(dea):], dea, bar))


def _pct_bullish(closes, n=20):
    """
    計算近 n 日技術面多頭訊號比率
    - KD 黃金交叉：K 從下穿越 D，且 K < 80
    - MACD 多頭：DIF > DEA 且兩者都在零軸以上
    回傳 (0~1) 的多頭比率
    """
    if len(closes) < n + 26:
        return 0.5  # 資料不足給中性

    # 取近 n 日
    recent = closes[-n:]

    # KD 信號
    kd_pairs = _calc_kd(recent)
    kd_bull = 0
    for i in range(1, len(kd_pairs)):
        k_prev, d_prev = kd_pairs[i - 1]
        k_cur, d_cur = kd_pairs[i]
        if k_prev < d_prev and k_cur > d_cur and k_cur < 80:
            kd_bull += 1

    # MACD 信號
    macd_vals = _calc_macd(recent)
    macd_bull = 0
    for i in range(1, len(macd_vals)):
        dif_prev, dea_prev, _ = macd_vals[i - 1]
        dif_cur, dea_cur, bar_cur = macd_vals[i]
        if dif_cur > dea_cur and dif_prev <= dea_prev and bar_cur > 0:
            macd_bull += 1

    total = len(kd_pairs) + len(macd_vals)
    if total == 0:
        return 0.5
    return (kd_bull + macd_bull) / total


# ── Percentile helper ────────────────────────────────

def _percentile_score(raw_values: dict) -> dict:
    """
    將一堆 {stock_id: raw_value} 轉成 Percentile 分數（0-100）
    越高分越好（波動性除外，會另外處理）
    """
    values = list(raw_values.values())
    mn, mx = min(values), max(values)
    result = {}
    for sid, val in raw_values.items():
        if mx == mn:
            result[sid] = 50
        else:
            result[sid] = round((val - mn) / (mx - mn) * 100, 2)
    return result


# ── 各維度評分工廠（單股票不回傳分數，回傳 raw 值供全量排名）──

def calc_momentum_raw(stocks: list) -> dict:
    """
    動能 raw：近20日每日收益率加總 Percentile
    用 raw close 計算，只看相對排名，不依賴還原價格
    每日收益率 = (今日收盤 - 昨日收盤) / 昨日收盤
    取 20日加總後 Percentile 排名
    """
    import statistics
    result = {}
    for sid in stocks:
        data = fetch_price_data(sid, days=20)
        if len(data) < 5:
            result[sid] = 0
            continue
        closes = [d["close"] for d in data]
        # 計算每日收益率，並Winsorize至±20%防止股票分割outlier
        daily_returns = []
        for i in range(1, len(closes)):
            if closes[i-1] and closes[i-1] > 0:
                ret = (closes[i] - closes[i-1]) / closes[i-1]
                ret = max(-0.20, min(0.20, ret))  # Winsorize ±20%
                daily_returns.append(ret)
        if len(daily_returns) < 3:
            result[sid] = 0
            continue
        # 20日加總收益率
        total_ret = sum(daily_returns)
        result[sid] = total_ret
    return result


def calc_technical_raw(stocks: list) -> dict:
    """技術面 raw：多頭訊號比率（0~1）"""
    result = {}
    for sid in stocks:
        data = fetch_adjusted_price_data(sid, days=50)  # 需要多一點歷史算 KD/MACD
        if len(data) < 30:
            result[sid] = 0
            continue
        closes = [d["close"] for d in data]
        result[sid] = _pct_bullish(closes)
    return result


def calc_growth_raw(stocks: list) -> dict:
    """成長 raw：月營收 YoY %（取最新月份）"""
    result = {}
    for sid in stocks:
        rev_data = fetch_monthly_revenue(sid)
        if not rev_data:
            result[sid] = 0
            continue
        yoy = rev_data[0].get("yoy_change", 0) or 0
        result[sid] = yoy
    return result


def calc_value_raw(stocks: list) -> dict:
    """
    價值 raw：PE + PB 評分（來自 Yahoo Finance）
    PE：越低越好（5~30 → 100~0）
    PB：越低越好（< 1 → 100, > 5 → 0）
    有資料的股票：算完平均後 Percentile
    無資料的股票：50（中性）
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT stock_id, pe, pb FROM yahoo_metrics")
    raw_data = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    conn.close()

    # 先算每檔的分數（PE + PB 平均）
    scores = {}
    for sid, (pe, pb) in raw_data.items():
        pe_score = 50
        pb_score = 50
        if pe and pe > 0:
            pe_score = max(0, min(100, round((30 - pe) / 25 * 100, 2)))
        if pb and pb > 0:
            pb_score = max(0, min(100, round((5 - pb) / 4 * 100, 2)))
        scores[sid] = (pe_score + pb_score) / 2

    # Percentile
    vals = list(scores.values())
    if not vals:
        return {sid: 50 for sid in stocks}
    mn, mx = min(vals), max(vals)
    result = {}
    for sid in stocks:
        if sid not in scores:
            result[sid] = 50.0
        elif mx == mn:
            result[sid] = 50.0
        else:
            result[sid] = round((scores[sid] - mn) / (mx - mn) * 100, 2)
    return result


def calc_fund_flow_raw(stocks: list) -> dict:
    """
    資金流 raw：近5日法人淨買超張數
    Percentile 排名（無資料的股票給 50）
    """
    # 先一次性抓所有股票的近5日淨買超
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_id, SUM(net_buy) as total_net
        FROM institutional
        WHERE date >= date('now', '-5 days')
        GROUP BY stock_id
    """)
    flow_raw = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    # Percentile：取有資料的全部股票計算 mn/mx
    vals = list(flow_raw.values())
    mn, mx = min(vals), max(vals)

    result = {}
    for sid in stocks:
        net = flow_raw.get(sid)
        if net is None:
            result[sid] = 50.0  # 無資料 → 中性
            continue
        if mx == mn:
            result[sid] = 50.0
        else:
            result[sid] = round((net - mn) / (mx - mn) * 100, 2)
    return result


def calc_liquidity_raw(stocks: list) -> dict:
    """流動性 raw：近20日均成交量"""
    result = {}
    for sid in stocks:
        data = fetch_adjusted_price_data(sid, days=20)
        if not data:
            result[sid] = 0
            continue
        avg_vol = sum(d.get("volume", 0) for d in data) / len(data)
        result[sid] = avg_vol
    return result


def calc_volatility_raw(stocks: list) -> dict:
    """穩健性 raw：20日收盤價標準差（越低越好）"""
    import statistics
    result = {}
    for sid in stocks:
        data = fetch_price_data(sid, days=20)
        if len(data) < 10:
            result[sid] = 999  # 預設高分（當異常值）
            continue
        closes = [d["close"] for d in data]
        # 變異係數（Coefficient of Variation）更公平
        mean = statistics.mean(closes)
        std = statistics.stdev(closes) if len(closes) > 1 else 0
        cv = std / mean if mean > 0 else 0
        result[sid] = cv  # CV 越低 = 波動越小 = 分數越高
    return result


def calc_leverage_raw(stocks: list) -> dict:
    """
    槓桿利用率 raw：近30日平均融資餘額 / 近30日平均成交金額
    比率越高 → 散戶槓桿越高 → 風險高 → 分數低
    """
    conn = get_conn()
    cur = conn.cursor()

    # 取最新 margin_date 往前30天
    cur.execute("SELECT MAX(date) FROM margin_short")
    latest_margin_date = cur.fetchone()[0] or "2020-01-01"

    # 一次性抓所有股票的 margin + 近30日平均成交量
    cur.execute("""
        SELECT m.stock_id, m.margin_balance,
               (SELECT AVG(volume) FROM daily_price
                WHERE stock_id = m.stock_id AND date >= date(m.date, '-30 days')) as avg_vol
        FROM margin_short m
        WHERE m.date = ?
    """, (latest_margin_date,))

    raw = {}
    for row in cur.fetchall():
        sid, margin_bal, avg_vol = row
        if avg_vol and avg_vol > 0:
            ratio = margin_bal / avg_vol
            raw[sid] = ratio
        else:
            raw[sid] = 0
    conn.close()

    # Percentile（越高分數越低，因為高槓桿 = 高風險）
    vals = list(raw.values())
    mn, mx = min(vals), max(vals)
    result = {}
    for sid in stocks:
        v = raw.get(sid)
        if v is None:
            result[sid] = 50.0
        elif mx == mn:
            result[sid] = 50.0
        else:
            result[sid] = 100 - round((v - mn) / (mx - mn) * 100, 2)
    return result


def calc_industry_raw(stocks: list) -> dict:
    """
    產業相對動能 raw：該股票 20日漲幅 vs 產業平均漲幅
    產業分類使用 Yahoo Finance sector，贏過產業平均越多 → 分數越高
    """
    conn = get_conn()
    cur = conn.cursor()

    # 一次性抓 Yahoo Finance 產業分類
    cur.execute("SELECT stock_id, sector FROM yahoo_metrics WHERE sector IS NOT NULL")
    yf_sectors = {row[0]: row[1] for row in cur.fetchall()}

    # 一次性抓所有股票的 stock_id + industry（stock_info fallback）
    cur.execute("SELECT stock_id, industry FROM stock_info WHERE industry IS NOT NULL AND industry != ''")
    si_industry = {row[0]: row[1] for row in cur.fetchall()}

    # 一次性抓所有股票的20日動能
    cur.execute("""
        SELECT stock_id,
               (SELECT close FROM daily_price WHERE stock_id = d.stock_id ORDER BY date DESC LIMIT 1) as latest_close,
               (SELECT close FROM daily_price WHERE stock_id = d.stock_id ORDER BY date DESC LIMIT 20 OFFSET 19) as old_close
        FROM daily_price d
        GROUP BY d.stock_id
    """)

    raw = {}
    industry_momentum = {}
    for row in cur.fetchall():
        sid, latest, old = row
        if latest and old and old > 0:
            pct = (latest - old) / old * 100
        else:
            pct = 0
        raw[sid] = pct
        # Yahoo Finance sector 優先，否則用 stock_info
        ind = yf_sectors.get(sid) or si_industry.get(sid) or "其他"
        if ind not in industry_momentum:
            industry_momentum[ind] = []
        industry_momentum[ind].append(pct)

    conn.close()

    industry_avg = {ind: sum(vals) / len(vals) for ind, vals in industry_momentum.items()}

    result = {}
    for sid in stocks:
        pct = raw.get(sid, 0)
        ind = yf_sectors.get(sid) or si_industry.get(sid) or "其他"
        avg = industry_avg.get(ind, 0)
        diff = pct - avg
        score = 50 + diff * 2.5
        result[sid] = max(0, min(100, round(score, 2)))
    return result


# ── 主評分 ───────────────────────────────────────────

def score_all():
    stocks = fetch_all_stocks()
    if not stocks:
        print("⚠️ 找不到任何股票資料")
        return []

    # 建立股票代號→公司名稱對照
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT stock_id, name FROM stock_info")
    stock_name = {r[0]: (r[1] or r[0]) for r in cur.fetchall()}
    conn.close()

    # 先算所有 raw 值
    print("  → 動能...")
    momentum_raw = calc_momentum_raw(stocks)
    print("  → 技術面...")
    tech_raw = calc_technical_raw(stocks)
    print("  → 資金流...")
    flow_raw = calc_fund_flow_raw(stocks)
    print("  → 流動性...")
    liq_raw = calc_liquidity_raw(stocks)
    print("  → 穩健性...")
    vol_raw = calc_volatility_raw(stocks)
    print("  → 槓桿...")
    lev_raw = calc_leverage_raw(stocks)
    print("  → 產業相對...")
    ind_raw = calc_industry_raw(stocks)

    # 全部 Percentile 化
    mom_s   = _percentile_score(momentum_raw)
    tech_s  = _percentile_score(tech_raw)
    flow_s  = _percentile_score(flow_raw)
    liq_s   = _percentile_score(liq_raw)

    # 波動性：越低越好 → Percentile 後取 100 - x
    vol_s_raw = _percentile_score(vol_raw)
    vol_s = {sid: 100 - v for sid, v in vol_s_raw.items()}

    # 槓桿：越低越好 → raw 已是 100 - percentile
    lev_s = lev_raw

    # 產業：越強於產業平均越好
    ind_s = ind_raw

    # 合併
    results = []
    for sid in stocks:
        mom   = mom_s.get(sid, 50)
        tech  = tech_s.get(sid, 50)
        flow  = flow_s.get(sid, 50)
        liq   = liq_s.get(sid, 50)
        vol   = vol_s.get(sid, 50)
        lev   = lev_s.get(sid, 50)
        ind   = ind_s.get(sid, 50)

        total = round(
            mom   * WEIGHTS["momentum"]
            + tech  * WEIGHTS["technical"]
            + flow  * WEIGHTS["fund_flow"]
            + liq   * WEIGHTS["liquidity"]
            + vol   * WEIGHTS["volatility"]
            + lev   * WEIGHTS["leverage"]
            + ind   * WEIGHTS["industry"],
            2
        )

        results.append({
            "stock_id":   sid,
            "name":       stock_name.get(sid, sid),
            "total":      total,
            "momentum":   round(mom, 2),
            "technical":  round(tech, 2),
            "fund_flow":  round(flow, 2),
            "liquidity":  round(liq, 2),
            "volatility": round(vol, 2),
            "leverage":   round(lev, 2),
            "industry":   round(ind, 2),
        })

    results.sort(key=lambda x: x["total"], reverse=True)
    return results


# ── ASCII 圖表 ────────────────────────────────────────

def ascii_chart(stock_id, width=60, height=12):
    data = fetch_price_data(stock_id, days=40)
    if len(data) < 5:
        return None
    closes = [d["close"] for d in data]
    mn, mx = min(closes), max(closes)
    rng = mx - mn or 1

    available = width - 8
    step = max(1, len(closes) // available)

    chart = [[" "] * available for _ in range(height)]
    for i in range(0, len(closes), step):
        price = closes[i]
        col = i // step
        if col >= available:
            break
        row = int((mx - price) / rng * (height - 1))
        row = max(0, min(height - 1, row))
        for r in range(height):
            if r == row:
                chart[r][col] = "█"
            elif r > row:
                chart[r][col] = "▄"

    lines = []
    for r, row_chars in enumerate(chart):
        price_label = f"{mx - r * rng / (height-1):.1f}"
        lines.append(f"{price_label:>8} │" + "".join(row_chars))
    return "\n".join(lines)


# ── 表格輸出 ─────────────────────────────────────────

def print_top30(results, limit=30, chart_stock=None):
    print()
    print(f"{'═'*110}")
    print(f"{'排名':^4} {'代號':^8} {'公司名稱':^16} {'總分':^6} {'動能':^6} {'技術':^6} {'資金':^6} {'流動':^6} {'穩健':^6} {'槓桿':^6} {'產業':^6}")
    print(f"{'─'*110}")
    for i, r in enumerate(results[:limit], 1):
        name = r.get('name', '')
        # 公司名稱太長時截斷
        if len(name) > 14:
            name = name[:12] + '..'
        print(
            f"{i:^4} {r['stock_id']:^8} {name:^16} {r['total']:^6.2f} "
            f"{r['momentum']:^6.2f} {r['technical']:^6.2f} "
            f"{r['fund_flow']:^6.2f} "
            f"{r['liquidity']:^6.2f} {r['volatility']:^6.2f} "
            f"{r['leverage']:^6.2f} {r['industry']:^6.2f}"
        )
    print(f"{'═'*110}")
    print(f"  共 {len(results)} 檔上榜")

    if chart_stock:
        chart_data = ascii_chart(chart_stock)
        if chart_data:
            print(f"\n📈 {chart_stock} 近40日價格圖：")
            print(chart_data)


# ── 寫入 DB ───────────────────────────────────────────

def save_to_db(results, run_date=None):
    if run_date is None:
        run_date = date.today().isoformat()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS top30_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            total_score REAL NOT NULL,
            momentum REAL,
            technical REAL,
            fund_flow REAL,
            liquidity REAL,
            volatility REAL,
            leverage REAL,
            industry REAL,
            rank INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("DELETE FROM top30_signals WHERE signal_date = ?", (run_date,))

    for rank, r in enumerate(results, 1):
        cur.execute("""
            INSERT INTO top30_signals
            (signal_date, stock_id, total_score, momentum, technical,
             fund_flow, liquidity, volatility, leverage, industry, rank)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_date,
            r["stock_id"],
            r["total"],
            r["momentum"],
            r["technical"],
            r["fund_flow"],
            r["liquidity"],
            r["volatility"],
            r["leverage"],
            r["industry"],
            rank,
        ))

    conn.commit()
    conn.close()
    print(f"\n✅ 已寫入 {len(results)} 筆記錄到 top30_signals（日期={run_date}）")


# ── 主程式 ───────────────────────────────────────────

def main():
    chart_opt = "--chart" in sys.argv
    save_opt  = "--save" in sys.argv

    results = score_all()

    if not results:
        print("❌ 無評分結果")
        return

    limit = min(30, len(results))
    chart_stock = results[0]["stock_id"] if results else None

    print_top30(results, limit=limit, chart_stock=chart_stock if chart_opt else None)

    if save_opt:
        save_to_db(results)
    else:
        print("\n💡 使用 --save 寫入資料庫，--chart 顯示圖表")


if __name__ == "__main__":
    main()