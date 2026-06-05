"""Low-price stock threshold — non-course proxy constant.

## Course stance
課程明示「低價股」概念（§09「低價股的處理節奏」），但**完全沒給**價格門檻數字。
老師只用「低 / 中 / 高」相對概念描述。明基材（8215）案例當時約 30-40 元，
但課程從未說「30 元以下 = 低價股」。

## Why this constant exists
`lowprice_first_pull_exit` light 需要一個數字來判斷「是否屬於低價股」，
但課程無明示數字，只能用業界 proxy（30 元）。

## Observation evidence
- 老師案例：錸德(2349)、億泰(1616)、中工(2515) 約 10-25 元
- 業界習慣：30 元作為「低價股」上界 proxy（含案例上沿，留緩衝）
- 課程未明示此數字 → 屬於課程外 proxy → 必須放 extras

## Usage
此模組由 features.py 直接 import（即使不啟用 extras，low_price_flag 仍計算）。
實際影響在 light layer：lowprice_first_pull_exit.yaml 標記 [EXTRAS]，
預設情況下 user 知道這個 light 的觸發門檻是課程外 proxy。

若 user 要用不同門檻，可：
    from scripts.kline.extras.low_price import LOW_PRICE_THRESHOLD
    # 修改此值或 monkeypatch 後重跑
"""

# [EXTRAS] 課程外 proxy — 課程無明示低價股門檻數字
# 業界粗略 proxy：30 元以下 = 低價股
LOW_PRICE_THRESHOLD: float = 30.0  # [EXTRAS] course-not-stated — industry proxy
