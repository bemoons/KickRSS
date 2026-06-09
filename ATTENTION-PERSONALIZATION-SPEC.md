# 开发文档：基于用户行为的注意力分级个性化与阅读画像

## 背景

KickRSS 的 classifier.py 目前在每次 ingestion 后通过 LLM 对新文章标注注意力等级（`read` / `skim` / `glance`），但该判定仅依赖文章标题和 category，不考虑用户的实际阅读偏好。用户已可手动修改注意力标签，但这些修改不会反馈到后续的自动分类中。

本需求包含两个目标：
1. **注意力分级个性化**：采集用户行为数据，聚合为偏好画像，注入分类器 prompt，使注意力等级判定逐步贴合用户习惯。
2. **阅读画像可视化**：向用户呈现兴趣主题标签云、话题趋势热力图、深度阅读文章记录，帮助用户觉察自身信息消费模式，打破信息茧房。

**核心约束**：严格遵守现有设计原则——AI 不决定文章是否显示，只调整注意力等级的初始分配。所有文章始终完整可见。画像仅用于调整 attention 标签和用户自我认知，永远不用于隐藏、过滤或降序排列任何文章。

**LLM 使用说明**：本功能的行为采集和评分计算完全在本地完成，不消耗 LLM token。但每日一次的兴趣主题提炼需要调用 LLM（约消耗 2000-3000 token/次）。因此本功能需设为**用户主动开启**，并在开启时明确告知 token 消耗。

---

## 现有架构参考

请先阅读项目根目录的 `DESIGN.md`，了解完整的系统设计。以下是与本需求直接相关的部分：

- **数据库**：SQLite WAL 模式，通过 `db.py` 初始化和迁移
- **分类器**：`classifier.py`，LLM 批量分类新文章，输出 category + attention
- **维护任务**：`maintenance.py`，由 `scheduler.py` 每日调度，执行清理和 category promotion
- **entries 表**：已有 `attention` 字段（`read`/`skim`/`glance`）和 `is_read`/`read_at` 字段
- **前端**：`static/app.js`，用户已可手动点击修改文章的 attention 标签

---

## 一、数据库变更（db.py）

### 1.1 新建 `engagement` 表

```sql
CREATE TABLE IF NOT EXISTS engagement (
    entry_id           INTEGER PRIMARY KEY REFERENCES entries(id),
    opened             INTEGER NOT NULL DEFAULT 0,
    active_dwell_ms    INTEGER NOT NULL DEFAULT 0,
    scrolled_pct       REAL NOT NULL DEFAULT 0.0,
    scrolled_to_bottom INTEGER NOT NULL DEFAULT 0,
    opened_original    INTEGER NOT NULL DEFAULT 0,
    favorited          INTEGER NOT NULL DEFAULT 0,
    manual_bump        TEXT,
    recorded_at        TEXT NOT NULL
);
```

字段说明：
- `opened`：用户是否点开了文章详情（0/1）
- `active_dwell_ms`：**有效停留时间**（毫秒）。仅计算用户实际在页面上活跃的时间，不包括切走、锁屏、发呆等无交互时段。具体采集逻辑见第二节
- `scrolled_pct`：全文滚动百分比（0.0-1.0），取历次打开的最大值
- `scrolled_to_bottom`：是否滚动到全文底部（0/1），即 `scrolled_pct >= 0.9`。单独存储是因为"看完全文"是一个比连续百分比更清晰的强信号
- `opened_original`：用户是否点击了"查看原文"链接跳转到源站（0/1）
- `favorited`：用户是否收藏了该文章（0/1）
- `manual_bump`：用户手动修改后的 attention 值（`read`/`skim`/`glance`），未修改则为 NULL
- `recorded_at`：记录时间，UTC ISO 格式

**信号选择说明**：不采集"是否请求摘要"和"聊天轮数"，因为这两个行为受用户配置影响（自动摘要开关），在不同配置下含义不同，作为信号不可靠。以上六个信号均为配置无关的用户主动行为。

### 1.2 entries 表新增收藏字段

```sql
ALTER TABLE entries ADD COLUMN is_favorited INTEGER NOT NULL DEFAULT 0;
ALTER TABLE entries ADD COLUMN favorited_at TEXT;
```

现有 entries 表没有收藏功能。新增两个字段。在 `db.py` 初始化中用 `ALTER TABLE ... ADD COLUMN` 包裹在 try-except 中（字段已存在时忽略错误），兼容已有数据库。

