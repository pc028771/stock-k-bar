# 權證小哥兩堂課 — 重疊度 Audit 與目錄合併方案

> 產出日期：2026-06-13
> 範圍：四季投資法（2026 新課、31 章）＋ 籌碼+技術分析（2019 舊課、19 章）
> 目的：判斷是否合併目錄／prefix／命名

---

## 🔴 最關鍵發現（先講結論前提）

**兩堂課同一講師 — 都是「權證小哥」本人。**

證據：
- `docs/四季投資法/pressplay_four_seasons_article_index.md:9` 第 1 篇標題：「**權證小哥**專訪｜揭秘『四季投資法』」
- `docs/權證小哥課程/快速上手筆記.md:3` 講師「**權證小哥**」
- 四季投資法 ch9-2「軟體：盤中當沖神器（**權證小哥**）」(`course_principles.md:370`、`course_principles.md:554`)
- 四季 ch11/ch12 操作示範用的「籌碼 K 線軟體」「分點調查局」「主力買賣超 0/10/20 門檻」⼀模⼀樣

→ 這不是「兩個不同老師」的 cross-course overlap，而是**同一講師、舊課（2019）的下一代版本（2026）**。
→ overlap 度本質上很高，但四季投資法把舊課的「布林+籌碼+分點」3 工具**重新包裝**成「主力資金春夏秋冬四階段」敘事框架 + 加上 CB（可轉債）槓桿工具。

這個事實**根本性影響合併方案的選擇**（見 §D）。

---

## A. 內容 overlap 程度（主題逐項比對）

### A1. 布林軌道（高度 overlap、定義一致）

| 主題 | 四季投資法 | 籌碼+技術分析 | 一致性 |
|---|---|---|---|
| 中軌定義 | 20MA（PDF CH3 P6 + ch3-2 vision）| 20MA（`快速上手筆記.md:65`、ch06 00:42-00:50）| ✅ 完全一致 |
| 帶寬公式 | 課程未直接給公式、但 ch3-2 用「上軌斜率 >1」「位階 0-100」表達寬窄 | **(上軌/下軌 - 1) × 100**（ch06 02:33-03:04、`detector_spec.md:35`）| ✅ 互補：舊課給公式、新課用 |
| 帶寬數值門檻 | 春「帶寬 <10」、夏「上軌斜率 >1」、立夏精準版「斜率 >3」(`course_principles.md:42,84,520`)| 「**台股平均 10、20 以上算寬、30 以上算很寬、5 以下算窄**」(ch06 03:17-03:25)| ✅ 完全一致（10/20/30 同一套門檻）|
| 上下軌何時算壓力支撐 | 隱含、未明確區分 | **窄帶寬時上下軌不是壓力/支撐；寬+平行時才是**（ch06 03:46-04:33、`快速上手筆記.md:68`）| ✅ 互補：舊課多了「窄帶寬不是壓力」這個重要判別 |
| 升龍拳/降龍掌型態名稱 | 用「立夏（開布林）」「平步青雲」未提升龍拳；秋天「曲終人散」概念有但未命名 | **6 種命名型態**：升龍拳/平步青雲/降龍掌/喝了再上/平分秋色/曲終人散（ch07 全章、`快速上手筆記.md:69-77`）| ⚠️ 名稱僅舊課有；新課的「立夏開布林」≈ 舊課「升龍拳」、新課「曲終人散」(`course_principles.md:76` 隱含) ≈ 舊課「曲終人散」（明確命名）|
| K 棒離開上軌停利 | 夏季操作「乖離過大停利」（敘事化）| **「K 棒一離開上軌就找停利點」**（ch07 04:52-05:01）| ✅ 一致、舊課更操作化 |

**小結**：布林部分**舊課給「定義 + 命名」、新課給「四季敘事 + 量化參數」**，互補性極強、零衝突。

---

### A2. 主力買賣超門檻（高度 overlap、完全一致）

