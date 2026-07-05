#!/usr/bin/env python3
"""Frank 戰法 detector 全集（純函式、無 DB 依賴）

課程內規則、對應 docs/frank/*/detector_specs.md。輸入統一：
  daily bar = dict(date, open, high, low, close, volume, ma5, ma10, ma20,
                   ma20_slope, bb_position, vol_ratio_20)  # 缺鍵視為 None
  m5 bar    = dict(ts, open, high, low, close, volume)

命名 = spec 的 detector id。回傳 dict(ok/signal, reason, ...)。
"""
from __future__ import annotations


def _g(bar, key):
    return bar.get(key) if bar else None


# ────────────────────── 核心戰法 ──────────────────────

def frank_2_entry(today: dict, prev: dict) -> dict:
    """戰法二進場（中軌分歧近似）: ma20↑ + close>ma20 + 回5MA再上."""
    c, ma5, ma20, slope = _g(today, "close"), _g(today, "ma5"), _g(today, "ma20"), _g(today, "ma20_slope")
    pc, pma5 = _g(prev, "close"), _g(prev, "ma5")
    if None in (c, ma5, ma20, slope, pc, pma5):
        return {"signal": False, "reason": "資料缺"}
    ok = slope > 0 and c > ma20 and pc <= pma5 and c > ma5
    return {"signal": ok, "reason": "回5MA再上" if ok else "條件未齊"}


def frank_score(today: dict, prev: dict, wall_high: float | None) -> dict:
    """戰法分數: 過城牆+2 / 頭頭高+1 / 壓布林頂+1 / 出量+1。score 0 = 反向 skip."""
    c = _g(today, "close")
    score, det = 0, []
    if wall_high and c and c > wall_high:
        score += 2; det.append("過城牆")
    if _g(prev, "high") and c and c > prev["high"]:
        score += 1; det.append("頭頭高")
    if (_g(today, "bb_position") or 0) >= 80:
        score += 1; det.append("壓布林頂")
    if (_g(today, "vol_ratio_20") or 0) >= 1.5:
        score += 1; det.append("出量")
    return {"score": score, "detail": det, "skip": score == 0}


def frank_exit_layer(bars: list[dict], opened_bb: bool, below_ma20_days: int) -> dict:
    """分層出場: 開布林→守5日 / 否則連2日破月線 or 月線下彎."""
    t = bars[-1]
    c, ma5, ma20, slope = _g(t, "close"), _g(t, "ma5"), _g(t, "ma20"), _g(t, "ma20_slope")
    if None in (c, ma5, ma20, slope):
        return {"exit": False, "reason": "資料缺", "below_ma20_days": below_ma20_days}
    if (_g(t, "bb_position") or 0) > 100:
        opened_bb = True
    if opened_bb:
        return {"exit": c < ma5, "reason": "破5日" if c < ma5 else "守5日中",
                "opened_bb": True, "below_ma20_days": 0}
    below = below_ma20_days + 1 if c < ma20 else 0
    if slope < 0:
        return {"exit": True, "reason": "月線下彎", "opened_bb": False, "below_ma20_days": below}
    return {"exit": below >= 2, "reason": f"破月線{below}日" if below else "守月線中",
            "opened_bb": False, "below_ma20_days": below}


# ────────────────────── 飆股 / 轉折 daily ──────────────────────

def frank_hot_stock_3_5_rule(bars: list[dict]) -> dict:
    """連 2 根 +5% 紅K → 第 3 天警戒；過 3 看 5；5 還噴 = 妖股."""
    if len(bars) < 3:
        return {"alert": None, "reason": "bars<3"}
    def big_red(i):
        b, p = bars[i], bars[i - 1]
        return (b["close"] and p["close"] and b["close"] > (b.get("open") or 0)
                and (b["close"] / p["close"] - 1) >= 0.05)
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        if big_red(i):
            n += 1
        else:
            break
    if n >= 5:
        return {"alert": "妖股", "streak": n, "reason": "連5+根大紅、乖離極大"}
    if n >= 4:
        return {"alert": "day5警戒", "streak": n, "reason": "明天=第5天、開盤看5m關鍵K"}
    if n >= 2:
        return {"alert": "day3警戒", "streak": n, "reason": "明天=第3天回檔高風險、開盤看5m關鍵K"}
    return {"alert": None, "streak": n, "reason": "無連續大紅"}


