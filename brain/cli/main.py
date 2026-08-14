"""Brain CLI — 个人知识管家的命令行入口。

用法:
    brain add "今天读到的好观点..."
    brain ingest ./notes/article.md
    brain search "RAG 优化策略"
    brain ask "我关于 Agent 架构的思考有哪些关键结论？"
    brain status
"""

import asyncio
import os
from pathlib import Path

import click
from loguru import logger

from brain.config import get_config
from brain.embedding import get_embedding_fn
from brain.ingestion.pipeline import IngestionPipeline
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# ============================================================
# 全局初始化
# ============================================================


def _get_pipeline() -> IngestionPipeline:
    """懒加载摄入流水线（包含 vector_store 和 metadata_store 的初始化）。"""
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)
    metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    # 在事件循环中初始化 metadata_store
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if not hasattr(_get_pipeline, "_metadata_initialized"):
        loop.run_until_complete(metadata_store.initialize())
        _get_pipeline._metadata_initialized = True

    pipeline = IngestionPipeline(
        vector_store=vector_store,
        metadata_store=metadata_store,
        chunk_size=cfg.ingestion.chunk_size,
        chunk_overlap=cfg.ingestion.chunk_overlap,
    )
    return pipeline


def _get_search_components():
    """懒加载搜索组件。"""
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)

    metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if not hasattr(_get_search_components, "_md_initialized"):
        loop.run_until_complete(metadata_store.initialize())
        _get_search_components._md_initialized = True

    return vector_store, metadata_store


def _run_async(coro):
    """在当前或新的事件循环中运行异步协程。"""
    try:
        asyncio.get_running_loop()  # 探测是否有运行中的事件循环
        # 已有运行中的事件循环，用新线程运行
        import concurrent.futures
        import threading

        future = concurrent.futures.Future()

        def _run():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result = new_loop.run_until_complete(coro)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                new_loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return future.result()
    except RuntimeError:
        # 没有运行中的事件循环，直接创建
        return asyncio.run(coro)


# ============================================================
# CLI 入口
# ============================================================


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="显示详细日志")
@click.option("--dry-run", is_flag=True, help="模拟运行，不实际调用 LLM")
@click.pass_context
def cli(ctx, verbose: bool, dry_run: bool):
    """Brain — 个人知识管家（第二大脑）

    本地优先、AI 驱动的知识管理系统。
    摄入你的笔记和想法，用自然语言搜索和提问。
    """
    ctx.ensure_object(dict)

    # 日志配置
    if verbose:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="DEBUG", format="{message}")
    else:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="INFO", format="{message}")
        # 抑制 ChromaDB / sentence-transformers 的内部日志
        import logging as std_logging

        for name in ["chromadb", "sentence_transformers", "transformers", "httpx", "urllib3"]:
            std_logging.getLogger(name).setLevel(std_logging.WARNING)

    if dry_run:
        cfg = get_config()
        cfg.dry_run = True

    ctx.obj["verbose"] = verbose


# ============================================================
# brain add — 快速添加笔记
# ============================================================


@cli.command()
@click.argument("text", required=True)
@click.option("--title", "-t", default=None, help="笔记标题（默认取文本第一行）")
def add(text: str, title: str | None):
    """快速添加一条笔记。

    \b
    示例:
      brain add "今天读了一篇关于 RAG 优化的文章，核心思路是..."
      brain add -t "RAG 优化笔记" "HyDE 方法通过假设性文档..."
    """
    pipeline = _get_pipeline()

    click.echo("📝 正在摄入...")
    note_id = _run_async(pipeline.ingest_text(text, title=title))
    click.echo(f"✅ 已摄入: {note_id}")


# ============================================================
# brain ingest — 批量导入文件
# ============================================================


@cli.command()
@click.argument("path", type=click.Path(exists=True))
def ingest(path: str):
    """摄入 Markdown 文件或目录。

    \b
    示例:
      brain ingest ./notes/article.md
      brain ingest ./notes/          # 摄入目录下所有 .md 文件
    """
    pipeline = _get_pipeline()
    target = Path(path)

    if target.is_file():
        if target.suffix != ".md":
            click.echo(f"⚠️  跳过非 Markdown 文件: {target.name}")
            return
        click.echo(f"📄 摄入: {target.name}")
        note_id = _run_async(pipeline.ingest_file(target))
        click.echo(f"✅ 完成: {note_id}")

    elif target.is_dir():
        md_files = list(target.rglob("*.md"))
        # 排除隐藏目录
        md_files = [f for f in md_files if not any(p.startswith(".") for p in f.parts)]
        click.echo(f"📂 发现 {len(md_files)} 个 Markdown 文件")

        for i, f in enumerate(md_files, 1):
            click.echo(f"  [{i}/{len(md_files)}] 摄入: {f.name}")
            try:
                note_id = _run_async(pipeline.ingest_file(f))
                click.echo(f"    ✅ {note_id}")
            except Exception as e:
                click.echo(f"    ❌ 失败: {e}")


