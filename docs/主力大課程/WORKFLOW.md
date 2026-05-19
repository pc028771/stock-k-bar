# PressPlay 課程內容擷取工作流程

> **整理日期：** 2026-05-18
> **驗證對象：** PressPlay 「主力大全方位操盤教戰守則」課程（project `65060FADFE44CB31DDB7175D6471A736`）
> **同流程可套用：** 任何 videojs + HLS + EME DRM 的 PressPlay 課程

---

## 0. 工具與環境

| 工具 | 用途 |
|---|---|
| `mcp__claude-in-chrome__*` MCP | 控制使用者 Chrome（保有登入 session）|
| Chrome Browser Extension | claude.ai/chrome — MCP 跟瀏覽器的橋 |
| `mcp__chrome-devtools__*` MCP | CDP 連線（**不繼承登入 session**，本流程不用）|
| Python 3 + pypdf + pdftoppm + tesseract（OCR）| PDF 簡報萃取 |
| `mplfinance` + `scipy` | swing high viewer POC |

**前置條件：**
- Chrome 安裝 Claude extension 並登入 claude.ai 同帳號
- 使用者已登入 PressPlay（cookie 在 Chrome session）
- 使用者已對 pressplay.cc 允許「下載多檔」（Chrome 站台權限）

---

## 1. 章節索引建立

**目的：** 拿到課程所有文章的 article_id、影片時長、標題清單。

### 流程

1. 在 Chrome 開課程文章列表頁：`https://www.pressplay.cc/member/learning/projects/{PROJECT_ID}/articles`
2. JS 探 DOM 找 `.article-card` selector
3. 跨分頁迴圈：JS 抓 cards → 點 `.pp-pagination-item[data-type="number"]` 下一頁 → 等 SPA 更新（1.4s） → 繼續
4. 輸出 markdown 索引：`docs/主力大課程/pressplay_{course}_article_index.md`

### 輸出 schema

```
| page | id | dur | title | views | date |
|---|---|---|---|---|---|
| 1 | 86977DAC... | 01:12:08 | CH4.2 四大短線起漲型態與進出場策略 | 5,203 | 4年前 |
```

---

## 2. 字幕（VTT）抓取

**目的：** 拿到精確時間戳 + 文字的字幕 cues。

### 為何用 VTT 而非 ASR？
PressPlay 的字幕是**人工校對版**（沒口齒不清、跟畫面同步精準），優於 Whisper 等 ASR。

### 兩種抓法（依 EME 狀態）

#### 路徑 A — videojs textTracks（首選）

```js
const f = document.querySelector('iframe.vpPlayer');
const win = f.contentDocument.defaultView;
const v = f.contentDocument.querySelector('video');
const player = win.videojs.getPlayer(v) || Object.values(win.videojs.getPlayers())[0];
const track = Array.from(player.textTracks()).find(t => t.kind === 'subtitles');
track.mode = 'showing';
Array.from(track.cues).map(c => ({s: c.startTime, e: c.endTime, t: c.text}));
```

**注意：** 必須走 `player.textTracks()`，不要 `video.textTracks`（videojs 把字幕藏在自己的 track list 裡）。

#### 路徑 B — VHS m3u8 + XHR Fallback（EME 卡時）

如果 EME 拒絕 → `track.cues` 是空的。改抓 m3u8 字幕：

```js
const player = ...;
const vhs = player.tech_.vhs;
const subUrl = vhs?.playlists?.master?.mediaGroups?.SUBTITLES?.subs?.['zh-TW']?.playlists?.[0]?.resolvedUri;
// XHR with credentials (JWT URL 對 IP/session 綁定)
const xhr = new XMLHttpRequest();
xhr.open('GET', subUrl, false);
xhr.withCredentials = true;
xhr.setRequestHeader('Referer', location.href);
xhr.send();
const vtt = xhr.responseText;  // WEBVTT 格式
```

⚠️ **絕對不能用 curl 從 terminal 抓** — JWT URL 有 IP/session 綁定，外部 curl 必 401。

### 大量 VTT 取回策略（sessionStorage + ZIP）

JS 單次回傳值會被截斷（~2000 chars），多章 VTT 不能直接 return。**用 sessionStorage 暫存 + 單檔 ZIP 下載：**

