#!/usr/bin/env python3
"""
setup_cron.py — 管理 trade-core 每日 cron job
用途：自動設定 Linux crontab，讓 daily_pipeline.py 每天 08:00 自動執行

功能：
  - 檢查並更新 / 新增 cron 設定
  - 時區：Asia/Taipei（TZ=Asia/Taipei）
  - stdout/stderr → /home/snow/trade-core/logs/cron_daily.log
  - 绝对路径：/usr/bin/python3 + /home/snow/trade-core/scripts/daily_pipeline.py
  - 顯示目前 cron 狀態供確認
  - 支援 --dry-run

使用方式：
  python3 setup_cron.py           # 安裝 cron
  python3 setup_cron.py --dry-run  # 只顯示會什麼，不實際安裝
"""

import sys
import subprocess
import argparse
from pathlib import Path

# ── 常數 ─────────────────────────────────────────────────────
WRAPPER   = "/home/snow/trade-core/scripts/cron_wrapper.sh"
LOG_DIR   = "/home/snow/trade-core/logs"
CRON_TAG  = "# tradecore-daily-pipeline"
CRON_JOB  = (
    f"{CRON_TAG}\n"
    'TZ=Asia/Taipei\n'
    'PYTHONPATH=/home/snow/trade-core/scripts\n'
    'FINMIND_TOKEN=${FINMIND_TOKEN:-}\n'
    f'0 8 * * * /bin/bash "{WRAPPER}"\n'
)
CRON_END  = "# tradecore-daily-pipeline-end"


def get_current_crontab() -> str:
    """讀取目前 crontab 內容，無內容則回傳空字串"""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    except Exception:
        return ""


def remove_old_entries(cron: str) -> str:
    """移除舊的 tradecore cron 區塊（若存在）"""
    lines = cron.splitlines()
    new_lines = []
    in_block = False
    for line in lines:
        if line.strip() == CRON_TAG:
            in_block = True
            continue
        if in_block:
            # 遇到 end tag 或下一個以 # 開頭的非 tag 行（保護用）
            if line.strip() == CRON_END:
                in_block = False
            continue
        new_lines.append(line)
    return "\n".join(new_lines).rstrip() + "\n"


def install_cron(dry_run: bool = False):
    """安裝或更新 cron job"""
    current = get_current_crontab()
    cleaned = remove_old_entries(current)

    if dry_run:
        print("=== DRY RUN：以下 cron 項目將被安裝 ===")
        print(CRON_JOB)
        print("=== 目前 crontab 狀態 ===")
        if current.strip():
            print(current)
        else:
            print("(目前無 crontab)")
        print("=== 執行後 crontab 將變為 ===")
        combined = (cleaned + "\n" + CRON_JOB).strip() + "\n"
        print(combined)
        print("=== DRY RUN END ===")
        return

    # 組合新 crontab
    new_crontab = (cleaned + "\n" + CRON_JOB).strip() + "\n"

    # 寫入 crontab
    proc = subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        text=True
    )
    if proc.returncode != 0:
        print(f"[ERROR] crontab 安裝失敗：{proc.stderr}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Cron 已安裝")
    show_status()


def remove_cron():
    """移除 cron job"""
    current = get_current_crontab()
    cleaned = remove_old_entries(current).strip() + "\n"
    if cleaned.strip():
        proc = subprocess.run(["crontab", "-"], input=cleaned, text=True)
    else:
        proc = subprocess.run(["crontab", "-r"], capture_output=True)
    print("[OK] Cron 已移除")
    show_status()


def show_status():
    """顯示目前 cron 狀態"""
    current = get_current_crontab()
    print("\n═══ 目前 Crontab 狀態 ═══")
    if CRON_TAG in current:
        print("✅  發現 tradecore daily pipeline cron job")
        # 找到 job 行
        for line in current.splitlines():
            if line.strip().startswith("0 8 "):
                print(f"   項目：{line.strip()}")
                break
    else:
        print("⛔  無 tradecore cron job（尚未設定）")

    # 顯示完整 crontab
    print("\n─── 完整 crontab ───")
    if current.strip():
        print(current)
    else:
        print("(空的)")
    print("───")

    # 顯示 wrapper 狀態
    w = Path(WRAPPER)
    print(f"\nWrapper 腳本：{WRAPPER}")
    if w.exists():
        print(f"✅  存在（mode={oct(w.stat().st_mode)[-3:]}）")
    else:
        print(f"⛔  不存在，請先建立 cron_wrapper.sh")

    log = Path(LOG_DIR)
    print(f"\nLog 目錄：{LOG_DIR}")
    if log.exists():
        print(f"✅  存在")
    else:
        print(f"⚠️   不存在，wrapper 會自動建立")


def main():
    parser = argparse.ArgumentParser(
        description="管理 tradecore 每日流水線 cron job"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="顯示會設定什麼但不安裝"
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="移除現有的 cron job"
    )
    args = parser.parse_args()

    # 前置檢查：wrapper 是否存在
    if not args.remove and not args.dry_run:
        if not Path(WRAPPER).exists():
            print(f"[ERROR] Wrapper 不存在：{WRAPPER}", file=sys.stderr)
            print("請先建立 cron_wrapper.sh", file=sys.stderr)
            sys.exit(1)

    if args.remove:
        remove_cron()
    else:
        install_cron(dry_run=args.dry_run)


if __name__ == "__main__":
    main()