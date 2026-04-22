# Trade Core
> 📊 Stephanie 量化交易系統核心引擎

---

## 系統定位

**本質：資料分析與收集系統**

Trade Core 是一個**市場機會發掘引擎**，用於追蹤及抓住股票、金融商品、加密貨幣全市場的投資機會。

**職責分工：**
- Trade Core 負責資料收集、、技術指標計算、訊號篩選、回測驗證、進化學習
- 交易執行交給 Freqtrade 或其他交易系統

## 資料流

```
市場數據 (FinMind / Yahoo Finance / Jin10)
        ↓
Trade Core (收集 + 分析 + 評分)
        ↓
輸出：Top30 推薦 / 掃描結果 / 進化建議
        ↓
交接給交易系統執行
```

---

## 系統架構

```
Trade Core
├── data/                      SQLite 資料庫
│   ├── stock_quant.db
│   └── crypto_coin_list.json  幣種 ID 快取
│
├── scripts/                    核心腳本（共 17 支）
│   ├── init_database.py           資料庫初始化
│   ├── batch_ingest.py             批次日K攝取（台股）
│   ├── ingest_daily_price.py      日K攝取（FinMind API）
│   ├── ingest_institutional.py     法人資料攝取
│   ├── ingest_revenue.py           月營收攝取
│   ├── ingest_financials.py       季財報攝取
│   ├── ingest_stock_info.py       基本資料 + PER/PBR
│   ├── ingest_us_stocks.py        美股資料（Yahoo Finance）
│   ├── ingest_crypto.py            加密幣資料（CoinGecko API）
│   ├── adjust_prices.py            還原權息引擎
│   ├── technical_indicators.py     技術指標引擎
│   ├── scanner.py                 股票篩選器（離線版）
│   ├── scan_and_record.py         篩選 → 訊號自動記錄
│   ├── backtest.py               回測引擎
│   ├── chart.py                  K線圖視覺化（mplfinance）
│   ├── daily_pipeline.py          每日量化流水線
│   ├── evolution.py               進化學習框架
│   ├── portfolio.py              倉位管理模組
│   └── dashboard.py             系統儀表板
│
├── logs/                       日誌與報告輸出
└── output/                     圖表產出目錄
```

---

## 已覆蓋市場

| 市場 | 資料範圍 | 標的數 |
|------|-----------|--------|
| **台股** | 日K、法人、營收、財報、還原價格 | 5 檔 |
| **美股** | 日K + 基本資料（還原） | 4 檔 |
| **加密幣** | 歷史日K + 即時報價 | 18+ 種 |

---

## 資料表總覽

| 資料表 | 說明 | 筆數 |
|--------|------|------|
| `daily_price` | 台股日K（原始） | ~1,550 |
| `adjusted_daily_price` | 台股日K（還原權息） | ~310 |
| `institutional` | 三大法人買賣 | ~2,754 |
| `monthly_revenue` | 月營收 | ~140 |
| `financials` | 季財報（EPS/毛利率/營益率等） | ~12 |
| `stock_info` | 個股基本資料 + PER/PBR | 1 |
| `trade_signals` | 訊號記錄 | ~16 |
| `trades` | 實際交易紀錄 | — |
| `alerts` | 警示日誌 | — |
| `macro_data` | 宏觀經濟數據 | — |
| `system_log` | 系統日誌 | — |
| `us_daily_price` | 美股日K（還原+分割） | ~2,004 |
| `us_stock_info` | 美股基本資料 | ~4 |
| `crypto_daily_price` | 加密幣日K | ~1,095 |
| `crypto_realtime` | 加密幣即時報價 | ~18 |

---

## 技術指標

- **MA 均線**：5 / 10 / 20 / 60 日
- **KD 指標**：K / D 值，低檔黃金交叉 / 高檔死亡交叉判定
- **MACD**：DIF / DEA / 柱狀圖，多空方向與動能強度
- **RSI**：14日相對強弱指標
- **布林帶**：20日 ±2σ 通道
- **均量**：5MA / 20MA 成交量

---

## 篩選器模式