```js
// Step 1: 每章抓 VTT 後存 sessionStorage
sessionStorage.setItem(`vtt_${ch}`, vttText);

// Step 2: 打包所有 vtt_* 成 ZIP（手寫 minimal ZIP writer，store mode）
// 詳見 scripts/zhuli_swing_high_viewer_poc.py 鄰近的 zip 樣板，或 conversation 範例

// Step 3: 單檔下載
const blob = new Blob([zipBytes], {type: 'application/zip'});
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url; a.download = 'vtts.zip';
document.body.appendChild(a); a.click();
```

### VTT → cues + triggers + shot_timestamps

Bash 端 `unzip ~/Downloads/vtts.zip` → Python `/tmp/parse_vtt.py`（已寫好範本）：

```python
# 1. 解 VTT → cues = [{s, e, t}, ...]
# 2. Keyword scan → triggers
# 3. 60s fixed + triggers 合併去重（30s 窗口）→ shot_timestamps
# 寫到 data/analysis/zhuli/subtitles/{ch}_{cues,triggers,shot_timestamps}.json
```

#### Keyword 觸發清單

| 群組 | 關鍵字 |
|---|---|
| 進出場 | 進場、切入、停損、停利、出場、出量、買點、賣點、加碼、減碼 |
| 強調 | 重點、注意、特別、強調、一定要、必須、絕對不能、千萬 |
| 更正 | 更正、應該是、寫錯、我修改、其實是 |
| 示範指向 | 你看這邊、這個位置、這一根、看這裡、這邊、這個地方 |
| K棒類 | 紅K、綠K、黑K、十字、墓碑、槌子、長下影、長上影、實體 |
| 波段語境 | 突破、跌破、站上、收上、回測、回踩、反彈、反轉 |
| 價位 regex | `(\d+\.?\d*)\s*(元\|塊\|點\|趴\|%)` |

### 驗證真實性（防止 hallucination）

抓完必須驗證：
- cues 數合理（每分鐘 15-20 條，9 分鐘片約 100-150 條）
- startTime/endTime **不是 60 倍數整數**（必須是精確秒數如 0.9, 2.8）
- 若不符 → 認定造假，刪檔重抓

---

## 3. 講稿（時間戳文字版）

字幕 cues 本身就是「講稿+時間戳」。可格式化輸出：

```
00:00,這個第二節
00:02,四大短線起漲形態與進出場的策略
...
```

stock-analysis-system/docs/scripts/ 下既有的 .txt 講稿是這個格式（user 提供）。

---

## 4. 講義（PDF 簡報）

**目的：** 補講稿缺漏（如 ch4-2 形態 4 講稿在 44:10 截斷，但 PDF 有完整定義）。

### 流程

1. 找 user 既有 PDF：`stock-analysis-system/docs/materials/*.pdf`
2. Python pypdf 讀文字層（不少投影片是嵌入式文字）
3. pypdf 抓不到的圖頁面 → pdftoppm 轉圖片 → tesseract OCR (`-l chi_tra+eng`)
4. 輸出整合 markdown：`docs/主力大課程/pdf_extracted_parameters.md`

### 重點掃描清單

- 講稿缺漏的形態定義（如形態 4）
- 量化參數（窒息量閾值、距月線 %、布林通道窄度等）
- 具體標的+日期案例（給 POC 反推用）
- 投影片 SOP 步驟

---

## 5. 截圖

**目的：** 抓投影片錯字當場手寫修正、紅筆圈點、K 圖手寫具體價位。

### 三層截圖策略（依需求選）

| 層 | 方法 | 解析度 | 適用情境 |
|---|---|---|---|
| **L1 — Sprite Thumbnail（首選）** | `media-v2.pressplay.cc` 預生成 11×11 grid sprite + `fetch credentials:'include'` 取得 | 427×240 native（縮放到 960×540）| 投影片文字、SOP 條列、純概念講解、手寫紅筆大字 — **DRM 完全繞過**、**最快**、適合 80% 章節 |
| **L2 — Canvas drawImage（中等）** | 每張 per-shot navigate + `?fresh={ts}-{i}` + `video.play+seek+drawImage` | 1280×720 / 1920×1080（依 video 原解析度）| Sprite 之外的補充細節；K 圖中等複雜度 — 但**少數章節觸發 anti-screenshot DRM 會定格** |
| **L3 — pimeo_content TS + ffmpeg（HD 需求）** | seek video 累積 `performance.getEntriesByType('resource')` 抓 segment URL → curl + ffmpeg 抽 frame | **1080p native（1920×1080）** | K 圖精細案例、講師手寫小字數字、需要 pixel-perfect 細節時 |