| 主題 | 四季投資法 | 籌碼+技術分析 | 一致性 |
|---|---|---|---|
| 主力定義 | 「前 15 名買超分點淨買超」(`course_principles.md:658` 籌碼 K 線欄位定義) | **「前 15 名買超分點 - 前 15 名賣超分點」**（ch02 01:36、ch11 02:23）| ✅ 完全一致 |
| 大買門檻 | 春「主力 5/10/20 日籌碼 >0」、立夏「主力 1/5/10/20 全 >0」（`course_principles.md:44,87,490`）| **0-10 小買、10-20 中買、20+ 大買**（ch11 02:34-02:39）| ✅ 一致：新課只規定方向、舊課給數字門檻 |
| 多頭籌碼三軸 | 「主力大買 + 散戶大買 + 集保戶大增 = 秋季倒貨」反向定義（`course_principles.md:153,322`）| **多頭 = 主力買+散戶賣+集保戶下降**（ch11 00:14-00:25、ch14）| ✅ 完全一致、新課用相同三軸 |
| 出貨四訊號 | 「分點大賣 + 主力 1/5/10/20 集中為負 + 集保戶大增 + 申報轉讓」（`course_principles.md:322-326`）| 「曲終人散 = 主力大賣 + 散戶大買 + 集保戶大增」（ch07 09:13-09:35）| ✅ 一致；新課多加「申報轉讓」+「分點集中」、舊課保留三軸最小集 |

**小結**：**完全相同的籌碼框架**，新課用四季敘事重組、舊課用 6 種型態 + 9 條策略呈現。**沒有任何衝突**。

---

### A3. 分點籌碼（中度 overlap、新課切角更細）

| 主題 | 四季投資法 | 籌碼+技術分析 | 一致性 |
|---|---|---|---|
| 關鍵分點定義 | 隱含於「分點調查局」「波段主力分點清單」(`course_principles.md:625` 12 個分點案例) | **「常常低買高賣 + 量大」**（ch09 01:50、`快速上手筆記.md:120`）| ✅ 一致；舊課給定義、新課給案例 |
| 找關鍵分點 SOP | 「分點調查局每 5 天看一次」（`course_principles.md:627`、隱含工具操作）| **3 方法**：高檔大賣／低檔大買／800-2000 天獲利排序（ch10、`detector_spec.md:116`）| ✅ 完全一致；舊課更 SOP 化 |
| 隔日沖識別 | **買均價 ≈ 漲停板**（ch9-1 02:57、`course_principles.md:547,661`）| 「同一秒鐘買多檔不同代號 = 程式交易（吃豆腐）」（隱含舊課常用、未明列）| ✅ 兩個切角互補 |
| 庫藏股分點 | **粉紅色分點 + 進場三條件（庫藏實施中 + 下通道 + 關鍵買）**（ch6-1 08:33、`course_principles.md:342`）| **粉紅色顯示 + 低檔大買高檔大賣 + 公司派出手**（ch10 01:58、ch15、`detector_spec.md:121`）| ✅ 完全一致；新課多了「下通道」這個布林條件 |
| 進場順序（誰先誰後）| 隱含於「波段主力分點清單」| **關鍵分點先進 → 投信 → 外資**（ch14 03:58-04:02、`detector_spec.md:184`）| ⚠️ 僅舊課明示；新課無此教學、屬舊課獨有 edge |

**小結**：**分點概念兩課一致，但舊課給「方法論 SOP」、新課給「實戰分點清單 + 庫藏股三條件」**。互補。

---

### A4. 集保戶數（高度 overlap、一致）

| 主題 | 四季投資法 | 籌碼+技術分析 | 一致性 |
|---|---|---|---|
| 大戶/散戶定義 | 隱含、未明列張數 | **散戶 = 100 張以下、大戶 = 10 張以上定義**（ch14、`快速上手筆記.md:127`）| ⚠️ 僅舊課明示 |
| 用途 | 「集保戶大增 = 秋季倒貨」（多處）| 「多頭：集保戶下降；空頭：集保戶大增」（ch11、ch14）| ✅ 完全一致 |
| 資料更新頻率 | 未提 | 未提（但 detector spec 寫週粒度、`detector_spec.md:230`）| ✅ 一致缺口 |

---