| 模式 | 說明 |
|------|------|
| `kd_gold_cross` | KD 低檔黃金交叉（K<30 時穿越） |
| `macd_bull` | MACD 多頭（DIF>DEA 且柱狀圖正值） |
| `ma_bull` | 均線多頭排列（MA5>MA20>MA60） |
| `vol_spike` | 量能暴增（>1.8 倍 20 日均量） |

---

## 回測策略

支援：KD 黃金交叉 / MACD 多頭 / 均線多頭排列 / RSI 超賣

可調參數：停損（預設 7%）、停利（預設 15%）、最長持有天數（預設 20）、滑價（預設 0.2%）

---

## 快速開始

### 1. 安裝依賴
```bash
pip install -r requirements.txt
pip install yfinance mplfinance --break-system-packages
```

### 2. 台股日K 攝取
```bash
# FinMind Token 寫入 ~/.trade_core.env
# FINMIND_TOKEN=your_token_here

# 單一股票
python3 scripts/ingest_daily_price.py --stock 4967 --start 2025-01-01

# 批次（多檔）
python3 scripts/batch_ingest.py --stocks 2330 2317 2454 3008 4967
```

### 3. 美股
```bash
python3 scripts/ingest_us_stocks.py --add SPY QQQ AAPL NVDA
```

### 4. 加密幣
```bash
python3 scripts/ingest_crypto.py --price               # 即時報價
python3 scripts/ingest_crypto.py --add bitcoin ethereum  # 歷史日K
```

### 5. 還原權息（Free tier 專用）
```bash
python3 scripts/adjust_prices.py --stock 4967
python3 scripts/adjust_prices.py --all                 # 全股票
```

### 6. 技術分析
```bash
python3 scripts/technical_indicators.py 4967
```

### 7. 股票篩選 + 訊號記錄
```bash
python3 scripts/scan_and_record.py --scan-type all        # 掃描並寫入訊號
python3 scripts/scan_and_record.py --scan-type macd_bull --dry-run  # 只看結果
```

### 8. 回測
```bash
python3 scripts/backtest.py --stock 2330 --strategy ma_bull
python3 scripts/backtest.py --stock 4967 --strategy kd_cross --stop-loss 0.07
```

### 9. K線圖
```bash
python3 scripts/chart.py --stock 2330 --days 120
python3 scripts/chart.py --stock bitcoin --days 90   # 加密幣也行
```

### 10. 每日流水線（Cron 自動執行）
```bash
# 每日 08:00 自動更新日K → 還原 → 掃描 → 報告發 Telegram
python3 scripts/daily_pipeline.py
```

### 11. 進化學習
```bash
python3 scripts/evolution.py --report                   # 勝率報告
python3 scripts/evolution.py --record --stock 4967 --result WIN --gain 18.5
```

### 12. 倉位管理
```bash
python3 scripts/portfolio.py --add 4967 --cost 200 --shares 1000 --type 波段
python3 scripts/portfolio.py --report
python3 scripts/portfolio.py --check-risk
```

### 13. 儀表板
```bash
python3 scripts/dashboard.py
```

---

## 風控鐵律

```
1. 單筆進場不超過總資金 5%
2. 單日虧損 > 3% → 停止所有新進場
3. 總持倉不超過 70%（保持 30% 空手）
4. 每筆交易必須有停損條件
5. 高波動、低流動性、題材末端股票提高警戒
```

---

## 進化學習

每次交易後記錄結果，系統自動追蹤：
- 哪種進場訊號勝率最高
- 哪些股票類型更符合風格偏好
- 哪些錯誤來自忽略哪個面向
- 成功與失敗案例，持續更新選股模板

---

## 依賴套件

```
requests>=2.28.0       # HTTP 請求
pandas>=1.5.0          # 數據處理
numpy>=1.23.0          # 數值計算
yfinance>=0.2.0        # Yahoo Finance 美股
mplfinance>=0.12.0     # K線圖繪製
matplotlib>=3.0         # 儀表板
python-dotenv>=1.0.0   # 環境變數
```

---

## 授權與作者

- **作者**：Stephanie — 超能股票小助手
- **系統版本**：v1.0
- **最後更新**：2026-04-20

---

_Trade Core — 讓數據說話，讓系統進化_