### 1.3 新建 `user_interests` 表

存储全局兴趣画像，跨所有订阅源通用。不按 feed 或 category 分组，解决新订阅源冷启动和跨源同主题打通的问题。

```sql
CREATE TABLE IF NOT EXISTS user_interests (
    id              INTEGER PRIMARY KEY,
    snapshot_date   TEXT NOT NULL UNIQUE,
    total_articles  INTEGER NOT NULL DEFAULT 0,
    high_engagement INTEGER NOT NULL DEFAULT 0,
    low_engagement  INTEGER NOT NULL DEFAULT 0,
    topics_json     TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    generated_at    TEXT NOT NULL
);
```

字段说明：
- `snapshot_date`：画像生成日期（`YYYY-MM-DD`），UNIQUE 约束确保每天最多一条
- `total_articles`：近 30 天有 engagement 记录的文章总数（供前端展示）
- `high_engagement`：高参与度文章数（供前端展示）
- `low_engagement`：低参与度文章数（供前端展示）
- `topics_json`：结构化的兴趣主题数据，JSON 格式，供前端画像页面渲染（详见第四节和第六节）
- `prompt_text`：自然语言偏好描述，直接注入分类器 prompt（详见第五节）
- `generated_at`：UTC ISO 时间戳

### 1.4 性能索引

```sql
CREATE INDEX IF NOT EXISTS idx_entries_fetched_at ON entries(fetched_at);
```

---

## 二、前端行为采集（static/app.js）

### 2.0 功能开关（Settings 页面）

在现有 Settings 模态框的 System Settings 区域新增一个开关：

- **标签**："阅读画像与智能分级"
- **说明文字**（开关下方，灰色小字）："开启后，系统将根据你的阅读习惯自动优化文章注意力分级。每日凌晨会消耗一次 AI 额度（约 2000-3000 token）用于分析阅读偏好。行为数据仅存储在本地。"
- **默认状态**：关闭
- **存储**：写入现有的系统设置机制（config 或 settings API），键名 `interest_profile_enabled`（布尔值）

开关关闭时：
- 前端**仍然采集** engagement 数据（采集本身不消耗 token，且数据积累有利于用户将来开启时跳过冷启动期）
- 后端每日维护任务**跳过** LLM 调用，不生成画像
- 分类器不注入偏好 prompt，回退到纯标题判断
- 画像页面入口隐藏，或点击后显示"功能未开启"引导

开关开启时：
- 正常执行全部流程

### 2.1 采集时机与数据

在用户**离开文章详情页**时（切换到其他文章、返回列表、关闭页面），收集一次 engagement 数据并发送到后端。

采集逻辑：

1. 用户进入详情页时，初始化采集状态：
   ```javascript
   let activeDwellMs = 0;      // 有效停留累计
   let lastActiveTime = Date.now();
   let isActive = true;
   let maxScrollPct = 0;
   let openedOriginal = false;
   const IDLE_TIMEOUT = 30000; // 30秒无交互视为离开
   let idleTimer = null;
   ```

2. **有效停留时间采集**（核心逻辑）：

   监听用户活跃信号（scroll、touchstart、mousemove、keydown），每次活跃时：
   - 如果当前 `isActive === true`，累加 `activeDwellMs += Date.now() - lastActiveTime`
   - 重置 `lastActiveTime = Date.now()`
   - 重置 idle 定时器

   idle 定时器到期时（30 秒无任何交互）：
   - 将最后一段活跃时间累加到 `activeDwellMs`
   - 设置 `isActive = false`，停止计时
   - 用户再次交互时恢复 `isActive = true`，重新开始计时

   页面不可见时（`visibilitychange` 事件，`document.hidden === true`）：
   - 立即停止计时，累加当前活跃段
   - 页面恢复可见时重新开始计时

   **注意**：活跃信号的监听应做节流（throttle 1-2 秒），避免性能开销。

3. 监听详情区的 scroll 事件，持续更新 `maxScrollPct = Math.max(maxScrollPct, scrollTop / (scrollHeight - clientHeight))`
4. 监听"查看原文"链接的点击事件，标记 `openedOriginal = true`
5. 离开详情页时发送请求

### 2.2 收藏功能（新增）

在详情页标题区域添加一个收藏按钮（星形或书签图标），视觉风格与现有的 attention 标签切换一致。

