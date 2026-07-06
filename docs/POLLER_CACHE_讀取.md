# 讀 poller cache 即時價（任何 session 共用）

poller 把即時價寫成檔案、**任何 session/process 直接讀同一份**、不用各自跑 poller。

## 讀法
```python
import json
d = json.load(open('/tmp/zhuli_cache/snapshot.json'))
print('更新時間:', d['ts'])
s = d['data']['2303']            # 代號當 key (聯電)
print(s['close'], s['change_rate'], s['open'], s['high'], s['low'])
```

## 三個 cache 檔
| 檔案 | 內容 |
|---|---|
| `/tmp/zhuli_cache/snapshot.json` | 全市場即時價 (~2800檔、close/change_rate/open/high/low) |
| `/tmp/zhuli_cache/positions.json` | 持倉 + 算好的損益/停損 |
| `/tmp/zhuli_cache/watchlist.json` | watchlist |

## 🔴 鐵則
- **只需 1 個 poller 在跑** → 其他 session **只 READ 檔案、禁自己啟動 poller**（重複打 Fubon API 撞 rate limit）
- 檢查 poller 是否在跑：`pgrep -f live_cache_poller`
- 更新頻率：盤中每 5s（見下）、盤後 600s（盤後價不動）
- **法人籌碼不在 cache**（在 DB `institutional_investors`、on-demand、晚上 20:00 更新確定版）

## poller 資料源
- 主：Fubon `get_snapshot_quotes_map(markets=('TSE','OTC'))` = **REST snapshot**（整市場 ~1s 真即時、非 websocket）
- fallback：FinMind `taiwan_stock_tick_snapshot`（也 REST）
- Rate limit：Fubon snapshot **300 req/min**、資料 ~1s 更新 → 盤中輪詢 5s（12/min、遠低於上限）