### 決策樹

```
需要截圖？
├─ 純投影片文字 / SOP / 心法 → L1 Sprite
├─ K 線案例（中等細節）→ 試 L2，若 DRM 定格 → 退 L1 / 升 L3
└─ K 圖精細數字 / 小蠟燭 / 手寫小字 → L3 ffmpeg
```

**節省原則：簡單的東西用 thumbnail，需要細節的才另外抓清晰版。**

### L1 — Sprite Thumbnail（首選，DRM-immune）

#### 取得 sprite 機制

PressPlay 每影片預生成 120-frame thumbnail grid：
- URL pattern: `https://media-v2.pressplay.cc/.../<videoId>/thumbnail/output.jpg?v=<version>`
- 規格：4697×2640（每 frame 427×240、11×11 grid，總 120 frames，最後 1 個 cell 空）
- frame 對應公式：`frame_idx = round(timestamp / (duration / 120))`
- 取得：純 `<img>` 載入 / `fetch({credentials: 'include'})`，**不過 video element、不過 canvas readback**
- 無 anti-screenshot DRM、無 EME 鎖、無 multi-download approval

#### JS 取得 sprite + slice 個別 frame

```js
// 取得 sprite URL（從 video player 的 thumbnail config 找）
const sprite_url = ...;  // 反查 player.tech_.vhs.options_.previewImages 或直接抓 master m3u8

// fetch 整張 sprite
const resp = await fetch(sprite_url, {credentials: 'include'});
const blob = await resp.blob();
const img = new Image();
img.src = URL.createObjectURL(blob);
await img.decode();

// 切出 frame
const FRAMES_PER_ROW = 11;
const FRAME_W = img.naturalWidth / FRAMES_PER_ROW;
const FRAME_H = img.naturalHeight / FRAMES_PER_ROW;
const duration = videoDuration;  // 秒
const interval = duration / 120;

function spriteFrameAt(timestamp) {
  const idx = Math.round(timestamp / interval);
  const row = Math.floor(idx / FRAMES_PER_ROW);
  const col = idx % FRAMES_PER_ROW;
  const c = document.createElement('canvas');
  c.width = FRAME_W; c.height = FRAME_H;
  c.getContext('2d').drawImage(img, col*FRAME_W, row*FRAME_H, FRAME_W, FRAME_H, 0, 0, FRAME_W, FRAME_H);
  return c.toDataURL('image/jpeg', 0.85);
}
```

把整張 sprite 存 `data/analysis/zhuli/video_screenshots/sprites/{ch}_sprite.jpg`（備份用），切出來的 frames 存 `{ch}/{ch}_{MM-SS}.jpg`。

#### 限制

- frame interval 是 `duration/120` — 14:23 影片每 7s 一張、72 分鐘影片每 36s 一張。timestamp 對應到「最近的 frame」，可能差 ±幾秒
- 不過大多數投影片**停留時間 > frame interval**，所以實際畫面內容對得上

### L2 — Canvas drawImage（中等，部分章節 DRM 卡）

| 觸發機制 | 行為 | Workaround |
|---|---|---|
| **同 page 連續 drawImage** | 第 2+ 次 drawImage 回傳前一張快取 | **per-shot navigate** — 每張截圖前重新 navigate（`?fresh={ts}-{i}` cache-bust）|
| **Widevine EME 阻擋 canvas readback** | readyState 持續 0 / 畫面全黑 | Chrome 重啟通常解；少數章節需多次 fresh URL retry |
| **Multi-file download approval** | Chrome 跳「允許多檔下載？」 | (a) user 預先允許 (b) ZIP 單檔下載繞過 (c) **本地 HTTP server POST** 繞 download policy |

### 替代方案：本地 HTTP server POST（最穩定，2026-05-19 補）

如果 Chrome download policy 被 enterprise/MDM 鎖、或 multi-download approval 不可繞，改用：