- 点击收藏时立即调用 `POST /entries/{entry_id}/favorite`（见后端 API 章节）
- 按钮状态跟随 `entries.is_favorited` 值
- 在条目列表的 entry-item 上，已收藏的文章显示一个小标记（如角标星号），但不影响排序或可见性
- 在订阅源树中可添加一个"收藏"虚拟分组（可选，不属于本期必须范围）

### 2.3 上报 API

离开文章时调用：

```
POST /entries/{entry_id}/engagement
Content-Type: application/json

{
  "active_dwell_ms": 45000,
  "scrolled_pct": 0.82,
  "opened_original": true
}
```

注意事项：
- `active_dwell_ms` 低于 2000ms 时不上报（误触/快速跳过，不构成有效行为）
- 页面 `beforeunload` 或 `visibilitychange(hidden)` 时也应尝试上报（用 `navigator.sendBeacon` 兜底），上报前先累加最后一段活跃时间
- 同一篇文章多次打开时，后端对 engagement 做 **累加更新**（active_dwell_ms 累加，scrolled_pct 取最大值，scrolled_to_bottom 取最大值，opened_original 取最大值，opened 保持 1）

### 2.4 手动修改同步

用户手动修改 attention 标签时，前端已有对应的 API 调用。在同一调用中（或追加一个字段），将 `manual_bump` 值写入 engagement 表。如果前端已有独立的 attention 修改 API，则后端在该 API handler 中同步写入 `engagement.manual_bump` 即可。

---

## 三、后端 API（main.py）

### 3.1 新增 engagement 上报接口

```python
@app.post("/entries/{entry_id}/engagement")
async def record_engagement(entry_id: int, data: dict):
    """
    接收前端行为数据，写入或更新 engagement 表。
    - opened 固定设为 1
    - active_dwell_ms 累加到现有值
    - scrolled_pct 取 max(现有值, 新值)
    - scrolled_to_bottom 设为 1 如果 scrolled_pct >= 0.9
    - opened_original 取 max(现有值, 新值)（一旦点过就不回退）
    - favorited 从 entries.is_favorited 实时读取，不由前端传入
    - recorded_at 更新为当前 UTC 时间
    """
```

`favorited` 的维护：在 engagement 记录写入/更新时，直接读取 `entries.is_favorited` 回填。

### 3.2 新增收藏接口

```python
@app.post("/entries/{entry_id}/favorite")
async def toggle_favorite(entry_id: int):
    """
    切换文章收藏状态。
    - 读取当前 is_favorited 值，取反写回
    - 收藏时写入 favorited_at = 当前 UTC 时间；取消收藏时清空 favorited_at
    - 同步更新 engagement.favorited（如果 engagement 记录存在）
    - 返回 {"is_favorited": 0 或 1}
    """
```

### 3.3 修改现有 attention 修改接口

在用户手动修改 attention 的现有 API handler 中，追加一行将新 attention 值写入 `engagement.manual_bump`。如果该 entry 尚无 engagement 记录，则 INSERT 一条（`opened=0, active_dwell_ms=0` 等默认值，仅设 `manual_bump`）。

### 3.4 新增画像数据 API

```python
@app.get("/profile/interests")
async def get_interest_profile():
    """
    返回最新的兴趣画像数据，供前端渲染。
    返回格式：
    {
      "snapshot_date": "2026-06-09",
      "total_articles": 342,
      "high_engagement": 87,
      "low_engagement": 64,
      "topics": {
        "high_interest": [
          {"topic": "芯片制裁与半导体", "description": "...", "strength": "high"},
          ...
        ],
        "low_interest": [
          {"topic": "融资动态", "description": "..."},
          ...
        ],
        "concentration_note": "..." 或 null
      },
      "attention_guide": "..."
    }
    如果画像不存在返回：
    {"status": "cold_start", "message": "阅读数据积累中，需至少15篇文章的阅读行为"}
    如果功能未开启返回：
    {"status": "disabled"}
    """
```

### 3.5 新增画像详情 API（标签点击展开用）

