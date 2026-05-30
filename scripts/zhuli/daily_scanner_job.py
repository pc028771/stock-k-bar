"""每日盤後 scanner 批次任務 — 跑三個結構 scanner 找明日打擊區候選.

依 daily scanner enforcement 規則（每個開盤日前晚-早上未跑要提醒）。

每個交易日 14:30 由 launchd 觸發跑此 script:
  1. 跑 shakeout_strong + small_structure + w_bottom_launch 全市場
  2. 取聯集 → 候選清單
  3. shakeout_strong 命中 + 老師常駐族群 → 標 ⭐（EV +10.1% vs +5.1% baseline）
  4. 輸出 markdown 到 /tmp/scanner_candidates_<DATE>.md
  5. 寫 flag 到 /tmp/scanner_done_<DATE>.flag（給 morning_report 跟 Claude session 檢查）

Usage:
  python scripts/zhuli/daily_scanner_job.py [--date YYYY-MM-DD] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Path setup
_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.extras.shakeout_strong import detect as detect_shakeout        # noqa
from zhuli.entry.small_structure import run_scan as small_structure_scan  # noqa
from zhuli.entry.w_bottom_launch import detect as detect_wbottom          # noqa

# 以下 scanner 尚未驗證門檻值，暫不加入 daily job
# from zhuli.entry.bbands_upper_break import detect as detect_bbands
# from zhuli.entry.bollinger_pullback import detect as detect_bb_pullback
# from zhuli.entry.intraday import detect as detect_intraday
# from zhuli.entry.overnight_swing import detect as detect_overnight
# from zhuli.entry.open_signal_entry import detect as detect_open_entry
# from zhuli.entry.open_signal_exit import detect as detect_open_exit
# from zhuli.entry.open_signal_filter import detect as detect_open_filter
# from zhuli.entry.pennant_flag import detect as detect_pennant
# from zhuli.entry.reversal_breakout import detect as detect_reversal
# from zhuli.entry.suffocation import detect as detect_suffocation

_DB   = Path.home() / ".four_seasons" / "data.sqlite"
_TMP  = Path("/tmp")
_REPO = Path(__file__).parent.parent.parent

# 老師族群對應表（teacher_sector_tickers.json）
# ticker → [族群1, 族群2, ...]
def _load_teacher_sectors() -> dict[str, list[str]]:
    import json
    p = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    mapping: dict[str, list[str]] = {}
    for sector, tickers in data.items():
        for t in tickers:
            mapping.setdefault(t, []).append(sector)
    return mapping

TEACHER_SECTOR_MAP: dict[str, list[str]] = _load_teacher_sectors()


def _load_teacher_picks() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """讀 teacher_picks_2026.json. 回傳 (tier, name, first_mention) per ticker."""
    import json
    p = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
    if not p.exists():
        return {}, {}, {}
    raw = json.loads(p.read_text())
    tier, name, first = {}, {}, {}
    for t, info in raw.items():
        if t == '_meta':
            continue
        tier[t] = info.get('tier_signal', '')
        name[t] = info.get('name', '')
        mentions = info.get('mentions', [])
        if mentions:
            first[t] = min(m['date'] for m in mentions)
    return tier, name, first


TEACHER_TIER, TEACHER_NAME, TEACHER_FIRST = _load_teacher_picks()

# Tier-A ticker 清單（從 cross_reference.py 統計：老師指名 × P90+ rate ≥30%, n≥2）
TIER_A_WBOTTOM = {
    '3016', '3037', '3189', '3481', '4919', '8027', '6173',
    '2454', '3026', '4576', '4958', '8064', '2327', '6285',
}
TIER_A_SMALLSTR = {
    '2303', '3189', '4958', '2454', '3036', '8103', '3702', '4919',
}

# 老師 core 但回測未抓到的 ticker（單獨觀察清單）
CORE_UNCOVERED = ['1605', '6664', '6217', '6207', '1785']

# 進場可行性門檻（距 MA10）
MA10_DIST_ENTRY_OK = 5.0    # ≤5% 距 MA10 = 最佳進場
MA10_DIST_RISKY = 10.0      # 5-10% = 可考慮、>10% = 已起漲、移至觀察


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def load_stock_info(db_path: Path) -> dict[str, dict]:
    """回傳 {ticker: {name, industry}} 對照表."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)
    rows = con.execute(
        "SELECT ticker, stock_name, industry_category FROM stock_info"
    ).fetchall()
    con.close()
    return {r[0]: {"name": r[1], "industry": r[2] or ""} for r in rows}


