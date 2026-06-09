# AI RSS Reader — 后端规格说明 (SPEC, 最终版)

> 本文件是交给 Claude Code 的实现契约。请**分阶段**实现(见 §13),每阶段完成后停下等待 review,不要提前动后续阶段的代码。技术选型、数据结构、流程已在本文档钉死,**不要自行替换或"优化"这些决策**;有疑问先问,不要猜。

---

## 0. 产品定位(读代码前先读这条,它决定一切取舍)

这是给**信息完成主义者**做的 RSS 阅读器:用户**订阅源不多、希望每天尽量全部过一遍、一篇都不漏、明确反对信息茧房**。

由此推出几条贯穿全局、不可违背的设计立场:

1. **AI 只压缩体积、分配注意力,绝不替用户做"看不看"的决定。** 不按兴趣排序、不降权、不隐藏任何文章。这与 Feedly / Particle / newscope 那类"帮你过滤、帮你少看"的产品**立场相反**——本产品刻意不做过滤。
2. **"全部已读"是核心目标,不是边角功能。** 整套设计服务于"用最低体力把所有东西都过一遍、然后清零"。
3. **不做按兴趣的过滤式学习**(它会建茧房,与定位冲突)。
4. **目标用户明确而窄**:源多、每天几百上千条、只想严筛捞几条的人**不是目标用户**,不为他们妥协设计。

---

## 1. 范围

- 本 spec 只覆盖**后端**:定期抓取、第一层 AI 标题分类 + 注意力档、懒加载全文与摘要、右栏对话,全部通过干净的 HTTP API 暴露。
- 前端是 §13 最后阶段,届时另给 spec。已确定的前端形态(供后端对齐 API):**桌面三栏**(左:源树 / 中:分类后的标题列表 / 右:摘要 + 可追问对话),**移动单栏三级下钻**,两端共享后端,**Telegram Mini App 起步**(复用 web 前端,走现有 frp 隧道暴露,不做原生 app)。
- 单用户自用形态;鉴权不在本 spec(留 `get_current_user()` 占位,默认 user=1)。

---

## 2. 技术栈(钉死)

- Python 3.11+;FastAPI + uvicorn。
- SQLite(WAL 模式);sqlite3 薄封装或 SQLModel,择简。
- 抓取:`feedparser` 解析 + `httpx` 条件请求(ETag / Last-Modified)。
- 全文提取:`trafilatura`;可配置改走 Patchright 渲染服务(应对 WAF/JS 站,如虎嗅)。
- 调度:`apscheduler`(抓取轮询 + 每日维护作业)。
- AI:**OpenAI 兼容** `/v1/chat/completions`(`openai` SDK)。端点/模型**用户自填**,且**按任务可分端点**(见 §6)。
- 配置:YAML,默认 `./config.yaml`。

---

## 3. 核心概念与流程

### 3.1 分类法:每源一张自演化的抽屉表

- **分类(classification),不是聚类(clustering)。** 每个源维护**自己的**一组"抽屉"(类别);新文章是"看标题做选择题,归入某个已有抽屉",不是每周期重新发现群组。**每源独立**:IT之家 的抽屉与虎嗅的抽屉互不相干(不同源内容形态不同——资讯流 vs 长文,天然该各走各的)。v1 **不做跨源共享抽屉**。
- **冷启动播种:** 添加源时,抓约 100 条历史标题,让 AI 看一遍,确立该源的初始抽屉表。
- **日常归类:** 之后每条新文章,用轻量 AI **只看标题**(+ feed 自带摘要)从"现有抽屉列表"里选一个塞进去。**这是封闭选择题,不是开放生成**,对本地小模型又快又稳。
- **永远存在一个特殊抽屉 `未归类`:** 选不进任何现有抽屉的,**一律进 `未归类`,当场绝不开新抽屉**(防止抽屉碎裂)。`未归类` 不可删除。
- **抽屉表只在两个时机生长:** ① 冷启动播种;② 每日维护作业(§3.4)把 `未归类` 里反复出现、攒够量的主题**提升为正式抽屉**。除此之外抽屉表只读。

### 3.2 注意力档:正交于分类,只改详略不改可见性

归类的**同一次 AI 调用**里,顺带为该标题输出一个注意力档(几乎零额外成本):
- `read`(值得细看)/ `skim`(扫一眼)/ `glance`(掠过)。
- **它只影响前端的视觉详略**(是否默认展开摘要行、亮/暗、大/小),**绝不影响是否出现**。没有 "skip" 档,什么都不跳过。

### 3.3 全文与摘要:feed 自带优先,不足才懒加载现抓

全文来源分两段式,**不再一刀切"全部点开才抓"**:

