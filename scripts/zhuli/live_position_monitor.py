"""即時持倉 + 開盤進場 screener (整合版).

兩階段:
- Phase 1 (9:00-9:25): 開盤 entry screening、判主候選 / 備案
- Phase 2 (9:25 後): 已持倉 P&L + 停損監控

用法:
    python scripts/zhuli/live_position_monitor.py

編輯下方:
- HELD: 已持倉部位 (Phase 2 監控)
- PLAN_PRIMARY: 鎖定的主候選 (Phase 1 開盤評估)
- PLAN_BACKUP: 備案 (主候選被 skip 時遞補)
- WATCH: 監控但已 skip 的標的

特性:
- 9:00-9:25 自動 entry screening、紅線 #9 (前 5 分 >5% skip) 內建
- 9:25+ 切到持倉 P&L 監控
- 停損突破 macOS 通知
- 30s 更新、彩色 console
"""
from __future__ import annotations

import argparse
import subprocess
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_SYS = Path("/Users/howard/Repository/stock-analysis-system")
if str(_SYS) not in sys.path:
    sys.path.insert(0, str(_SYS))

from clients.fubon_client import FubonClient  # noqa

DB = Path.home() / ".four_seasons" / "data.sqlite"

# ─────────────────────────────────────────────────────────────────────────
# 編輯區 (每天晚上鎖 plan 時改)
# ─────────────────────────────────────────────────────────────────────────

# 已進場部位 (Phase 2 P&L 監控): (tk, name, entry, shares, stop)
HELD = [
    ('6285', '啟碁', 315.0, 1000, 307.4),
    ('2485', '兆赫', 73.4,  5000, 70.0),
    ('1605', '華新', 40.1,  8000, 38.75),
]

# 已實現 (今日累計)
REALIZED = -21388  # 3016 嘉晶

# 鎖定主候選 (Phase 1 開盤 entry screening): (tk, name, target_shares, stop, 理由)
# = 你 23:00 鎖定的 plan 3 檔
PLAN_PRIMARY = [
    # 6/1 已進場、若 6/2 plan 改、編輯這裡
    # 範例: ('1605', '華新', 8000, 38.75, 'Tier-S 子弟兵'),
]

# 備案 (Phase 1 主候選被 skip 時遞補): (tk, name, target_shares, stop_pct, 理由)
PLAN_BACKUP = [
    # 範例: ('3149', '正達', 3000, 0.07, '老師台股康寧'),
]

# 已 SKIP 的監控 (萬一回穩): (tk, name, ref_close, stop, kind)
WATCH = [
    ('5425', '台半', 116.5, 113.0, 'SKIP'),
    ('2481', '強茂', 162.5, 178.5, 'SKIP'),
    ('3675', '德微', 413.0, 454.0, 'SKIP'),
    ('3016', '嘉晶', 138.0, 133.5, 'SOLD'),
]

# ─────────────────────────────────────────────────────────────────────────

class C:
    R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
    BOLD = '\033[1m'; DIM = '\033[2m'; END = '\033[0m'; CLR = '\033[H\033[J'


def notify_mac(title: str, msg: str):
    try:
        subprocess.run(['osascript', '-e',
                       f'display notification "{msg}" with title "{title}" sound name "Glass"'],
                       check=False, timeout=3)
    except Exception:
        print('\a', end='', flush=True)


def fmt_pnl(pnl: float, pct: float = 0) -> str:
    color = C.G if pnl >= 0 else C.R
    sign = '+' if pnl >= 0 else ''
    if pct != 0:
        return f"{color}{sign}{pnl:,.0f} ({sign}{pct:.1f}%){C.END}"
    return f"{color}{sign}{pnl:,.0f}{C.END}"


def fmt_dist(dist: float) -> str:
    if dist < 0: return f"{C.R}{dist:+.1f}%{C.END}"
    if dist < 1: return f"{C.Y}{dist:+.1f}%{C.END}"
    return f"{C.G}{dist:+.1f}%{C.END}"


def load_prev_close(ticker: str) -> float | None:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        con.close()
        return float(r[0]) if r else None
    except Exception:
        return None