def _build_hit_dict(
    t: str,
    df: pd.DataFrame,
    scanner_name: str,
    stock_info: dict,
    target_date: str,
    vol_ratio_min: float,
    exit_strategy: str,
) -> dict | None:
    """單 ticker + scanner 命中後建立 hit dict，回傳 None 表示過濾掉."""
    last_row = df.iloc[-1]
    last_close = last_row['close']
    last_vol_ratio = float(last_row['vol_ratio_20']) if pd.notna(last_row.get('vol_ratio_20')) else 0

    if last_vol_ratio < vol_ratio_min:
        return None

    info = stock_info.get(t, {"name": "", "industry": ""})
    teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])

    ma10 = float(last_row['ma10']) if pd.notna(last_row.get('ma10')) else None
    if scanner_name in ('w_bottom_launch', 'shakeout_strong') and ma10:
        stop_note = f"MA10停利 ~{ma10:.2f}"
    else:
        stop_px = round(float(df.iloc[-6:-1]['close'].min()), 2)
        stop_note = f"守底{stop_px:.2f}"

    dist_ma10 = None
    if ma10 and ma10 > 0:
        dist_ma10 = round((float(last_close) - ma10) / ma10 * 100, 1)

    teacher_tier = TEACHER_TIER.get(t, '')
    days_since = None
    if t in TEACHER_FIRST:
        days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

    tier = '一般'
    timing_bonus = ''
    if scanner_name == 'w_bottom_launch':
        if t in TIER_A_WBOTTOM:
            tier = '🔥 Tier-A'
        elif teacher_tier in ('core', 'frequent'):
            tier = '⭐ Tier-B'
        if days_since is not None and 8 <= days_since <= 30:
            timing_bonus = ' ✨黃金期'
    elif scanner_name == 'small_structure':
        if t in TIER_A_SMALLSTR:
            tier = '🔥 Tier-A'
        elif teacher_tier in ('core', 'frequent'):
            tier = '⭐ Tier-B'
        if days_since is not None and days_since > 30:
            timing_bonus = ' ✨二波期'
    elif scanner_name == 'shakeout_strong':
        tier = '➕ 加碼用'

    return {
        'ticker': t,
        'name': info['name'],
        'industry': info['industry'],
        'teacher_sectors': teacher_sectors,
        'close': float(last_close),
        'vol_ratio': round(last_vol_ratio, 1),
        'stop_note': stop_note,
        'exit_strategy': exit_strategy,
        'tier': tier,
        'timing_bonus': timing_bonus,
        'teacher_tier': teacher_tier,
        'days_since_first_mention': days_since,
        'dist_ma10_pct': dist_ma10,
    }