# ============================================================
# brain search — 语义搜索
# ============================================================


@cli.command()
@click.argument("query", required=True)
@click.option("--top-k", "-k", default=5, help="返回结果数量 (默认 5)")
@click.option("--tag", "-t", default=None, help="按标签过滤 (例如 --tag \"AI Agent\")")
def search(query: str, top_k: int, tag: str | None):
    """语义搜索知识库。

    \b
    示例:
      brain search "RAG 优化策略"
      brain search -k 10 "Agent 架构设计"
      brain search --tag "Python" "异步编程"
    """
    vector_store, metadata_store = _get_search_components()

    # 标签过滤: 获取匹配标签的所有 note_id
    tag_note_ids: set | None = None
    if tag:
        click.echo(f"🔍 搜索: {query}  [标签: {tag}]\n")
        # 查询 SQLite 中有该标签的所有活跃笔记
        all_notes = _run_async(metadata_store.list_notes(limit=10000))
        tag_note_ids = set()
        for note in all_notes:
            note_tags = _run_async(metadata_store.get_note_tags(note.id))
            if any(tag.lower() in t.name.lower() for t in note_tags):
                tag_note_ids.add(note.id)
        if not tag_note_ids:
            click.echo(f"  没有标记为 '{tag}' 的笔记。")
            return
    else:
        click.echo(f"🔍 搜索: {query}\n")

    results = vector_store.search(query, top_k=max(top_k * 2, 20))

    if not results:
        click.echo("  没有找到相关结果。")
        return

    # 去重按 note_id，可选按标签过滤
    seen_notes: dict[str, list] = {}
    for r in results:
        if tag_note_ids is not None and r.note_id not in tag_note_ids:
            continue
        if r.note_id not in seen_notes:
            seen_notes[r.note_id] = []
        seen_notes[r.note_id].append(r)

    if not seen_notes:
        click.echo(f"  没有同时匹配查询和标签 '{tag}' 的结果。")
        return

    # 显示结果（带标签）
    for i, (note_id, chunks) in enumerate(seen_notes.items(), 1):
        if i > top_k:
            break
        best = max(chunks, key=lambda c: c.score)
        title = best.note_title or best.metadata.get("title", "无标题")

        # 获取标签用于显示
        note_tags = _run_async(metadata_store.get_note_tags(note_id))
        tag_str = ""
        if note_tags:
            tag_names = [t.name for t in note_tags[:3]]
            tag_str = " [" + ", ".join(tag_names) + "]"

        click.echo(f"  {i}. [{best.score:.2f}] {title}{tag_str}")
        click.echo(f"     {best.content[:150].replace(chr(10), ' ')}...")
        click.echo(f"     id: {note_id}")
        click.echo()


# ============================================================
# brain ask — 深度问答
# ============================================================


@cli.command()
@click.argument("question", required=True)
@click.option("--simple", "-s", is_flag=True, help="使用简单 RAG 模式（不用 DeepAgents）")
def ask(question: str, simple: bool):
    """基于知识库的深度问答。

    \b
    默认使用 DeepAgents 多步推理（多次搜索 + 关联追踪）。
    示例:
      brain ask "我关于 Agent 架构的思考有哪些关键结论？"
      brain ask -s "ChromaDB 参数"    # 简单 RAG 模式
    """
    vector_store, metadata_store = _get_search_components()

    if simple:
        # 降级模式：简单 RAG
        _ask_simple(question, vector_store, metadata_store)
    else:
        # DeepAgents 模式：多步推理
        _ask_deep(question, vector_store, metadata_store)


