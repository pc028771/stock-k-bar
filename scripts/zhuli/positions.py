"""
Source of truth for HELD / WATCH / PLAN_PRIMARY / TEACHER_PERSONAL_TIERS。

v1 (live_position_monitor.py) 和 v2 (live_position_monitor_v2.py) 都 import 此檔、
避免重複定義 + 命名混淆。

維護時改這裡、不要改 v1。
"""
from __future__ import annotations

# 🎯 老師 6/15-6/16 個人持倉族群順序 (per memory feedback_teacher_personal_holdings_20260616)
# 1=重壓、6=輕配置；不在表 = 不對齊老師 6 族群
TEACHER_PERSONAL_TIERS: dict[str, tuple[int, str]] = {
    # Tier 1: 成熟製程 (聯電系)
    '2303': (1, '🥇 成熟製程'),
    '3264': (1, '🥇 成熟製程+封測'),
    '6257': (1, '🥇 成熟製程+封測'),
    '3265': (1, '🥇 成熟製程+封測'),
    # Tier 2: 光學鏡頭
    '3008': (2, '🥈 光學鏡頭'),
    '4938': (2, '🥈 光學鏡頭'),
    '3406': (2, '🥈 光學鏡頭'),
    '6209': (2, '🥈 光學鏡頭'),
    # Tier 3: 矽晶圓
    '6182': (3, '🥉 矽晶圓'),
    '3532': (3, '🥉 矽晶圓'),
    '6488': (3, '🥉 矽晶圓'),
    # Tier 4: 面板
    '3481': (4, '4️⃣ 面板'),
    '3149': (4, '4️⃣ 面板'),
    # Tier 5: ABF
    '8046': (5, '5️⃣ ABF'),
    '1303': (5, '5️⃣ ABF/CCL'),
    '3037': (5, '5️⃣ ABF'),
    '3189': (5, '5️⃣ ABF'),
    # Tier 6: 被動
    '2375': (6, '6️⃣ 被動'),
    '2472': (6, '6️⃣ 被動'),
    '2327': (6, '6️⃣ 被動'),
    '2492': (6, '6️⃣ 被動'),
    '6173': (6, '6️⃣ 被動'),
    '3026': (6, '6️⃣ 被動'),
    '6449': (6, '6️⃣ 被動'),
}
# 格式: dict (必填: ticker, name, cost, shares, stop; 選填: tactic, priority, source, sector, note)
# 舊 tuple (ticker, name, cost, shares, stop) 自動 convert
HELD = [
    # 6285 啟碁 6/15 全清 @ $273 (-$43,053 / -13.66%)、按紀律出場 (晚 5 天、6/8 已破停損)
    {
        'ticker': '1605', 'name': '華新',
        'cost': 40.23, 'shares': 12000, 'stop': 38.75,
        'strategy_mode': 'core',       # 核心持倉、結構底停損
        'tactic': '核心', 'priority': 3,
        'source': '老師重壓',
        'sector': '紅海第二棒',
        'note': '6/2 8 張 @ $40.1 + 6/3 加 4 張 @ $40.5、均 $40.23'
    },
    {
        'ticker': '2885', 'name': '元大金',
        'cost': 58.0, 'shares': 10000, 'stop': 64.6,
        'strategy_mode': 'core',       # 核心配置、結構底 trailing
        'tactic': '配置', 'priority': 1,
        'source': '配置部位',
        'sector': '金融',
        'note': '6/16 trailing ↑ $64.6 (6/15 新黑K低、已脫離成本 +11%、原 $62.2)'
    },
    {
        'ticker': '3481', 'name': '群創',
        'cost': 58.7, 'shares': 2000, 'stop': 51.0,
        'strategy_mode': 'disposal_swing',  # 處置股紀律: stop = 進場時 MA10
        'tactic': '題材', 'priority': 3,
        'source': '老師明示 6/3 + 處置中 (6/17 處置最後一天、6/18 出關)',
        'sector': '面板/族群補漲',
        'note': '🔒 6/4 D+1 進處置、6/8-12 跌破 MA10 但老師「希望均線過來」、6/15-16 站回 MA10 ($51) 結構修復、stop = MA10 $51 (處置股紀律、非 trailing $56.2)、6/18 出關當天觀察、不主動砍'
    },
    # 8046 南電 6/5 全清 (1000 @ $851 + 200 @ $838、共鎖 ~$57.7k 損)
    {
        'ticker': '1303', 'name': '南亞',
        'cost': 104.5, 'shares': 1000, 'stop': 96.9,
        'strategy_mode': 'swing',
        'tactic': '題材', 'priority': 3,
        'source': '老師明示 6/5 Stage 1 1/3',
        'sector': 'ABF/塑化',
        'note': '6/5 Stage 1 進 1 張 @ $104.5、6/15 trailing ↑ $96.9 (6/9 新黑K低、原 MA20 $92.7)'
    },
    # 3264 欣銓 6/10 全清 @ $222 (-$7,345 / -3.21%)、按尼克老師「沒收復 6/5 低」規則出場
    # 6257 矽格 6/10 全清 @ $212 (-$11,808 / -5.30%)、同 3264 一起減倉
    {
        'ticker': '2303', 'name': '聯電',
        'cost': 139.0, 'shares': 1000, 'stop': 137.0,
        'strategy_mode': 'swing',
        'tactic': '戰略級', 'priority': 3,
        'source': '老師明示 6/14 戰略級 + 6/16「黑K+籌碼漂亮」模式',
        'sector': '成熟製程',
        'note': '6/17 10:30 限價 $139 成交、盤中 stop $137 被測 2 次 ($137.5 → $136.5 → $137 反彈)、結構底極限、按課程鐵則收盤為準、13:25 收盤定奪、明日 6/18 開盤大殺 → 紀律砍、絕對不加碼 Stage 2、target $145、戰略級 ⭐⭐⭐'
    },
    {
        'ticker': '6239', 'name': '力成',
        'cost': 346.0, 'shares': 1000, 'stop': 340.0,
        'strategy_mode': 'swing',
        'tactic': '題材', 'priority': 3,
        'source': '老師三重背書 6/13 OSAT + 6/14 融資股 + 6/11 直播',
        'sector': '封測 OSAT',
        'note': '6/16 13:26 Stage 1 進 1 張 @ $346、緊 stop $340 (盤中均線)、結構 stop $321 (今 L)、目標 $357-370'
    },
]
# 格式: dict (必填: ticker, name, shares, stop; 選填: tactic, priority, source, sector, note, reason)
# 舊 tuple (ticker, name, shares, stop, reason) 自動 convert
PLAN_PRIMARY: list = [
    # 6/16 過期 plan 移除:
    #   - 1605 華新加碼: 6/16 沒執行、user 重新評估後仍未拍板
    #   - 2472 立隆電: 6/16 跌停 -9.97%、stop $361 必然破、plan 失效
    # 6/17 2303 聯電已成交 → 移入 HELD
    #
    # 6/17 user 自選 2891 中信金新進場 (替代 2885 元大金求爆發力)
    {
        'ticker': '2891', 'name': '中信金',
        'shares': 1000,                  # 1 張試水 (Stage 1)
        'target_price': 70.8,            # 6/16 close
        'stop': 68.0,                    # MA10 ~$68.4 略低、結構底
        'condition': (
            '次一交易日 (6/22 端午後) 13:00 後尾盤 + 收盤 ≥ $69 + '
            '守 MA10 ~$68.4 + 不跳空 +3%+ + 6/16 籌碼延續 (外資/投信仍進)'
        ),
        'priority': 'new_entry',
        'rationale': (
            '雙軸籌碼大買: 6/16 外資 +4,277 / 投信 +2,183、5d 累 +3,835 / '
            '距 MA10 +3.5% 打擊區 / user 求爆發力替代 2885 元大金 (太穩)。'
            '⚠️ 6/16 是紅 K body 不在老師「買綠」universe、'
            '但金融類 K body 慣性偏紅、漲幅 +1.0% 不算大紅、'
            '配合籌碼強進可作 special case。'
        ),
        'sizing': '$71k (~2.2% of cash)',
        'skip_if': '開盤跳空 ≥ +3% / 跌破 MA10 / 大盤崩 / 籌碼次日轉空'
    },
]

