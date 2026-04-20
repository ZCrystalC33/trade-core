# 【Trade Core 架構分析報告】
> 審視日期：2026-04-20
> 審視範圍：18支Python腳本、SQLite資料庫、多市場資料整合

---

## 1. 系統全景圖

### 1.1 目錄結構

```
trade_core/
├── data/
│   ├── stock_quant.db           ← 單一SQLite資料庫（含14張表）
│   └── crypto_coin_list.json    ← CoinGecko幣種ID快取
├── scripts/                     ← 18支Python腳本（4,377行）
│   ├── init_database.py         ← 資料庫初始化（純DDL）
│   ├── ingest_* (7支)          ← 資料攝取層
│   ├── adjust_prices.py         ← 資料轉換層（還原權息）
│   ├── technical_indicators.py  ← 技術指標計算
│   ├── scanner.py               ← 股票篩選（離線版）
│   ├── scan_and_record.py       ← 篩選+訊號寫入
│   ├── backtest.py              ← 回測引擎
│   ├── chart.py                 ← K線視覺化
│   ├── daily_pipeline.py         ← Cron排程流水線
│   ├── evolution.py             ← 進化學習框架
│   ├── portfolio.py             ← 倉位管理
│   └── dashboard.py            ← 系統儀表板
├── logs/
└── output/
```

### 1.2 模組分層架構

```
┌─────────────────────────────────────────────┐
│           應用層（Application）              │
│  daily_pipeline / evolution / portfolio       │
├─────────────────────────────────────────────┤
│           分析層（Analysis）                  │
│  technical_indicators / scanner /           │
│  scan_and_record / backtest                 │
├─────────────────────────────────────────────┤
│         資料轉換層（Transform）              │
│  adjust_prices.py                          │
├─────────────────────────────────────────────┤
│           攝取層（Ingest）                  │
│  ingest_daily_price / ingest_institutional   │
│  ingest_revenue / ingest_financials        │
│  ingest_stock_info / ingest_us_stocks       │
│  ingest_crypto                             │
├─────────────────────────────────────────────┤
│           資料庫（Storage）                 │
│  SQLite: 14張表（台股/美股/加密幣/交易）   │
└─────────────────────────────────────────────┘
```

---

## 2. 模組依賴關係

### 2.1 呼叫依賴圖

```
technical_indicators.py  ← 被 scanner.py、scan_and_record.py 依賴
    ↑                       （核心共享函式庫）
    |
scanner.py  ← 被 daily_pipeline.py 呼叫（--scan）
    ↑
scan_and_record.py  ← 依賴 technical_indicators.py

adjust_prices.py  ← 被 daily_pipeline.py 呼叫（--skip-adjust）

backtest.py  ← 無依賴（自給自足）
    ├── 獨立實作一套技術指標（幾乎相同邏輯）
    └── 獨立讀取資料庫

daily_pipeline.py  ← 主協調器
    ├── 依賴 ingest_single_price
    ├── 依賴 adjust_prices.process_stock
    ├── 依賴 scan_and_record.run_scan
    └── 依賴 chart.py / 其他呈現層

evolution.py / portfolio.py / dashboard.py  ← 獨立，僅依賴SQLite
```

### 2.2 重複實作問題 ⚠️

| 技術指標 | technical_indicators.py | backtest.py |
|---------|----------------------|------------|
| calc_ma | ✅ | ✅（幾乎相同） |
| calc_kd | ✅ | ✅（相同） |
| calc_macd | ✅ | ✅（相同） |
| calc_rsi | ✅ | ✅（相同） |

**問題**：backtest.py 自帶一套完整的指標計算邏輯，與 technical_indicators.py 高度重複。
任何指標邏輯更新需要同步兩處。

**建議**：將指標計算統一為一個共享模組 `indicators.py`，其他腳本統一 import。

---

## 3. 資料流設計

### 3.1 台股資料流