- **抓取时**先看 feed 自带的 `content`/`description` 长度:
  - **够长(≥ `min_text_chars`)→ 直接清洗后当全文存入 `fulltext`,标 `status=ok`、`fetcher=feed`。** 这类是"全文源"(实测虎嗅 rss.huxiu.com 给完整正文,阮一峰亦给全文),抓取即得全文,**零额外抓取、零点开延迟**。
  - **不够长(只给导语)→ 标 `entries.fulltext_ready=0`,抓取时不抓全文页。** 这类是"导语源"(IT之家、cnBeta),等用户点开才现抓。
- **feed 自带的全文是带噪 HTML**(虎嗅含 `<p data-check-id>`、`text-remarks`、来源 span、微信链接等),**必须先清洗**:抽纯正文、去无关属性/备注/来源、保留段落结构(trafilatura/readability 可对已有 HTML 片段做清洗,无需重新抓页面)。
- **导语源点开时才现抓**文章页(trafilatura,失败 fallback 渲染服务),抓回清洗存库。
- **摘要懒加载 + 缓存**:点开某篇才生成单篇摘要并缓存。**但全文源(抓取即有全文)的摘要可后台预生成**(见 §3.5 可选预生成)。

#### 标题党 / 纯视频的处理(硬规则)
- 全文(无论来自 feed 还是现抓)**清洗后过短/基本无文字**(纯视频/图集)→ **不调 AI 编摘要**,返回标注"此文主要为视频/图片,无正文可总结" + 原文链接。
- 正文与标题明显不符 → 生成摘要的 prompt **额外负责点破**(开头一句说明实际内容与标题的关系)。
- **严禁对空/无效内容编造摘要。**
- 抓取时粗筛:feed content 极短 + 含 `<video>`/`<iframe>` → 预打 `likely_no_text` 标,前端中栏挂图标提示。

### 3.5 (可选)read 档与全文源的摘要预生成

为改善"想细看的长文点开要等几秒"的体感,提供一个**默认关闭的开关** `summary.pregenerate`:
- 开启后,后台在抓取/分类后,对**注意力档 = `read` 且全文已就绪(`fulltext_ready=1`)**的条目预先生成摘要并缓存。
- 量很小(只覆盖最想细看、且全文现成的少数,如虎嗅 read 档、Solidot),却精准消除最在意那批的等待。
- glance/skim 仍纯懒加载,不浪费。
- 摘要/对话调用应走**无思考端点**(避免 thinking 拖慢首 token);响应**流式输出**,把等待变成"立刻见字"。

### 3.4 每日维护作业(低频,唯一让抽屉表生长的时机)

每天定时跑一次,对每个源:
- 扫 `未归类` 中**最近一段时间**的条目,识别反复出现、累计达到阈值的主题 → **提升为该源的正式抽屉**,把相关条目迁入。
- (可选)合并语义重复的碎抽屉(如"AI"与"人工智能")。低频维护,不在每次抓取时做。
- **`未归类` 不生成摘要**:它内部无共同主题,强行总结只会产出废话。前端直接**陈列其全部标题**,由用户自行扫过。

---

## 4. 数据模型 (SQLite)

```sql
CREATE TABLE feeds (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    site_url        TEXT,
    etag            TEXT,
    last_modified   TEXT,
    last_fetched_at TEXT,
    seeded          INTEGER NOT NULL DEFAULT 0,   -- 是否已完成冷启动播种
    enabled         INTEGER NOT NULL DEFAULT 1
);

-- 每源的抽屉(分类)。含一个不可删的 "未归类"
CREATE TABLE categories (
    id          INTEGER PRIMARY KEY,
    feed_id     INTEGER NOT NULL REFERENCES feeds(id),
    name        TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,        -- 1 = "未归类" 兜底抽屉
    created_at  TEXT,
    UNIQUE(feed_id, name)
);

CREATE TABLE entries (
    id            INTEGER PRIMARY KEY,
    feed_id       INTEGER NOT NULL REFERENCES feeds(id),
    category_id   INTEGER REFERENCES categories(id),  -- 归类结果
    guid          TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT,
    author        TEXT,
    published_at  TEXT,
    fetched_at    TEXT,
    raw_content   TEXT,                 -- feed 自带内容(可能截断)
    attention     TEXT,                 -- read | skim | glance
    likely_no_text INTEGER DEFAULT 0,   -- 抓取时粗筛:疑似无正文
    fulltext_ready INTEGER NOT NULL DEFAULT 0, -- 全文是否已就绪(feed 自带够长=1;导语源待现抓=0)
    is_read       INTEGER NOT NULL DEFAULT 0,
    read_at       TEXT,
    classified_at TEXT,
    UNIQUE(feed_id, guid)
);
CREATE INDEX idx_entries_cat ON entries(category_id, is_read);
CREATE INDEX idx_entries_feed_unread ON entries(feed_id, is_read);

-- 懒加载:全文缓存
CREATE TABLE fulltext (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries(id),
    content    TEXT,                    -- 提取到的正文;空/极短表示无正文
    status     TEXT,                    -- ok | no_text | fetch_failed
    fetched_at TEXT,
    fetcher    TEXT                     -- feed | trafilatura | rendering_service
);

-- 懒加载:单篇摘要缓存
CREATE TABLE summaries (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries(id),
    content    TEXT NOT NULL,
    clickbait_note TEXT,                -- 若标题与正文不符的点破说明,可空
    model      TEXT,
    created_at TEXT
);

-- 右栏对话:按 entry 维度存多轮
CREATE TABLE chat_messages (
    id         INTEGER PRIMARY KEY,
    entry_id   INTEGER NOT NULL REFERENCES entries(id),
    role       TEXT NOT NULL,           -- user | assistant
    content    TEXT NOT NULL,
    created_at TEXT
);
```

