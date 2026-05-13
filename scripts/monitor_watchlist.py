"""
即時監控腳本 — 使用 stock-analysis-system FubonClient
用法：python scripts/monitor_watchlist.py
Ctrl+C 結束
"""

import sys
import os
import time
import subprocess
from datetime import datetime

# 引用 stock-analysis-system 的 client
SAS_PATH = os.path.join(os.path.dirname(__file__), "../../stock-analysis-system")
sys.path.insert(0, os.path.abspath(SAS_PATH))

os.environ.setdefault("FUBON_PID",             "A123309212")
os.environ.setdefault("FUBON_API_KEY",         "2C7AAECD2FEDB7095F3167FE2A05C62636AE436899CD874D65AB7560036DA6A1")
os.environ.setdefault("FUBON_CREDENTIAL_FILE", "/Users/howard/.fubon/A123309212_20270401.p12")
os.environ.setdefault("FUBON_CREDENTIAL_PWD",  "My253845")

from clients.fubon_client import FubonClient  # noqa: E402

# ── 監控清單 ──────────────────────────────────────────────────────────────
# 每檔格式：(代號, 名稱, {price: (描述, 方向)})
# 方向 "below" = 現價跌破此位發出警示；"above" = 現價站上此位發出提示
WATCHLIST = [
    ("2303", "聯電", {
        104.5: ("缺口下緣 / 昨收", "below"),
        95.0:  ("5/11缺口下緣",    "below"),
    }),
    ("3481", "群創", {
        35.5: ("5/13缺口下緣 / 昨收", "below"),
        32.3: ("5/12缺口下緣",         "below"),
    }),
    ("8358", "金居", {
        500.0: ("前高壓力",        "above"),
        474.5: ("5/12低點",        "below"),
        446.0: ("5/11低點 / 注意", "below"),
        436.5: ("5/8低點 / 停損",  "below"),
    }),
]

INTERVAL = 30   # 更新間隔（秒）
MARKET_OPEN  = (9,  0)
MARKET_CLOSE = (13, 35)

# ─────────────────────────────────────────────────────────────────────────────

def market_is_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def fmt_change(val: float) -> str:
    if val > 0:
        return f"\033[91m▲{val:.2f}\033[0m"
    if val < 0:
        return f"\033[92m▼{abs(val):.2f}\033[0m"
    return f"─{abs(val):.2f}"


def fmt_pct(val: float) -> str:
    if val > 0:
        return f"\033[91m+{val:.2f}%\033[0m"
    if val < 0:
        return f"\033[92m{val:.2f}%\033[0m"
    return f"{val:.2f}%"


def check_alerts(close: float, levels: dict) -> list[str]:
    alerts = []
    for price, (desc, direction) in sorted(levels.items(), reverse=True):
        if direction == "below" and close <= price:
            alerts.append(f"  \033[93m⚠  跌破 {price}（{desc}）\033[0m")
        elif direction == "above" and close >= price:
            alerts.append(f"  \033[96m✓  站上 {price}（{desc}）\033[0m")
    return alerts


def level_refs(close: float, levels: dict) -> str:
    parts = []
    for price, (desc, direction) in sorted(levels.items(), reverse=True):
        triggered = (direction == "below" and close <= price) or \
                    (direction == "above" and close >= price)
        marker = "●" if triggered else "○"
        arrow  = "↓" if direction == "below" else "↑"
        parts.append(f"{marker}{arrow}{price}({desc})")
    return "  ".join(parts)


def render(client: FubonClient) -> None:
    # 清畫面（ANSI escape，不呼叫 shell）
    print("\033[2J\033[H", end="")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status   = "\033[92m盤中\033[0m" if market_is_open() else "\033[90m非交易時間\033[0m"
    print(f"  即時監控  {now_str}  {status}")
    print("  " + "─" * 74)
    print(f"  {'代號':6} {'名稱':5} {'現價':>8} {'開':>8} {'高':>8} {'低':>8} {'漲跌':>9} {'漲跌%':>8} {'量(張)':>8}")
    print("  " + "─" * 74)

    for sid, name, levels in WATCHLIST:
        s = client.get_realtime_snapshot(sid)
        if not s:
            print(f"  {sid:6} {name:5}  無法取得")
            continue

        close = s["close"]
        print(
            f"  {sid:6} {name:5}"
            f" {close:>8.2f}"
            f" {s['open']:>8.2f}"
            f" {s['high']:>8.2f}"
            f" {s['low']:>8.2f}"
            f" {fmt_change(s['change_price']):>18}"
            f" {fmt_pct(s['change_rate']):>17}"
            f" {s['total_volume']:>8,}"
        )
        for alert in check_alerts(close, levels):
            print(alert)
        print(f"  {level_refs(close, levels)}")
        print()

    print(f"  [{INTERVAL}s 自動更新]  Ctrl+C 離開")


def main() -> None:
    print("連線中...")
    client = FubonClient()
    try:
        client._ensure_connected()
        print("連線成功，開始監控。\n")
        while True:
            render(client)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\n結束監控。")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