### A5. 量價關係 / K 線（低度 overlap、新課更深）

| 主題 | 四季投資法 | 籌碼+技術分析 | 一致性 |
|---|---|---|---|
| 起漲訊號 | 「立夏 = 大漲長紅 + 開布林 + 爆量」（`course_principles.md:97`）| 「布林軌道打開 + 沿上軌前進」（ch03 01:35、ch07）| ✅ 一致 |
| 起跌訊號 | 「秋季長紅後黑 K、月線殺兩次」（`course_principles.md:141`）| 「降龍掌 = 高檔出貨後開下軌」（ch07 06:13）| ✅ 一致 |
| 一紅一黑震盪 | **秋天明確型態**（`course_principles.md:140,161`）| 未明列、僅「曲終人散」隱含 | ⚠️ 僅新課明示 |
| 法說會行情 | 未提 | **1/4/7/10 月底法說會隔天易有大行情**（ch04、`快速上手筆記.md:36`）| ⚠️ 僅舊課獨有 |
| 董監改選 | 未提 | **年底/3 年一次、連買 + 股淨比低 + 持股低**（ch04、ch12、`快速上手筆記.md:38`）| ⚠️ 僅舊課獨有 |

---

### A6. 可轉債（CB）— 僅新課有

| 主題 | 四季投資法 | 籌碼+技術分析 |
|---|---|---|
| CB 全套教學 | **春季最強武器**（ch2-3）、夏季 CB 拉抬意願（ch3-3）、秋季 CB 轉換出貨（ch4-2）、CB 委買/市值差距 ≥10、賣回殖利率 >4%、負債比 <60%、25 個 CB 案例（`course_principles.md:260-300,886-918`）| ❌ 完全沒提 |
| CB 代號表 | **25 個 CB 代號 ↔ 母股對照**（`course_principles.md:885`）| ❌ 無 |

**這是新課最大的獨有 edge — CB 槓桿放大春天/夏天獲利效率**。舊課完全沒 CB 內容。

---

### A7. 季節敘事框架 — 僅新課有

| 主題 | 四季投資法 | 籌碼+技術分析 |
|---|---|---|
| 春夏秋冬四階段 | **核心敘事**（吃貨→拉抬→出貨→離場）| ❌ 無季節敘事；只有「多頭/空頭」二元分類 |
| 主力 vs 散戶平行時空 | **核心觀念**（`course_principles.md:19`）| ❌ 無 |
| 入秋三大警訊 | **月線兩次跌破 + 均線結構劣化 + 龍頭處置**（ch7-1）| ❌ 無 |
| 量化參數彙整表 | **完整 §九 30+ 參數**（`course_principles.md:466-550`）| ❌ 無、舊課只給布林帶寬 + 主力 20 張兩個門檻 |
| 嘉賓觀點（葉芷娟/股魚/邱沁宜）| **trailing stop 8/6/2 / 折價 7-10% / 月線兩次拉回 / 渣男暖男**（`course_principles.md:840-861`）| ❌ 無 |
| 月度實戰觀測 | **202603/04/05 三份月報**（`course_principles.md:866-882`）| ❌ 無 |

---

### A8. 多策略交叉 / 飆股口袋名單 — 僅舊課明示工程化

| 主題 | 籌碼+技術分析 | 四季投資法 |
|---|---|---|
| 9 條多頭策略 | **明列**（ch12、`detector_spec.md:144`）| 隱含於「立夏選股參數」(`course_principles.md:489-495`) |
| 6 條空頭策略 | **明列**（ch12 鏡像）| 隱含於「秋季選股參數」(`course_principles.md:497-501`) |
| 多策略交叉案例 | **超眾/亞光（多）、網家/聚陽/碩禾（空）**（ch13）| ❌ 無 |
| Score = 命中條件數 | **舊課明示方法論**（`快速上手筆記.md:177`）| ❌ 新課用「立夏/盛夏/秋/冬」邊界式分類 |

---

### A9. 權證 / 牛熊證（高度互補）