def _ask_deep(question: str, vector_store, metadata_store) -> None:
    """DeepAgents 多步推理问答"""
    from brain.agents.researcher import ResearcherAgent

    click.echo("🧠 深度研究中...（多次搜索 + 关联追踪）")

    try:
        agent = ResearcherAgent(vector_store, metadata_store)
        answer = _run_async(agent.research(question))
        click.echo(f"\n{answer}\n")
    except Exception as e:
        click.echo(f"❌ DeepAgents 研究失败: {e}")
        click.echo("提示: 使用 brain ask -s 切换简单 RAG 模式。")


def _ask_simple(question: str, vector_store, metadata_store) -> None:
    """简单 RAG 模式（降级方案）"""
    results = vector_store.search(question, top_k=5)
    if not results:
        click.echo("  没有找到相关内容来回答这个问题。")
        return

    context_parts = []
    seen_notes = set()
    for r in results:
        if r.note_id not in seen_notes:
            seen_notes.add(r.note_id)
            context_parts.append(
                f"--- 来源: {r.note_title} (id: {r.note_id}) ---\n{r.content}"
            )
    context = "\n\n".join(context_parts)

    prompt = f"""你是一个个人知识库助手。基于用户的知识库内容回答问题。

知识库内容:
{context}

用户问题: {question}

请基于知识库内容回答。引用具体的来源（笔记标题）。
如果知识库中没有足够信息，请诚实说明。"""

    click.echo("🤔 思考中...")

    try:
        from brain.llm import get_chat_model

        llm = get_chat_model()
        response = llm.invoke(prompt)
        answer = response.content

        click.echo(f"\n{answer}\n")
        click.echo("📚 参考来源:")
        for r in results[:5]:
            click.echo(f"  • {r.note_title} (相似度: {r.score:.2f})")
    except Exception as e:
        click.echo(f"❌ LLM 调用失败: {e}")
        click.echo("提示: 检查 DEEPSEEK_API_KEY 环境变量是否已设置。")


# ============================================================
# brain status — 知识库统计
# ============================================================


@cli.command()
def status():
    """查看知识库统计信息。"""
    vector_store, metadata_store = _get_search_components()

    chunk_count = vector_store.count()
    note_count = _run_async(metadata_store.count_notes())

    # 标签统计
    all_notes = _run_async(metadata_store.list_notes(limit=10000))
    tag_counts: dict[str, int] = {}
    total_connections = 0
    for note in all_notes:
        tags = _run_async(metadata_store.get_note_tags(note.id))
        for t in tags:
            tag_counts[t.name] = tag_counts.get(t.name, 0) + 1
        conns = _run_async(metadata_store.get_connections(note.id))
        total_connections += len(conns)
    # 每个 connection 被数了两次（source 和 target 各一次）
    total_connections //= 2

    click.echo("🧠 Brain 知识库状态\n")
    click.echo(f"  笔记总数:   {note_count}")
    click.echo(f"  分块总数:   {chunk_count}")
    click.echo(f"  AI 标签数:  {len(tag_counts)}")
    click.echo(f"  AI 关联数:  {total_connections}")

    # 热门标签
    if tag_counts:
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        click.echo("\n🏷️  热门标签:")
        for name, count in top_tags:
            click.echo(f"  [{count}] {name}")

    # 最近笔记
    recent_notes = _run_async(metadata_store.list_notes(limit=5))
    if recent_notes:
        click.echo("\n📝 最近摄入的笔记:")
        for note in recent_notes:
            date_str = note.ingested_at[:10] if note.ingested_at else "未知"
            tags = _run_async(metadata_store.get_note_tags(note.id))
            tag_str = ""
            if tags:
                tag_str = "  [" + ", ".join(t.name for t in tags[:3]) + "]"
            click.echo(f"  [{date_str}] {note.title}{tag_str}")


# ============================================================
# brain connections — 查看笔记关联
# ============================================================


