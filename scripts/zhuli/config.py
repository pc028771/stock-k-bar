"""Default parameters for zhuli course strategies.

All values are CALIBRATABLE — see calibration.py for the update interface.

Course source: 主力大全方位操盤教戰守則 (林家洋)
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