def frank_sunrise_line(bars: list[dict]) -> dict:
    """日出線: 連3根跌K + 收腳K + 紅K收過收腳K高。共識=守日出K低."""
    if len(bars) < 5:
        return {"signal": False, "reason": "bars<5"}
    t = bars[-1]
    if not (t.get("open") and t["close"] > t["open"]):
        return {"signal": False, "reason": "今日非紅K"}
    foot = bars[-2]  # 收腳K候選
    if t["close"] <= (foot.get("high") or 9e9):
        return {"signal": False, "reason": "未收過收腳K高"}
    lo_body = min(foot.get("open") or 0, foot["close"])
    if not (foot.get("low") is not None and lo_body > foot["low"]):
        return {"signal": False, "reason": "前根無收腳（下影）"}
    seg = [b["close"] for b in bars[-5:-1]]  # 收腳K含在內、往前 4 根
    down = sum(1 for a, b in zip(seg, seg[1:]) if b < a)
    if down < 3:
        return {"signal": False, "reason": f"前置連跌不足({down}/3)"}
    return {"signal": True, "defend": t.get("low"), "reason": "日出成立、守日出K低"}


def frank_sunset_line(bars: list[dict]) -> dict:
    """日落線: 連3根漲K + 上影K + 黑K收破上影K低。共識=日落K高不過."""
    if len(bars) < 5:
        return {"signal": False, "reason": "bars<5"}
    t = bars[-1]
    if not (t.get("open") and t["close"] < t["open"]):
        return {"signal": False, "reason": "今日非黑K"}
    shadow = bars[-2]
    hi_body = max(shadow.get("open") or 0, shadow["close"])
    if not (shadow.get("high") is not None and shadow["high"] > hi_body):
        return {"signal": False, "reason": "前根無上影"}
    if t["close"] >= (shadow.get("low") or 0):
        return {"signal": False, "reason": "未收破上影K低"}
    seg = [b["close"] for b in bars[-5:-1]]
    up = sum(1 for a, b in zip(seg, seg[1:]) if b > a)
    if up < 3:
        return {"signal": False, "reason": f"前置連漲不足({up}/3)"}
    return {"signal": True, "cap": t.get("high"), "reason": "日落成立、日落K高=壓"}


def frank_kd_divergence(closes: list[float], k_values: list[float], lookback: int = 40) -> dict:
    """KD 背離（近2波）: 價創新低KD沒創低=低背；價創新高KD沒創高=高背."""
    if len(closes) < lookback or len(k_values) < lookback:
        return {"divergence": None, "reason": f"bars<{lookback}"}
    c, k = closes[-lookback:], k_values[-lookback:]
    half = lookback // 2
    lo1, lo2 = min(c[:half]), min(c[half:])
    klo1, klo2 = min(k[:half]), min(k[half:])
    hi1, hi2 = max(c[:half]), max(c[half:])
    khi1, khi2 = max(k[:half]), max(k[half:])
    if lo2 < lo1 and klo2 > klo1:
        return {"divergence": "low", "reason": "低檔背離：價創低KD墊高 → 留意日出+分歧"}
    if hi2 > hi1 and khi2 < khi1:
        return {"divergence": "high", "reason": "高檔背離：價創高KD下不去 → 留意日落"}
    return {"divergence": None, "reason": "無背離"}