@cli.command()
@click.option("--note-id", "-n", default=None, help="指定笔记 ID（不指定则列出全部）")
def connections(note_id: str | None):
    """查看笔记之间的 AI 关联。

    \b
    示例:
      brain connections                   # 列出全部关联
      brain connections -n a1b2c3d4e5f6  # 指定笔记的关联
    """
    _, metadata_store = _get_search_components()

    if note_id:
        # 查看特定笔记的关联
        note = _run_async(metadata_store.get_note(note_id))
        if note is None:
            click.echo(f"❌ 笔记不存在: {note_id}")
            return

        conns = _run_async(metadata_store.get_connections(note_id))
        click.echo(f"🔗 {note.title} 的关联 ({len(conns)} 条)\n")

        if not conns:
            click.echo("  暂无关联。")
            return

        for c in conns:
            # 判断当前笔记是 source 还是 target
            other_id = c.target_note_id if c.source_note_id == note_id else c.source_note_id
            other_note = _run_async(metadata_store.get_note(other_id))
            other_title = other_note.title if other_note else other_id[:8]

            relation_icon = {
                "related": "🔗",
                "extends": "➡️",
                "contradicts": "⚡",
                "references": "📖",
            }.get(c.relation_type.value, "🔗")

            click.echo(f"  {relation_icon} [{c.relation_type.value}] → {other_title}")
            if c.description:
                click.echo(f"    {c.description}")
            click.echo(f"    强度: {c.strength:.0%}  |  id: {other_id}")
            click.echo()
    else:
        # 列出全部关联
        all_notes = _run_async(metadata_store.list_notes(limit=10000))
        all_conns: list[tuple] = []  # (conn, source_title, target_title)
        seen = set()

        for note in all_notes:
            conns = _run_async(metadata_store.get_connections(note.id))
            for c in conns:
                pair = tuple(sorted([c.source_note_id, c.target_note_id]))
                if pair not in seen:
                    seen.add(pair)
                    source_note = _run_async(metadata_store.get_note(c.source_note_id))
                    target_note = _run_async(metadata_store.get_note(c.target_note_id))
                    all_conns.append((
                        c,
                        source_note.title if source_note else c.source_note_id[:8],
                        target_note.title if target_note else c.target_note_id[:8],
                    ))

        click.echo(f"🔗 知识库关联 ({len(all_conns)} 条)\n")

        if not all_conns:
            click.echo("  暂无 AI 发现的关联。摄入更多同主题笔记后会自动发现。")
            return

        for conn, src_title, tgt_title in all_conns:
            relation_icon = {
                "related": "🔗",
                "extends": "➡️",
                "contradicts": "⚡",
                "references": "📖",
            }.get(conn.relation_type.value, "🔗")

            click.echo(f"  {relation_icon} [{conn.relation_type.value}] {src_title}")
            click.echo(f"    → {tgt_title}")
            if conn.description:
                click.echo(f"    {conn.description}")
            click.echo(f"    强度: {conn.strength:.0%}")
            click.echo()


# ============================================================
# brain digest — 每日/每周知识摘要
# ============================================================


@cli.command()
@click.option("--weekly", "-w", is_flag=True, help="生成本周趋势报告（默认每日简报）")
def digest(weekly: bool):
    """生成知识摘要。

    \b
    示例:
      brain digest           # 昨日知识简报
      brain digest --weekly  # 本周知识趋势
    """
    _, metadata_store = _get_search_components()

    from brain.services.digest import DigestService

    svc = DigestService(metadata_store)

    if weekly:
        click.echo("📊 生成每周趋势...")
        result = _run_async(svc.weekly())
    else:
        click.echo("📅 生成每日摘要...")
        result = _run_async(svc.daily())

    click.echo(f"\n{result}")


# ============================================================
# brain review — 复习提醒
# ============================================================


@cli.command()
@click.option("--limit", "-n", default=5, help="显示数量 (默认 5)")
def review(limit: int):
    """查看需要复习的旧笔记。

    \b
    示例:
      brain review
      brain review -n 10
    """
    _, metadata_store = _get_search_components()

    from brain.services.review import ReviewService

    svc = ReviewService(metadata_store)
    due = _run_async(svc.get_due_items(limit=limit))

    if not due:
        click.echo("✅ 所有笔记都是最近摄入的，暂无需要复习的内容。")
        return

    click.echo(f"📖 需要复习的笔记 ({len(due)} 条)\n")

    for i, (note, freshness, tags) in enumerate(due, 1):
        # 新鲜度转文字
        if freshness < 0.2:
            status = "🔴"
        elif freshness < 0.3:
            status = "🟡"
        else:
            status = "🟢"

        date_str = note.ingested_at[:10] if note.ingested_at else "未知"
        tag_str = " [" + ", ".join(tags[:2]) + "]" if tags else ""

        click.echo(f"  {i}. {status} [{date_str}] {note.title}{tag_str}")
        click.echo(f"     新鲜度: {freshness:.0%}  |  id: {note.id}")
        click.echo()


# ============================================================
# brain watch — 文件监听
# ============================================================


