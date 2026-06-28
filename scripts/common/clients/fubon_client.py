"""Fubon Securities market data client.

從 stock-analysis-system/clients/fubon_client.py vendor 過來、砍掉 stock-k-bar
不使用的方法 (`load_60m_kbar` / `load_kbar_tf` / `fetch_macd_dif` /
`get_movers` / `get_actives`、`get_price` 也砍 — stock-k-bar 用 FinMind 拿歷史)。

使用 fubon_neo SDK (https://www.fbs.com.tw/TradeAPI/) 實作只讀 market data。

SDK 安裝:
    pip install /Users/howard/.fubon/fubon_neo-2.2.8-cp37-abi3-macosx_11_0_arm64.whl

Env vars (或傳到 constructor):
    FUBON_ACCOUNT_ID   — 身分證字號 (personalID)
    FUBON_API_KEY      — API Key（優先；需搭配 FUBON_ACCOUNT_ID）
    FUBON_PASSWORD     — 登入密碼（傳統憑證登入時用；有 API_KEY 則忽略）
    FUBON_CERT_PATH    — 憑證 .p12 路徑（網頁憑證匯出後填入）
    FUBON_CERT_PW      — 憑證密碼（預設 = 身分證字號）

(向後相容: 也接受舊 env var FUBON_PID / FUBON_PWD / FUBON_CREDENTIAL_FILE /
FUBON_CREDENTIAL_PWD)

Login methods (擇一):
    A. API Key login (>= v2.2.7、推薦):
       sdk.apikey_login(FUBON_ACCOUNT_ID, FUBON_API_KEY, FUBON_CERT_PATH, FUBON_CERT_PW)
    B. Password login (傳統):
       sdk.login(FUBON_ACCOUNT_ID, FUBON_PASSWORD, FUBON_CERT_PATH, FUBON_CERT_PW)

Rate limits:
    Intraday:   300 req/min
    Snapshot:   300 req/min
    Historical: 60 req/min
    WebSocket:  200 symbols / connection、最多 5 連線
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd

from common.clients.base import SnapshotDict

logger = logging.getLogger(__name__)

# ── Rate-limit circuit breaker ────────────────────────────────────────────────
# 被打到 rate limit 時、繼續每 ticker 每輪硬打 = (1) log 洪水 (2) 限額一直不恢復。
# 命中 429/Fugle rate exceeded → 進入 cooldown：cooldown 內直接回 None、不打 API、
# 不重複 log (只在進入時 log 一次)、讓限額自己恢復。
_RATE_COOLDOWN_SEC = 60.0
_rate_blocked_until: float = 0.0


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return "rate limit" in s or "429" in s or "too many" in s


def _snap_from_quote(q) -> "SnapshotDict | None":
    """單筆 quote dict → normalized SnapshotDict。get_realtime_snapshot +
    批次 get_snapshot_quotes_map 共用、欄位對應一致 (避免兩處 drift)。"""
    if not q:
        return None
    # 富邦官方 schema (2026-06 doc 驗證):
    #   單檔 intraday.quote → 巢狀 total.tradeVolume
    #   批次 snapshot/quotes → 平的 tradeVolume (無 total 物件)
    # 兩種形狀都吃: 先平的、再巢狀。
    total = _get(q, "total") or {}
    trade_volume_shares = _safe_int(
        _get(q, "tradeVolume", "trade_volume")
        or _get(total, "tradeVolume", "trade_volume")) or 0
    trade_value = _safe_float(
        _get(q, "tradeValue", "trade_value")
        or _get(total, "tradeValue", "trade_value")) or 0.0
    close = _safe_float(
        _get(q, "closePrice", "close_price") or _get(q, "lastPrice", "last_price"))
    if close is None:
        return None
    return {
        "close":        close,
        "open":         _safe_float(_get(q, "openPrice", "open_price")) or 0.0,
        "high":         _safe_float(_get(q, "highPrice", "high_price")) or 0.0,
        "low":          _safe_float(_get(q, "lowPrice", "low_price")) or 0.0,
        "change_price": _safe_float(_get(q, "change")) or 0.0,
        "change_rate":  _safe_float(_get(q, "changePercent", "change_percent")) or 0.0,
        "total_volume": trade_volume_shares // 1000,   # 股 → 張
        "total_amount": trade_value,
    }


# ---------------------------------------------------------------------------
# Response-parsing helpers
# ---------------------------------------------------------------------------

def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """安全從 dict / SDK object 取值、嘗試多個 key 名稱。

    依序試 snake_case、attribute、camelCase 三種形式、第一個命中即回傳。
    """
    for key in keys:
        # dict-style
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
        # attribute-style (SDK objects)
        if hasattr(obj, key):
            v = getattr(obj, key)
            if v is not None:
                return v
        # camelCase alternative (some SDK versions)
        camel = _to_camel(key)
        if isinstance(obj, dict) and camel in obj:
            return obj[camel]
        if hasattr(obj, camel):
            v = getattr(obj, camel)
            if v is not None:
                return v
    return default


def _to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _extract_data(resp: Any) -> list[dict]:
    """從 SDK response (.data / dict / list) 抽出 list[dict]。"""
    if resp is None:
        return []
    if hasattr(resp, "data") and resp.data is not None:
        data = resp.data
    elif isinstance(resp, dict) and "data" in resp:
        data = resp["data"]
    elif isinstance(resp, list):
        data = resp
    else:
        data = [resp]

    if not data:
        return []

    out: list[dict] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
        else:
            try:
                out.append({k: v for k, v in vars(item).items() if not k.startswith("_")})
            except TypeError:
                out.append({})
    return out


def _extract_single(resp: Any) -> dict:
    items = _extract_data(resp)
    return items[0] if items else {}


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# FubonClient
# ---------------------------------------------------------------------------

class FubonClient:
    """Fubon Securities market data client。

    Lazy initialization: SDK 在第一次呼叫 API 時才連線。

    保留方法 (stock-k-bar grep 確認真實使用):
        - get_realtime_snapshot — 即時快照
        - load_kbar             — 過去 N 日 1 分 K + 今日 1 分 K
        - get_snapshot_quotes   — 全市場單一 market 快照
        - fetch_intraday_candles — async 多檔 × 多週期、httpx 並發
        - subscribe_quotes      — WebSocket 訂閱
        - disconnect            — cleanup
    """

    def __init__(
        self,
        account_id: str | None = None,
        api_key: str | None = None,
        password: str | None = None,
        cert_path: str | None = None,
        cert_password: str | None = None,
    ) -> None:
        # 保留舊 env var 名稱向後相容 (FUBON_PID / FUBON_PWD / FUBON_CREDENTIAL_*)
        self.account_id    = account_id    or os.environ.get("FUBON_PID", "") or os.environ.get("FUBON_ACCOUNT_ID", "")
        self.api_key       = api_key       or os.environ.get("FUBON_API_KEY", "")
        self.password      = password      or os.environ.get("FUBON_PWD", "") or os.environ.get("FUBON_PASSWORD", "")
        self.cert_path     = cert_path     or os.environ.get("FUBON_CREDENTIAL_FILE", "") or os.environ.get("FUBON_CERT_PATH", "")
        self.cert_password = cert_password or os.environ.get("FUBON_CREDENTIAL_PWD", "") or os.environ.get("FUBON_CERT_PW", "")

        self._sdk: Any        = None
        self._reststock: Any  = None  # sdk.marketdata.rest_client.stock
        self._account: Any    = None  # accounts.data[0]

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Lazy login + market-data 連線、失敗拋 RuntimeError。"""
        if self._reststock is not None:
            return

        try:
            from fubon_neo.sdk import FubonSDK  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "fubon_neo SDK 未安裝。"
                "從 https://www.fbs.com.tw/TradeAPI/ 下載 .whl 再 pip install。"
            ) from exc

        sdk = FubonSDK()

        # 優先用 API Key login (>= v2.2.7)、缺 api_key 則 fallback password
        if self.api_key:
            accounts = sdk.apikey_login(
                self.account_id,
                self.api_key,
                self.cert_path,
                self.cert_password,
            )
        else:
            accounts = sdk.login(
                self.account_id,
                self.password,
                self.cert_path,
                self.cert_password,
            )

        if not _get(accounts, "is_success", "isSuccess", default=False):
            msg = _get(accounts, "message", default="unknown error")
            raise RuntimeError(f"Fubon login failed: {msg}")

        sdk.init_realtime()

        self._sdk = sdk
        data = _get(accounts, "data", default=[])
        self._account = data[0] if data else None
        self._reststock = sdk.marketdata.rest_client.stock
        logger.info("FubonClient connected")

    def disconnect(self) -> None:
        """Logout + reset 連線狀態。"""
        if self._sdk is not None:
            try:
                self._sdk.logout()
            except Exception:
                pass
        self._sdk = None
        self._reststock = None
        self._account = None

    # ------------------------------------------------------------------
    # Snapshot / KBar
    # ------------------------------------------------------------------

    def get_realtime_snapshot(self, stock_id: str) -> SnapshotDict | None:
        """即時盤中報價。

        Fubon API 欄位映射至 SnapshotDict:
            closePrice / lastPrice → close
            openPrice              → open
            highPrice              → high
            lowPrice               → low
            change                 → change_price
            changePercent          → change_rate
            total.tradeVolume      → total_volume (股 → 張、÷1000)
            total.tradeValue       → total_amount

        Returns None 當不可得 (盤後 / API error / rate-limit cooldown 中)。
        """
        global _rate_blocked_until
        # 指數類 symbol (TAIEX/TPEX 等純字母、無數字) 富邦/Fugle 無 stock intraday 端點
        # (官方文件確認 404)。直接回 None、不打 API、不洗 warning。指數報價走 FinMind
        # (見 WSPriceCache._index_snapshot)。股票/ETF/債券 ETF (00679B 等含數字) 不受影響。
        if not any(c.isdigit() for c in str(stock_id)):
            return None
        if time.monotonic() < _rate_blocked_until:
            return None                      # cooldown 中：不打 API、不 log
        try:
            self._ensure_connected()
            resp = self._reststock.intraday.quote(symbol=stock_id)
            q = _extract_single(resp)
            return _snap_from_quote(q)

        except Exception as exc:
            if _is_rate_limit(exc):
                _rate_blocked_until = time.monotonic() + _RATE_COOLDOWN_SEC
                logger.warning("FubonClient rate-limited、暫停 snapshot %.0fs (期間回 None、不重打)",
                               _RATE_COOLDOWN_SEC)
            else:
                logger.warning("FubonClient.get_realtime_snapshot(%s) failed: %s", stock_id, exc)
            return None

    def load_kbar(self, stock_id: str, days: int = 14) -> pd.DataFrame | None:
        """過去 N 個 calendar day 的 1 分 K + 今日盤中 1 分 K。

        Returns DataFrame columns: datetime, open, high, low, close, volume。
        Returns None 沒資料。

        Note: 歷史 1 分 K 受 FBS 保留期限影響、不可得時 fallback 用更大週期。
        """
        try:
            self._ensure_connected()
            today = date.today()
            start = (today - timedelta(days=days)).isoformat()
            yesterday = (today - timedelta(days=1)).isoformat()

            frames: list[pd.DataFrame] = []

            # --- Historical 1-min candles (past days) ---
            if start <= yesterday:
                try:
                    resp = self._reststock.historical.candles(
                        **{"symbol": stock_id, "from": start, "to": yesterday, "timeframe": "1"}
                    )
                    rows = _extract_data(resp)
                    if rows:
                        df_hist = pd.DataFrame(rows)
                        df_hist = _normalize_ohlcv_columns(df_hist)
                        df_hist["datetime"] = pd.to_datetime(df_hist["date"])
                        frames.append(df_hist)
                except Exception as exc:
                    logger.debug("FubonClient.load_kbar historical failed for %s: %s", stock_id, exc)

            # --- Today's intraday 1-min candles ---
            try:
                resp_today = self._reststock.intraday.candles(
                    symbol=stock_id, timeframe="1"
                )
                rows_today = _extract_data(resp_today)
                if rows_today:
                    df_today = pd.DataFrame(rows_today)
                    df_today = _normalize_ohlcv_columns(df_today)
                    date_col = df_today["date"].astype(str)
                    if date_col.str.len().max() <= 5:  # "HH:MM" format
                        df_today["datetime"] = pd.to_datetime(
                            today.isoformat() + " " + date_col
                        )
                    else:
                        df_today["datetime"] = pd.to_datetime(date_col)
                    frames.append(df_today)
            except Exception as exc:
                logger.debug("FubonClient.load_kbar intraday failed for %s: %s", stock_id, exc)

            if not frames:
                return None

            combined = pd.concat(frames, ignore_index=True)
            combined = combined.dropna(subset=["close"])
            if combined.empty:
                return None

            return (
                combined[["datetime", "open", "high", "low", "close", "volume"]]
                .sort_values("datetime")
                .reset_index(drop=True)
            )

        except Exception as exc:
            logger.warning("FubonClient.load_kbar(%s) failed: %s", stock_id, exc)
            return None

    # ------------------------------------------------------------------
    # Intraday candles (multi-symbol async)
    # ------------------------------------------------------------------

    def fetch_intraday_candles(
        self,
        symbols: list[str],
        timeframes: "list[str] | None" = None,
    ) -> "dict[str, dict[str, pd.DataFrame | None]]":
        """並發抓多檔 × 多週期的今日盤中 K 線。

        每次呼叫回傳整段 session-to-now bars (開盤到現在分鐘)。
        refresh cycle 每次呼叫拿最新 bar 給 MACD 計算用。

        Args:
            symbols:    股票代號清單
            timeframes: timeframe 清單 (預設 ["5", "60"])

        Returns:
            {symbol: {timeframe: DataFrame(datetime, open, high, low, close, volume) or None}}
        """
        import asyncio
        import httpx

        if timeframes is None:
            timeframes = ["5", "60"]

        self._ensure_connected()
        base_url = self._reststock.config["base_url"]
        headers = {"X-SDK-TOKEN": self._reststock.config["sdk_token"]}
        today = date.today()

        async def _fetch_one(
            client: httpx.AsyncClient,
            sem: asyncio.Semaphore,
            sym: str,
            tf: str,
        ) -> "pd.DataFrame | None":
            async with sem:
                try:
                    resp = await client.get(f"{base_url}/intraday/candles/{sym}", params={"timeframe": tf})
                    rows = resp.json().get("data") or []
                    if not rows:
                        return None
                    df = pd.DataFrame(rows)
                    df = _normalize_ohlcv_columns(df)
                    date_col = df["date"].astype(str)
                    if date_col.str.len().max() <= 5:  # "HH:MM"
                        df["datetime"] = pd.to_datetime(today.isoformat() + " " + date_col)
                    else:
                        df["datetime"] = pd.to_datetime(date_col)
                    return (
                        df[["datetime", "open", "high", "low", "close", "volume"]]
                        .dropna(subset=["close"])
                        .sort_values("datetime")
                        .reset_index(drop=True)
                    )
                except Exception as exc:
                    logger.warning("fetch_intraday_candles(%s, %s) failed: %s", sym, tf, exc)
                    return None

        async def _gather_all() -> "dict[str, dict[str, pd.DataFrame | None]]":
            sem = asyncio.Semaphore(2)
            keys = [(sym, tf) for sym in symbols for tf in timeframes]
            async with httpx.AsyncClient(headers=headers) as client:
                values = await asyncio.gather(*[_fetch_one(client, sem, sym, tf) for sym, tf in keys])
            results: dict[str, dict[str, pd.DataFrame | None]] = {sym: {} for sym in symbols}
            for (sym, tf), val in zip(keys, values):
                results[sym][tf] = val
            return results

        return asyncio.run(_gather_all())

    # ------------------------------------------------------------------
    # Market-wide snapshot + WebSocket subscription
    # ------------------------------------------------------------------

    def get_snapshot_quotes(self, market: str = "TSE") -> list[dict]:
        """抓全市場 (TSE/OTC/...) 快照。

        Args:
            market: "TSE" (上市) / "OTC" (上櫃) / "ESB" (興櫃一般) /
                    "TIB" (創新板) / "PSB" (興櫃戰略)

        Returns:
            list[dict]、失敗回空 list。
        """
        try:
            self._ensure_connected()
            resp = self._reststock.snapshot.quotes(market=market)
            return _extract_data(resp)
        except Exception as exc:
            logger.warning("FubonClient.get_snapshot_quotes(%s) failed: %s", market, exc)
            return []

    def get_snapshot_quotes_map(self, markets=("TSE", "OTC")) -> dict:
        """批次拿整盤快照 → {symbol: SnapshotDict}。

        ⚡ 1-2 個 request 拿全市場 (vs 逐檔 get_realtime_snapshot 數百 req)。
        WS fallback / 大量 ticker 用、避免打爆 snapshot 300/min。rate-limit cooldown
        中直接回 {}。symbol 欄位嘗試 symbol / stock_id / code。
        """
        global _rate_blocked_until
        if time.monotonic() < _rate_blocked_until:
            return {}
        out: dict = {}
        for mkt in markets:
            try:
                self._ensure_connected()
                rows = _extract_data(self._reststock.snapshot.quotes(market=mkt))
            except Exception as exc:
                if _is_rate_limit(exc):
                    _rate_blocked_until = time.monotonic() + _RATE_COOLDOWN_SEC
                    logger.warning("FubonClient rate-limited (batch)、暫停 %.0fs", _RATE_COOLDOWN_SEC)
                    break
                logger.warning("get_snapshot_quotes_map(%s) failed: %s", mkt, exc)
                continue
            for q in rows or []:
                sym = _get(q, "symbol", "stock_id", "code")
                snap = _snap_from_quote(q)
                if sym and snap:
                    out[str(sym)] = snap
        return out

    def subscribe_quotes(
        self,
        symbols: list[str],
        on_message: Any,
        channel: str = "aggregates",
    ) -> Any:
        """訂閱 WebSocket 即時報價。

        Args:
            symbols:    股票代號清單
            on_message: callback(message: str) -> None
            channel:    "aggregates" (best quote + trade) / "trades" / "books" / "candles"

        Returns:
            WebSocket stock client (呼叫 .disconnect() 終止)。

        Note: 單一連線最多 200 symbols、同時最多 5 連線。
        """
        try:
            self._ensure_connected()
            ws = self._sdk.marketdata.websocket_client.stock
            ws.on("message", on_message)
            ws.connect()
            for symbol in symbols:
                ws.subscribe({"channel": channel, "symbol": symbol})
            return ws
        except Exception as exc:
            logger.error("FubonClient.subscribe_quotes failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OHLCV_ALIASES: dict[str, list[str]] = {
    "date":   ["date", "Date"],
    "open":   ["open", "Open", "openPrice", "open_price"],
    "high":   ["high", "High", "highPrice", "high_price"],
    "low":    ["low",  "Low",  "lowPrice",  "low_price"],
    "close":  ["close", "Close", "closePrice", "close_price"],
    "volume": ["volume", "Volume", "tradeVolume", "trade_volume"],
}


def _normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """將 SDK 回傳的 column 名稱統一改成標準 OHLCV。"""
    rename: dict[str, str] = {}
    for std_name, aliases in _OHLCV_ALIASES.items():
        for alias in aliases:
            if alias in df.columns and std_name not in df.columns:
                rename[alias] = std_name
                break
    if rename:
        df = df.rename(columns=rename)
    for col in ("date", "open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = None
    return df
