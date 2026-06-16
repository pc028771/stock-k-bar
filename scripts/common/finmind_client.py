"""共用 FinMind v4 API client、含 quota-aware rate limiting + disk cache。

設計重點:
1. 啟動 + 每 5 分鐘呼叫 /v2/user_info 同步真實 quota (api_request_limit_hour) + 已用次數
2. **Per-minute proportional reset** (leaky bucket):
   - 視為每分鐘按比例釋放配額 (e.g. 6000/hr → 100/min drain)
   - 每次 access 前根據 elapsed 算 drain、used 線性下降
   - 比「整點 reset」更貼近 FinMind 的 rolling-hour 配額機制
3. Local counter + 檔案鎖 (~/.finmind_quota.json) 跨 process 共享、多 script 並跑安全
4. 接近 80% 配額自動 throttle (sleep 拉長)、≥95% 強制等回流
5. 收到 402 quota exceeded 自動 backoff + re-sync user_info
6. 收到 429/5xx exponential backoff
7. **Disk cache** (~/.finmind_cache/、可關):
   - key = (dataset, data_id, start, end) → JSON
   - 含今日資料 (end_date >= today) 不 cache
   - TTL 預設 30 天、可自訂

環境變數:
- FINMIND_TOKEN: API token (必須)
- FINMIND_QUOTA_MODE: 'strict' (預設、402/95% 拋錯) | 'wait' (sleep 到回流)
- FINMIND_CACHE: '1' (預設、開) | '0' (關)
- FINMIND_VERBOSE: '1' (印 debug)

使用範例:
    from common.finmind_client import get_client
    df = get_client().fetch_dataset(
        dataset="TaiwanStockPrice", data_id="2330",
        start_date="2026-06-01", end_date="2026-06-15",
    )
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# ── Config ───────────────────────────────────────────────────────────────────

_API_BASE = "https://api.finmindtrade.com/api/v4"
_USER_INFO_URL = "https://api.web.finmindtrade.com/v2/user_info"
_QUOTA_FILE = Path.home() / ".finmind_quota.json"
_CACHE_DIR = Path.home() / ".finmind_cache"
_QUOTA_SYNC_INTERVAL_SEC = 300   # 5 分鐘 re-sync /v2/user_info
_DEFAULT_TIMEOUT = 30
_DEFAULT_CACHE_TTL_DAYS = 30

# Throttle gates (usage_ratio → 該 request 前的 sleep 秒)
_THROTTLE_GATES = [
    (0.80, 0.5),
    (0.90, 1.0),
    (0.95, 3.0),
]


@dataclass
class QuotaState:
    limit_hour: int = 6000
    used: float = 0.0            # 用 float 才能做 fractional drain
    last_drain_ts: float = 0.0   # 上次 drain timestamp
    last_sync_ts: float = 0.0    # 上次 sync /v2/user_info timestamp

    @property
    def usage_ratio(self) -> float:
        return min(1.0, self.used / max(1, self.limit_hour))

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit_hour - self.used)

    def to_dict(self) -> dict:
        return {
            "limit_hour": self.limit_hour,
            "used": self.used,
            "last_drain_ts": self.last_drain_ts,
            "last_sync_ts": self.last_sync_ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QuotaState":
        return cls(
            limit_hour=int(d.get("limit_hour", 6000)),
            used=float(d.get("used", 0.0)),
            last_drain_ts=float(d.get("last_drain_ts", 0.0)),
            last_sync_ts=float(d.get("last_sync_ts", 0.0)),
        )


# ── Leaky-bucket drain ───────────────────────────────────────────────────────

def _drain(state: QuotaState, now: float) -> None:
    """按 elapsed × (limit_hour / 3600) 線性釋放配額、模擬 rolling-hour。"""
    if state.last_drain_ts <= 0:
        state.last_drain_ts = now
        return
    elapsed = max(0.0, now - state.last_drain_ts)
    if elapsed <= 0:
        return
    drain_amount = elapsed * (state.limit_hour / 3600.0)
    state.used = max(0.0, state.used - drain_amount)
    state.last_drain_ts = now


# ── Quota file (cross-process counter) ───────────────────────────────────────

def _load_quota() -> QuotaState:
    if not _QUOTA_FILE.exists():
        return QuotaState(last_drain_ts=time.time())
    try:
        with open(_QUOTA_FILE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            d = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return QuotaState.from_dict(d)
    except Exception:
        return QuotaState(last_drain_ts=time.time())


def _save_quota(state: QuotaState) -> None:
    tmp = _QUOTA_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(state.to_dict(), f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        tmp.replace(_QUOTA_FILE)
    except Exception:
        pass


def _atomic_update(fn) -> QuotaState:
    """以檔鎖 atomic read → modify → write。fn(state) 就地改 state。"""
    _QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _QUOTA_FILE.exists():
        _save_quota(QuotaState(last_drain_ts=time.time()))
    try:
        with open(_QUOTA_FILE, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                d = json.load(f)
                state = QuotaState.from_dict(d)
            except Exception:
                state = QuotaState(last_drain_ts=time.time())
            fn(state)
            f.seek(0)
            f.truncate()
            json.dump(state.to_dict(), f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return state
    except Exception:
        state = _load_quota()
        fn(state)
        return state


# ── Disk cache ───────────────────────────────────────────────────────────────

def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _cache_key(dataset: str, data_id: str | None, start: str | None,
               end: str | None) -> str:
    raw = f"{dataset}|{data_id or ''}|{start or ''}|{end or ''}"
    h = hashlib.sha1(raw.encode()).hexdigest()[:16]
    safe_id = (data_id or "ALL").replace("/", "_")
    return f"{dataset}_{safe_id}_{h}.json"


def _is_query_cacheable(end_date: str | None) -> bool:
    """含「今天」資料不 cache、避免快取到不完整 row。"""
    if not end_date:
        return False  # 沒指定 end → 含今天、不 cache
    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        return end_dt < datetime.now().date()
    except ValueError:
        return False


def _cache_get(key: str, ttl_days: int) -> dict | None:
    path = _CACHE_DIR / key
    if not path.exists():
        return None
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > ttl_days:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _cache_put(key: str, payload: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_CACHE_DIR / key).write_text(json.dumps(payload))
    except Exception:
        pass


# ── Client ───────────────────────────────────────────────────────────────────

class FinMindQuotaError(Exception):
    """配額耗盡 (strict mode 下拋出)。"""


class FinMindClient:
    def __init__(
        self,
        token: str | None = None,
        quota_mode: str | None = None,
        use_cache: bool | None = None,
        cache_ttl_days: int = _DEFAULT_CACHE_TTL_DAYS,
        verbose: bool | None = None,
    ):
        self.token = token or os.environ.get("FINMIND_TOKEN")
        if not self.token:
            raise RuntimeError(
                "FINMIND_TOKEN 未設定、export 後再試 (見 ~/.zshenv)"
            )
        env_mode = os.environ.get("FINMIND_QUOTA_MODE", "strict").lower()
        self.quota_mode = (quota_mode or env_mode).lower()
        if self.quota_mode not in ("strict", "wait"):
            raise ValueError(f"quota_mode 必須是 strict / wait: {self.quota_mode}")
        env_cache = os.environ.get("FINMIND_CACHE", "1") == "1"
        self.use_cache = env_cache if use_cache is None else bool(use_cache)
        self.cache_ttl_days = cache_ttl_days
        env_verbose = os.environ.get("FINMIND_VERBOSE", "0") == "1"
        self.verbose = env_verbose if verbose is None else bool(verbose)
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.token}"
        # 啟動時 sync 一次 quota
        self._sync_quota_if_needed(force=True)

    # ── public API ───────────────────────────────────────────────────────────

    def fetch_dataset(
        self,
        dataset: str,
        data_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        extra_params: dict | None = None,
        bypass_cache: bool = False,
    ) -> pd.DataFrame:
        """打 /api/v4/data、回 DataFrame。"""
        params: dict[str, Any] = {"dataset": dataset}
        if data_id:
            params["data_id"] = data_id
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if extra_params:
            params.update(extra_params)
        # Cache lookup
        cache_key = None
        if (self.use_cache and not bypass_cache and not extra_params
                and _is_query_cacheable(end_date)):
            cache_key = _cache_key(dataset, data_id, start_date, end_date)
            cached = _cache_get(cache_key, self.cache_ttl_days)
            if cached is not None:
                if self.verbose:
                    print(f"[FinMind] cache HIT: {cache_key}")
                return pd.DataFrame(cached.get("data", []))
        data = self._get(f"{_API_BASE}/data", params)
        if data.get("status") != 200:
            raise RuntimeError(f"FinMind API error: {data.get('msg', data)}")
        if cache_key:
            _cache_put(cache_key, data)
        return pd.DataFrame(data.get("data", []))

    def datalist(self, dataset: str) -> list[Any]:
        data = self._get(f"{_API_BASE}/datalist", {"dataset": dataset})
        return data.get("data", []) if data.get("status") == 200 else []

    def quota_status(self) -> dict:
        state = self._sync_quota_if_needed()
        return {
            "limit_hour": state.limit_hour,
            "used": round(state.used, 1),
            "remaining": round(state.remaining, 1),
            "usage_pct": round(state.usage_ratio * 100, 1),
            "synced_at": (datetime.fromtimestamp(state.last_sync_ts).isoformat()
                          if state.last_sync_ts else None),
            "mode": self.quota_mode,
            "cache": "on" if self.use_cache else "off",
        }

    def clear_cache(self) -> int:
        """刪光 disk cache、回傳刪除檔數。"""
        if not _CACHE_DIR.exists():
            return 0
        n = 0
        for p in _CACHE_DIR.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
        return n

    # ── internals ────────────────────────────────────────────────────────────

    def _get(self, url: str, params: dict) -> dict:
        self._throttle_if_needed()
        for attempt in range(4):
            try:
                resp = self._session.get(url, params=params,
                                          timeout=_DEFAULT_TIMEOUT)
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
                continue
            # 計入 quota
            _atomic_update(lambda s: (_drain(s, time.time()),
                                       setattr(s, "used", s.used + 1)))
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    raise RuntimeError(
                        f"FinMind 回傳非 JSON: {resp.text[:200]}")
            if resp.status_code == 402:
                self._sync_quota_if_needed(force=True)
                if self.quota_mode == "wait":
                    self._sleep_for_recharge(margin_pct=10)
                    continue
                raise FinMindQuotaError(
                    f"FinMind 配額耗盡 (402)、quota={self.quota_status()}"
                )
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(30, 2 ** attempt)
                if self.verbose:
                    print(f"[FinMind] HTTP {resp.status_code} retry in {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"FinMind HTTP {resp.status_code}: {resp.text[:200]}"
            )
        raise RuntimeError("FinMind 多次重試後仍失敗")

    def _throttle_if_needed(self) -> None:
        state = self._sync_quota_if_needed()
        ratio = state.usage_ratio
        sleep_sec = 0.0
        for gate, sec in _THROTTLE_GATES:
            if ratio >= gate:
                sleep_sec = sec
        if ratio >= 0.99:
            if self.quota_mode == "wait":
                self._sleep_for_recharge(margin_pct=10)
                return
            raise FinMindQuotaError(
                f"FinMind 配額將耗盡 ({ratio*100:.1f}%)、強制停 (strict mode)"
            )
        if sleep_sec > 0:
            if self.verbose:
                print(f"[FinMind] throttle: usage {ratio*100:.1f}% "
                       f"→ sleep {sleep_sec}s")
            time.sleep(sleep_sec)

    def _sync_quota_if_needed(self, force: bool = False) -> QuotaState:
        """drain 加 5 分鐘 sync /v2/user_info 修正。"""
        def _do_sync(state: QuotaState) -> None:
            now = time.time()
            _drain(state, now)
            if not force and (now - state.last_sync_ts) < _QUOTA_SYNC_INTERVAL_SEC:
                return
            try:
                r = self._session.get(_USER_INFO_URL, timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    if d.get("status") == 200:
                        state.limit_hour = int(
                            d.get("api_request_limit_hour")
                            or d.get("api_request_limit") or 6000)
                        # remote 是 server 真實 used、用它修正本地估算
                        remote_used = float(d.get("user_count") or 0)
                        state.used = remote_used
                        state.last_sync_ts = now
                        state.last_drain_ts = now
                        if self.verbose:
                            print(f"[FinMind] sync: "
                                   f"{remote_used:.0f}/{state.limit_hour}")
            except requests.RequestException:
                pass
        return _atomic_update(_do_sync)

    def _sleep_for_recharge(self, margin_pct: int = 10) -> None:
        """睡到剩餘 margin_pct % 配額為止。"""
        state = _load_quota()
        target_used = state.limit_hour * (1 - margin_pct / 100.0)
        excess = max(0.0, state.used - target_used)
        # drain rate = limit_hour / 3600 (per sec)
        wait_sec = excess / (state.limit_hour / 3600.0)
        wait_sec = min(max(wait_sec, 1), 3600)  # cap 1 hr
        if self.verbose:
            print(f"[FinMind] 配額耗盡、睡 {wait_sec:.0f}s 等回流到 "
                   f"≤{margin_pct}% 餘額")
        time.sleep(wait_sec)
        self._sync_quota_if_needed(force=True)


# ── 便利 wrapper ─────────────────────────────────────────────────────────────

_default_client: FinMindClient | None = None


def get_client(**kwargs) -> FinMindClient:
    """全 process 共用 default client。"""
    global _default_client
    if _default_client is None:
        _default_client = FinMindClient(**kwargs)
    return _default_client


if __name__ == "__main__":
    import argparse
    import json as _j
    p = argparse.ArgumentParser()
    p.add_argument("--clear-cache", action="store_true")
    p.add_argument("--mode", choices=["strict", "wait"], default=None)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    c = FinMindClient(
        quota_mode=args.mode,
        use_cache=not args.no_cache,
        verbose=args.verbose,
    )
    if args.clear_cache:
        n = c.clear_cache()
        print(f"已清 {n} 個 cache 檔")
    print(_j.dumps(c.quota_status(), indent=2, ensure_ascii=False))