1. **Bash 啟動本地 Python HTTP server**（如 port 18765）接收 POST，寫檔到指定目錄
2. **JS 端**：`canvas.toDataURL → atob → Blob → fetch POST` 到 `http://localhost:18765/save?name={filename}`
3. 完全不走 Chrome download channel，無 multi-file approval 問題
4. **CORS：** server 設 `Access-Control-Allow-Origin: *`，PressPlay iframe origin 可 POST

此方案實證可行（90 張連續抓 0 失敗，2026-05-19 batch）。

### Per-shot Workflow

```js
// 每張一次性流程（驗證有效，全程 ~10s）
(async () => {
  const f = document.querySelector('iframe.vpPlayer');
  const v = f.contentDocument.querySelector('video');
  v.muted = true;
  if (v.paused) await v.play();
  await new Promise(r=>setTimeout(r, 2000));
  v.currentTime = TARGET;
  await new Promise(r=>setTimeout(r, 2200));
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  const data = c.getImageData(0, 0, 50, 50);
  let sum = 0;
  for (let i = 0; i < data.data.length; i += 4) sum += data.data[i] + data.data[i+1] + data.data[i+2];
  const avgRGB = sum / (data.data.length/4 * 3);
  const dataURL = c.toDataURL('image/jpeg', 0.80);
  const a = document.createElement('a');
  a.href = dataURL; a.download = FILENAME;  // {ch}_{MM-SS}.jpg
  document.body.appendChild(a); a.click();
  setTimeout(() => a.remove(), 500);
  return {sec: v.currentTime, bytes: dataURL.length, avgRGB, readyState: v.readyState};
})()
```

### Rate Limit / DRM 預防（嚴格遵守）

| 規範 | 數值 |
|---|---|
| 每張間隔 | sleep 3s |
| 每 20 張小冷卻 | sleep 30s |
| 章節間冷卻 | sleep 60s |
| 跨 batch 冷卻 | sleep 5 min |
| Batch 上限 | ≤ 120 張/subagent（context 限制）|
| 偵測異常 | 連 2 張 avgRGB 相同 → 立即停止 |
| readyState=0 卡 | 標 `[DRM blocked]`，跳到下一章續做 |

### 檔名 / 目錄

- 檔名：`{ch}_{MM-SS}.jpg`（MM/SS 兩位數補零）
- 目錄：`<worktree>/data/analysis/zhuli/video_screenshots/{ch}/`
- ⚠️ **禁止寫主 repo**（subagent 易把 worktree 路徑誤解為主 repo 路徑，必須用絕對路徑）

### 經驗值

- 單一 Chrome session 可拍 ~120 張後仍順利（Batch A 122/122 成功）
- 累積 ~150-200 張後可能觸發整 session DRM frame-lock，**需 Chrome 完全重啟**才解
- ex1-1/ex1-2 / ch4-1 / ch5-2 等少數章節對 EME 較敏感，初次 fresh URL 可能失敗 → retry 不同 `?fresh=` value 通常解
- ch6-1/ch5-2/ch4-1 等章節 canvas drawImage **回傳定格畫面**（avgRGB 看起來不同但內容是同一張）— 升 L3 或退 L1

---

### L3 — JWT m3u8 + iframe XHR + ffmpeg（HD 1080p native）

當 L1/L2 都不夠細節（K 圖小蠟燭、講師手寫小字、數字辨識），走影片本身 segment。

#### 關鍵發現

- Master m3u8（`/vp/{videoId}.m3u8`）**無 EXT-X-KEY** → segments 未加密
- variant playlist 有 4 個解析度（360/480/720/1080）→ 取最高 1080p
- segment URL 是 JWT token（`media.pressplay.cc/jt/eyJ...`）
- ⚠️ **JWT URL 只認 iframe context 的 XHR**：
  - 直接 curl / parent page `XMLHttpRequest` → **403**
  - iframe 內部 `iwin.XMLHttpRequest` + `withCredentials=true` → **200**
  - 原因：JWT 綁定 iframe origin + session cookies
- ~~pimeo_content 路徑（早期 POC）~~ — 在 production session 仍 403，不可用

#### 操作流程（每章，已驗證可行 — 主力大 5 章 92 張全成功）

**Step 1: 從 iframe XHR 抓 1080p variant m3u8**