```
FinMind API
    │
    ├─── ingest_daily_price.py ─→ daily_price 表
    │                                 │
    │                                 ↓
    ├─── ingest_institutional.py ─→ institutional 表
    ├─── ingest_revenue.py ─→ monthly_revenue 表
    ├─── ingest_financials.py ─→ financials 表
    └─── ingest_stock_info.py ─→ stock_info 表

daily_price 表
    │
    ↓
adjust_prices.py（還原引擎）
    │
    ↓
adjusted_daily_price 表（還原後價格）
    │
    ├──→ technical_indicators.py ─→ 訊號判定
    ├──→ backtest.py ─→ 績效回測
    └──→ scanner.py ─→ 候選篩選
```

### 3.2 美股/加密幣資料流

```
Yahoo Finance（yfinance）
    └─── ingest_us_stocks.py ─→ us_daily_price 表
                                     │
                                     ↓（backtest.py 直接讀取）

CoinGecko API
    ├─── ingest_crypto.py（--price） ─→ crypto_realtime 表（即時）
    └─── ingest_crypto.py（--add） ─→ crypto_daily_price 表（歷史）
```

### 3.3 交易訊號流

```
scanner.py（離線篩選）
    │
    ↓（手動觸發）
scan_and_record.py
    │
    ↓（寫入）
trade_signals 表（stock_id / signal_type / price / indicators_json）
    │
    ↓（讀取）
evolution.py（勝率統計）
    │
    ↓
選股模板自動更新
```

---

## 4. 資料庫 Schema 設計分析

### 4.1 設計評分

| 維度 | 分數 | 說明 |
|------|------|------|
| 正規化 | 8/10 | 基本符合3NF，適當使用 JSON 欄位 |
| 索引策略 | 7/10 | 有基本索引，但無複合索引 |
| 擴充性 | 6/10 | 新市場需新建資料表，改動成本高 |
| 一致性 | 8/10 | 外鍵關係明確（stock_id + date） |
| 可追蹤性 | 7/10 | system_log / alerts 表齊備 |

### 4.2 Schema 問題與風險

**問題①：還原日K 表（adjusted_daily_price）無對應掃描腳本**

現況：`adjusted_daily_price` 表已存在，但 `technical_indicators.py` 仍讀取 `daily_price`。
`backtest.py` 優先讀 `adjusted_daily_price`，`scanner.py` 只讀 `daily_price`。
兩者不一致，會導致同一標的在不同模組使用不同價格。

**問題②：backtest.py 的停損停利計算用收盤價**

```python
# backtest.py 中的停損判斷
current_price = data[i]["close"]
pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
```

**問題**：使用當日收盤價判斷停損，現實中需要等隔日開盤才能賣出。
真實停損可能更寬（滑價+隔日缺口風險）。

**問題③：trades 表的 signal_id 欄位**

```python
signal_id  INTEGER DEFAULT NULL
```

理論上 `signal_id` 應參照 `trade_signals.id`，但沒有建立外鍵約束。
實際上 `scan_and_record.py` 寫入 `trade_signals` 時不回傳 ID，導致 `trades.signal_id` 幾乎永遠是 NULL。

**問題④：crypto_daily_price 表缺少 OHLC**

```sql
open  REAL,
high  REAL,
low   REAL,
close REAL,
volume INTEGER,
```

但 `compute_ohlc` 函式是從一分鐘價格陣列合成 OHLC（取最大/最小為高低），這不是真正的 OHLC，是估算值。

---

## 5. 核心邏輯審視

### 5.1 技術指標計算邏輯

#### ✅ KD 指標（正確）
```python
# 標準 KD 計算
RSV = (Close - N_Low) / (N_High - N_Low) * 100
K = 2/3 * prev_K + 1/3 * RSV
D = 2/3 * prev_D + 1/3 * K
```

#### ✅ MACD 指標（正確）
```python
DIF = EMA(close, 12) - EMA(close, 26)
DEA = EMA(DIF, 9)
MACD_Bar = 2 * (DIF - DEA)
```

