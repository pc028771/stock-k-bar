"""Default parameters for zhuli course strategies.

All values are CALIBRATABLE — see calibration.py for the update interface.

Course source: 主力大全方位操盤教戰守則 (尼克)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any


@dataclass
class SuffocationConfig:
    """Parameters for H 窒息量策略 (zhuli_suffocation).

    Fields are grouped into:
      - Hard rules: spec-defined constants from course, generally not tunable.
      - Soft margins: calibratable via CLI or JSON override file.
      - Liquidity filters: operational filters (course-neutral defaults).
      - Boost score conditions: ideal conditions for signal quality scoring.
    """

    # === Hard rules from course (spec-defined, generally not tunable) ===
    # Source: strategy-indicators.md §H — 「當日成交量 < 20 日內最大量的 10%」
    max20_volume_ratio: float = 0.10  # vol < max(vol_20d) * 0.10
    # Source: course_principles.md §16 — 「必要：月線上彎」
    require_ma20_slope_up: bool = True  # 月線 (20MA) 上彎為必要

    # === Soft margins (calibratable) ===
    # 往前 N 日找窒息量 K；候選窒息量必須在出量 K 的前一根
    # Spec: Ex1-3 05:00 SOP 投影片 — 「等下一根出量 K」，i.e., lookback=1
    lookback_days: int = 1  # 候選窒息量 = 昨天；今天 = 出量 K

    # 出量 K 量增門檻（spec 只說「比前一根多」，未定具體倍數）
    # Source: strategy-indicators.md §H — 「next_bar.volume > suffocation_bar.volume」
    breakout_volume_multiplier: float = 1.0  # 1.0 = 嚴格按 spec「比前一根多」

    # === Liquidity filters (course-neutral operational defaults) ===
    # 流動性過濾，沿用 main 慣例；可透過 CLI 覆寫
    min_avg_volume_20: int = 200   # 千股 (vol_ma20 單位)
    min_close: float = 10.0        # 元

    # === Boost score conditions (ideal 多頭排列) ===
    # Source: strategy-indicators.md §H — 「理想（最高勝率）：5/10/20/60ma 排列正確且皆上彎」
    # 若 True = 必要條件（會過濾掉不符合的）；若 False = 只加分、不過濾
    ideal_ma_alignment_required: bool = False  # 預設加分不過濾

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SuffocationConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "SuffocationConfig":
        """Load config overrides from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "SuffocationConfig":
        """Apply KEY=VALUE string overrides (from CLI --config-override).

        Values are coerced to the correct Python type based on the field's
        current default type (bool, int, float).

        Example:
            cfg.apply_overrides({"min_close": "15.0", "lookback_days": "2"})
        """
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown SuffocationConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return SuffocationConfig.from_dict(d)


