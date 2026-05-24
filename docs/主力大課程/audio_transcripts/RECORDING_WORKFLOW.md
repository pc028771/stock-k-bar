# 老師音檔錄製 + 轉錄自動化 Workflow

> 適用：PressPlay 影片轉音檔 → mlx-whisper 轉錄 → 整合進系統
> 環境前提：BlackHole 2ch + Multi-Output Device 已設為 Default Output

## 流程概觀

```
Chrome MCP 找影片 → AppleScript 啟動 QuickTime 錄音 → JS 播放 2x → 等待
  → AppleScript 停止+存到 ~/Movies → shell mv 到 docs/ → mlx_whisper 轉錄
```

## 關鍵教訓

### ❌ 失敗 pattern（會遺失錄音）

```applescript
tell document 1
    save in (POSIX file "/path/to/foo.m4a")  -- 可能失敗
    close saving no                           -- 但這行還是執行 → 內容遺失
end tell
```

**問題**：QuickTime audio recording save 要 `.mov` 副檔名；`.m4a` 直接 fail。
更糟：即使 save 失敗，`close saving no` 仍會關文件 → 錄音永久消失。

### ✅ 安全 pattern（user 不在電腦前）

**關鍵：用 `export ... using settings preset "Audio Only"`，不用 `save`**

- `save` 走的 API 只接受 .mov
- `export` 走的是 GUI File→Export As 的 API，可以直接輸出 .m4a（跟 GUI File→Save 結果一致）

```applescript
-- 1. Stop 錄音
tell document 1
    stop
end tell
delay 1

-- 2. Export 為 .m4a 到目標路徑（直接到 docs/ 也可）
set targetPath to "/Users/howard/Repository/stock-k-bar/docs/主力大課程/錄音_" & ¬
    (do shell script "date +%Y%m%d_%H%M%S") & ".m4a"
export document 1 in POSIX file targetPath using settings preset "Audio Only"
delay 2

-- 3. 確認檔案存在後才關
if (do shell script "test -f " & quoted form of targetPath & " && echo OK || echo MISSING") is "OK" then
    tell document 1 to close saving no
else
    -- 不關文件，保留 user 之後手動處理
    return "EXPORT FAILED, document kept open"
end if
```

不需要 shell mv，export 一步到位。

## 完整錄製腳本範例

```bash
#!/bin/bash
# record_pressplay.sh <iframe_index> <expected_duration_2x_sec> <output_filename>
IFRAME_IDX=$1
DURATION=$2
OUT_NAME=$3

# Step 1: Start QuickTime recording
osascript -e 'tell application "QuickTime Player" to activate' \
          -e 'tell application "QuickTime Player" to start (new audio recording)'

sleep 1

# Step 2: Trigger video play via Chrome MCP (caller does this)
echo "Now trigger video play in Chrome at 2x speed"

# Step 3: Wait expected duration + buffer
sleep $((DURATION + 30))

# Step 4: Stop + export 為 .m4a 直接到 docs/（用 export 不用 save）
TARGET="docs/主力大課程/${OUT_NAME}"
osascript <<APPLE
tell application "QuickTime Player"
    tell document 1 to stop
    delay 1
    export document 1 in POSIX file "$TARGET" using settings preset "Audio Only"
    delay 2
end tell
APPLE

# Step 5: 確認檔案存在才關閉文件
if [ -f "$TARGET" ]; then
    osascript -e 'tell application "QuickTime Player" to close document 1 saving no'
    echo "Saved: $TARGET"
else
    echo "ERROR: Export failed, QuickTime document kept open for manual recovery"
    exit 1
fi
```

## 重點檢核

| Step | 風險 | 防護 |
|---|---|---|
| 啟動錄音 | QuickTime 沒回應 | osascript exit code 檢查 |
| 影片播完才停 | 影片實際時長 != 推估 | 多 30 秒 buffer |
| Save 到 ~/Movies | .m4a 副檔名會 fail | 用 .mov |
| 關閉文件 | 內容沒存就關 → 永久遺失 | 必須先確認檔案存在 |
| 移到 docs/ | 路徑包含中文需 quote | 整段路徑用 "" |

## 轉錄階段

```bash
mlx_whisper "<m4a_path>" \
  --model mlx-community/whisper-large-v3-mlx \
  --language zh \
  --output-format txt \
  --output-dir /tmp
```

- 25 分鐘音檔約 5-10 分鐘轉錄（M2 Pro）
- 末尾可能有「重複句子幻覺循環」，需手動切除（grep 找重複句、截斷）
- 2x 速沒影響準確度
- 簡中錯字（和珅堂、新藏店等）後續手動正規化成台灣繁中