#### ✅ RSI 指標（正確）
使用 SMA 版 RSI（Wilder 平滑法），邏輯正確。

#### ⚠️ 布林帶計算（微小問題）
```python
std = (sum((x - ma[i]) ** 2 for x in window) / period) ** 0.5
```
使用**母體標準差**（N），多數技術分析使用**樣本標準差**（N-1）。差異微小，長期無顯著影響。

### 5.2 還原權息引擎（基本正確，有一處問題）

#### ✅ 後視還原邏輯（正確）
```python
# 從新到舊遍歷，維護累積股利
cumulative_div += ex_dates.get(date, 0)
factors[date] = cumulative_div
```

#### ⚠️ 股票股利稀釋未完整處理

```python
# 當前實作：股票股利只加到 cash_div 裡
total_cash = (cash_div or 0) + (stat_surp or 0)
# stock_div（股票股利）被忽略了
```

台灣股票股利稀釋會導致股數增加，價格在除權後理論上會「自然稀釋」，
用 `CashEarningsDistribution + CashStatutorySurplus` 的方式只能還原**現金股利**的影響，
股票股利的稀釋效果（股數增加）在本實作中被忽略。

**影響**：有股票股利的標的（十銓目前無股票股利，影響可控）。

### 5.3 回測引擎假設與限制

| 假設 | 風險 | 等級 |
|------|------|------|
| 收盤價=成交價 | 無法處理當日缺口 | ⚠️ 中 |
| 無交易成本（佣金/稅） | 台股交易成本0.142%+ | ⚠️ 中 |
| 固定停損7%/停利15% | 不見得適合所有標的 | 🟡 低 |
| 單筆全押 | 無部位管理 | 🔴 高 |
| 歷史不代表未來 | 過擬合風險 | 🟡 低 |

**最大問題：無交易成本**

台灣股票交割費用約 0.142%（0.3%手續費打折後），加上證交稅 0.3%，
一進一出約 0.5% 的固定成本。
在勝率 50%、平均報酬 2% 的策略下，0.5% 成本會吃掉 20-25% 的獲利。

---

## 6. Scanner 訊號判定一致性問題

### 6.1 Scanner 與 technical_indicators 訊號命名不一致

| 模組 | 訊號名 | 意義 |
|------|--------|------|
| `technical_indicators.py` | `KD_LowGoldCross` | K>D 且 K<30 |
| `backtest.py` | `kd_low_gold` | K>D 且 K<30 |
| `scanner.py` | `scan_kd_gold_cross()` | **K>D 且 K<max_k（可設60）** |

**問題**：`scanner.py` 的 `scan_kd_gold_cross(min_k=20, max_k=60)` 參數範圍，
與 `technical_indicators.py` 的低檔定義（K<30）不完全一致。

### 6.2 `scan_and_record.py` 的訊號寫入問題

`scan_and_record.py` 在 `run_scan()` 執行篩選時：

```python
if not dry_run:
    for sig_type in sigs.keys():
        save_signal(sid, sig_type, ...)
```

**問題**：同一支股票同一日會寫入**多筆訊號**（KD黃金交叉 + MACD多頭 = 2筆），
但 `sigs` 是 dict，key 是訊號類型，會根據技術指標訊號各自寫入。

實測：2317 同日產生 3 筆訊號（KD_GOLD_CROSS / MACD_BULL / MACD_BAR_POS），
這是合理的，但 `trade_signals` 表的 `signal_id` 欄位從未被正確使用來關聯 trades 表。

---

## 7. 設計模式識別

| 模式 | 出現位置 | 說明 |
|------|----------|------|
| **Pipe & Filter** | daily_pipeline.py | Step1→Step2→Step3→Step4 流水線 |
| **Strategy** | backtest.py `Strategies` 類 | 多策略可交換（kd_cross/macd_bull/ma_bull） |
| **Template Method** | evolution.py | 訊號統計流程固定，細節各異 |
| **Data Mapper** | 所有 ingest_* 腳本 | API JSON → SQLite 欄位對映 |
| **Registry** | 所有模組 | `get_token()` 統一 Token 取得 |
| **Lazy Initialization** | adjust_prices.py | 貨幣金融據快取到 `~/.trade_core.env` |