@dataclass
class OpenSignalConfig:
    """Parameters for M 主力意圖判斷策略 (open_signal_filter).

    Source: strategy-indicators.md §M 主力意圖判斷（Ch7-3）

    Fields are grouped into:
      - Hard rules: spec-defined constants from course.
      - Soft margins: calibratable via CLI or JSON override.
      - Liquidity filters: operational filters (course-neutral defaults).
    """

    # === Hard rules — 收高開低（bearish_exit）===
    # 前日收盤需在當日 high 的 N 倍以上（收最高），預設 90%
    # Source: strategy-indicators.md §M — 「前一天出量實紅K 收最高（或收相對高點）」
    bearish_prev_close_position: float = 0.9

    # 今日開盤 ≤ 前日收盤 × (1 + N)，N=0.0 = 開平/開低
    # Source: strategy-indicators.md §M — 「次日開平、開綠」
    bearish_today_open_max_gain: float = 0.0

    # === Hard rules — 收低開高（bullish_entry）===
    # 前日收盤需在當日 low 的 N 倍以下（收最低），預設 0.1（即 close ≤ low * 1.1）
    # Source: strategy-indicators.md §M — 「前一天出量實黑K 收最低」
    bullish_prev_close_position: float = 0.1

    # 今日開盤 ≥ 前日收盤 × (1 + N)，N=0.0 = 開平/開高
    # Source: strategy-indicators.md §M — 「次日開平、開紅」
    bullish_today_open_min_gain: float = 0.0

    # === Hard rules — 漲停開平警示（limit_up_flat_warning）===
    # |today_open − prev_close| / prev_close 低於此門檻 = 開平盤
    # Source: strategy-indicators.md §M — 「漲停的標的隔天開平盤也是危險訊號」
    limit_up_flat_open_threshold: float = 0.005  # ±0.5%

    # === Soft margins (calibratable) ===
    # 前日需出量：前日 volume > 5MA volume × multiplier
    # Source: strategy-indicators.md §M — 「前一天出量」
    require_prev_volume_burst: bool = True
    prev_volume_multiplier: float = 1.0  # 1.0 = 嚴格按 spec「量 > 5MA」

    # === Liquidity filters (course-neutral operational defaults) ===
    min_avg_volume_20: int = 200   # 千股
    min_close: float = 10.0        # 元

    # === Phase 2 placeholder ===
    # 大盤普跌例外 filter（國際利空時 bearish_exit 不適用）
    # 預設 OFF，Phase 2 補實作
    apply_market_regime_filter: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OpenSignalConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "OpenSignalConfig":
        """Load config overrides from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "OpenSignalConfig":
        """Apply KEY=VALUE string overrides (from CLI --config-override)."""
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown OpenSignalConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return OpenSignalConfig.from_dict(d)


@dataclass
class InstitutionalFirstBuyConfig:
    """Parameters for J 投信首買策略 (zhuli_institutional_firstbuy).

    Source: strategy-indicators.md §J 投信首買策略（Ex2-3）
            course_principles.md §17 投信跟單加碼

    Fields are grouped into:
      - Hard rules: spec-defined constants from course.
      - Soft margins: calibratable via CLI or JSON override.
      - Liquidity filters: operational filters (course-neutral defaults).
      - Boost score conditions: ideal conditions for signal quality scoring.
    """

    # === Hard rules from course (spec-defined) ===
    # Source: strategy-indicators.md §J — 「投信突然買（至少200張）」
    # ex2-3 截圖 01:23 投影片確認；03:00 手寫說可降至 50 但勝率降低
    min_firstbuy_volume: int = 200          # 首日 ≥ 200 張（user 拍板可調至 50）

    # Source: strategy-indicators.md §J — 「前面至少 2 個月（最好 3 個月）無投信買超」
    # ex2-3 字幕 05:42、截圖 07:24 確認「越長空白越高勝率」
    # 預設 60 天（約 2 個月）；user 拍板
    no_buy_window_days: int = 60            # 前 60 天無投信買超

    # 「無投信買超」的定義：sitc_net ≤ 0（含賣超與零買）
    # Source: strategy-indicators.md §J — 「前面都非常乾淨」（字幕 01:53）
    no_buy_threshold: float = 0.0          # 前 window 內 sitc_net 必須全部 ≤ 0

    # === Soft margins (calibratable) ===
    # 技術面多頭排列（5>10>20）課程說「理想條件」而非必要
    # Source: strategy-indicators.md §J — 「籌碼 + 技術面：均線多頭排列、未發散 → 勝率加成」
    # ex2-3 截圖 11:13 — 「活用：技術面不好但夠低也可進場」
    require_ma_alignment: bool = False      # 預設非必要（加分）

    # === 價籌背離（加分條件）===
    # Source: strategy-indicators.md §J — 「當日個股收黑K但投信買超 => 價籌背離」
    # ex2-3 截圖 04:00 手寫強調；截圖 09:39 具體案例
    # 加分：收黑K（close < open）且投信買超 > 0
    bullish_price_divergence_bonus: bool = True  # 計分加成用，不做過濾

    # === Liquidity filters (course-neutral operational defaults) ===
    min_avg_volume_20: int = 200            # 20日均量 ≥ 200 張（流動性門檻）
    min_close: float = 10.0                 # 收盤 ≥ 10 元

    # === Boost score conditions (ideal 多頭排列) ===
    # Source: strategy-indicators.md §J — 「技術面：5/10/20 多頭排列（理想）」
    # 若 require_ma_alignment = False，ideal_ma_align 只當 bonus score 欄位輸出
    # 若 require_ma_alignment = True，ideal_ma_align 不符合的直接過濾

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InstitutionalFirstBuyConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "InstitutionalFirstBuyConfig":
        """Load config overrides from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "InstitutionalFirstBuyConfig":
        """Apply KEY=VALUE string overrides (from CLI --config-override)."""
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown InstitutionalFirstBuyConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return InstitutionalFirstBuyConfig.from_dict(d)