```python
@app.get("/profile/topic-detail")
async def get_topic_detail(topic: str):
    """
    返回指定话题的详细数据，供前端标签点击展开面板使用。
    
    实现方式：从最新 user_interests.topics_json 中找到该 topic 对应的文章标题列表，
    然后从 engagement 表关联查询这些文章的具体行为数据。
    
    返回格式：
    {
      "topic": "芯片制裁与半导体",
      "stats": {
        "article_count": 23,
        "favorite_count": 5,
        "original_count": 8
      },
      "weekly_trend": [3, 4, 3, 5, 6, 5, 7, 8, 8, 9, 9, 9],
      "articles": [
        {
          "title": "美国再收紧对华芯片出口管制细则公布",
          "source": "IT之家",
          "entry_id": 12345,
          "badges": ["favorited", "opened_original"]
        },
        ...
      ]
    }
    """
```

**实现说明**：此接口需要在 `topics_json` 中为每个 topic 保存关联的 `entry_id` 列表（见第四节 LLM 调用后的后处理逻辑），用于反查 engagement 详情。`weekly_trend` 是将该 topic 关联的文章按发布周分组计数，最近 12 周，每周一个数字。

---

## 四、兴趣画像聚合（maintenance.py）

### 4.1 新增每日任务：`build_user_interest_profile()`

在现有的 daily maintenance 调度中追加此任务（在 category promotion 之后执行）。

#### 第一步：检查前置条件

```python
def build_user_interest_profile(db):
    """
    聚合近 30 天所有订阅源的 engagement 数据，
    通过 LLM 提炼全局兴趣画像，写入 user_interests 表。
    """

    # 检查功能开关，未开启则跳过
    if not get_setting(db, 'interest_profile_enabled', default=False):
        return
```

#### 第二步：查询 engagement 数据

```python
    rows = db.execute("""
        SELECT
            e.id AS entry_id,
            e.title,
            e.attention AS ai_attention,
            e.published_at,
            f.title AS feed_name,
            g.active_dwell_ms,
            g.scrolled_pct,
            g.scrolled_to_bottom,
            g.opened_original,
            g.favorited,
            g.manual_bump
        FROM entries e
        JOIN engagement g ON g.entry_id = e.id
        JOIN feeds f ON f.id = e.feed_id
        WHERE e.fetched_at > datetime('now', '-30 days')
          AND g.opened = 1
    """).fetchall()

    # 冷启动：数据不足时跳过
    if len(rows) < 15:
        return
```

#### 第三步：按参与度评分分组

```python
    def engagement_score(row):
        """
        加权评分，越高越说明用户关注。
        只使用不受配置影响的可靠信号。
        """
        score = 0
        # 显式主动行为（强信号）
        if row['manual_bump'] == 'read':   score += 5   # 最强正信号
        if row['manual_bump'] == 'glance': score -= 3   # 最强负信号
        if row['favorited']:               score += 4
        if row['opened_original']:         score += 3
        if row['scrolled_to_bottom']:      score += 2   # 看完全文
        # 隐式行为（弱信号，设上限避免长文天然占优）
        score += min(row['active_dwell_ms'] / 60000, 2)  # 每分钟 1 分，上限 2
        score += row['scrolled_pct'] * 1.5               # 滚动 100% 得 1.5 分
        return score

    scored = [(engagement_score(r), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)

    high = [r for s, r in scored if s >= 4]
    low  = [r for s, r in scored if s <= 0]
```

#### 第四步：调用 LLM 提炼兴趣主题

将高参与度和低参与度的文章标题分别列出，调用一次 LLM，输出结构化的兴趣画像。

```python
    # 取标题列表（各最多 80 条，避免 prompt 过长）
    high_titles = [f"[{r['feed_name']}] {r['title']}" for r in high[:80]]
    low_titles  = [f"[{r['feed_name']}] {r['title']}" for r in low[:80]]

    prompt = f"""你是一个用户阅读行为分析助手。以下是某用户近30天的RSS阅读记录。

## 用户高度关注的文章（长时间阅读、滚动到底、收藏、查看原文、手动提升注意力）
{chr(10).join('- ' + t for t in high_titles) if high_titles else '（数据不足）'}

## 用户较少关注的文章（快速跳过、很少互动）
{chr(10).join('- ' + t for t in low_titles) if low_titles else '（数据不足）'}

请分析并输出以下 JSON（不要输出其他内容）：
{{
  "high_interest": [
    {{"topic": "主题名称（简短，4-10字）", "description": "一句话描述用户在这个主题上的关注点", "strength": "high 或 medium"}},
    ...
  ],
  "low_interest": [
    {{"topic": "主题名称", "description": "一句话描述"}},
    ...
  ],
  "attention_guide": "一段自然语言，50-120字，概括用户的整体阅读倾向，供分类器参考。格式示例：'用户高度关注XX和XX方向，尤其是涉及XX的内容应标为read；对XX和XX类内容兴趣较低，可标为glance。'",
  "concentration_note": "如果 high_interest 中超过半数主题属于同一领域，输出一句温和的提醒（20-40字），否则设为 null"
}}

要求：
- high_interest 提取 3-8 个主题，按关注强度从高到低排列
- low_interest 提取 2-5 个主题
- 主题应跨订阅源归纳，不要按订阅源罗列
- 如果某类文章高参与和低参与中都有，说明用户对该主题的子方向有选择性，请在 description 中体现
- attention_guide 必须具体到可操作，不要说"用户关注科技"这种空话
"""
```