---

## 8. 已知問題與風險摘要

| 問題 | 等級 | 影響 |
|------|------|------|
| backtest.py 指標與 technical_indicators.py 重複實作 | 🟡 中 | 維護成本高，易出錯 |
| 還原日K只覆蓋4967，其他4檔台股仍是原始價格 | 🟡 中 | 回測結果可能失真 |
| backtest 無交易成本（0.5% 固定成本） | 🔴 高 | 勝率/報酬率被高估 |
| backtest 用收盤價計算停損（非真實成交價） | 🟡 中 | 實際虧損可能更大 |
| adjusted_daily_price 與 daily_price 讀取不一致 | 🟡 中 | Scanner/回測使用不同價格基準 |
| trades.signal_id 永遠是 NULL | 🟡 中 | 無法追蹤訊號與交易的對應關係 |
| stock_div（股票股利）稀釋未被還原 | 🟡 低 | 目前十銓無股票股利，影響可控 |
| 布林帶使用母體標準差（非樣本） | 🟢 極低 | 差異可忽略 |
| crypto OHLC 為估算值非真實OHLC | 🟢 低 | 僅供參考方向 |
| 鴻海(2317)還原價格顯示-100%（需查證） | 🟡 中 | 可能因還原機制或資料問題 |

---

## 9. 改進建議（優先順序）

### 第一優先（影響準確性）

**① 補完還原日K覆蓋**
```bash
python3 adjust_prices.py --all
```
盡快對所有5檔台股執行還原，確保 Scanner 和回測使用同一價格基準。

**② 將 backtest 的指標實作統一到 shared/indicators.py**

```python
# 建議新增：shared/indicators.py
# 所有腳本 import 此模組，杜絕重複實作
```

**③ 加入交易成本**
```python
COST_RATE = 0.005  # 0.5%（手續費+證交稅）
entry_price = close * (1 + slippage + COST_RATE)
exit_price  = close * (1 - slippage - COST_RATE)
```

**④ 修復 trades.signal_id 鏈**
在 `scan_and_record.py` 的 `save_signal()` 回傳新增 ID，
並在平倉時寫入對應的 signal_id。

### 第二優先（系統穩健性）

**⑤ 建立資料庫遷移腳本**
用 Alembic 或手動 SQL script 管理 Schema 版本。

**⑥ 加入日誌查詢接口**
`system_log` 表已存在，但沒有查詢介面。

**⑦ 美股/加密幣的 Scanner 支援**
目前 Scanner 只掃台股資料庫（`daily_price`），
應該擴充到可以同時掃美股（`us_daily_price`）和加密幣（`crypto_daily_price`）。

### 第三優先（長期價值）

**⑧ 參數優化框架**
用 Grid Search 對 stop_loss / take_profit / max_hold_days 做參數掃描，
找出各策略的最佳參數組合。

**⑨ 即時行情對接**
目前只有 FinMind（日K延遲一天），
如需真正日內策略，需要即時行情源（WebSocket 或逐筆資料）。

---

## 10. 架構評分總覽

| 維度 | 分數 | 備註 |
|------|------|------|
| 程式碼品質 | 7/10 | 邏輯正確、结构清晰，少量重複實作 |
| 資料庫設計 | 7/10 | 基本正規化，缺乏複合索引 |
| 可維護性 | 6/10 | 指標重複實作是最大問題 |
| 自動化程度 | 8/10 | Cron流水線完整 |
| 擴充性 | 7/10 | 新市場需新建腳本/資料表，框架支援 |
| 商業價值 | 7/10 | 基本工具鏈完整，真實使用需補足還原覆蓋 |

**總評：7/10 — 實用級量化系統基礎，未達 production-ready**

---

_分析人：Stephanie_
_審視時間：2026-04-20_