@dataclass
class SwingBreakoutConfig:
    """Parameters for A 大波段選股策略 (zhuli_swing_breakout).

    Source: strategy-indicators.md §A 大波段選股策略（Swing Breakout）
            course_principles.md §7 大波段選股 SOP

    Fields are grouped into:
      - Hard rules: spec-defined constants from course, generally not tunable.
      - Soft margins: calibratable via CLI or JSON override file.
      - Liquidity filters: operational filters (course-neutral defaults).
    """

    # === 籌碼面（必要，擇一）===
    # Source: strategy-indicators.md §A — 「外資（或投信）買超 ≥ 1/3 當日成交量，或 ≥ 兩萬張」
    # User 拍板：3.0x volume ratio 即 1/3
    institutional_volume_ratio: float = 1 / 3          # 法人買超 ≥ 1/3 當日成交量
    institutional_volume_absolute: int = 20000          # 或 ≥ 兩萬張（課程明說）

    # === 技術面（必要）===
    # Source: strategy-indicators.md §A — 「20ma 與 60ma 皆呈現上彎」
    require_ma20_slope_up: bool = True                  # 月線上彎（必要）
    require_ma60_slope_up: bool = True                  # 季線上彎（必要）

    # === 距月線理想條件 ===
    # Source: strategy-indicators.md §A — 「理想：當前股價離 20MA 在 5% 以內」
    # enforce_dist_to_ma20 = False → 理想條件（只加分，不過濾）
    # enforce_dist_to_ma20 = True  → 必要條件（過濾掉不符合的）
    max_dist_to_ma20_pct: float = 0.05                  # 距月線 ≤ 5%（理想門檻）
    enforce_dist_to_ma20: bool = False                  # 預設理想條件不強制（CLI 可開）

    # === 族群密度（必要）===
    # Source: strategy-indicators.md §A — 「同產業 ≥ 3 檔出現在買超前列」
    sector_density_min_count: int = 3                   # 同族群 ≥ 3 檔籌碼面成立
    require_sector_density: bool = True                 # 族群面為必要條件

    # === MA60 近底部放寬條件（實驗性，非課程明說）===
    # 當 MA60 仍在下彎，但幅度極小（幾近平坦）且 MA20 已連續上彎 → 視為「即將轉彎」
    # 觸發條件（同時滿足）：
    #   1. ma60_slope_5d < 0（MA60 仍在下彎）
    #   2. 5日 MA60 最大跌幅 < ma60_near_bottom_max_drop_pct（近乎平坦）
    #   3. MA20 連續 ma60_near_bottom_ma20_up_days 天上彎
    # 啟用條件：ma60_near_bottom_enabled = True（預設 ON）
    # 診斷依據：docs/主力大課程/analysis/scanner_diagnosis_6449_delay.md
    #   6449 鈺邦 5/5 attack day: MA60 slope = -0.0096（5日跌幅 0.71%）
    #   當日 MA20 slope = +0.020 且已連續 > 5 天上彎 → 值得放行
    ma60_near_bottom_enabled: bool = True                # 預設啟用
    ma60_near_bottom_max_drop_pct: float = 1.0          # 5日 MA60 最大跌幅 < 1.0%
    ma60_near_bottom_ma20_up_days: int = 5              # MA20 連續上彎天數門檻

    # === 流動性過濾（課程中立操作門檻）===
    min_avg_volume_20: int = 200                        # 20日均量 ≥ 200 張
    min_close: float = 10.0                             # 收盤 ≥ 10 元

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SwingBreakoutConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "SwingBreakoutConfig":
        """Load config overrides from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "SwingBreakoutConfig":
        """Apply KEY=VALUE string overrides (from CLI --config-override).

        Values are coerced to the correct Python type based on the field's
        current default type (bool, int, float).

        Example:
            cfg.apply_overrides({"institutional_volume_ratio": "0.25"})
        """
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown SwingBreakoutConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return SwingBreakoutConfig.from_dict(d)


@dataclass
class BBandsUpperBreakConfig:
    """Parameters for D 布林上軌進出策略 (zhuli_bbands_upper_break).

    Course source: strategy-indicators.md §D 布林上軌進出策略
                   (HD vision Ch4-2 32:07 / 34:47 / 35:19 已驗證)

    Logic:
        1. 計算 20 日布林：BB_middle = MA20, BB_std = 20d close std,
           BB_upper = mid + 2*std, BB_lower = mid - 2*std
        2. 通道窄度 = (BB_upper - BB_lower) / BB_middle
        3. **突破前一天**（不是突破當天）的 bandwidth 是判斷依據
        4. 起漲 K：close > BB_upper 且 volume > prev_volume
        5. 二買點 = BB_upper_next * 0.99（簡化用今日 BB_upper × 0.99）
        6. 出場：實體綠 K 跌入上軌之內（close < BB_upper）
    """

    # === Hard rules from course (spec-defined) ===
    # 起漲 K 必要條件
    require_close_above_upper: bool = True   # close > BB_upper
    require_volume_increase: bool = True     # volume > prev_volume

    # === Soft margins (calibratable) ===
    # 通道窄度門檻（突破前一天計）
    # spec: < 0.10 = 飆股理想；> 0.10 也可飆但爆發力較弱
    # 預設 0.30 包含 HD vision 全部 3 個 case (6672/3006/6237 bandwidth 0.15-0.19)
    # 嚴格隔日沖版可調為 0.06
    bandwidth_max: float = 0.30
    bandwidth_ideal: float = 0.10   # < 此值算 ideal (加分用)

    # 通道形狀：排除明顯下降趨勢
    # spec: 「不可為下降趨勢；最佳橫盤壓縮；上升趨勢可用但爆發力較弱」
    # ⚠️ 課程「下降趨勢」是視覺判斷不是 5 天斜率嚴格負，預設關閉避免漏抓橫盤微負 case
    # 啟用後用 ma60_slope_5d > ma60_slope_tolerance 過濾
    require_ma60_not_declining: bool = False
    ma60_slope_tolerance: float = -0.005   # 允許 5 天內微跌 0.5% 以內（橫盤容忍）

    # === Liquidity filters ===
    min_avg_volume_20: int = 200   # 千股
    min_close: float = 10.0        # 元

    # === Output options ===
    # 出口 stop_loss: BB_upper (跌入上軌之內 → 出場)
    # 出口 second_buy_estimate: BB_upper * 0.99 (二買點預估)
    second_buy_factor: float = 0.99

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BBandsUpperBreakConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "BBandsUpperBreakConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "BBandsUpperBreakConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown BBandsUpperBreakConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return BBandsUpperBreakConfig.from_dict(d)


@dataclass
class OvernightSwingConfig:
    """Parameters for G 隔日沖策略 (zhuli_overnight_swing).

    Course source: strategy-indicators.md §G 隔日沖策略
                   (HD vision Ch6-1 04:39+05:18, Ch6-2 00:44 已驗證)

    定義: 今天尾盤 (1:20-1:25) 買、隔天開盤賣；目標每日 1-2% 達標。

    Logic (個股篩選):
        條件 1（布林）: K 棒突破布林高軌 + 通道窄率 < bandwidth_max
        條件 2（K 棒）: 長紅 > body_min, 量 > min_volume_張, 量增 > prev_volume_multiplier
        條件 3（斜率）: 月線斜率 > ma20_slope_min

    大盤條件 (可選): 加權指數 + OTC 都需「量增紅K + close > 5ma」
    """

    # === 條件 1: 布林 ===
    # HD vision Ch6-2 00:44 — 「布林窄率 < 6%」(嚴格 spec)
    # ⚠️ 課程 3 個 case (2351/6271/3149) bandwidth_prev > 0.20，不符合 spec
    # → 預設 0.06 嚴格版；可 cfg_override 放寬至 0.30 包含 case
    bandwidth_max: float = 0.06
    require_close_above_upper: bool = True

    # === 條件 2: K 棒 ===
    # HD vision Ch6-2 00:44 — 「長紅棒 > 3.5%，量 > 1,000 張，量增 > 前日 0.1%」
    body_min: float = 0.035                  # 長紅 > 3.5%
    min_volume_lots: int = 1000              # 量 > 1,000 張 (volume / 1000)
    prev_volume_multiplier: float = 1.001    # 量增 > 前日 0.1%

    # === 條件 3: 月線斜率 ===
    # HD vision Ch6-2 00:44 — 「月線斜率 > 0.4」
    # ⚠️ 「0.4」具體單位 spec 不明（可能為 5 天斜率百分比、線性回歸斜率元/天等）
    # 暫用 5 天 proxy 0.4% (寬鬆) + cfg 可調
    ma20_slope_min: float = 0.004

    # === 大盤條件 (可選) ===
    # HD vision Ch6-1 04:39+05:18 — 「加權 + OTC 量增紅K + 收盤 > 5ma」
    require_market_filter: bool = False      # 預設關閉避免缺資料
    market_taiex_ticker: str = "TAIEX"       # 加權指數
    market_otc_ticker: str = "TPEX"          # OTC 櫃買指數

    # === Liquidity filters ===
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OvernightSwingConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "OvernightSwingConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "OvernightSwingConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown OvernightSwingConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return OvernightSwingConfig.from_dict(d)


@dataclass
class ReversalBreakoutConfig:
    """Parameters for C 反轉形態策略 (zhuli_reversal_breakout).

    Course source: strategy-indicators.md §C 反轉形態 (Ch4-2 line 217-356)

    定義: 一路下跌的標的，出現一根反轉紅K 整根站上所有均線 + 突破下降趨勢線。

    Logic:
        1. 紅 K: close > open
        2. ma20 在 K 棒實體下方 (body_low > ma20)
        3. ma10 在實體下方 (body_low > ma10) — 額外確認
        4. 短均線上彎 (ma5_slope_5d > 0)
        5. 均線發散度有限 (避免 6441 廣錠失敗特徵)
        6. 前 60 日跌深 (有下降趨勢)
    """

    # === Hard rules from course ===
    require_red_bar: bool = True              # 紅 K (close > open)
    require_body_above_ma20: bool = True      # ma20 必須在實體下方
    require_body_above_ma10: bool = True      # ma10 必須在實體下方
    require_ma5_uptrend: bool = True          # ma5 上彎

    # === Soft margins ===
    # 均線發散度 (max - min)/close — 太大 = 均線發散，反轉不穩
    # 6441 失敗 5.31% / 1904 1.67% / 3042 2.88%
    max_ma_dispersion: float = 0.05

    # 前 N 日跌深 (反轉特徵)
    lookback_decline_days: int = 60
    min_decline_pct: float = 0.10              # (H-L)/H > 10% 才算有「下降趨勢」可反轉

    # === Output ===
    # 切入價: 反轉紅K 下方 1/3 (low + (high-low)/3)
    entry_third_factor: float = 1.0/3.0
    # 停損: 反轉紅K 低點
    # 停損就是 K 棒 low

    # === Liquidity ===
    min_avg_volume_20: int = 200
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReversalBreakoutConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "ReversalBreakoutConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "ReversalBreakoutConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown ReversalBreakoutConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return ReversalBreakoutConfig.from_dict(d)


@dataclass
class PennantFlagConfig:
    """Parameters for B 形態一：旗形/旗杆 (zhuli_pennant_flag).

    Course source: strategy-indicators.md §B (Ch4-2 line 9-216)

    定義: 旗杆紅K + 兩根整理 K 棒（旗子）+ 第三天/第四天切入

    Logic:
        t-2: 旗杆 (pole) — 紅 K (close > open)
        t-1: 旗子第 1 根 — close > ma5, volume < pole_volume
        t   : 旗子第 2 根 (今日) — close > ma5, volume < pole_volume
        兩根旗子 close > 旗杆 (low + close)/2 mid line
    """

    # === Hard rules from course ===
    require_pole_red: bool = True              # 旗杆紅 K
    require_consolidation_close_above_ma5: bool = True   # 旗子收盤 > ma5
    require_consolidation_volume_below_pole: bool = True  # 旗子量縮 < 旗杆量
    require_consolidation_above_pole_mid: bool = True    # 旗子 close > 旗杆 (low+close)/2

    # === Soft margins ===
    # 旗杆上影線限制（不可太長）
    # spec: 「可帶少量上影線（不可太長）」
    pole_max_upper_shadow_ratio: float = 0.5  # 上影 / 實體 ≤ 0.5

    # 切入價: 收盤價 (第三天尾盤切入)
    # 停損: 收盤跌破 5ma
    # 加碼: 後續再出現旗形

    # === Liquidity ===
    min_avg_volume_20: int = 200
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PennantFlagConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "PennantFlagConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "PennantFlagConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown PennantFlagConfig key: '{key}'. Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return PennantFlagConfig.from_dict(d)


@dataclass
class InstitutionalSwingConfig:
    """Parameters for I 投信跟單策略 (zhuli_institutional_swing).

    Course source: strategy-indicators.md §I + HD vision Ex2-1 + Ex2-2

    Logic:
        條件 1: 5 日累計投信買進 / 股本 ≥ 1.5%
        條件 2: 剛上榜（前 N 天無此條件成立）
        條件 3: MA5 > MA10 > MA20 皆上彎（短均線多頭排列）
        警戒: inst_holding_pct > 12%（隨時倒貨，目前 FinMind 無此資料）
    """

    # === Hard rules from course ===
    min_5d_buy_pct: float = 0.015           # 5 日 sitc_buy / shares ≥ 1.5%
    # spec: 「最好 ≥ 1.5%」(Ex2-2)
    use_sitc_buy_not_net: bool = True        # 用累計買進 (非淨買)

    # ⚠️ 改加分不過濾（user 偏好）— 均線已排列 = 趨勢中段已晚，
    # 抓更多獲利空間應允許「其他指標達到但均線還沒排列」進場
    require_ma_alignment: bool = False        # MA5 > MA10 > MA20 上彎 (加分)

    # 「剛上榜」窗口：過去 N 天無此 ticker 命中
    first_appearance_days: int = 30

    # === Soft margins ===
    # 警戒線 (目前 FinMind 無投信持股 ratio 資料 → log only)
    warn_holding_pct: float = 0.12

    # === Liquidity ===
    min_avg_volume_20: int = 200
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InstitutionalSwingConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "InstitutionalSwingConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "InstitutionalSwingConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown InstitutionalSwingConfig key: '{key}'. Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return InstitutionalSwingConfig.from_dict(d)


@dataclass
class IntradayConfig:
    """Parameters for F 當沖策略 (zhuli_intraday).

    Course source: strategy-indicators.md §F 當沖策略 (Ch5-1 + Ch5-2 + Ch5-3)
                   HD vision Ch5-2 案例: 3141 晶宏 / 2314 台揚 / 2010 春源 / 3006 晶豪科

    Note: scanner 只做前夜選股 (日 K 級)，盤中執行（5 分 K, VWAP, 突破第一根 K 高點）
    不在 scanner 範圍 — 由 user 手動執行。

    Logic (前夜篩選):
        1. MA5 > MA10 > MA20 三條均線多頭排列且皆上彎
        2. 近 2 日成交量 > 2 萬張
        3. 近 3 日 (H-L)/L 振幅 > 8%
        4. 近 3 日周轉率 (volume_3d_sum / shares_issued) > 20%
        5. 股價離月線 (close-ma20)/ma20 < 30%

    精選 (Ch5-2):
        距前高 (60D high) < 10%
    """

    # === Hard rules from course ===
    # ⚠️ 改加分不過濾（user 偏好）— 均線排列是趨勢中段晚進場訊號，
    # F 當沖更依賴量價爆發而非均線多頭排列
    require_ma_alignment: bool = False      # MA5>10>20 + 三條上彎 (加分)
    min_vol_2d_lots: int = 20000            # 兩天量 > 2 萬張
    min_range_3d: float = 0.08              # 3 天振幅 > 8%
    min_turnover_3d: float = 0.20           # 3 天周轉率 > 20%
    max_dist_from_ma20: float = 0.30        # 股價離月線 < 30%

    # === Ch5-2 精選 ===
    max_dist_from_prev_high: float = 0.10   # 距 60D 高 < 10%
    prev_high_lookback_days: int = 60       # 前高 lookback

    # === Ch5-2 量能突破倍率（2026-06-05 補實作）===
    # 「右下角近期量 > 左邊前高的量」、「衝擊前高需要更大量」
    require_breakout_vol: bool = False           # 預設 OFF（向後相容）
    min_breakout_vol_ratio: float = 1.0          # 今日量 / 前高那天量 ≥ N

    # === Liquidity ===
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IntradayConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "IntradayConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "IntradayConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(f"Unknown IntradayConfig key: '{key}'. Valid: {list(d.keys())}")
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return IntradayConfig.from_dict(d)


@dataclass
class BollingerPullbackConfig:
    """Parameters for E 布林回測策略 (zhuli_bollinger_pullback).

    Course source: strategy-indicators.md §E + PDF p.127 + sprite scan ch4-2 48:05-71:32
    Core case: 3042 晶技 (反轉+旗型+中軌+上軌+回補缺口+站上大量高點離開上軌出場)

    Logic:
        前置: 過去 N 天曾經 close > BB_upper (D 觸發過，曾跳出布林上軌)
        觸發: 急漲後回測到 MA20 附近，量縮，不跌破，第二波啟動
        進場: 第二波第一根攻擊 K
        停損: 收盤跌破 MA20
        出場: 沿用 D — 實體綠 K 跌入上軌之內

    判別條件:
        1. close > MA20 (未跌破中軌)
        2. close 距 MA20 ≤ pullback_proximity_max (回測到 MA20 附近)
        3. 過去 prerequisite_lookback 天 close 曾 > BB_upper (D pattern 觸發過)
        4. ma5_will_rise (短均線將上揚 = 第二波啟動)
        5. 回測量縮: 近 N 日 mean vol < 過去 60 日 max vol × pullback_volume_ratio_max
    """

    # === Hard rules ===
    require_close_above_ma20: bool = True       # 不跌破中軌 (停損)

    # 距 MA20 比例 (close 接近 MA20 = 回測位置)
    # spec: 「回跌至中軌」 — close 在 MA20 上方但接近
    pullback_proximity_max: float = 0.10        # close ≤ MA20 × 1.10 (距 MA20 10% 內)

    # 前置: 過去 N 天 close > BB_upper 至少一次 (D scanner 觸發過)
    prerequisite_lookback: int = 60
    require_d_prerequisite: bool = True

    # 第二波啟動: ma5 將上揚 (扣抵預判)
    require_ma5_will_rise: bool = True

    # 回測量縮: 近 N 日 mean volume / 過去 60 日 max volume
    pullback_volume_ratio_max: float = 0.30
    pullback_volume_window: int = 10            # 近 10 日 mean vol

    # 量增確認 (第二波攻擊 K 量需 > 近 5 日 mean × 1.0)
    require_attack_volume: bool = True
    attack_volume_multiplier: float = 1.0       # 今 volume > 近 5 日 mean × 1.0

    # === Liquidity ===
    min_avg_volume_20: int = 200
    min_close: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BollingerPullbackConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "BollingerPullbackConfig":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "BollingerPullbackConfig":
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(f"Unknown BollingerPullbackConfig key: '{key}'. Valid: {list(d.keys())}")
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return BollingerPullbackConfig.from_dict(d)