#### 第五步：后处理——为每个 topic 关联 entry_id

LLM 返回的是抽象主题，需要将具体文章关联回去，供前端详情面板使用。

```python
    result = call_llm(prompt)  # 复用现有的 ai.py 中的 LLM 调用函数
    parsed = json.loads(result)

    # 为每个 topic 关联 entry_id：
    # 用简单的关键词匹配，将 high/low 列表中的文章标题与 LLM 输出的 topic 名做模糊匹配
    # 为 topics_json 中的每个 topic 添加 entry_ids 列表
    all_topics = parsed.get('high_interest', []) + parsed.get('low_interest', [])
    for topic_item in all_topics:
        topic_name = topic_item['topic']
        matched_ids = []
        for r in rows:
            # 简单匹配：topic 名中的关键字出现在文章标题中
            # 例如 topic="芯片制裁与半导体"，拆分为 ["芯片", "制裁", "半导体"]，
            # 标题中包含任意一个即算匹配
            keywords = [w for w in topic_name if len(w) >= 2]  # 按实际实现选择分词策略
            if any(kw in r['title'] for kw in keywords):
                matched_ids.append(r['entry_id'])
        topic_item['entry_ids'] = matched_ids[:20]  # 最多保留 20 条
```

**注意**：关键词匹配不需要精确，漏匹配可以接受（最多影响详情面板的展示），不需要引入分词库。如果项目中已有 jieba 可用于更精确的分词，没有则用简单的子串匹配。

#### 第六步：写入数据库

```python
    db.execute("""
        INSERT INTO user_interests (snapshot_date, total_articles, high_engagement,
            low_engagement, topics_json, prompt_text, generated_at)
        VALUES (date('now'), ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(snapshot_date) DO UPDATE SET
            total_articles = excluded.total_articles,
            high_engagement = excluded.high_engagement,
            low_engagement = excluded.low_engagement,
            topics_json = excluded.topics_json,
            prompt_text = excluded.prompt_text,
            generated_at = excluded.generated_at
    """, (len(rows), len(high), len(low),
          json.dumps(parsed, ensure_ascii=False),
          parsed['attention_guide']))
```

### 4.2 冷启动处理

如果近 30 天 engagement 记录不足 15 篇文章（`opened = 1`），跳过 LLM 调用，不生成画像。分类器回退到纯标题判断的现有行为。

### 4.3 历史画像保留

`user_interests` 保留最近 90 天的每日快照。超过 90 天的在 maintenance 清理任务中删除：

```sql
DELETE FROM user_interests WHERE snapshot_date < date('now', '-90 days');
```

保留历史数据是为了支撑前端热力图的周维度趋势展示。

---

## 五、分类器 prompt 注入（classifier.py）

### 5.1 新增函数：`get_interest_prompt(db)`

```python
def get_interest_prompt(db) -> str:
    """
    读取最新一条 user_interests.prompt_text，返回给分类器使用。
    如果没有画像数据，返回空字符串（不注入）。
    """
    row = db.execute("""
        SELECT prompt_text FROM user_interests
        ORDER BY snapshot_date DESC LIMIT 1
    """).fetchone()
    if row and row['prompt_text']:
        return f"\n\n## 用户阅读偏好（基于近30天行为自动生成）\n{row['prompt_text']}"
    return ""
```

### 5.2 注入位置

在 `classifier.py` 中现有的分类 prompt 构造处，追加偏好描述。伪代码：