@cli.command()
@click.option("--dir", "-d", default=None, help="监听目录（默认配置的 notes_dir）")
def watch(dir: str):
    """监听目录，Markdown 文件变化自动摄入知识库。

    \b
    示例:
      brain watch                    # 监听默认目录
      brain watch -d ./my_notes      # 监听指定目录
      Ctrl+C 停止
    """
    from pathlib import Path

    from brain.ingestion.watcher import FileWatcher

    cfg = get_config()
    watch_dir = Path(dir) if dir else cfg.storage.notes_dir
    pipeline = _get_pipeline()

    watcher = FileWatcher(
        watch_dir=watch_dir,
        ingest_callback=lambda p: _record_ingest(watcher, pipeline, p),
        debounce_seconds=cfg.ingestion.debounce_seconds,
    )

    click.echo(f"👀 监听目录: {watch_dir}")
    click.echo("   放入/修改 .md 文件将自动摄入，Ctrl+C 停止")

    try:
        watcher.start()
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n停止监听")
        watcher.stop()


def _record_ingest(watcher, pipeline, file_path) -> None:
    """文件摄入回调——记录事件到 watcher。"""
    try:
        note_id = pipeline.ingest_file_sync(file_path)
        watcher.record_event(file_path.name, note_id)
        click.echo(f"✅ 已摄入: {file_path.name} → {note_id}")
    except Exception as e:
        click.echo(f"❌ 摄入失败: {file_path.name}: {e}")


# ============================================================
# brain rss — RSS 订阅管理
# ============================================================


@cli.group()
def rss():
    """RSS 订阅管理——拉取订阅源文章自动摄入知识库。"""


@rss.command("add")
@click.argument("url")
def rss_add(url: str):
    """添加 RSS 订阅源。"""
    pipeline = _get_pipeline()
    _, metadata_store = _get_search_components()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(pipeline, metadata_store)
    feed_id = source.add_feed(url)
    click.echo(f"✅ 已添加订阅源 #{feed_id}: {url}")


@rss.command("list")
def rss_list():
    """列出全部 RSS 订阅源。"""
    _, metadata_store = _get_search_components()


    # RssSource 只需要 metadata_store 就能列
    feeds = metadata_store.list_rss_feeds()
    if not feeds:
        click.echo("暂无订阅源。用 brain rss add <url> 添加")
        return

    for f in feeds:
        title = f["title"] or "(未拉取)"
        last = f["last_fetched_at"][:10] if f["last_fetched_at"] else "从未"
        click.echo(f"  #{f['id']} {f['url']}")
        click.echo(f"     标题: {title} | 累计摄入: {f['entry_count']} | 上次拉取: {last}")


@rss.command("fetch")
def rss_fetch():
    """立即拉取所有订阅源的新文章。"""
    pipeline = _get_pipeline()
    _, metadata_store = _get_search_components()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(pipeline, metadata_store)
    summary = source.fetch_all()
    click.echo(f"📡 检查 {summary['feeds_checked']} 个源，新增摄入 {summary['new_entries']} 条")
    for err in summary["errors"]:
        click.echo(f"  ❌ {err}")


@rss.command("remove")
@click.argument("feed_id", type=int)
def rss_remove(feed_id: int):
    """删除 RSS 订阅源。"""
    _, metadata_store = _get_search_components()
    ok = metadata_store.delete_rss_feed(feed_id)
    if ok:
        click.echo(f"✅ 已删除订阅源 #{feed_id}")
    else:
        click.echo(f"❌ 订阅源 #{feed_id} 不存在")


# ============================================================
# brain ui — 启动 Web 界面
# ============================================================


@cli.command()
@click.option("--port", "-p", default=7860, help="端口号 (默认 7860)")
@click.option("--host", "-h", default="127.0.0.1", help="绑定地址")
def ui(port: int, host: str):
    """启动 Web 界面（FastAPI + Vue）。

    \b
    示例:
      brain ui
      brain ui -p 8080
    """
    import uvicorn

    click.echo(f"🧠 Brain API 启动: http://{host}:{port}")
    click.echo(f"📖 API 文档: http://{host}:{port}/docs")
    uvicorn.run(
        "brain.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


# ============================================================
# 入口
# ============================================================


def main():
    """CLI 入口函数。"""
    try:
        cli()
    finally:
        # ChromaDB / sentence-transformers 的非 daemon 线程会阻止进程退出，
        # 用 os._exit 强制退出（CLI 命令执行完后不涉及数据丢失风险）
        os._exit(0)


if __name__ == "__main__":
    main()