| 主題 | 籌碼+技術分析 | 四季投資法 |
|---|---|---|
| 權證教學 | **ch16-19 完整 4 章**（內含價值/DELTA/THETA/挑權證 3 口訣）| ❌ 無 |
| 牛證避股利稅 | 有（ch04）| ❌ 無 |
| 結論：盤整不能買權證 | 有（ch15 11:52）| ❌ 無 |

---

### 衝突清單（兩課同概念但講不同）

**結論：零衝突。** 所有 overlap 部分定義/門檻/方向都一致；差別只在「新課更敘事化、舊課更操作化」。

唯一需要注意的是新舊命名映射：

| 概念 | 舊課（2019）名稱 | 新課（2026）名稱 |
|---|---|---|
| 布林收斂後突破 | 升龍拳 | 立夏（開布林） |
| 高檔倒貨型態 | 曲終人散 | 秋季出貨 |
| 沿下軌走的空頭 | 降龍布林掌 | 冬季 / 秋轉冬 |

---

## B. 工程 prefix 衝突 audit

### B1. 命名衝突檢查

| 項目 | `four_seasons_` 現有 | `xiaoge_` 規劃中 | 衝突 |
|---|---|---|---|
| scripts | `four_seasons_classify.py` / `four_seasons_backtest.py` / `four_seasons_accuracy.py`（已實作）| `xiaoge_bb_squeeze_breakout` / `xiaoge_main_chip_holder` / `xiaoge_key_broker_signal` 等（未實作）| ❌ 沒命名衝突（不同 detector 名）|
| docs 目錄 | `docs/四季投資法/`| `docs/權證小哥課程/`| ❌ 沒衝突 |
| data 目錄 | `data/analysis/four_seasons/`| `data/analysis/xiaoge/`| ❌ 沒衝突 |
| DB 路徑 | **`~/.four_seasons/data.sqlite`**（symlink → `~/four_seasons_local/data.sqlite`）| 未定 | ⚠️ DB 路徑是 four_seasons 命名、但實際上是「主力大 zhuli」共用 DB（`scripts/zhuli/db.py:47` MAIN_DB 用此路徑）|
| FK / DB schema | broker_statement / 各種主力大 table 共用 | 規劃用同一 DB | ❌ 沒衝突 |

### B2. `~/.four_seasons/` DB 路徑的歷史包袱

關鍵發現（`scripts/zhuli/db.py:47`）：
```python
MAIN_DB: Path = Path.home() / ".four_seasons" / "data.sqlite"
```

這個 DB 路徑在主力大課程（zhuli）、四季投資法、未來的 xiaoge 都會用到。**改 DB 路徑是 high-risk**（要 migrate `~/.four_seasons/` 整個 sqlite 檔），目前**不建議動 DB 路徑**。

但這也代表：**「four_seasons」這個字串本來就不只是四季投資法、是 stock-k-bar 整個資料庫 root 名稱**。這降低了「把 four_seasons 改名 xiaoge」的合理性。

### B3. 既有 code 破壞度評估

| 改動 | 破壞度 | 涉及檔案 |
|---|---|---|
| Rename `scripts/four_seasons_*.py` → `scripts/xiaoge_*.py` | 🟡 medium | 3 個檔案 + 5 個 zhuli/scripts cross-ref + 4 個 worktree 副本 |
| Move `docs/四季投資法/` → `docs/權證小哥/四季投資法/` | 🟢 low | 純 docs、無 code import |
| Move `data/analysis/four_seasons/` → `data/analysis/xiaoge/seasons/` | 🟡 medium | scripts 內 `DEFAULT_OUT` 路徑要改 |
| 改 DB 路徑 `~/.four_seasons/` → `~/.xiaoge/` | 🔴 high | 4 個 zhuli scripts + 整個 sqlite 檔遷移 + 所有 worktree |

---

## C. 推薦合併方案比較

### 方案 A：完全合併（最積極）

**做什麼**：
- prefix 統一為 `xiaoge_`：rename `four_seasons_classify.py` → `xiaoge_seasons_classify.py`
- 目錄改 `docs/權證小哥/{四季,籌碼技術}/`
- data 改 `data/analysis/xiaoge/{seasons,chip}/`
- DB 路徑改 `~/.xiaoge/data.sqlite`