---

## 5. 摄入层 (Ingester)

留迁移缝,v1 只写原生实现:
```python
class Ingester(Protocol):
    def fetch_new(self, feed: Feed) -> list[RawEntry]: ...
    def fetch_seed(self, feed_url: str, n: int = 100) -> list[RawEntry]: ...
```
`FeedparserIngester`:httpx 条件请求(304 跳过);feedparser 解析;去重键 `guid` 取 `entry.id`,缺失退回 `entry.link`;死链/超时 try/except + 退避 + 单源故障隔离;OPML 导入。

---

## 6. AI 层配置(用户自填 OpenAI 兼容端点,按任务可分)

```yaml
ai:
  default:
    base_url: "http://localhost:9999/v1"
    api_key:  ""
    model:    "qwen-local"
  tasks:
    classify:        # 第一层:看标题选抽屉 + 标注意力档(快、便宜、封闭选择)
      batch_size: 25
      max_concurrency: 2
    seed:            # 冷启动:看 100 条标题立初始抽屉表
      model: "qwen-local"
    summary:         # 点开单篇才调;含标题党点破、空内容拒绝编造
      max_tokens: 400
    chat:            # 右栏追问;可指更大/远程模型
      base_url: "http://localhost:40000/v1"
      model:    "qwen-local-nothink"
      max_tokens: 1200

  pregenerate: false   # §3.5 是否对 read 档且全文已就绪的条目后台预生成摘要(默认关)
  stream: true         # 摘要/对话流式输出

fulltext:
  fetcher: "trafilatura"           # 导语源现抓时用;trafilatura | rendering_service
  rendering_service_url: "http://localhost:3100/render"
  min_text_chars: 200              # 全文长度阈值:feed content ≥ 此值则抓取时直接当全文存;清洗后 < 此值视为 no_text

classify:
  promote_threshold: 5             # 未归类中同主题累计达到此数,每日维护时提升为正式抽屉
```

> **不存在 `interest_profile`,不存在任何按兴趣的学习/排序配置。** 这是定位决定的(§0)。

---

## 7. 第一层:分类 + 注意力档(抓取时,每条独立,天然增量)

抓取得到新条目后,对每条调用 `classify` 任务。输入:标题(+ feed 自带摘要) + **该源当前抽屉名列表**。要求严格 JSON:
```json
{"category": "<必须是给定抽屉之一,或 '未归类'>", "attention": "read|skim|glance"}
```
规则:
- 只能从给定抽屉里选,选不出 → `未归类`。**不在此步开新抽屉。**
- 批量 20–30 条一调;JSON 校验失败/类别非法 → 重跑一次,再失败则 `category=未归类, attention=skim`,不阻塞轮询。
- **每条独立处理,与积压量无关**:没有批次、没有聚类、不回算旧条目。

冷启动 `seed` 任务单独:抓 100 条标题 → 让 AI 产出一组初始抽屉名(含合理粒度,数量适中)→ 写入 `categories`(并建好 `未归类`)→ 置 `feeds.seeded=1` → 再对这 100 条逐条归类。

---

## 8. 全文获取与摘要

**全文来源(两段式,见 §3.3):**
- 抓取时 feed 自带 content ≥ `min_text_chars` → 清洗后即存 `fulltext(status=ok, fetcher=feed)`,`entries.fulltext_ready=1`。
- 否则 `fulltext_ready=0`,点开时才现抓文章页(trafilatura,失败 fallback 渲染服务),清洗存库。

`GET /entries/{id}/summary`:
1. 有 `summaries` 缓存 → 直接返回(全文源若开了预生成,通常已命中)。
2. 无 → 确保 `fulltext`:`fulltext_ready=0` 的现抓;清洗后正文 < `min_text_chars` → `status=no_text`。
3. `no_text` → **不调 AI**,返回"此文主要为视频/图片,无正文可总结" + 链接。
4. 正文正常 → 调 `summary`(走无思考端点、流式),prompt 要求:生成摘要;正文与标题明显不符则在 `clickbait_note` 点破;**严禁对空内容编造**。缓存后返回。

