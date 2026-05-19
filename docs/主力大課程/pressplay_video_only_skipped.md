# PressPlay 主力大課程 — 純影片頁清單（無文字內文）

**抓取日期:** 2026-05-17
**課程:** 趨勢題材+族群金流+籌碼筆記=交易思維（project `486FF42F3707EF327074AC136F3CA819`）
**目的:** 記錄 16 篇候選文章中，「無文字內文僅有影片」的文章，後續若要消化內容須自行觀看影片。

## 判定方法

對每篇文章 navigate 後執行：
```js
document.querySelector('.article-content')?.innerText
```
若回傳長度 < 100 字（實際全是空白換行），判定為純影片頁。

## 抽樣探勘結果（confirmed by direct probe）

| ID | 標題 | 時長 | `.article-content` 字數 | 判定 |
|---|---|---|---|---|
| F6C1C3B7A25E3FB4CCB91BFFD75D5CE3 | ［策略心法分享課］交易前先搞懂你在賺哪一種錢 | 29:06 | 1,772 | **有內文** ✅ 已存檔 |
| EB4C7B0C2A6A6213E4D1A13DAA255229 | 復盤策略課 | 27:55 | 13 | 純影片 ⊘ |
| 64E5F179A91A17FFE7D6C037C41A6DAD | 4/17技術面培訓課程 | 24:06 | 40 | 純影片 ⊘ |
| 208588D4A0032049B1C3C96CA5BF57AC | 4/21技術面培訓課程(實戰和牛) | 21:49 | 28 | 純影片 ⊘ |
| 8F808A329EC8BB4F42EA565B406063F6 | 1/8技術面培訓課程（系列最長 40:21）| 40:21 | 40 | 純影片 ⊘ |
| 66F1708DF9CE3A81BED9614028B6240F | 4/6技術面培訓課程(實戰和牛)（系列最長 40:52） | 40:52 | 29 | 純影片 ⊘ |

5/5 「技術面培訓」/「復盤策略課」系列 = 全部純影片。Pattern conclusive。

## 跳過清單（pattern-based，未個別 probe 但同系列）

下列為剩下 9 篇技術面培訓系列，**未個別 probe**，但屬同系列、同類型 video-only 模式：

| ID | 標題 | 時長 | URL |
|---|---|---|---|
| 01D7F51084A7F37F4C75C02D0A0BEBFB | 3/31技術面培訓課程 | 17:52 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/01D7F51084A7F37F4C75C02D0A0BEBFB |
| 9AB7D51477D90F2D5D62C62B8E9D5A60 | 3/20技術面培訓課程 | 18:43 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/9AB7D51477D90F2D5D62C62B8E9D5A60 |
| 6DF4A85649B82BCED1A9B6C4D8242308 | 2/24技術面培訓課程 | 18:41 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/6DF4A85649B82BCED1A9B6C4D8242308 |
| 1DC3EF77E71B1EC124C6DDDA66D31EDD | 2/5技術面培訓課程 | 21:59 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/1DC3EF77E71B1EC124C6DDDA66D31EDD |
| B7F2DACEC2EF17D8A88364721F764974 | 1/30技術面培訓課程 | 14:28 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/B7F2DACEC2EF17D8A88364721F764974 |
| 2604C65AB6A839BD9184FE7F7269F3CB | 12/17技術面培訓課程 | 20:26 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/2604C65AB6A839BD9184FE7F7269F3CB |
| 7D5EEB7044E7298B4445C1534E8582D6 | 5/22技術面培訓課程(實戰和牛) | 22:22 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/7D5EEB7044E7298B4445C1534E8582D6 |
| 5ECE0936D955FF513C9F7CBF7AE6FECC | 5/9技術面培訓課程(實戰和牛) | 23:07 | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/5ECE0936D955FF513C9F7CBF7AE6FECC |
| 9043CB5B2F72094AE0D1D8546AE2CFB3 | 3/24技術面培訓課程(實戰和牛) | （無時長） | https://www.pressplay.cc/project/486FF42F3707EF327074AC136F3CA819/articles/9043CB5B2F72094AE0D1D8546AE2CFB3 |

## 排除（非影片，公告類）

| ID | 標題 | 備註 |
|---|---|---|
| CAA81DF374D22F27654DB961C8EBED1B | 技術面培訓專案(實戰和牛)轉移群組 | 公告，coordinator 已指示跳過 |

## 後續建議

- **技術面培訓 / 復盤策略課 / 實戰和牛系列：純影片頁，要消化內容必須自行看影片**，無法用文字 scraping。
- **「策略心法分享課」這類文章有內文**，是老師親寫的心法 + 本週新聞題材對照，未來抓其他文章類型（如「本週市場資訊報」「盤後課後檢討」「課前預習」「市場核心報告」等）值得 probe 看看。
- 在 probe「策略心法分享課」時發現該篇有引用另一篇「上次學到」（id `124D27F14375A17AE849A2BE44C3FA47`，實際標題「［本週市場資訊報］你該做最強還是高期望值」），快速 probe 發現該篇 `.article-content` 有 **5,684 字**內文，是長文範例 — 不在這次 16 篇任務範圍內，但可作為下一輪批次抓取的高優先 candidate。