**工程量**：🔴 high（含 DB migration + 4 個 worktree 同步）

**破壞度**：🔴 high（DB 路徑改動風險最大）

**長期維護**：🟢 long-term clean；但短期成本高、容易出 bug

**風險**：
- DB migration 失敗會中斷 zhuli 主力大每日 scanner
- 4 個 worktree 都要同步改、容易漏
- 既有 backtest 報告路徑 reference 都失效

---

### 方案 B：保留 prefix 但合併目錄（折衷）⭐ 我的推薦

**做什麼**：
- **docs**：`docs/四季投資法/` + `docs/權證小哥課程/` → 合併為 `docs/權證小哥/{四季投資法,籌碼技術分析}/`
- **prefix 保持不變**：`four_seasons_*` 維持、`xiaoge_*` 用於舊課新 detector
- **data 不動**：`data/analysis/four_seasons/` 和 `data/analysis/xiaoge/` 維持
- **DB 路徑不動**：`~/.four_seasons/data.sqlite` 維持（已是事實上的共用 root）
- **加 README**：在 `docs/權證小哥/README.md` 寫明「兩堂課同講師、四季是 2026 新版、籌碼技術是 2019 舊版、prefix 為何不同的歷史脈絡」

**工程量**：🟢 low（只動 docs 移動 + 加 1 個 README）

**破壞度**：🟢 low（不動 code、不動 DB、不動 data path）

**長期維護**：🟡 prefix 不一致需要 README 解釋，但因為兩 prefix 分指**新課敘事框架** vs **舊課工具型 detector**，意義明確、不算包袱

**為什麼推薦**：
1. 兩課**互補不衝突**，沒必要強制統一 prefix
2. `four_seasons_` 已深入 DB 路徑、改動風險過高
3. docs 合併能體現「同講師」的事實、降低未來閱讀混淆
4. 不破壞既有 3 個 four_seasons script + 4 個 worktree

---

### 方案 C：保持完全獨立（最保守）

**做什麼**：
- 不動任何目錄/prefix
- 只在 MEMORY 加一條 cross-reference「兩課同講師、新舊版對照」

**工程量**：🟢 zero

**破壞度**：🟢 zero

**長期維護**：🟡 兩個獨立目錄看起來像兩個老師、需要每次靠 MEMORY 提醒；新人（或未來 Howard 自己）容易誤判

**問題**：未來再加第 3 堂權證小哥課程（如有）會變成第 3 個獨立目錄、越來越散亂

---

### 方案 D：自訂方案 — 「合併 docs + xiaoge_chip_ prefix」

**做什麼**：
- docs 合併同方案 B
- 舊課新 detector 用 `xiaoge_chip_*`（明示是「籌碼+技術分析」這堂的）
- 留 `xiaoge_seasons_*` 作為未來「四季投資法新 detector」的 prefix（讓兩堂課 prefix 對稱）
- 既有 `four_seasons_classify.py` 暫不 rename、加 deprecation note：未來新加的四季 detector 用 `xiaoge_seasons_*`

**工程量**：🟢 low（同方案 B）

**破壞度**：🟢 low

**長期維護**：🟢 命名對稱性好

**缺點**：未來 `four_seasons_classify.py` 跟 `xiaoge_seasons_*.py` 並存會混亂、要明確規範「新加在 xiaoge_seasons_、不動 four_seasons_」

---

## D. 結論建議

### 推薦方案：**方案 B**（保留 prefix、合併 docs 目錄）

### 為什麼

**1. overlap 是「同講師新舊版」、不是「不同講師相同主題」**
- 概念零衝突、新課是舊課的敘事重組 + CB 強化
- 不需要強制統一 prefix 來「對齊兩個來源」

**2. `four_seasons_` 已成為 DB root 命名、改動代價遠超效益**
- `~/.four_seasons/data.sqlite` 是 stock-k-bar 主資料庫
- 連 zhuli 主力大課程都 share 這個 DB
- 改名 = 4 個 worktree + DB migration + 多檔 script 路徑 + backtest 報告 reference 全變
- 風險不對等