## 9. 第三层:右栏对话

`POST /entries/{id}/chat {message}`:以该篇标题 + 全文(若有)+ 已有摘要为上下文,带 `chat_messages` 历史,调 `chat` 任务,追加存储并返回。前端右栏在摘要下方即对话区。

---

## 10. 每日维护作业

`apscheduler` 每日一次,对每个源:扫 `未归类` 近期条目 → 同主题累计 ≥ `promote_threshold` → 新建正式抽屉并迁移条目;(可选)合并语义重复抽屉。`未归类` 永不摘要。

---

## 11. HTTP API 契约

```
# 源与分类
GET  /feeds                         → [{id,title,unread_count}]
POST /feeds {url}                   → 新增源并触发冷启动播种(异步)
GET  /feeds/{id}/categories         → [{id,name,is_default,unread_count}]
GET  /categories/{id}/entries?unread=1&limit=&offset=
                                    → [{id,title,url,author,published_at,attention,is_read,likely_no_text}]

# 三层下钻
GET  /entries/{id}/summary          → {summary,clickbait_note,status} (懒加载+缓存)
POST /entries/{id}/chat {message}   → {reply, history}
GET  /entries/{id}/fulltext         → {content,status}  (供前端"展开全文")

# 已读 / 清场
POST /entries/{id}/read             → {ok}
POST /entries/read {ids:[...]}      → {ok,count}
POST /categories/{id}/read          → {ok,count}   # 整抽屉已读
POST /feeds/{id}/read               → {ok,count}   # 整源已读(湮灭)

# 管理
POST /import/opml (multipart)       → {ok,added}
POST /refresh                       → {ok,fetched,new_entries}
GET  /healthz                       → {ok}
```

---

## 12. 后台作业

- 抓取轮询:默认 10–15 分钟。`enabled=1` 源 → 条件请求 → 解析 → 去重写 entries → 对新 entries 跑 §7 分类。并发受 `classify.max_concurrency` 限;单源故障隔离。
- 冷启动:新增源后异步跑 `seed`(§7 末)。
- 每日维护:§10。

---

## 13. 分阶段里程碑(逐阶段实现,阶段间停下等 review)

**阶段一 — 核心抓取,无 AI。** schema + FeedparserIngester + OPML/新增源 + 条件请求轮询 + 去重 + 已读(单条/整抽屉/整源)+ `/feeds` `/categories` `/entries` `/refresh`。新增源时先把所有条目塞进 `未归类`(无 AI)。验收:文章流入、去重正确、三级已读可用。

**阶段二 — 第一层 AI。** `classify` + `seed` + 每源抽屉表 + 注意力档 + `未归类` 兜底。验收:新源播种出合理抽屉;新文章稳定归入抽屉或未归类;批失败优雅降级;不回算旧条目。

**阶段三 — 全文 + 懒加载摘要。** 全文两段式(feed 自带够长则抓取时即存并清洗;导语源点开才现抓,trafilatura 失败转渲染服务)+ `/summary` `/fulltext` + 清洗 + 缓存 + 标题党点破 + 纯视频/空内容拒绝编造 +(可选)read 档预生成 + 流式。验收:全文源点开秒出(已就绪)、导语源现抓可用;HTML 清洗干净;无正文不胡编;命中缓存不重复。

**阶段四 — 右栏对话 + 每日维护。** `/chat` + `chat_messages` + 每日维护(未归类提升抽屉)。验收:对话有上下文;未归类中攒够的主题能转正。

**阶段五 — 前端。** 桌面三栏起步,移动单栏 + Telegram Mini App(届时另给 spec)。

---

## 14. 给实现者的约束(请遵守)

- 严格按阶段推进,阶段末停下等 review,不写后续阶段代码。
- **绝不实现任何按兴趣的过滤、排序降权、隐藏文章的逻辑**(违反 §0 定位)。注意力档只改前端详略。
- **分类是"封闭选择题",不是聚类**:每条独立归入已有抽屉或未归类,不分批、不回算、当场不开新抽屉。
- 全文**优先用 feed 自带**(够长则抓取时清洗即存),**不足才点开现抓**(trafilatura→渲染服务);**feed 自带 HTML 必须先清洗**;摘要懒加载+缓存,全文源可选后台预生成。
- **严禁对空/无效正文编造摘要**;纯视频/图集如实标注;标题党在摘要中点破。
- AI 输出(分类 JSON 等)必须校验后入库,失败有降级路径,不得阻断轮询。
- 配置不得硬编码:AI 端点/模型、间隔、阈值全走 config / DB。
- 单源故障隔离,不拖垮整轮抓取。
- 不引入未列出的重型依赖;有更好想法先讨论。