def run_scanners(target_date: str, db_path: Path) -> dict[str, list[dict]]:
    """跑三個 scanner 並回傳每個的命中清單.

    small_structure 改用 run_scan(combined_df, universe='sector_week')，
    由 watchlist.py 統一處理族群過濾 + tier 分類。
    shakeout_strong + w_bottom_launch 維持原有 per-ticker 邏輯。
    """
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
    stock_info = load_stock_info(db_path)

    # 全市場 ticker
    all_tickers = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
            (target_date,)
        ).fetchall()
    ]

    results = {'shakeout_strong': [], 'small_structure': [], 'w_bottom_launch': []}

    # ⚠️ 只放已驗證門檻的 scanner
    VOL_RATIO_MIN = {
        'w_bottom_launch': 2.0,
        'shakeout_strong': 2.0,
    }
    EXIT_STRATEGY = {
        'w_bottom_launch': 'ma5_trail',
        'small_structure': 'structural_low',
        'shakeout_strong': 'ma5_trail',
    }

    # ── shakeout_strong + w_bottom_launch：維持 per-ticker 邏輯 ─────────────
    per_ticker_scanners = {
        'w_bottom_launch': detect_wbottom,   # 84% 上漲、平均 +2.54%（已驗證）
        'shakeout_strong': detect_shakeout,  # 3/3 案例命中（已驗證，需 overhead 特徵）
    }

    # 同時載入 df，供 small_structure combined df 使用
    ticker_dfs: dict[str, pd.DataFrame] = {}

    for t in all_tickers:
        df = pd.read_sql("""
            SELECT ? as ticker,
                   trade_date, trade_date as date,
                   open, high, low, close, volume,
                   vol_ratio_20, ma5, ma10, ma20, ma60,
                   vol_ma20, bb_upper, bb_lower, bb_mid,
                   ma20_slope, ma20_slope_proxy
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(t, t, target_date, target_date))
        if len(df) < 100:
            continue

        # 補充 derived columns
        df['prev_close'] = df['close'].shift(1)
        df['prev_open'] = df['open'].shift(1)
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        df['ma5_slope_5d'] = df['ma5'].diff(5)
        df['volume_ratio'] = df['vol_ratio_20']  # alias

        ticker_dfs[t] = df

        for scanner_name, fn in per_ticker_scanners.items():
            try:
                sig = fn(df)
                if hasattr(sig, 'iloc') and sig.iloc[-1]:
                    hit = _build_hit_dict(
                        t, df, scanner_name, stock_info, target_date,
                        VOL_RATIO_MIN[scanner_name], EXIT_STRATEGY[scanner_name],
                    )
                    if hit is not None:
                        results[scanner_name].append(hit)
            except Exception:
                pass

    con.close()

    # ── small_structure：改用 run_scan(combined_df, universe='sector_week') ──
    # run_scan 在 watchlist_mode=True 時呼叫 run_watchlist，
    # 內部處理 sector_week 過濾 + 條件命中分 tier，不再需要 per-ticker iteration。
    print(f"  [small_structure] 使用 run_scan(universe='sector_week')...")
    try:
        if ticker_dfs:
            combined_df = pd.concat(list(ticker_dfs.values()), ignore_index=True)
            ss_wl = small_structure_scan(
                combined_df,
                target_date=target_date,
                universe='sector_week',
                watchlist_mode=True,
            )
        else:
            ss_wl = pd.DataFrame()

        if ss_wl is None or (hasattr(ss_wl, 'empty') and ss_wl.empty):
            print("  [small_structure] sector_week 無主推族群或無命中 → 候選數 0")
            ss_wl = pd.DataFrame()

        # 將 watchlist DataFrame 轉成與其他 scanner 相同格式的 hit dict list
        for _, row in ss_wl.iterrows():
            t = row.get('ticker', '')
            if not t:
                continue
            df_t = ticker_dfs.get(t)
            if df_t is None or df_t.empty:
                # 沒有載入此 ticker 的 df（可能 <100 筆被過濾），用 row 欄位補
                last_close = row.get('close', 0)
                ma10_val = None
                last_vol_ratio = 0.0
                stop_note = '—'
                dist_ma10 = None
            else:
                last_row = df_t.iloc[-1]
                last_close = last_row['close']
                last_vol_ratio = float(last_row['vol_ratio_20']) if pd.notna(last_row.get('vol_ratio_20')) else 0
                ma10_val = float(last_row['ma10']) if pd.notna(last_row.get('ma10')) else None
                stop_px = round(float(df_t.iloc[-6:-1]['close'].min()), 2)
                stop_note = f"守底{stop_px:.2f}"
                dist_ma10 = round((float(last_close) - ma10_val) / ma10_val * 100, 1) if ma10_val else None

            info = stock_info.get(t, {"name": "", "industry": ""})
            teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
            teacher_tier = TEACHER_TIER.get(t, '')
            days_since = None
            if t in TEACHER_FIRST:
                days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

            # Tier mapping：watchlist tier → daily_scanner_job tier
            wl_tier = row.get('tier', '')
            if wl_tier == '🔥 高機率':
                tier = '🔥 Tier-A' if t in TIER_A_SMALLSTR else ('⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般')
            elif wl_tier == '⚠️ 中機率':
                tier = '⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般'
            else:
                tier = '一般'

            timing_bonus = ' ✨二波期' if (days_since is not None and days_since > 30) else ''

            hit = {
                'ticker': t,
                'name': info['name'],
                'industry': info['industry'],
                'teacher_sectors': teacher_sectors,
                'close': float(last_close),
                'vol_ratio': round(last_vol_ratio, 1),
                'stop_note': stop_note,
                'exit_strategy': EXIT_STRATEGY['small_structure'],
                'tier': tier,
                'timing_bonus': timing_bonus,
                'teacher_tier': teacher_tier,
                'days_since_first_mention': days_since,
                'dist_ma10_pct': dist_ma10,
            }
            results['small_structure'].append(hit)

    except Exception as e:
        print(f"  [small_structure] run_scan 失敗: {e}（小結構候選數 0）")

    return results


def _primary_stop(stop_notes: dict) -> str:
    """多 scanner 命中時取主要停損備注（shakeout > w_bottom > small_structure）."""
    for s in ('shakeout_strong', 'w_bottom_launch', 'small_structure'):
        if s in stop_notes:
            return stop_notes[s]
    return '—'


def _tier_rank(hit: dict) -> int:
    """Tier 排序鍵（越小越優先）."""
    t = hit.get('tier', '一般')
    bonus = hit.get('timing_bonus', '')
    if t == '🔥 Tier-A' and bonus:
        return 0
    if t == '🔥 Tier-A':
        return 1
    if t == '⭐ Tier-B' and bonus:
        return 2
    if t == '⭐ Tier-B':
        return 3
    if t == '➕ 加碼用':
        return 4
    return 5


def _format_hit_row(h: dict, show_scanner=False) -> str:
    """單列輸出 markdown."""
    parts = [h['ticker'], h.get('name', '')]
    if show_scanner:
        parts.append(h.get('scanner_name', ''))
    sectors = h.get('teacher_sectors', [])
    parts.append('/'.join(sectors) if sectors else h.get('industry', ''))
    parts.append(f"{h['close']:.2f}")
    parts.append(f"{h.get('vol_ratio', '—')}x")
    d = h.get('dist_ma10_pct')
    parts.append(f"{d:+.1f}%" if d is not None else '—')
    days = h.get('days_since_first_mention')
    parts.append(f"{days}d" if days is not None else '—')
    tt = h.get('teacher_tier', '')
    parts.append(tt if tt else '—')
    parts.append(h.get('stop_note', '—'))
    return '| ' + ' | '.join(parts) + ' |'


def render_markdown(target_date: str, results: dict[str, list[dict]]) -> str:
    """產出 Tier-based 打擊區候選 markdown."""
    # 把每個 hit 帶 scanner_name 後 flatten 成單一 list
    all_hits = []
    for scanner, hits in results.items():
        for h in hits:
            h = dict(h)
            h['scanner_name'] = scanner
            all_hits.append(h)

    # 加碼判斷：shakeout 命中且該 ticker 30 天內有 W底/小結構訊號 → 標 ➕
    prior_entries = set()
    for h in all_hits:
        if h['scanner_name'] in ('w_bottom_launch', 'small_structure'):
            prior_entries.add(h['ticker'])
    for h in all_hits:
        if h['scanner_name'] == 'shakeout_strong' and h['ticker'] in prior_entries:
            h['has_prior_entry'] = True
        else:
            h['has_prior_entry'] = False

    # 分組
    def in_section(h, section):
        d = h.get('dist_ma10_pct')
        tier = h.get('tier', '一般')
        # 進場區：Tier-A/B 且距 MA10 ≤ MA10_DIST_RISKY
        if section == 'entry':
            return tier in ('🔥 Tier-A', '⭐ Tier-B') and (d is None or d <= MA10_DIST_RISKY)
        if section == 'extended':  # 已起漲（後續觀察）
            return tier in ('🔥 Tier-A', '⭐ Tier-B') and d is not None and d > MA10_DIST_RISKY
        if section == 'add_position':
            return h['scanner_name'] == 'shakeout_strong' and h.get('has_prior_entry')
        if section == 'general':
            return tier == '一般' and h['scanner_name'] != 'shakeout_strong'
        return False

    entry_hits = sorted([h for h in all_hits if in_section(h, 'entry')],
                       key=lambda h: (_tier_rank(h), h.get('dist_ma10_pct') or 999))
    extended_hits = sorted([h for h in all_hits if in_section(h, 'extended')],
                          key=lambda h: (_tier_rank(h), h.get('dist_ma10_pct') or 999))
    add_position_hits = sorted([h for h in all_hits if in_section(h, 'add_position')],
                              key=lambda h: h['ticker'])
    general_hits = sorted([h for h in all_hits if in_section(h, 'general')],
                         key=lambda h: -(h.get('vol_ratio') or 0))

    md = [
        f"# 打擊區候選 — {target_date} 收盤後",
        f"",
        f"> Tier 排序：🔥 Tier-A（P90+ 高機率）→ ⭐ Tier-B（老師指名）→ ➕ 加碼 → 一般",
        f"> ✨黃金期 = W底 + 老師首提 8-30天；✨二波期 = 小結構 + 老師首提 >30天",
        f"> 「距MA10」> 10% 表示已起漲、移至「後續觀察名單」",
        f"",
        f"## 各 scanner 統計",
        f"",
        f"| Scanner | 命中數 |",
        f"|---|---|",
    ]
    for s, hits in results.items():
        md.append(f"| {s} | {len(hits)} |")
    md.append(f"| **可進場** (Tier-A/B 距MA10≤10%) | **{len(entry_hits)}** |")
    md.append(f"| **後續觀察** (Tier-A/B 但已起漲) | **{len(extended_hits)}** |")
    md.append(f"| **加碼候選** (Shakeout + 已有訊號) | **{len(add_position_hits)}** |")
    md += [f""]

    # === 可進場區 ===
    if entry_hits:
        md += [
            f"## 🎯 可進場 — Tier-A/B 候選（距 MA10 ≤ 10%）",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 量比 | 距MA10 | 首提後 | 老師 | 停損 |",
            f"|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in entry_hits:
            tier_label = h.get('tier', '') + h.get('timing_bonus', '')
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            days = h.get('days_since_first_mention')
            days_str = f"{days}d" if days is not None else '—'
            md.append(f"| **{h['ticker']}** {tier_label} | {h['name']} | {h['scanner_name']} | "
                      f"{sectors_str} | {h['close']:.2f} | {h.get('vol_ratio', '—')}x | "
                      f"{h.get('dist_ma10_pct', 0):+.1f}% | {days_str} | "
                      f"{h.get('teacher_tier') or '—'} | {h.get('stop_note', '—')} |")
        md.append(f"")

    # === 後續觀察區（已起漲）===
    if extended_hits:
        md += [
            f"## ⚠️ 後續觀察 — Tier-A/B 但已起漲（距 MA10 > 10%）",
            f"",
            f"> 等回測 MA10 附近再進場；現在追進場潛在虧損 = 距 MA10",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 距MA10 | 老師 | 備註 |",
            f"|---|---|---|---|---|---|---|---|",
        ]
        for h in extended_hits:
            tier_label = h.get('tier', '') + h.get('timing_bonus', '')
            md.append(f"| {h['ticker']} {tier_label} | {h['name']} | {h['scanner_name']} | "
                      f"{'/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')} | "
                      f"{h['close']:.2f} | {h.get('dist_ma10_pct', 0):+.1f}% | "
                      f"{h.get('teacher_tier') or '—'} | "
                      f"距 MA10 太遠，等回測 |")
        md.append(f"")

    # === 加碼候選 ===
    if add_position_hits:
        md += [
            f"## ➕ 加碼候選 — Shakeout × 已有 W底/小結構訊號",
            f"",
            f"> 30 天內已有進場訊號的 ticker 出現 shakeout（主力洗盤後爆量）= 加碼確認",
            f"> 沒持倉者不要當第一次進場用（Shakeout 冷進場效果差）",
            f"",
            f"| Ticker | 名稱 | 族群 | 收盤 | 量比 | 距MA10 |",
            f"|---|---|---|---|---|---|",
        ]
        for h in add_position_hits:
            md.append(f"| {h['ticker']} | {h['name']} | "
                      f"{'/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')} | "
                      f"{h['close']:.2f} | {h.get('vol_ratio', '—')}x | "
                      f"{h.get('dist_ma10_pct', 0):+.1f}% |")
        md.append(f"")

    # === 老師 core 但 scanner 未抓到 ===
    md += [
        f"## 📋 老師 core 級指名（scanner 未命中，手動關注）",
        f"",
        f"| Ticker | 名稱 |",
        f"|---|---|",
    ]
    for t in CORE_UNCOVERED:
        n = TEACHER_NAME.get(t, '')
        md.append(f"| {t} | {n} |")
    md += [f""]

    # === 一般候選（壓縮顯示）===
    if general_hits:
        md += [
            f"## 一般命中（無老師指名/非常勝軍，量比降冪前 30）",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 量比 | 距MA10 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for h in general_hits[:30]:
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            md.append(f"| {h['ticker']} | {h['name']} | {h['scanner_name']} | "
                      f"{sectors_str} | {h['close']:.2f} | {h.get('vol_ratio', '—')}x | {d_str} |")
        md.append(f"")

    md += [
        f"---",
        f"",
        f"## 出場策略 + Tier 來源",
        f"",
        f"- W底/Shakeout: **MA10 收盤跌破 → 隔日 open 出**",
        f"- 小結構: **整理底收盤跌破出**（或同 MA10 兩擇一）",
        f"- Tier-A 來源：2026 回測（P90+ ≥30% 命中率 + 老師 core/frequent，n≥2）",
        f"",
        f"產生時間: {datetime.now():%Y-%m-%d %H:%M:%S}",
    ]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="目標收盤日（預設今天）")
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--output-dir", default="/tmp")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    db_path = Path(args.db)
    out_dir = Path(args.output_dir)

    print(f"=== Daily Scanner Job ===")
    print(f"目標日期: {target_date}")
    print(f"DB: {db_path}")
    print()

    results = run_scanners(target_date, db_path)

    print(f"\n結果:")
    for s, hits in results.items():
        print(f"  {s}: {len(hits)} 檔")

    md = render_markdown(target_date, results)

    out_md = out_dir / f"scanner_candidates_{target_date}.md"
    out_md.write_text(md, encoding="utf-8")
    print(f"\n→ 寫入 {out_md}")

    flag = out_dir / f"scanner_done_{target_date}.flag"
    flag.write_text(f"done at {datetime.now().isoformat()}\n")
    print(f"→ flag {flag}")


if __name__ == "__main__":
    main()
