"""即時持倉監控 — 顯示 console、含 P&L、停損距離、停損突破警示.

用法:
    python scripts/zhuli/live_position_monitor.py

編輯下面 HELD / WATCH / REALIZED 變數設定你的持倉。

特性:
- 每 N 秒刷新一次 (預設 30s)
- 三檔健康狀態用顏色 (🟢/⚠️/🔴)
- 停損突破會 macOS terminal 響鈴 + osascript notification
- 印出今日 P&L (帳面 + 已實現)
- 30 秒內單檔 ±1% 跳動會 highlight
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Fubon client
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
if str(_SYS) not in sys.path:
    sys.path.insert(0, str(_SYS))

from clients.fubon_client import FubonClient  # noqa

# ─────────────────────────────────────────────────────────────────────────
# 編輯區: 持倉設定
# ─────────────────────────────────────────────────────────────────────────

# 已進場部位: (ticker, name, entry_price, shares, stop_loss)
HELD = [
    ('6285', '啟碁', 315.0, 1000, 307.4),   # 1 張
    ('2485', '兆赫', 73.4,  5000, 70.0),    # 5 張
    ('1605', '華新', 40.1,  8000, 38.75),   # 8 張
]

# 已實現損益 (今日累計)
REALIZED = -21388  # 3016 嘉晶 -$21,388

# 監控但未進場的標的: (ticker, name, ref_price, stop, kind)
WATCH = [
    ('5425', '台半', 116.5, 113.0, 'SKIP'),
    ('2481', '強茂', 162.5, 178.5, 'SKIP'),
    ('3675', '德微', 413.0, 454.0, 'SKIP'),
    ('3016', '嘉晶', 138.0, 133.5, 'SOLD'),
]

# ─────────────────────────────────────────────────────────────────────────
# ANSI Colors
# ─────────────────────────────────────────────────────────────────────────

class C:
    R = '\033[91m'
    G = '\033[92m'
    Y = '\033[93m'
    B = '\033[94m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'
    CLR = '\033[H\033[J'   # clear screen + home


def notify_mac(title: str, msg: str):
    """macOS notification + 響鈴."""
    try:
        subprocess.run(
            ['osascript', '-e',
             f'display notification "{msg}" with title "{title}" sound name "Glass"'],
            check=False, timeout=3,
        )
    except Exception:
        # Fallback: terminal bell
        print('\a', end='', flush=True)


def fmt_pnl(pnl: float, pct: float) -> str:
    color = C.G if pnl >= 0 else C.R
    sign = '+' if pnl >= 0 else ''
    return f"{color}{sign}{pnl:,.0f} ({sign}{pct:.1f}%){C.END}"


def fmt_dist(dist: float) -> str:
    if dist < 0:
        return f"{C.R}{dist:+.1f}%{C.END}"
    elif dist < 1:
        return f"{C.Y}{dist:+.1f}%{C.END}"
    else:
        return f"{C.G}{dist:+.1f}%{C.END}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', type=int, default=30, help='polling interval (seconds)')
    parser.add_argument('--no-clear', action='store_true', help='不清螢幕、append 模式')
    parser.add_argument('--no-notify', action='store_true', help='關閉 macOS 通知')
    args = parser.parse_args()

    client = FubonClient()
    prev_prices: dict[str, float] = {}
    stop_break_notified: set[str] = set()

    print(f"{C.BOLD}{C.B}=== 即時持倉監控 (interval {args.interval}s) ==={C.END}")
    print(f"持倉: {len(HELD)} 檔 | Watchlist: {len(WATCH)} 檔")
    print(f"已實現: {fmt_pnl(REALIZED, 0)}")
    print("按 Ctrl+C 停止")
    print()
    time.sleep(1)

    while True:
        try:
            now = datetime.now().strftime('%H:%M:%S')
            total_pnl = 0.0
            buf = []

            buf.append(f"{C.BOLD}┌{'─'*78}┐{C.END}")
            buf.append(f"{C.BOLD}│ ⏰ {now}  即時持倉監控{' '*55}│{C.END}")
            buf.append(f"{C.BOLD}├{'─'*78}┤{C.END}")
            buf.append(f"{C.BOLD}│ 已進場部位{' '*65}│{C.END}")
            buf.append(f"{C.BOLD}├{'─'*78}┤{C.END}")

            for tk, name, entry, shares, stop in HELD:
                try:
                    snap = client.get_realtime_snapshot(tk)
                    c = float(snap.get('close', 0))
                except Exception:
                    buf.append(f"│ {tk} {name:6} [快照失敗]" + ' ' * 50 + "│")
                    continue

                pnl = (c - entry) * shares
                pnl_pct = (c - entry) / entry * 100 if entry > 0 else 0
                dist_stop = (c - stop) / c * 100 if c > 0 else 0
                total_pnl += pnl

                # 30s tick
                prev = prev_prices.get(tk)
                prev_prices[tk] = c
                tick_str = ''
                if prev is not None and prev > 0:
                    tick = (c - prev) / prev * 100
                    if abs(tick) >= 0.5:
                        arrow = '↑' if tick > 0 else '↓'
                        color = C.G if tick > 0 else C.R
                        tick_str = f" {color}{arrow}{tick:+.1f}%{C.END}"

                # 停損突破 → 通知
                key = f"{tk}_break"
                if dist_stop < 0:
                    if key not in stop_break_notified:
                        stop_break_notified.add(key)
                        if not args.no_notify:
                            notify_mac(f"🚨 {tk} {name} 跌破停損",
                                       f"現 ${c:.1f} vs 停損 ${stop:.1f}、損 ${pnl:,.0f}")
                else:
                    stop_break_notified.discard(key)

                pnl_str = fmt_pnl(pnl, pnl_pct)
                dist_str = fmt_dist(dist_stop)
                line = (f"│ {tk} {name:6} 入${entry:>7.2f}×{shares:>5} | 現${c:>7.2f}{tick_str:>15} | "
                        f"P&L{pnl_str:>30} | 距停{dist_str:>20} │")
                buf.append(line)

            buf.append(f"{C.BOLD}├{'─'*78}┤{C.END}")
            today = total_pnl + REALIZED
            today_str = fmt_pnl(today, 0)
            real_str = fmt_pnl(REALIZED, 0)
            book_str = fmt_pnl(total_pnl, 0)
            buf.append(f"{C.BOLD}│ 帳面 {book_str:>40} | 已實現 {real_str:>20} │{C.END}")
            buf.append(f"{C.BOLD}│ 💰 今日總計 {today_str:>60} │{C.END}")
            buf.append(f"{C.BOLD}├{'─'*78}┤{C.END}")

            # Watchlist
            buf.append(f"{C.BOLD}│ Watchlist (SKIP){' '*60}│{C.END}")
            for tk, name, prev_close, stop, kind in WATCH:
                try:
                    snap = client.get_realtime_snapshot(tk)
                    c = float(snap.get('close', 0))
                except Exception:
                    continue
                chg = (c - prev_close) / prev_close * 100 if prev_close > 0 else 0
                dist_stop = (c - stop) / c * 100 if c > 0 else 0
                tag = '🔴弱' if dist_stop < 0 else '🟡回穩'
                chg_color = C.R if chg < 0 else C.G
                buf.append(f"│   {tk} {name:6} ${c:>7.2f} ({chg_color}{chg:+.1f}%{C.END}) 距停損 {fmt_dist(dist_stop):>20} {tag}" + ' ' * 18 + "│")

            buf.append(f"{C.BOLD}└{'─'*78}┘{C.END}")
            buf.append("")
            buf.append(f"{C.DIM}下次更新: {args.interval}s | Ctrl+C 結束{C.END}")

            if not args.no_clear:
                print(C.CLR, end='')
            print('\n'.join(buf))

            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n{C.B}結束{C.END}")
            break
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