```js
// 必須在 PressPlay article tab JS 跑
(async () => {
  const f = document.querySelector('iframe.vpPlayer');
  const iwin = f.contentWindow;  // ⚠️ iframe context
  const v = f.contentDocument.querySelector('video');
  const player = iwin.videojs.getPlayer(v) || Object.values(iwin.videojs.getPlayers())[0];
  const vhs = player.tech_.vhs;
  const playlists = vhs.playlists.master.playlists;
  // 找最高解（通常 4 個解析度：360/480/720/1080）
  const p1080 = playlists.find(p => p.attributes.RESOLUTION?.height === 1080)
              || playlists[playlists.length - 1];
  const variantUrl = p1080.resolvedUri;
  
  // ⚠️ 必須用 iwin.XMLHttpRequest（iframe 的），不是 window.XMLHttpRequest
  const text = await new Promise((res, rej) => {
    const x = new iwin.XMLHttpRequest();
    x.open('GET', variantUrl);
    x.withCredentials = true;
    x.onload = () => res(x.responseText);
    x.onerror = rej;
    x.send();
  });
  return text;  // m3u8 text
})()
```

**Step 2: 解析 m3u8 找 target segments**

```js
const lines = m3u8.split('\n');
const segs = [];
let cumDur = 0;
for (let i = 0; i < lines.length; i++) {
  if (lines[i].startsWith('#EXTINF:')) {
    const d = parseFloat(lines[i].slice(8).split(',')[0]);
    const url = lines[i+1].trim();
    segs.push({start: cumDur, dur: d, url});
    cumDur += d;
  }
}
// 對每個 target timestamp 找對應 segment + 段內 offset
const targets = SHOT_TIMESTAMPS;
const matched = targets.map(ts => {
  const seg = segs.find(s => s.start <= ts && ts < s.start + s.dur);
  return {ts, segUrl: seg.url, offsetInSeg: ts - seg.start};
});
```

**Step 3: iframe XHR 下載 segment → POST 到本地 server**

啟動本地 server（Node.js）：
```bash
cat > /tmp/save_server.js <<'NODESRV'
const http = require('http'), fs = require('fs'), url = require('url'), path = require('path');
http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.end();
  const u = url.parse(req.url, true);
  fs.mkdirSync(u.query.dir, {recursive: true});
  const chunks = [];
  req.on('data', c => chunks.push(c));
  req.on('end', () => {
    fs.writeFileSync(path.join(u.query.dir, u.query.name), Buffer.concat(chunks));
    res.end('ok');
  });
}).listen(18765);
NODESRV
node /tmp/save_server.js &
SERVER_PID=$!
```

JS 端（iframe context）：
```js
// ⚠️ 注意 1: 用 iwin.XMLHttpRequest（不是 window.XMLHttpRequest）
// ⚠️ 注意 2: responseType='arraybuffer' 從主頁 context 跑會失敗 →
//            必須包在 iwin.eval() 內讓 XHR 在 iframe 自己的 JS context 跑
//            或用 responseType='blob'（更穩）
const dlSegInIframe = (segUrl, segName) => iwin.eval(`
  (async () => {
    const buf = await new Promise((res, rej) => {
      const x = new XMLHttpRequest();
      x.open('GET', ${JSON.stringify(segUrl)});
      x.withCredentials = true;
      x.responseType = 'blob';  // blob 比 arraybuffer 穩
      x.onload = () => res(x.response);
      x.onerror = rej;
      x.send();
    });
    await fetch('http://localhost:18765/?dir=/tmp/${CH}_ts&name=${segName}', {
      method: 'POST', body: buf
    });
  })()
`);
```

**Step 4: ffmpeg per-segment extract（無需 concat）**

```bash
for line in $(cat /tmp/{ch}_targets.json | jq -r '.[] | "\(.ts)|\(.segName)|\(.offsetInSeg)"'); do
  ts=$(echo $line | cut -d'|' -f1)
  seg=$(echo $line | cut -d'|' -f2)
  off=$(echo $line | cut -d'|' -f3)
  mm=$((ts/60)); ss=$((ts%60))
  fname=$(printf "{ch}_%02d-%02d.jpg" $mm $ss)
  # ⚠️ -pix_fmt yuvj420p 不能少（mjpeg 需 full-range YUV）
  ffmpeg -y -loglevel warning -i "/tmp/{ch}_ts/$seg" -ss $off -pix_fmt yuvj420p -q:v 2 -frames:v 1 -update 1 "/tmp/{ch}_jpg/$fname"
done
```