def frank_daily_neckline(bars: list[dict], window: int = 60) -> dict:
    """頸線2步驟: 壓力位多次撞不過 → 突破後回測守住 = 頸線."""
    if len(bars) < window:
        return {"neckline": None, "reason": f"bars<{window}"}
    seg = bars[-window:]
    highs = [b["high"] for b in seg if b.get("high")]
    if not highs:
        return {"neckline": None, "reason": "無high資料"}
    res = max(highs[: window // 2])          # 前半段壓力
    later = seg[window // 2:]
    broke = [b for b in later if b["close"] > res]
    if not broke:
        return {"neckline": None, "reason": "壓力未突破"}
    after_break = later[later.index(broke[0]):]
    retests = [b for b in after_break[1:] if b.get("low") and b["low"] <= res * 1.02]
    held = retests and all(b["close"] >= res * 0.99 for b in retests)
    if held:
        return {"neckline": res, "reason": f"頸線 {res} 成立（突破+回測守住）、收破才出"}
    return {"neckline": None, "reason": "突破但回測未守/未回測"}


def frank_bottom_3_soldiers(bars: list[dict]) -> dict:
    """底部紅三兵: 連2日爆量後、第3日要過高才成立."""
    if len(bars) < 4:
        return {"formed": None, "reason": "bars<4"}
    d1, d2, d3 = bars[-3], bars[-2], bars[-1]
    burst = all((b.get("vol_ratio_20") or 0) >= 1.5 for b in (d1, d2))
    if not burst:
        return {"formed": None, "reason": "前2日非連續爆量"}
    if d3["close"] > (max(d1.get("high") or 0, d2.get("high") or 0)):
        return {"formed": True, "reason": "第3日過高、紅三兵成立"}
    return {"formed": False, "reason": "第3日未過高 → 失敗、觸發開低脫逃 SOP"}


def frank_credit_ratio_trend(ratios: list[float]) -> dict:
    """券資比趨勢: 攀升=空軍燃料、由升轉降=小心（僅強勢股適用）."""
    if len(ratios) < 5:
        return {"trend": None, "reason": "資料<5日"}
    up = sum(1 for i in range(-4, 0) if ratios[i] > ratios[i - 1])
    if ratios[-1] < ratios[-2] < ratios[-3]:
        return {"trend": "falling", "reason": "券資比連降 → 強勢股要更小心"}
    if up >= 3:
        return {"trend": "rising", "reason": "券資比攀升 → 空軍燃料、上漲延續"}
    return {"trend": "flat", "reason": "無明確趨勢"}


def frank_lock_limit_up_next_day(prev_close: float, today_open: float,
                                  today_low: float | None = None) -> dict:
    """鎖漲停隔日 SOP: 開高≥2.5%安全 / 破平盤出觀望 / 開低直接離場."""
    gap = (today_open / prev_close - 1) * 100
    if gap < 0:
        return {"action": "exit", "reason": f"開低 {gap:+.1f}% → 直接離場（脫逃 SOP）"}
    broke_flat = today_low is not None and today_low < prev_close
    if gap < 2.5:
        return {"action": "caution", "reason": f"開高不足 {gap:+.1f}%（<2.5%）易引賣壓"
                + ("、盤中已破平盤→先出觀望" if broke_flat else "")}
    if broke_flat:
        return {"action": "exit_watch", "reason": "開高後殺破平盤 → 先出觀望"}
    return {"action": "hold", "reason": f"開高 {gap:+.1f}% ≥2.5%、續看"}


# ────────────────────── 5 分 K（盤中 / stock_minute_kbar）──────────────────────

def _ema(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def frank_1_5m(m5_closes: list[float]) -> dict:
    """5m 戰法一: 10EMA vs 60EMA + 60EMA 斜率."""
    if len(m5_closes) < 12:
        return {"in_zhanfa1": None, "reason": "bars<12"}
    e10, e60 = _ema(m5_closes, 10), _ema(m5_closes, 60)
    up = e10[-1] > e60[-1]
    slope = e60[-1] - e60[max(0, len(e60) - 7)]
    return {"in_zhanfa1": up and slope > 0, "cross_up": up, "slope_up": slope > 0,
            "e10": e10[-1], "e60": e60[-1],
            "reason": "戰法一成立" if (up and slope > 0) else "未成立/被壓"}


def frank_open_5m_key_level(bar1: dict, bar2: dict, prev_day_high: float) -> dict:
    """開盤5分K關鍵價: 強=第2根過第1根高；弱=過不了。防守=第1根一半."""
    b1h, b1l = bar1["high"], bar1["low"]
    mid = (b1h + b1l) / 2
    strong = bar2["close"] > b1h
    over_prev = b1h > prev_day_high
    chg2 = None
    if strong and bar2["close"] and bar1.get("open"):
        chg2 = (bar2["close"] / bar1["open"] - 1) * 100
    out = {"key_high": b1h, "key_low": b1l, "defend_mid": mid,
           "over_prev_high": over_prev}
    if strong:
        out.update(bias="strong", reason="第2根過第1根高=偏強、關鍵價=第1根高、防守一半"
                   + ("、⚠️>6%要能鎖停否則快進快出" if chg2 and chg2 > 6 else ""))
    else:
        out.update(bias="weak", reason="第2根未過高=偏弱、關鍵價=第1根低（破低即弱）")
    return out


def frank_pop_check_2m(m2_closes: list[float]) -> dict:
    """炸板後 2m 戰法一: 守住 → 90%+ 鎖回."""
    r = frank_1_5m(m2_closes)  # 同公式、2m bars
    if r["in_zhanfa1"] is None:
        return {"relock_likely": None, "reason": r["reason"]}
    return {"relock_likely": bool(r["in_zhanfa1"]),
            "reason": "2m戰法一守住→90%+鎖回" if r["in_zhanfa1"] else "2m戰法一破→不強勢"}


def frank_slow_move_alert(open_pct: float, minutes_since_open: int, is_slow_up: bool) -> dict:
    """緩漲緩跌: 開盤<+7% + 2~10分內出現緩漲/緩跌 = 假動作警戒."""
    if not (2 <= minutes_since_open <= 10):
        return {"alert": False, "reason": "非2-10分窗口"}
    if abs(open_pct) >= 7:
        return {"alert": False, "reason": "開盤已±7%、不適用"}
    kind = "緩漲" if is_slow_up else "緩跌"
    return {"alert": True, "reason": f"{kind}=主力假動作機率高、冷靜等回測10EMA/60EMA、"
            f"{'大單賣+過不了搓合前高才賣' if is_slow_up else '大單買+不破搓合前低才買'}"}


def frank_5tick_fake_order(bid_total: int, ask_total: int,
                            big_ask_at_top: bool, big_bid_at_top: bool,
                            in_zhanfa1: bool) -> dict:
    """五檔假掛單: 委賣>>委買且大單非第1檔+符戰法一=偏多；反之偏空."""
    if ask_total >= bid_total * 1.5 and not big_ask_at_top and in_zhanfa1:
        return {"bias": "bull", "reason": "大量假委賣（非第1檔）+戰法一 → 偏多別急拋"}
    if bid_total >= ask_total * 1.5 and not big_bid_at_top and not in_zhanfa1:
        return {"bias": "bear", "reason": "大量假委買（非第1檔）+破戰法一 → 偏空別抄底"}
    return {"bias": None, "reason": "無明確假掛單特徵"}


# ────────────────────── self-check ──────────────────────

def demo():
    mk = lambda **kw: {"date": "", "open": None, "high": None, "low": None,
                       "close": None, "volume": 0, "ma5": None, "ma10": None,
                       "ma20": None, "ma20_slope": None, "bb_position": None,
                       "vol_ratio_20": None, **kw}
    # 戰法二: 昨收<=昨5MA、今收>5MA、月線↑
    prev = mk(close=100, ma5=101)
    today = mk(close=104, ma5=102, ma20=98, ma20_slope=0.5)
    assert frank_2_entry(today, prev)["signal"]
    # score: 過城牆+頭頭高
    s = frank_score(mk(close=110, bb_position=85, vol_ratio_20=2.0),
                    mk(high=108), wall_high=109)
    assert s["score"] == 5 and not s["skip"]
    assert frank_score(mk(close=100), mk(high=105), None)["skip"]
    # 3・5 法則: 連2大紅 → day3 警戒
    seq = [mk(open=90, close=91), mk(open=91, close=92),
           mk(open=92, close=97.5), mk(open=98, close=103)]
    assert frank_hot_stock_3_5_rule(seq)["alert"] == "day3警戒"
    # 日出: 連3跌 + 收腳 + 紅K過高
    bars = [mk(open=105, close=104, high=106, low=103),
            mk(open=104, close=101, high=104, low=100),
            mk(open=101, close=99, high=101, low=98),
            mk(open=99, close=98.5, high=99.5, low=96),   # 收腳(下影)
            mk(open=98.5, close=100.5, high=100.6, low=98)]  # 紅K收過收腳高99.5
    assert frank_sunrise_line(bars)["signal"], frank_sunrise_line(bars)
    # 鎖漲停隔日: 開低=exit
    assert frank_lock_limit_up_next_day(100, 98)["action"] == "exit"
    assert frank_lock_limit_up_next_day(100, 103, 101)["action"] == "hold"
    # 5m 戰法一: 上升序列
    up = [100 + i * 0.3 for i in range(80)]
    assert frank_1_5m(up)["in_zhanfa1"]
    # 紅三兵: 連2爆量+第3日過高
    b3 = [mk(high=100, vol_ratio_20=2.0), mk(high=103, vol_ratio_20=1.8),
          mk(close=105, vol_ratio_20=1.0)]
    assert frank_bottom_3_soldiers([mk()] + b3)["formed"] is True
    # KD 背離: 價新低 KD 墊高
    closes = [100 - i * 0.5 for i in range(20)] + [90 - i * 0.3 for i in range(20)]
    kvals = [50 - i for i in range(20)] + [35 + i * 0.5 for i in range(20)]
    assert frank_kd_divergence(closes, kvals)["divergence"] == "low"
    print("all detector self-checks passed")


if __name__ == "__main__":
    demo()