```python
# 现有逻辑：构造分类 prompt
system_prompt = "你是一个 RSS 文章分类助手..."
user_prompt = f"以下是需要分类的文章标题：\n{titles_block}"

# === 新增：注入全局兴趣画像（仅在功能开启时）===
if get_setting(db, 'interest_profile_enabled', default=False):
    interest_text = get_interest_prompt(db)
    if interest_text:
        system_prompt += interest_text
```

这个 prompt 是全局的，不区分 feed_id。同一份兴趣画像应用于所有订阅源的分类，新增订阅源立即生效。

---

## 六、用户画像展示页面（前端新增）

### 6.1 入口

在 Header 区域新增一个"阅读画像"入口按钮（图标建议用雷达图或指纹图标），点击后打开画像页面。画像功能未开启时隐藏此入口，或点击后显示引导开启的提示。

### 6.2 页面整体布局（从上到下）

```
+----------------------------------------------------------+
|  [30天阅读: 342篇]  [深度阅读: 87篇]  [快速略过: 164篇]  |  ← 统计卡片
+----------------------------------------------------------+
|                                                          |
|    芯片制裁   开源大模型   AI应用落地   隐私安全          |
|      Linux   自托管  编程工具  网络安全  云计算           |  ← 标签云
|        量子计算  社交媒体  融资动态  人事变动             |    （可点击）
|                                                          |
+----------------------------------------------------------+
|  ┌─ 芯片制裁与半导体 ─────────────────────── ✕ ─┐       |
|  │ 深度阅读 23篇  收藏 5篇  查看原文 8次         │       |
|  │ ▁▂▂▃▄▃▅▆▆▇▇▇  (每周参与度柱状图)            │       |  ← 详情面板
|  │ ● 美国再收紧芯片出口管制...    IT之家 ⭐ 🔗  │       |    （标签点击
|  │ ● ASML最新财报：中国区...     cnBeta    🔗  │       |     后展开）
|  │ ● 国产EDA工具链现状与突围...  虎嗅   ⭐ 🔗  │       |
|  └──────────────────────────────────────────────┘       |
+----------------------------------------------------------+
|                话题关注趋势（近12周）                      |
|          W1 W2 W3 W4 W5 W6 W7 W8 W9 W10 W11 W12        |
| 芯片制裁  ░░░▒▒▒▓▓▓███                                  |
| 开源大模型 ░░▒▒▒▒▓▓███▓                                  |  ← 热力网格
| AI应用    ▒▒▒▓▒▒░▒▓▒▓▓                                  |
| 隐私安全  ▓▓▓▒▒░░░░░░░                                  |
| Linux    ▒▒░▒░░░░░░░░                                    |
| 融资/人事 ░░ ░░ ░  ░░                                    |
+----------------------------------------------------------+
| 💡 你近三周的阅读集中在半导体和大模型方向...              |  ← 洞察提示
+----------------------------------------------------------+
```

### 6.3 顶部统计卡片

一行三个数字卡片，简洁展示近 30 天阅读量：
- 打开过的文章总数（`total_articles`）
- 深度阅读数（`high_engagement`）
- 快速略过数（`low_engagement`）

数据来自 `GET /profile/interests` 返回值。

### 6.4 兴趣标签云

用标签云展示所有 LLM 提取的兴趣主题（`high_interest` + `low_interest`），标签的视觉编码：
- **字号**：按关注度权重缩放（高关注的大、低关注的小），范围 12px-24px
- **颜色**：高关注主题（`strength: high`）用 accent 色（indigo），中等关注用 teal，低关注用灰色
- **字重**：高关注 500，其余 400
- 标签随机排列（每次打开顺序不同），避免用户形成位置依赖

**标签可点击**，点击后展开详情面板（见 6.5）。当前选中的标签用 outline 高亮。

### 6.5 标签详情面板（点击展开）

点击任意标签后，在标签云下方展开一个详情面板，数据来自 `GET /profile/topic-detail?topic=xxx`。面板内容从上到下：

**统计行**：该话题下深度阅读篇数、收藏篇数、查看原文次数——三个数字水平排列。

**每周参与度柱状图**：12 根垂直小柱子，每根代表一周，高度和透明度编码该周在该话题上的文章参与量。用户可直观看到话题关注度的上升或下降趋势。

**深度阅读文章列表**：列出该话题下用户深度阅读过的文章（按参与度排序），每条显示：
- 文章标题
- 来源订阅源名称（灰色小字）
- 行为标记（收藏用星号 badge，查看原文用链接 badge）

