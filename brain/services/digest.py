"""每日摘要服务。

基于 LangChain PromptTemplate + LLM，将昨日/本周的笔记整理为结构化摘要。
"""

from datetime import date, timedelta

from langchain_core.prompts import PromptTemplate
from loguru import logger

from brain.llm import get_chat_model
from brain.storage.metadata import MetadataStore

DAILY_DIGEST_PROMPT = PromptTemplate.from_template("""你是一个个人知识管家。基于用户昨日摄入的笔记，生成一份知识简报。

## 昨日笔记列表
{notes_section}

## AI 发现的标签
{tags_section}

## AI 发现的关联
{connections_section}

请生成以下格式的知识简报（Markdown）：

### 📅 {date_str} 知识简报

**摄入概况**: （一句话总结昨日摄入的内容量和主题方向）

**核心主题**:
- （列出 1-3 个最突出的主题，每个一句说明）

**值得关注的关联**:
- （如果有 AI 发现的关联，提取最有趣的 1-2 条）

**回顾建议**: 基于昨日内容，给出一条可执行的回顾/深入学习建议。

保持简洁，总字数控制在 300 字以内。""")


WEEKLY_TREND_PROMPT = PromptTemplate.from_template("""你是一个个人知识管家。基于用户本周的笔记摄入，分析知识趋势。

## 本周笔记列表
{notes_section}

## 标签分布统计
{tags_stats}

## 关联统计
总关联数: {connection_count}

请分析：

### 📊 {start_date} ~ {end_date} 知识趋势

**学习主题分布**: （本周你关注了哪些主题领域？）

**趋势洞察**: （你的关注点有什么变化趋势？有没有新出现的兴趣方向？）

**知识盲区**: （哪些相关领域你还没有涉及，值得关注？）

**下周建议**: 基于本周的学习轨迹，给出一条下周的学习方向建议。

总字数控制在 400 字以内。""")


class DigestService:
    """摘要服务 — 生成每日简报和每周趋势分析。"""

    def __init__(self, metadata_store: MetadataStore):
        self._store = metadata_store

    def daily_sync(self, target_date: date | None = None) -> str:
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        return self._generate(target_date=target_date, days_range=1,
                              prompt_template=DAILY_DIGEST_PROMPT,
                              title_date=target_date.isoformat())

    def weekly_sync(self) -> str:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return self._generate(target_date=monday, days_range=7,
                              prompt_template=WEEKLY_TREND_PROMPT,
                              title_date=f"{monday.isoformat()} ~ {today.isoformat()}")

    async def daily(self, target_date: date | None = None) -> str:
        """生成指定日期的知识简报。默认昨天。

        Returns:
            Markdown 格式的摘要字符串
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        logger.info(f"生成每日摘要: {target_date}")
        return self._generate(
            target_date=target_date,
            days_range=1,
            prompt_template=DAILY_DIGEST_PROMPT,
            title_date=target_date.isoformat(),
        )

    async def weekly(self) -> str:
        """生成本周知识趋势分析。

        Returns:
            Markdown 格式的趋势报告
        """
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        logger.info(f"生成每周趋势: {monday} ~ {today}")
        return self._generate(
            target_date=monday,
            days_range=7,
            prompt_template=WEEKLY_TREND_PROMPT,
            title_date=f"{monday.isoformat()} ~ {today.isoformat()}",
        )

    def _generate(
        self,
        target_date: date,
        days_range: int,
        prompt_template: PromptTemplate,
        title_date: str,
    ) -> str:
        """核心生成逻辑。"""
        # 1. 收集时间范围内的笔记
        all_notes = self._store.list_notes(limit=10000)

        start_date = target_date
        end_date = target_date + timedelta(days=days_range)

        range_notes = [
            n
            for n in all_notes
            if n.ingested_at
            and start_date.isoformat() <= n.ingested_at[:10] <= end_date.isoformat()
        ]

        if not range_notes:
            if days_range == 1:
                return f"### 📅 {title_date} 知识简报\n\n昨日没有摄入新笔记。"
            else:
                return f"### 📊 {title_date} 知识趋势\n\n本周没有摄入新笔记。"

        # 2. 收集标签和关联
        all_tags: dict[str, int] = {}
        total_conns = 0
        connection_descriptions: list[str] = []

        for note in range_notes:
            tags = self._store.get_note_tags(note.id)
            for t in tags:
                all_tags[t.name] = all_tags.get(t.name, 0) + 1

            conns = self._store.get_connections(note.id)
            total_conns += len(conns)
            for c in conns:
                if c.description:
                    connection_descriptions.append(c.description)

        # 3. 组装 prompt
        notes_section = "\n".join(
            f"- [{n.ingested_at[:10] if n.ingested_at else '?'}] {n.title}"
            for n in range_notes
        )

        tags_section = (
            "\n".join(f"- {name} (×{count})" for name, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True))
            if all_tags
            else "无"
        )

        conns_section = (
            "\n".join(f"- {desc}" for desc in connection_descriptions[:5])
            if connection_descriptions
            else "无"
        )

        tag_stats = (
            "\n".join(
                f"- {name}: {count} 篇"
                for name, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
            )
            if all_tags
            else "无"
        )

        # 4. LLM 生成
        llm = get_chat_model()

        if days_range == 1:
            prompt = prompt_template.format(
                notes_section=notes_section,
                tags_section=tags_section,
                connections_section=conns_section,
                date_str=title_date,
            )
            response = llm.invoke(prompt)
            return response.content
        else:
            prompt = prompt_template.format(
                notes_section=notes_section,
                tags_stats=tag_stats,
                connection_count=total_conns // 2,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            response = llm.invoke(prompt)
            return response.content