**3. docs 合併解決閱讀混淆**
- `docs/權證小哥/{四季投資法,籌碼技術分析}/` 一眼看出同講師
- 加 README 寫清楚 2019 vs 2026、新舊命名對照
- 兩個 prefix 並存有歷史脈絡可解釋

**4. 工程改動最小、可即刻執行**
- 只需 `git mv docs/四季投資法 docs/權證小哥/四季投資法` + `git mv docs/權證小哥課程 docs/權證小哥/籌碼技術分析` + 新增 README
- 不動任何 .py、不動 DB、不動 data/
- 不破壞 4 個 worktree

### 具體執行步驟（給 Howard 拍板後參考）

```bash
# 1. 建立合併目錄
mkdir -p docs/權證小哥

# 2. 移動兩個現有目錄
git mv docs/四季投資法 docs/權證小哥/四季投資法
git mv docs/權證小哥課程 docs/權證小哥/籌碼技術分析

# 3. 新建 docs/權證小哥/README.md（內容見下）

# 4. grep 既有 docs path reference、更新（NEXT_SESSION.md、READING_REPORT.md 等）
grep -rn "docs/四季投資法\|docs/權證小哥課程" --include="*.md" --include="*.py"
```

### 建議 README 內容（docs/權證小哥/README.md）

> # 權證小哥課程（總目錄）
>
> 收錄權證小哥兩堂線上課程的整理筆記。**兩堂課同一講師、不同年代、互補不衝突。**
>
> ## 課程清單
>
> | 課程 | 上線年份 | docs 子目錄 | data 路徑 | scripts prefix | 章節數 |
> |---|---|---|---|---|---|
> | **四季投資法**（新）| 2026 | `四季投資法/` | `data/analysis/four_seasons/` | `four_seasons_*` | 31 |
> | **籌碼+技術分析**（舊）| 2019 | `籌碼技術分析/` | `data/analysis/xiaoge/` | `xiaoge_*`（規劃中、尚未實作）| 19 |
>
> ## 新舊版關係
>
> 四季投資法 = 籌碼+技術分析的 2026 敘事重組版 + CB 槓桿強化。共用底層工具（布林軌道、主力買賣超、分點、集保戶數），但用「春夏秋冬主力四階段」框架重新包裝。
>
> ## 新舊命名對照（同概念不同名）
>
> | 舊課（2019）| 新課（2026）|
> |---|---|
> | 升龍拳 | 立夏（開布林）|
> | 曲終人散 | 秋季出貨四訊號 |
> | 降龍布林掌 | 冬季 / 秋轉冬 |
>
> ## prefix 為何不統一
>
> `four_seasons_` 已成為 stock-k-bar 主 DB root 名稱（`~/.four_seasons/data.sqlite`），改名代價過高。`xiaoge_` 用於舊課新 detector 的工程實作。詳見 `docs/權證小哥/cross_course_overlap_audit.md`。

---

## 附錄：源頭引用清單

- 四季投資法主 spec：`docs/四季投資法/course_principles.md` 943 行（時間戳齊全）
- 四季 PressPlay 索引：`docs/四季投資法/pressplay_four_seasons_article_index.md` 第 1 篇即「權證小哥專訪」
- 舊課 transcript：`data/analysis/xiaoge/transcripts/ch01.txt`–`ch19.txt`（19 章）
  - ch06：布林帶寬定義
  - ch07：6 種布林型態（升龍拳/平步青雲/降龍掌/喝了再上/平分秋色/曲終人散）
  - ch11：多空頭籌碼三軸 + 主力 0/10/20 門檻
  - ch12：9 條多頭 + 6 條空頭策略 + 飆股口袋名單
  - ch14-15：關鍵分點實作 + 庫藏股分點
- 既有實作：`scripts/four_seasons_classify.py`、`scripts/four_seasons_backtest.py`、`scripts/four_seasons_accuracy.py`
- DB 路徑：`scripts/zhuli/db.py:47` `MAIN_DB = ~/.four_seasons/data.sqlite`