def classify_open(open_price: float, prev_close: float) -> tuple[str, str, str]:
    """回 (level_emoji, msg, severity)."""
    if open_price <= 0 or prev_close <= 0:
        return ('?', '無資料', 'unknown')
    chg = (open_price - prev_close) / prev_close * 100
    if open_price >= prev_close * 1.095:
        return ('❌', f'接近漲停 ({chg:+.1f}%)、鎖死買不到', 'skip')
    if chg > 5.0:
        return ('❌', f'開盤 {chg:+.1f}% > +5% (紅線 #9)', 'skip')
    if chg > 3.0:
        return ('⚠️', f'開盤 {chg:+.1f}% (gap-up 警示)', 'warn')
    if chg >= 0:
        return ('✅', f'開盤 {chg:+.1f}% (穩定強、可進)', 'ok')
    if chg >= -3.0:
        return ('🟡', f'開盤 {chg:+.1f}% (小弱)', 'neutral')
    return ('🔴', f'開盤 {chg:+.1f}% (顯著弱、慎入)', 'weak')


def render_phase1_screener(client, now_str: str) -> list[str]:
    """Phase 1 開盤 entry screening (9:00-9:25)."""
    lines = [f"{C.BOLD}━━━ {now_str}  PHASE 1: 開盤 ENTRY SCREENING ━━━{C.END}"]

    # 持倉開盤健康度 (已進的、看 entry 是不是好價)
    if HELD:
        lines.append(f"{C.BOLD}📊 已持倉開盤健康度{C.END}")
        for tk, name, entry, shares, stop in HELD:
            try:
                snap = client.get_realtime_snapshot(tk)
                o = float(snap.get('open', 0))
                c = float(snap.get('close', 0))
                prev = load_prev_close(tk)
                level, msg, sev = classify_open(o, prev) if prev else ('?','no prev','unknown')
                # entry vs open: 你進的價跟開盤比、有沒有買在好點
                entry_vs_open = (entry - o)/o*100 if o else 0
                entry_vs_current = (entry - c)/c*100 if c else 0
                entry_tag = ''
                if entry_vs_open < -1:
                    entry_tag = f"{C.G}🎯 進得好 (低 open {entry_vs_open:.1f}%){C.END}"
                elif entry_vs_open > 1:
                    entry_tag = f"{C.Y}⚠️ 追高了 (高 open {entry_vs_open:+.1f}%){C.END}"
                else:
                    entry_tag = f"{C.DIM}入價貼開盤{C.END}"
                pnl = (c - entry)*shares
                lines.append(f"  {level} {tk} {name:6}  前${prev or 0:.1f}→開${o:.1f}→現${c:.1f}  入${entry:.1f}")
                lines.append(f"      {msg}")
                lines.append(f"      {entry_tag} | 帳面 {fmt_pnl(pnl)} | 停損 ${stop}")
            except Exception as e:
                lines.append(f"  {tk} err: {e}")
        lines.append("")

    if not PLAN_PRIMARY:
        if not HELD:
            lines.append(f"{C.DIM}PLAN_PRIMARY 空、編輯腳本開頭設定{C.END}")
        return lines

    lines.append(f"{C.BOLD}🎯 待進場主候選{C.END}")

    skipped = []
    for tk, name, shares, stop, reason in PLAN_PRIMARY:
        try:
            snap = client.get_realtime_snapshot(tk)
            o = float(snap.get('open', 0))
            c = float(snap.get('close', 0))
            prev = load_prev_close(tk)
            level, msg, sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
            chg_open = (o - prev)/prev*100 if prev else 0
            cost = o * shares
            lines.append(f"  {level} {tk} {name:6}  前${prev or 0:.1f}→開${o:.1f} ({chg_open:+.1f}%)  現${c:.1f}")
            lines.append(f"      {msg}")
            lines.append(f"      sizing: {shares} 股 ≈ ${cost:,.0f}、停損 ${stop}、{reason}")
            if sev in ('skip', 'warn'):
                skipped.append(tk)
        except Exception as e:
            lines.append(f"  {tk} {name}: err {e}")

    if skipped:
        lines.append("")
        lines.append(f"{C.BOLD}{C.Y}⚠️ {len(skipped)} 主候選 skip/警示、推薦備案 (按穩定強排序){C.END}")
        sev_order = {'ok': 0, 'neutral': 1, 'warn': 2, 'weak': 3, 'skip': 4, 'unknown': 5}
        backup_evaluated = []
        for tk, name, shares, stop_pct, reason in PLAN_BACKUP:
            try:
                snap = client.get_realtime_snapshot(tk)
                o = float(snap.get('open', 0))
                c = float(snap.get('close', 0))
                prev = load_prev_close(tk)
                level, msg, sev = classify_open(o, prev) if prev else ('?','no prev','unknown')
                chg_open = (o-prev)/prev*100 if prev else 0
                backup_evaluated.append((sev, -chg_open, tk, name, shares, prev, o, c, level, msg, reason, stop_pct))
            except Exception:
                pass
        backup_evaluated.sort(key=lambda x: (sev_order.get(x[0], 9), x[1]))
        for item in backup_evaluated[:3]:
            sev, _, tk, name, shares, prev, o, c, level, msg, reason, stop_pct = item
            stop = round((prev or 0) * (1 - stop_pct), 1)
            chg_open = (o - (prev or 1))/(prev or 1)*100
            cost = o * shares
            lines.append(f"  {level} {tk} {name:6}  前${prev or 0:.1f}→開${o:.1f} ({chg_open:+.1f}%)  現${c:.1f}")
            lines.append(f"      {msg}")
            lines.append(f"      sizing: {shares} 股 ≈ ${cost:,.0f}、停損 ${stop}、{reason}")
    else:
        lines.append(f"{C.G}✅ 主候選全部 OK、無需備案{C.END}")

    return lines