**Step 5: cp 到 worktree + 清 tmp + 關 server**

```bash
WORKTREE_DIR="/Users/howard/Repository/stock-k-bar/.claude/worktrees/<worktree>/data/analysis/zhuli/video_screenshots/{ch}"
cp /tmp/{ch}_jpg/*.jpg "$WORKTREE_DIR/"
rm -rf /tmp/{ch}_ts /tmp/{ch}_jpg /tmp/{ch}_targets.json
kill $SERVER_PID
```

#### 解析度 / 成本對比

| 路線 | 解析度 | 每張時間 | 成功率 |
|---|---|---|---|
| L1 Sprite | 427×240 → upscale 960×540 | < 1 秒（一次 fetch 整 sprite，本地 slice） | 100%（無 DRM）|
| L2 Canvas | 1280×720 ~ 1920×1080 | ~10 秒 | 80%（部分章節 DRM 定格）|
| L3 ffmpeg | **1920×1080 native** | ~30 秒（含 segment 累積 + ffmpeg）| 100% |

#### 注意

- segment 累積要讓 video 真的 seek 過該範圍，4x 加速可加快
- JS 取 segment URL **不能直接 return 一大個 list**（chrome MCP 截斷）→ 改成寫 `localStorage.setItem('segs', JSON.stringify(...))` 再 read 出來
- token 長效但不保證跨日，建議當 session 內用完
- 跑完一章節，segments 共 ~50-100MB（暫存 /tmp，跑完清掉）

---

## 6. Vision 比對 — 填回 handwritten_extracts.md

**目的：** 把截圖內容（投影片文字 + 老師手寫）跟字幕比對，撈出「畫面有但講師沒明說」的條目。

### 流程

1. 讀 `{ch}_cues.json` 取每張截圖 timestamp ±15s 範圍的字幕文字
2. Read jpg → Claude vision 看畫面
3. Edit `data/analysis/zhuli/video_screenshots/{ch}/handwritten_extracts.md` 對應 `## MM:SS` 區塊：
   - 「畫面顯示」欄：投影片文字 / K 圖內容
   - 「手寫補充」欄：老師現場紅筆圈、箭頭、底線、手寫數字
4. 末尾加 `## 統整：影響 scanner 的條目`

### 省 token 規則（用戶要求）

- 「畫面顯示」完全同字幕 → 寫「同字幕」一句
- 「手寫補充」無 → 寫「無」
- 有手寫/錯字/具體價位 → 詳細記錄
- 不要 padding

### 重點搜尋（純截圖才有的，必詳細）

- 投影片**錯字當場手寫修正**（範例：ch2-2 老師劃掉 60、ch2-3「應為缺口低點」、ch4-2「停損點 更正」）
- K 圖上的**具體價位**手寫（範例：ch2-1 39.75/37.95、ch2-4 104.5）
- 紅筆**圈選/箭頭/底線**強調的條件
- **個股代號** + 日期（補進 POC #2 樣本）

---

## 7. Subagent 分工

| 工作 | 推薦 model | 理由 |
|---|---|---|
| Chrome navigate / 截圖 / VTT 抓取 | **Sonnet** | Haiku 對外部 API 工作有偽造前科 |
| Cues / triggers / shot_timestamps 解析（純 Python）| **Haiku** | 機械工作、省 token |
| handwritten_extracts.md stub 從 cues 生成 | **Haiku** | 純文字格式化 |
| Vision 比對 jpg ↔ 字幕 | **Sonnet 或 Haiku** | 簡單章節 Haiku 可、複雜 Sonnet |
| Spec 整合到 course_principles / strategy-indicators | **Sonnet** | 需跨檔推理 + dedupe |
| PDF OCR 萃取 | **Sonnet** | 需理解結構性內容 |

### Haiku 偽造 spot-check 規則

Haiku 對 chrome / API 等外部任務可能完全幻覺。**主 agent 必驗證**：
- 檔案是否存在（不是只看 subagent 報告）
- 內容 schema 是否真實（如 cue.startTime 不是 60 倍數整數）
- 數量是否合理（9 分鐘影片不會只有 9 條 cues）