# 觀察清單 (dict 格式、兼容舊 tuple)
WATCH = [
    # ─────────────────────────────────────────────────────────────
    # 🎯 6/16 本週重點 (this-week、6/14 文章 + 直播多重背書、最高優先)
    # ⚠️ 暫時策略、下次老師直播 / line 更新就要換
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '6239', 'name': '力成',
        'ref_close': 327.0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師 6/13 OSAT + 6/14 融資股 + 6/11 直播明確 (三重 mention)',
        'sector': '封測 OSAT',
        'note': '⭐⭐⭐ 6/13 OSAT 黃金期 (AMD 加碼 + 一線滿載漲 10%)、6/14 本週融資股、6/15 -6.6% 大綠 K + 距 MA10 -1.6% = 完美「買綠」'
    },
    {
        'ticker': '3211', 'name': '順達',
        'ref_close': 428.5, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師明示 6/14 本週錢 BBU',
        'sector': 'BBU',
        'note': '⭐⭐ 6/14 本週錢 BBU 族群 (與 4931 並列、4931 標分點)、AI server 必需、6/15 平盤 距 MA10 +1.3% 安全打擊區'
    },
    {
        'ticker': '3708', 'name': '上緯投控',
        'ref_close': 119.0, 'stop': None,
        'tactic': '波段', 'priority': 2,
        'source': '老師明示 6/14 波段分點 (新補)',
        'sector': 'CB 公式觀察 / 機器人 / 航太',
        'note': '⭐⭐ 6/14 波段分點: 庫藏股 2/25 開新一期 + 三引擎轉型 (航太+機器人+循環經濟)、老師等 CB 發行確認主力意圖 (CB 公式: 訂低=無限可能)、距 MA10 -0.5% 完美'
    },
    {
        'ticker': '3264', 'name': '欣銓',
        'ref_close': 228.0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師 6/13 OSAT 雙重背書 + 6/3 圈起來中長期 + 6/14 universe',
        'sector': '封測 OSAT',
        'note': '⭐⭐⭐ 6/13 OSAT 雙重背書 (與 6257 並列首選)、6/16 11:48 回測 MA10 (+0.7%) 綠 K 回 = 完美「買綠」狀態、等 13:00 後尾盤 confirm'
    },
    {
        'ticker': '6257', 'name': '矽格',
        'ref_close': 222.0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師 6/13 OSAT 雙重背書 + 6/3 圈起來中長期 + 6/14 universe',
        'sector': '封測 OSAT',
        'note': '⭐⭐⭐ 6/13 OSAT 雙重背書 (與 3264 並列首選)、6/16 11:48 回測 MA10 (+0.8%) 綠 K 回 = 完美「買綠」狀態、等 13:00 後尾盤 confirm'
    },

    # ─────────────────────────────────────────────────────────────
    # Tier-A: 6/14 直播戰術主推 (戰略 + 戰術雙重背書)
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '2303', 'name': '聯電',
        'ref_close': 0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師明示 6/14 戰略級',
        'sector': '成熟製程',
        'note': '⭐⭐⭐ 6/14 戰略級 4 大論述 (8 吋復甦/22nm Intel/DTC 先進封裝/邊緣 AI)、CB 7/中觀察、6/15 處置出關'
    },
    {
        'ticker': '2404', 'name': '漢唐',
        'ref_close': 0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師明示 6/14 廠務主推',
        'sector': '廠務設備',
        'note': '⭐⭐⭐ 6/14 廠務 = 6/9 三選一最強 (工業電腦/光學/廠務)、6/13 已漲停、6/16-17 等回踩'
    },
    {
        'ticker': '2375', 'name': '凱美',
        'ref_close': 0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師明示 6/14 題材文',
        'sector': '被動元件',
        'note': '⭐⭐⭐ 6/14 被動 60% 主流、6/13 黑 K +7% 但融資大增 = 黑得好、低點重要'
    },
    {
        'ticker': '2472', 'name': '立隆電',
        'ref_close': 0, 'stop': None,
        'tactic': '波段', 'priority': 3,
        'source': '老師明示 6/14 題材文',
        'sector': '被動元件',
        'note': '⭐⭐⭐ 6/14 被動 60% 主流 (與 2375 並列)、文章 + 直播雙重背書'
    },
    # 6239 / 3264 / 6257 已升級為「6/16 本週重點」、移至頂部
    {
        'ticker': '8096', 'name': '擎亞',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14 題材文',
        'sector': '記憶體通路',
        'note': '⭐⭐ 6/14 題材文升級'
    },

    # ─────────────────────────────────────────────────────────────
    # Tier-B: 6/14 直播 Q&A 提及 + 個案
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '2484', 'name': '希華',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '石英',
        'note': '⭐⭐ 6/14 石英 30% 族群 (與 3042 晶技並列、最多 2 檔規則)'
    },
    {
        'ticker': '3042', 'name': '晶技',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '石英',
        'note': '⭐⭐ 6/14 石英 30% 族群 (與 2484 希華並列)、6/3 已站全均線'
    },
    {
        'ticker': '4938', 'name': '玉晶光',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14 Q8',
        'sector': '光學',
        'note': '⭐⭐ 6/14 Q8 提問: 6/13 大黑 K + 融資大增 = 黑得好、矽光子 FAU 概念'
    },
    {
        'ticker': '3008', 'name': '大立光',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '光學',
        'note': '⭐⭐ 6/14 凱基三多重新布局、6/13 黑 K 灌下但態度仍做多、處置中買'
    },
    {
        'ticker': '8086', 'name': '松川精密',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '電子零組件',
        'note': '⭐⭐ 6/14 凱基松山 (阿 Ben) 新布局、台達電繼電器供應商、均線上'
    },
    {
        'ticker': '6549', 'name': '長科',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14 Q2',
        'sector': '封測',
        'note': '⭐⭐ 6/14 Q2 提問: 有族群性、中口咬可做不重壓、封測導線架 (與界霖/順德並列)'
    },
    # 🔴 6/14 Q9 ABF 載板族群「老師收手不買」(Whisper 誤譯校正、user 6/16):
    #   - 主角: 4958 臻鼎 (個股強但老師觀望)
    #   - 族群弱: 8046 南電 / 3189 景碩 / 3037 欣興 (ABF 載板)
    #   - 第 11+12 觀念: 個股強但族群弱 → 主力效率不高 → 收手
    # → 4958/8046/3189/3037 整族不買、3293 鈊象與 Q9 無關 (Whisper 誤譯)
    {
        'ticker': '2476', 'name': '鉅祥',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14 Q12',
        'sector': '其他',
        'note': '⭐ 6/14 Q12 Johnson 提問: 不死鳥型態、命懸一線、有融資特徵、可看籌碼'
    },
    {
        'ticker': '6147', 'name': '頎邦',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14 + 6/4 圈起來',
        'sector': '封測',
        'note': '⭐⭐ 6/14 凱基松山買到快 30 億的老的代表股、6/4 圈起來 (3 次提及升 frequent)'
    },

    # ─────────────────────────────────────────────────────────────
    # 🔴 6/16 ABF 載板升戰略 watchlist (per project_zhuli_market_info_20260616)
    # 從 6/14 Q9「不買」→ 6/16「ABF 子族群戰略觀察」、4958 最強
    # ⚠️ 不是進場訊號、是觀察、等回測 + 老師明示時點
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '4958', 'name': '臻鼎-KY',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師明示 6/16 ABF 戰略 watchlist',
        'sector': 'ABF 載板',
        'note': '⭐⭐ 6/16 升戰略觀察 (ABF 內最強、外資+均線+光通訊共振)、6/16 距 MA10 +12% 過熱、等回測'
    },
    {
        'ticker': '3037', 'name': '欣興',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師明示 6/16 ABF 戰略 watchlist',
        'sector': 'ABF 載板',
        'note': '⭐⭐ 6/16 升戰略觀察 (ABF 次強)、配合 4958 動向、不獨立操作'
    },
    {
        'ticker': '8046', 'name': '南電',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 1,
        'source': '老師明示 6/16 ABF 戰略 watchlist (跟隨)',
        'sector': 'ABF 載板',
        'note': '⭐ 6/16 ABF 跟隨檔、配合 4958/3037 動向、不獨立操作'
    },
    {
        'ticker': '3189', 'name': '景碩',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 1,
        'source': '老師明示 6/16 ABF 戰略 watchlist (跟隨)',
        'sector': 'ABF 載板',
        'note': '⭐ 6/16 ABF 跟隨檔、配合 4958/3037 動向、不獨立操作'
    },

    # ─────────────────────────────────────────────────────────────
    # 🔴 6/16 外資買超族群追蹤清單 (per 法人籌碼課文章正文 block)
    # 原文: 「外資買超族群」 — 權值 / ABF / 光通 CPO / 單兵
    # ABF 4 檔已上面戰略 watchlist 段; 此段補權值區 + 光通 + 單兵
    # ─────────────────────────────────────────────────────────────
    # 權值區 (5 檔)
    {
        'ticker': '2454', 'name': '聯發科',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (權值區)',
        'sector': '權值 IC',
        'note': '⭐⭐ 6/16 外資買超權值區、跟台積電同步看'
    },
    {
        'ticker': '3711', 'name': '日月光投控',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (權值區) + OSAT 龍頭背書',
        'sector': '權值 / OSAT',
        'note': '⭐⭐ 6/16 OSAT 一線龍頭、跟 6239 力成同族'
    },
    {
        'ticker': '2308', 'name': '台達電',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (權值區、廠商 7788 松川精密)',
        'sector': '權值 / 電源',
        'note': '⭐⭐ 6/16 權值區、廠商鏈包含 7788 松川精密'
    },
    {
        'ticker': '7788', 'name': '松川精密',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 1,
        'source': '老師 6/16 提及 (2308 台達電廠商)',
        'sector': '電源廠商鏈',
        'note': '⭐ 6/16 廠商鏈跟隨檔、配合 2308 動向'
    },
    {
        'ticker': '2379', 'name': '瑞昱',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (權值區)',
        'sector': '權值 IC',
        'note': '⭐⭐ 6/16 外資買超權值區'
    },
    {
        'ticker': '3034', 'name': '聯詠',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (權值區)',
        'sector': '權值 IC',
        'note': '⭐⭐ 6/16 外資買超權值區'
    },
    # 光通 CPO (2 檔)
    {
        'ticker': '6451', 'name': '訊芯-KY',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (光通 CPO) — 線下',
        'sector': '光通訊 CPO',
        'note': '⭐⭐ 6/16 光通 CPO 新領頭族群、但 6/16 K 線在均線下、等回測'
    },
    {
        'ticker': '3450', 'name': '聯鈞',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (光通 CPO)',
        'sector': '光通訊 CPO',
        'note': '⭐⭐ 6/16 光通 CPO 新領頭'
    },
    # 單兵 (2 檔、3211 已在「6/16 本週重點」段不重複)
    {
        'ticker': '2347', 'name': '聯強',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 1,
        'source': '老師 6/16 外資買超族群 (單兵、線下太下面)',
        'sector': '通路',
        'note': '⭐ 6/16 K 線跌得太深、老師明說「線下太下面」、不主動進'
    },
    {
        'ticker': '4931', 'name': '新盛力',
        'ref_close': 0, 'stop': None,
        'tactic': '戰略觀察', 'priority': 2,
        'source': '老師 6/16 外資買超族群 (單兵、BBU 跟 3211 同族)',
        'sector': 'BBU',
        'note': '⭐⭐ 6/16 BBU 族群 (跟 3211 順達同族)、外資買超'
    },

    # ─────────────────────────────────────────────────────────────
    # 🟡 User 自選觀察 (6/17、非老師明示)
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '2891', 'name': '中信金',
        'ref_close': 70.8, 'stop': None,
        'tactic': '波段', 'priority': 2,
        'source': 'User 自選 6/17 (金融爆發力替代 2885 元大金)',
        'sector': '金融',
        'note': '⭐⭐ 6/16 外資 +3765 投信 +2183 雙軸進、距 MA10 +3.5% 打擊區、5d 外資累 +3835、user 替代 2885 求爆發力'
    },

    # ─────────────────────────────────────────────────────────────
    # Tier-C: 6/14 處置出關複合機會 (戰術級操作點)
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '6182', 'name': '合晶',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '矽晶圓',
        'note': '⭐ 6/14 6/15 出處置 + 上週直播提過矽晶圓族群'
    },
    {
        'ticker': '2492', 'name': '華新科',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': '被動元件',
        'note': '⭐ 6/14 6/17 出處置 + 上週直播提過被動族群'
    },
    {
        'ticker': '8358', 'name': '金居',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/14',
        'sector': 'CCL',
        'note': '⭐ 6/14 6/17 + 6/18 雙重出處置'
    },
    {
        'ticker': '8064', 'name': '東捷',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 + 6/14 universe',
        'sector': '玻璃設備',
        'note': '⭐ 6/14 universe 玻璃設備 (8064 / 8027 準備出關)、frequent tier'
    },

    # ─────────────────────────────────────────────────────────────
    # Tier-D: 6/13 OSAT 龍頭 + 新入榜 (戰略級觀察、不重壓)
    # ─────────────────────────────────────────────────────────────
    {
        'ticker': '3711', 'name': '日月光投控',
        'ref_close': 0, 'stop': None,
        'tactic': '波段', 'priority': 1,
        'source': '老師明示 6/13 OSAT',
        'sector': '半導體封測',
        'note': '⭐ 6/13 OSAT 龍頭、不在 picks 但需技術+籌碼雙過、波動小不重壓'
    },
    {
        'ticker': '8150', 'name': '南茂',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 1,
        'source': '老師明示 6/13 OSAT',
        'sector': '半導體封測',
        'note': '⭐ 6/13 OSAT 首次入榜、觀察 1-2 週'
    },

    # 6/3 加 — 過去 5d shakeout 補進候選 (保留 1 檔表現好的)
    {
        'ticker': '6906', 'name': '微邦',
        'ref_close': 103.5, 'stop': 95.0,
        'tactic': '短打', 'priority': 2,
        'source': 'shakeout_strong (5/26 confirmed)',
        'sector': '電子小型',
        'note': '🟢 5/26 shakeout 確認、距 MA10 +5%、6/3 紅 K +2.5% 反轉、漲幅初期'
    },
]