def render_phase2_holdings(client, now_str: str, prev_prices: dict, notified: set) -> list[str]:
    """Phase 2 持倉 P&L 監控 (9:25 後)."""
    lines = [f"{C.BOLD}━━━ {now_str}  PHASE 2: 持倉 P&L ━━━{C.END}"]
    total_pnl = 0.0

    if not HELD:
        lines.append(f"{C.DIM}未進場、無持倉監控{C.END}")
    else:
        for tk, name, entry, shares, stop in HELD:
            try:
                snap = client.get_realtime_snapshot(tk)
                c = float(snap.get('close', 0))
                prev = prev_prices.get(tk)
                prev_prices[tk] = c
                pnl = (c - entry) * shares
                pnl_pct = (c - entry)/entry*100 if entry else 0
                dist = (c - stop)/c*100 if c else 0
                total_pnl += pnl

                # 停損 alert
                key = f"{tk}_break"
                if dist < 0:
                    if key not in notified:
                        notified.add(key)
                        notify_mac(f"🚨 {tk} {name} 跌破停損 ${stop}",
                                   f"現 ${c:.1f}、損 ${pnl:,.0f}")
                else:
                    notified.discard(key)

                tag = '🔴破!' if dist<0 else ('⚠️緊' if dist<1 else '🟢')
                lines.append(f"  {tk} {name:6} 入${entry:.1f}×{shares}股 | "
                            f"現${c:.1f} | P&L {fmt_pnl(pnl, pnl_pct):>30} | 距停{fmt_dist(dist)} {tag}")
            except Exception as e:
                lines.append(f"  {tk} {name}: err {e}")

    today = total_pnl + REALIZED
    lines.append("")
    lines.append(f"  帳面 {fmt_pnl(total_pnl)} | 已實現 {fmt_pnl(REALIZED)} | 💰 今日 {fmt_pnl(today)}")

    # Watchlist
    if WATCH:
        lines.append("")
        lines.append(f"{C.DIM}Watchlist (SKIP){C.END}")
        for tk, name, ref, stop, kind in WATCH:
            try:
                snap = client.get_realtime_snapshot(tk)
                c = float(snap.get('close', 0))
                chg = (c-ref)/ref*100 if ref else 0
                dist = (c-stop)/c*100 if c else 0
                tag = '🔴弱' if dist<0 else '🟡守'
                chg_color = C.R if chg<0 else C.G
                lines.append(f"  {tk} {name:6} ${c:.1f} ({chg_color}{chg:+.1f}%{C.END}) 距停 {fmt_dist(dist)} {tag}")
            except Exception:
                pass

    return lines


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--interval', type=int, default=30)
    p.add_argument('--no-clear', action='store_true')
    p.add_argument('--no-notify', action='store_true')
    p.add_argument('--force-phase', choices=['1', '2'], help='強制階段、debug 用')
    args = p.parse_args()

    client = FubonClient()
    prev_prices = {}
    notified = set()

    while True:
        try:
            now = datetime.now()
            now_str = now.strftime('%H:%M:%S')
            h, m = now.hour, now.minute

            # 自動判斷階段
            in_phase1 = h == 9 and m <= 25
            if args.force_phase == '1':
                in_phase1 = True
            elif args.force_phase == '2':
                in_phase1 = False

            if not args.no_clear:
                print(C.CLR, end='')

            print(f"{C.BOLD}{C.B}=== 即時 monitor (interval {args.interval}s) ==={C.END}")
            print()

            if in_phase1:
                for line in render_phase1_screener(client, now_str):
                    print(line)
            else:
                for line in render_phase2_holdings(client, now_str, prev_prices, notified):
                    print(line)

            print()
            print(f"{C.DIM}下次 {args.interval}s | Ctrl+C 結束{C.END}")
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n{C.B}結束{C.END}")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(5)


if __name__ == '__main__':
    main()
