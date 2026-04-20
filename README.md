# Trade Core
> Stephanie 量化交易系統核心引擎

---

## 📌 系統定位

Trade Core 是 Stephanie（老闆的專屬股票交易助理）的量化系統核心，負責：
- 資料攝取與儲存
- 技術指標計算
- 訊號生成與篩選
- 交易策略框架（規劃中）
- 風控與倉位管理（規劃中）

---

## 🏗️ 系統架構

```
Trade Core
├── data/                  ← SQLite 資料庫
├── scripts/
│   ├── init_database.py       # 資料庫初始化
│   ├── ingest_*               # 資料攝取模組
│   ├── technical_indicators.py # 技術指標引擎
│   └── scanner.py              # 股票篩選器
├── backtest/              ← 回測框架（規劃中）
├── execution/             ← 券商串接（規劃中）
├── risk/                  ← 風控引擎（規劃中）
├── visualization/          ← 視覺化（規劃中）
└── evolution/             ← 進化學習（規劃中）
```

---

## 📊 已建構模組

### 資料庫（SQLite）
| 資料表 | 說明 |
|--------|------|
| `daily_price` | 日K（OHLCV） |
| `institutional` | 三大法人買賣 |
| `monthly_revenue` | 月營收 |
| `financials` | 季財報 |
| `stock_info` | 個股基本資料 |
| `trade_signals` | 訊號記錄 |
| `trades` | 實際交易紀錄 |
| `alerts` | 警示日誌 |
| `macro_data` | 宏觀經濟數據 |
| `system_log` | 系統日誌 |

### 技術指標引擎
- ✅ MA（均線：5/10/20/60）
- ✅ KD 指標
- ✅ MACD（DIF/DEA/柱狀圖）
- ✅ RSI（14日）
- ✅ 布林帶（20日±2σ）
- ✅ 均量（5MA/20MA）

### 股票篩選器
- ✅ KD 低檔黃金交叉
- ✅ MACD 多頭（DIF>DEA 且柱狀圖轉正）
- ✅ 量能暴增（>1.8倍 20日均量）
- ✅ 均線多頭排列（MA5>MA20>MA60）

---

## 🚧 規劃中模組

### ① 資料層
| 模組 | 狀態 | 說明 |
|------|------|------|
| FinMind 日K | 🟡 待Token | 需申請 API Token |
| FinMind 法人 | 🟡 待Token | 三大法人每日資料 |
| FinMind 月營收 | 🟡 待Token | 月營收追蹤 |
| FinMind 季財報 | 🟡 待Token | 財報攝取 |
| yfinance 美股 | 📋 規劃 | 美股即時/歷史 |
| 宏觀經濟 | 📋 規劃 | CPI、利率、VIX |

### ② 策略層
| 模組 | 狀態 |
|------|------|
| 技術指標引擎（擴充） | ✅ 基礎完成 |
| 訊號產生器 | ✅ 基礎完成 |
| 選股篩選器 | ✅ 基礎完成 |
| 策略回測引擎 | 📋 規劃 |
| 策略優化框架 | 📋 規劃 |

### ③ 執行層
| 模組 | 狀態 |
|------|------|
| 券商 API 串接 | 📋 規劃 |
| 紙本交易（Paper Trading）| 📋 規劃 |
| 實盤對接 | 📋 規劃 |

### ④ 風控層
| 模組 | 狀態 |
|------|------|
| 倉位管理 | 📋 規劃 |
| 停損機制 | 📋 規劃 |
| 停利機制 | 📋 規劃 |
| 風險引擎 | 📋 規劃 |

### ⑤ 監控警示層
| 模組 | 狀態 |
|------|------|
| Cron 排程引擎 | ✅ 可用 |
| Telegram 通知 | ✅ 可用 |
| 條件掃描器 | ✅ 基礎 |
| 自動報表 | 📋 規劃 |

### ⑥ 視覺化層
| 模組 | 狀態 |
|------|------|
| K線圖（mplfinance）| 📋 規劃 |
| 技術指標圖 | 📋 規劃 |
| 族群熱力圖 | 📋 規劃 |
| 儀表板 | 📋 規劃 |

### ⑦ 進化學習層
| 模組 | 狀態 |
|------|------|
| 交易復盤日誌 | 📋 規劃 |
| 勝率追蹤 | 📋 規劃 |
| 訊號有效性分析 | 📋 規劃 |
| 自我優化框架 | 📋 規劃 |

---

## 🛠️ 快速開始

### 1. 安裝依賴
```bash
pip install -r requirements.txt
```

### 2. 初始化資料庫
```bash
python3 scripts/init_database.py
```

### 3. 攝取日K資料（需 FinMind Token）
```bash
python3 scripts/ingest_daily_price.py \
  --stock 4967 \
  --start 2025-01-01 \
  --end 2026-04-20 \
  --token 你的token
```

或使用模擬資料（無需 Token）：
```bash
python3 scripts/ingest_daily_price.py --stock 4967 --demo
```

### 4. 技術分析
```bash
python3 scripts/technical_indicators.py 4967
```

### 5. 股票掃描
```bash
python3 scripts/scanner.py
```

---

## 🔑 關鍵規則

### 風控鐵律
- 單筆進場不超過總資金 5%
- 單日虧損超過 3% → 停止所有新進場
- 總持倉不超過 70%（最少 30% 空手）
- 每筆交易必須有停損條件

### 資料紀律
- 即時資料必須來自工具，不靠記憶臆測
- 資料不足時明確標示「需補資料確認」
- 禁止虛構或扭曲數據

### 進化原則
- 每筆交易後記錄復盤
- 持續追蹤訊號勝率
- 每季檢視策略有效性

---

## 📁 目錄結構

```
trade_core/
├── README.md
├── .gitignore
├── requirements.txt
├── data/
│   └── stock_quant.db         # SQLite 資料庫
├── logs/
│   └── data_ingest.log        # 攝取日誌
├── scripts/
│   ├── init_database.py
│   ├── ingest_daily_price.py
│   ├── ingest_institutional.py
│   ├── ingest_revenue.py
│   ├── ingest_financials.py
│   ├── technical_indicators.py
│   └── scanner.py
├── backtest/                 # 回測框架（規劃）
├── execution/                # 券商串接（規劃）
├── risk/                     # 風控引擎（規劃）
├── visualization/            # 視覺化（規劃）
└── evolution/                # 進化學習（規劃）
```

---

## 👤 作者

Stephanie — 超能股票小助手（老闆的專屬量化交易助理）

---

_最後更新：2026-04-20_
