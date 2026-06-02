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
    # 6285: 6/2 尾盤 306 出 1 張 (加碼那張)、剩 1 張 @ 315 (老師明示原始)
    # Stage 1 / 3 (老師明示首發、可分批至 3 張)
    # Stage 2 觸發: 307-313 紅 K + 量縮 + 不破 307.5 → 加 1 張
    # Stage 3 觸發: 突破 320 + 量 ≥ 1.5x + 站 2 天 + 漲 ≥ 346.5 → 加最後 1 張
    ('6285', '啟碁', 315.0, 1000, 307.4),
    ('1605', '華新', 40.1,  8000, 38.75),
]

# 已實現 (今日累計、每日歸零)
REALIZED = 0

# 鎖定主候選 (Phase 1 開盤 entry screening): (tk, name, target_shares, stop, 理由)
# 6/3 主推
PLAN_PRIMARY = [
    ('4722', '國精化', 1000, 268.0, '🔒A 處置 D+6、三軸 🟢、流動性差 sizing 1 張試水、停損 268'),
]

# 備案 (Phase 1 主候選被 skip 時遞補): (tk, name, target_shares, stop, 理由)
# 6/3 全 skip、結構壞 + 籌碼弱
PLAN_BACKUP = []

# 觀察清單: (tk, name, ref_close, stop, kind)
WATCH = [
    ('6207', '雷科',   127.0, 115.0, '🟡 距 MA10 +9.4%、等回測 115-120 守住、外資 6/2 -1,606'),
    ('8046', '南電',   862.0, 834.0, '🔴 MA5/10/20 全破、外資 -3,125、待結構修復'),
    ('1717', '長興',    78.7, None,  '🔴 外資 6/2 -9,497 巨賣、結構壞、AI 內部追蹤'),
]

# ─────────────────────────────────────────────────────────────────────────

class C:
    R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
    BOLD = '\033[1m'; DIM = '\033[2m'; END = '\033[0m'
    # 無閃爍 frame: cursor home (不清螢幕)、每行用 EOL 清殘字
    HOME = '\033[H'         # 游標回左上
    EOL  = '\033[K'         # 清除到行尾 (蓋掉前一 frame 殘字)
    ALT_ON  = '\033[?1049h'  # 進 alt screen (退出後還原原 terminal 內容)
    ALT_OFF = '\033[?1049l'
    HIDE = '\033[?25l'       # 隱藏游標
    SHOW = '\033[?25h'
    CLR = HOME              # 向後相容、舊用法直接等於 HOME


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
                snap = client.get_realtime_snapshot(tk) or {}
                o = float(snap.get('open') or 0)
                c = float(snap.get('close') or 0)
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
            snap = client.get_realtime_snapshot(tk) or {}
            o = float(snap.get('open') or 0)
            c = float(snap.get('close') or 0)
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
                snap = client.get_realtime_snapshot(tk) or {}
                o = float(snap.get('open') or 0)
                c = float(snap.get('close') or 0)
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
        from datetime import datetime as _dt
        _now = _dt.now()
        _market_open = (_now.hour, _now.minute) >= (9, 0) and (_now.hour, _now.minute) < (13, 30)
        for tk, name, entry, shares, stop in HELD:
            try:
                snap = client.get_realtime_snapshot(tk)
                no_data = snap is None or not snap.get('close')
                if no_data:
                    if _market_open:
                        # 盤中卻沒資料 = Fubon API 接不到
                        data_status = f"{C.R}❌ API err{C.END}"
                    else:
                        data_status = f"{C.DIM}盤前{C.END}"
                    c = load_prev_close(tk) or entry
                else:
                    data_status = f"{C.G}LIVE{C.END}"
                    c = float(snap['close'])
                prev = prev_prices.get(tk)
                prev_prices[tk] = c
                pnl = (c - entry) * shares
                pnl_pct = (c - entry)/entry*100 if entry else 0
                dist = (c - stop)/c*100 if c else 0
                if not no_data:
                    total_pnl += pnl
                pre_market = no_data  # 向後相容

                # 停損 alert
                key = f"{tk}_break"
                if dist < 0:
                    if key not in notified:
                        notified.add(key)
                        notify_mac(f"🚨 {tk} {name} 跌破停損 ${stop}",
                                   f"現 ${c:.1f}、損 ${pnl:,.0f}")
                else:
                    notified.discard(key)

                if no_data:
                    tag = data_status
                else:
                    tag = '🔴破!' if dist<0 else ('⚠️緊' if dist<1 else '🟢')
                lines.append(f"  {tk} {name:6} 入${entry:.1f}×{shares}股 | "
                            f"{'昨' if no_data else '現'}${c:.1f} | P&L {fmt_pnl(pnl, pnl_pct):>30} | 距停{fmt_dist(dist)} {tag}")
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
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0)
                if c == 0:
                    c = load_prev_close(tk) or ref
                    pre = True
                else:
                    pre = False
                chg = (c-ref)/ref*100 if ref else 0
                dist = (c-stop)/c*100 if (c and stop) else 0
                tag = f"{C.DIM}盤前{C.END}" if pre else ('🔴弱' if (stop and dist<0) else '🟡守')
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

    # 進 alt screen + 隱藏游標（退出時還原）
    use_alt = not args.no_clear
    if use_alt:
        sys.stdout.write(C.ALT_ON + C.HIDE)
        sys.stdout.flush()

    def _emit(line: str):
        # 每行尾接 EOL 清殘字、避免新 frame 內容比舊 frame 短時留鬼影
        sys.stdout.write(line + C.EOL + '\n')

    try:
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

                if use_alt:
                    # 只回左上、不清螢幕 → 無閃爍
                    sys.stdout.write(C.HOME)

                _emit(f"{C.BOLD}{C.B}=== 即時 monitor (interval {args.interval}s)  {now_str} ==={C.END}")
                _emit("")

                if in_phase1:
                    for line in render_phase1_screener(client, now_str):
                        _emit(line)
                else:
                    for line in render_phase2_holdings(client, now_str, prev_prices, notified):
                        _emit(line)

                _emit("")
                _emit(f"{C.DIM}下次 {args.interval}s | Ctrl+C 結束{C.END}")
                # 清剩餘螢幕（蓋掉舊 frame 殘留行）
                sys.stdout.write('\033[J')
                sys.stdout.flush()
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                _emit(f"[ERROR] {e}")
                sys.stdout.flush()
                time.sleep(5)
    finally:
        if use_alt:
            sys.stdout.write(C.SHOW + C.ALT_OFF)
            sys.stdout.flush()
        print(f"{C.B}結束{C.END}")


if __name__ == '__main__':
    main()
