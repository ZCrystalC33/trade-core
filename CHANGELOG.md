# CHANGELOG — Trade Core

All notable changes to this project will be documented in this file.

---

## [Unreleased]

> System is in active development. Breaking changes will be noted here.

---

## [v1.0.0] — 2026-04-20

### Added

#### 資料層
- **`init_database.py`** — SQLite 資料庫初始化（11張表）
- **`batch_ingest.py`** — 台股批次日K攝取（多檔一次入庫）
- **`ingest_daily_price.py`** — 台股日K（FinMind API，支援 `--demo` 模擬模式）
- **`ingest_institutional.py`** — 三大法人買賣資料（FinMind API）
- **`ingest_revenue.py`** — 月營收資料（FinMind API）
- **`ingest_financials.py`** — 季財報（FinMind API，自動攤平為季度格式）
- **`ingest_stock_info.py`** — 個股基本資料 + PER/PBR/殖利率
- **`adjust_prices.py`** — 還原權息引擎（Free tier 專用，解決 `TaiwanStockPriceAdj` 需要 Backer 等級的問題）
- **`ingest_us_stocks.py`** — 美股資料（Yahoo Finance yfinance，支援還原價格、股票分割）
- **`ingest_crypto.py`** — 加密幣資料（CoinGecko API，支援 18+ 主流幣還原即時報價與歷史日K）

#### 策略層
- **`technical_indicators.py`** — 技術指標引擎（純 Python 實現，無需 talib）
  - MA / KD / MACD / RSI / 布林帶 / 均量
- **`scanner.py`** — 股票篩選器（4種模式：KD 黃金交叉、MACD 多頭、均線多頭、量能暴增）
- **`scan_and_record.py`** — 篩選 → 訊號自動寫入 `trade_signals` 表（支援 `--dry-run`）
- **`backtest.py`** — 回測引擎
  - 支援策略：KD 黃金交叉、MACD 多頭、均線多頭排列、RSI 超賣
  - 可調參數：停損（7%）、停利（15%）、最長持有天數（20）、滑價（0.2%）

#### 視覺化層
- **`chart.py`** — K線圖產出（mplfinance，支援台股/美股/加密幣，自動讀取還原價格）
- **`dashboard.py`** — 系統儀表板（文字版 + PNG 四格圖：資料覆蓋/訊號分布/勝率/完成度）

#### 監控與自動化
- **`daily_pipeline.py`** — 每日量化流水線
  - Step1: 日K 更新 → Step2: 還原價格 → Step3: Scanner → Step4: 產出報告 → Step5: Telegram 通知
  - Cron Job 已設定：**每日 08:00（Asia/Taipei）**自動執行

#### 進化與風控
- **`evolution.py`** — 進化學習框架
  - 訊號勝率統計（按訊號類型）
  - 個股勝率統計
  - 自動生成進化洞察（勝率最高/最低訊號警示）
  - 自動更新選股模板
  - 手動記錄交易結果（`--record`）
- **`portfolio.py`** — 倉位管理模組
  - 新增持倉 / 平倉 / 持倉報告 / 風控檢查
  - 風控規則：單筆 5% 上限 / 停損 7% / 停利 15% / 總持倉 70% 上限

### Changed

- **`technical_indicators.py`** — KD 指標計算重構，修正 `k_val` 變數範圍錯誤
- **`adjust_prices.py`** — 還原邏輯重構，納入 `CashStatutorySurplus`（法定公積紅利）計算，正確還原台股除權息

### Fixed

- `TaiwanStockPriceAdj` Free tier 不支援問題 → 自建還原引擎繞過
- `TaiwanStockMonthRevenue` 日期格式改為 `YYYY-MM-DD`
- `TaiwanStockFinancialStatements` 欄位重構，正確解析攤平後的季度格式

---

## [v0.1.0] — 2026-04-20

### Added
- Initial commit：Trade Core 量化系統第一版
- 基本架構：目錄結構、資料庫 Schema、初步 README
- `OPERATING_RULES.md`：Stephanie 操作手冊與流程定義

---

## 版本說明

| 版本 | 狀態 |
|------|-------|
| `v0.1.0` | 第一版，基礎架構 |
| `v1.0.0` | 正式版，主要模組齊備 |

---

## 即將到來（規劃中）

- [ ] 還原日K 覆蓋全股票（目前僅 4967 完成）
- [ ] 美股還原價格自動同步（yfinance 自動處理，但需確保歷史完整性）
- [ ] 台股加權指數、大盤總體情緒指標
- [ ] 宏觀經濟資料（VIX / CPI / 利率）
- [ ] 策略參數自動優化（Grid Search）
- [ ] 實盤券商串接（需高強度風控）
- [ ] 選擇權 / 期貨資料支援

---

_格式遵循 [Keep a Changelog](https://keepachangelog.com/) v1.1.0_