面板右上角有关闭按钮。同时只展开一个面板（点击另一个标签时替换内容）。展开/收起使用 CSS 过渡动画。

如果该话题没有深度阅读记录（如低兴趣话题），显示"该话题的深度阅读文章较少，暂无记录"。

### 6.6 话题关注趋势热力网格

类似 GitHub 贡献图的 **话题×周** 网格：
- **纵轴**：LLM 提取的主要话题（取 `high_interest` 全部 + `low_interest` 前 2 个，共约 6-8 行）
- **横轴**：最近 12 周（W1-W12），W12 为本周
- **色块**：indigo 色系，透明度编码参与强度（无参与 → 全透明，最高参与 → 深色）
- **悬停提示**：显示"话题 · 第N周 · X篇"

热力图的数据来源：从 `user_interests` 历史快照中按周聚合，或由 `GET /profile/interests` 接口直接返回预计算的周数据（在 `topics_json` 中附带 `weekly_trend` 数组）。

右下角提供图例：从浅到深 5 个色块，标注"少"到"多"。

### 6.7 底部洞察提示

如果 LLM 返回了 `concentration_note`（兴趣过度集中提示），在页面底部显示一个带图标的提示框：

> "你近三周的阅读集中在半导体和大模型方向，隐私安全和开发工具类内容的关注度在下降。试试翻翻那些被标为 glance 的文章？"

如果 `concentration_note` 为 null，改为显示一段通用的引导文字：

> "这是基于你近 30 天的阅读行为自动生成的兴趣画像。如果你发现某些你认为重要的主题出现在小字标签中，也许值得在下次刷新时多留意它们。"

视觉风格：左侧 3px indigo 竖线，浅色背景，13px 灰色文字。温和促进反思，不说教。

---

## 七、整体数据流

```
用户阅读行为（有效停留、滚动到底、查看原文、收藏、手动调整）
    ↓ (前端采集 → POST /engagement, POST /favorite)
engagement 表 + entries.is_favorited
    ↓ (maintenance.py 每日聚合 + LLM 一次调用)
user_interests 表
    ├──→ topics_json → 前端画像页面
    │       ├── 标签云（兴趣全貌，可点击）
    │       ├── 详情面板（单话题深入：统计 + 趋势 + 文章列表）
    │       ├── 热力网格（话题×周 趋势变化）
    │       └── 洞察提示（信息茧房觉察）
    └──→ prompt_text → classifier.py 分类 prompt
                            ↓
                    entries.attention 更准确的初始判定
```

---

## 八、实现注意事项

1. **不要引入新的 Python 依赖**。聚合用纯 SQL + Python 标准库完成。兴趣主题提取由 LLM 完成，不需要 jieba 或其他 NLP 库。

2. **engagement 上报不应阻塞前端**。POST 请求使用 fire-and-forget 模式（`fetch` 不 await 或用 `sendBeacon`），上报失败静默忽略。

3. **数据库迁移**。在 `db.py` 的初始化逻辑中增加 `CREATE TABLE IF NOT EXISTS` 语句，确保现有数据库升级时自动建表，无需手动迁移。`entries` 表的新字段用 `ALTER TABLE ADD COLUMN` 包裹在 try-except 中兼容已有数据库。

4. **冷启动**。engagement 记录不足 15 篇时，不生成画像，分类器回退到纯标题判断的现有行为。前端画像页面显示"数据积累中"状态。

5. **功能默认关闭**。`interest_profile_enabled` 默认为 `false`。前端 engagement 数据采集不受此开关影响（采集本身零 token 消耗），确保用户开启功能时已有数据积累、可跳过冷启动。只有 LLM 调用和 prompt 注入受开关控制。

6. **LLM 调用开销**。每日聚合仅调用一次 LLM（提炼兴趣主题），不是逐 feed 或逐 category 调用。prompt 输入约为 160 条标题 + 指令，输出约 300-500 字 JSON，总计约 2000-3000 token。此开销必须在开关说明文字中向用户明确告知。

7. **隐私**。所有数据均存储在本地 SQLite，偏好画像传给本地 LLM，不离开用户的机器。

8. **画像不影响文章可见性**。画像仅用于调整 attention 标签和用户自我认知，永远不用于隐藏、过滤或降序排列任何文章。这一原则需在前端和后端都严格遵守。
