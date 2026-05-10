# 突破攻擊策略原型驗證

資料庫：`/Users/howard/.four_seasons/data.sqlite`

樣本：2025-01-02 至 2026-05-08

本次驗證 `breakout_attack` 在加入可交易限制與停損模型後，是否仍能保留趨勢追蹤邊際。

## 假設

- 訊號：收盤突破 60 日前高、收紅、收盤接近日高、量比至少 1.2、且收盤在 MA60 上方。
- 進場：訊號日收盤後成立，隔日開盤買進。
- 可交易限制：排除注意股、處置股；20 日均量至少 500,000 股；收盤價至少 10 元。
- 停損模型：`breakout_stop = min(訊號日低點, 突破價) * 0.995`，以及 `ATR14` 停損。

## 核心結果

| variant | n | mean_10d_net_pct | win_rate_10d_net_pct | mean_10d_stop_breakout_net_pct | mean_10d_stop_atr14_net_pct | mean_20d_net_pct | win_rate_20d_net_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breakout_attack_base | 5655 | 0.889 | 42.44 | 0.428 | 0.684 | 3.276 | 44.9 |
| breakout_attack_tradable | 3515 | 0.775 | 43.24 | 0.034 | 0.408 | 4.127 | 47.65 |
| breakout_next_not_low_open | 2547 | 0.412 | 42.17 | -0.103 | 0.18 | 3.344 | 46.53 |
| breakout_next_low_open | 968 | 1.729 | 46.07 | 0.395 | 1.006 | 6.188 | 50.62 |
| breakout_high_close | 2675 | 0.904 | 43.07 | 0.165 | 0.519 | 4.346 | 48.41 |
| breakout_volume_strong | 3130 | 0.836 | 42.94 | 0.087 | 0.496 | 4.086 | 47.06 |
| breakout_non_bull | 1134 | 2.179 | 46.74 | 1.171 | 1.801 | 6.027 | 51.59 |

## 市場環境分組

| variant | market_regime | n | mean_10d_net_pct | win_rate_10d_net_pct | mean_20d_net_pct |
| --- | --- | --- | --- | --- | --- |
| breakout_attack_base | bear | 288 | 0.661 | 43.4 | 2.204 |
| breakout_attack_base | bull | 3737 | 0.149 | 40.54 | 2.276 |
| breakout_attack_base | range | 1630 | 2.625 | 46.63 | 5.758 |
| breakout_attack_tradable | bear | 180 | -0.496 | 40.56 | 1.598 |
| breakout_attack_tradable | bull | 2381 | 0.106 | 41.58 | 3.222 |
| breakout_attack_tradable | range | 954 | 2.684 | 47.9 | 6.863 |
| breakout_high_close | bear | 139 | -0.564 | 38.85 | 1.725 |
| breakout_high_close | bull | 1830 | 0.242 | 41.86 | 3.456 |
| breakout_high_close | range | 706 | 2.91 | 47.03 | 7.169 |
| breakout_next_low_open | bear | 57 | -0.54 | 38.6 | 1.045 |
| breakout_next_low_open | bull | 635 | 0.755 | 43.62 | 5.389 |
| breakout_next_low_open | range | 276 | 4.439 | 53.26 | 9.089 |
| breakout_next_not_low_open | bear | 123 | -0.475 | 41.46 | 1.855 |
| breakout_next_not_low_open | bull | 1746 | -0.13 | 40.84 | 2.434 |
| breakout_next_not_low_open | range | 678 | 1.97 | 45.72 | 5.957 |
| breakout_non_bull | bear | 180 | -0.496 | 40.56 | 1.598 |
| breakout_non_bull | range | 954 | 2.684 | 47.9 | 6.863 |
| breakout_volume_strong | bear | 159 | -0.587 | 40.25 | 1.373 |
| breakout_volume_strong | bull | 2129 | 0.055 | 41.01 | 3.013 |
| breakout_volume_strong | range | 842 | 3.081 | 48.34 | 7.31 |

## 判讀

- `breakout_attack_tradable` 的 10 日淨報酬為 0.775%，20 日淨報酬為 4.127%。
- `breakout_next_not_low_open` 與 `breakout_next_low_open` 分開後，可以直接檢查「隔日不開低」是否真能改善交易報酬，而不是只改善 close-basis 延續。
- 若 `ATR14` 停損 consistently 優於突破低點停損，代表突破策略同樣不適合用過緊停損。

## 重點比較

- `breakout_next_not_low_open` 10 日淨報酬：0.412%
- `breakout_next_low_open` 10 日淨報酬：1.729%
- `breakout_next_not_low_open` 20 日淨報酬：3.344%
- `breakout_next_low_open` 20 日淨報酬：6.188%