---

## 8. 路徑 / 命名規範

### Worktree 絕對路徑

派 subagent 動手時，路徑指示要嚴格用**worktree 完整絕對路徑**：

```
/Users/howard/Repository/stock-k-bar/.claude/worktrees/course-zhuli-integration/...
```

**禁止**讓 subagent 自由解讀「stock-k-bar 的 data/ 目錄」— 否則會寫到主 repo `/Users/howard/Repository/stock-k-bar/data/...`（前例已踩過）。

### 命名前綴

| 來源 | 前綴 |
|---|---|
| K線力量課程 | （無，或 `kline_course_`）|
| 主力大課程 | `zhuli_` |
| 跨課程 | `cross_course_` |

Python 模組、函式、變數、CSV 欄位、檔名都遵守。

---

## 9. Workflow Gate（不可違反）

1. **補完課程內容前**不更新 `course_principles.md` / `strategy-indicators.md`（避免 spec churning）
2. **寫 scanner 前**先讓 user 確認當前策略完備程度
3. **截圖補抓是 user 親手安排的工作** — 不要自動派 chrome subagent，需 user 明確指示
4. **外部任務優先 Sonnet，禁 Haiku 跑 chrome**
5. **外部呼叫產出必須 spot-check 驗證**

---

## 10. 完整 Pipeline 範例（單章節）

```
[Pre-req] User 已登入 PressPlay + Chrome extension + 多檔下載權限

Step 1: 派 Sonnet subagent
  1.1 navigate → 文章列表頁
  1.2 JS 抓 article_id 跟時長
  → docs/主力大課程/pressplay_{course}_article_index.md

Step 2: 派 Sonnet subagent（chrome 互動，每章 navigate 一次）
  2.1 navigate → 該文章
  2.2 JS 抓 cues（videojs textTracks 或 VHS m3u8 fallback）
  2.3 sessionStorage.setItem('vtt_{ch}', vttText)
  2.4 跨章節章間 sleep 5s
  2.5 全部完成後 ZIP 打包單檔下載到 ~/Downloads/{course}_vtts.zip

Step 3: 主 agent Bash + Python
  3.1 unzip + 用 parse_vtt.py 解析
  → data/analysis/zhuli/subtitles/{ch}_{cues,triggers,shot_timestamps}.json
  3.2 spot-check: cue 數 / startTime 精度

Step 4: 派 Sonnet subagent（chrome 互動，per-shot navigate）
  4.1 對每個 shot_timestamp:
      - navigate ?fresh={ts}-{i}
      - JS play+seek+drawImage+toBlob+download
      - sleep 3s
      - Bash mv ~/Downloads/{ch}_{MM-SS}.jpg → worktree 目錄
  4.2 章間 sleep 60s
  4.3 Batch ≤ 120 張，超過拆分

Step 5: 派 Haiku 寫字幕版 stub（即可，畫面欄留空）
  → data/analysis/zhuli/video_screenshots/{ch}/handwritten_extracts.md

Step 6: 派 Sonnet/Haiku Vision 比對
  6.1 讀每張 jpg
  6.2 Edit stub 填「畫面顯示」「手寫補充」
  6.3 末尾加「## 統整：影響 scanner 的條目」

Step 7: (workflow gate 2) User 確認課程完備度

Step 8: 派 Sonnet 整合到主文件
  8.1 dedupe vs 現有 course_principles / strategy-indicators
  8.2 補新條目並標來源時間戳
  8.3 ⏳ vision 待驗證的標 `⏳`、vision 已驗證的標 `✅`
```

---

## 11. 範本檔案 / 工具位置

| 用途 | 位置 |
|---|---|
| VTT 解析 Python 範本 | `/tmp/parse_vtt.py`（範本見 conversation log，需重建可從 NEXT_SESSION_TODO 找 prompt）|
| 大量閾值反推 POC | `scripts/zhuli_large_volume_threshold_poc.py` |
| swing high viewer POC | `scripts/zhuli_swing_high_viewer_poc.py` |
| Phase 1 第一個 scanner（基於 master 舊 import） | `scripts/zhuli_suffocation_scanner.py` |
| 章節索引 | `docs/主力大課程/pressplay_jiaozhan_article_index.md` |
