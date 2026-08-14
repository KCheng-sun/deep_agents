"""Brain REST API — FastAPI 后端。

启动: brain ui  或  uvicorn brain.api.server:app

端点:
  POST   /api/notes          — 添加笔记
  POST   /api/ingest         — 上传 Markdown 文件
  GET    /api/search         — 语义搜索
  POST   /api/ask            — 深度问答（DeepAgents）
  GET    /api/status         — 知识库统计
  GET    /api/connections    — 查看关联
  GET    /api/digest         — 每日/每周摘要
  GET    /api/review         — 复习提醒
"""

import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, Field

from brain.agents.researcher import ResearcherAgent
from brain.config import get_config
from brain.embedding import get_embedding_fn
from brain.ingestion.pipeline import IngestionPipeline
from brain.services.digest import DigestService
from brain.services.review import ReviewService
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(title="Brain API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 服务初始化（同步，线程安全）
# ============================================================

_pipeline: IngestionPipeline | None = None
_vector_store: VectorStore | None = None
_metadata_store: MetadataStore | None = None
_checkpointer = None  # LangGraph SqliteSaver——HIL 中断恢复用
_watcher = None  # FileWatcher——文件监听（可经 API 启停）
_scheduler = None  # TaskScheduler——定时任务调度


def _init():
    global _pipeline, _vector_store, _metadata_store, _checkpointer, _scheduler
    if _metadata_store is not None:
        return
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    _vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)
    _metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    _metadata_store.initialize()
    _pipeline = IngestionPipeline(
        vector_store=_vector_store,
        metadata_store=_metadata_store,
        chunk_size=cfg.ingestion.chunk_size,
        chunk_overlap=cfg.ingestion.chunk_overlap,
    )

    # HIL 中断恢复所需的 checkpointer（thread_id = session_id）
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpoint_path = cfg.storage.data_dir / "checkpoints.db"
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    _checkpointer = SqliteSaver(conn)

    # 定时任务调度器
    from brain.services.scheduler import build_default_scheduler

    _scheduler = build_default_scheduler(_pipeline, _metadata_store, _vector_store)
    _scheduler.start()

    # 回填历史知识片段的向量（幂等 upsert，已向量化的不受影响）
    for frag in _metadata_store.list_knowledge_fragments(limit=10000):
        try:
            _vector_store.add_fragment(frag["id"], frag["title"], frag["content"])
        except Exception as e:
            logger.warning(f"片段 #{frag['id']} 向量回填失败: {e}")


# 启动时预初始化
@app.on_event("startup")
def _startup():
    _init()


# ============================================================
# 请求/响应模型
# ============================================================


class NoteAddRequest(BaseModel):
    text: str = Field(..., min_length=1, description="笔记内容")
    title: str | None = Field(None, description="标题")


class NoteResponse(BaseModel):
    note_id: str
    message: str


class SearchResultItem(BaseModel):
    rank: int
    score: float
    title: str
    content_preview: str
    note_id: str
    tags: list[str]


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(None, description="会话 ID（不传则自动创建新会话）")


class AskResponse(BaseModel):
    question: str
    answer: str


class StatusResponse(BaseModel):
    note_count: int
    chunk_count: int
    tag_count: int
    connection_count: int
    top_tags: list[dict]
    recent_notes: list[dict]
    connections: list[dict]


class ConnectionItem(BaseModel):
    source_title: str
    target_title: str
    relation_type: str
    description: str | None
    strength: float


class DigestResponse(BaseModel):
    content: str


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionItem(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    timeline: list = []
    created_at: str


class SessionMessagesResponse(BaseModel):
    session_id: str
    title: str
    messages: list[MessageItem]


# ============================================================
# API 端点
# ============================================================


@app.post("/api/notes", response_model=NoteResponse)
def add_note(req: NoteAddRequest):
    """快速添加笔记。"""
    _init()
    note_id = _pipeline.ingest_text_sync(req.text, title=req.title)
    return NoteResponse(note_id=note_id, message="摄入成功")


@app.get("/api/notes/{note_id}/content")
def get_note_content(note_id: str):
    """精确取回笔记完整正文（复习卡片展开用）。"""
    _init()
    note = _metadata_store.get_note(note_id)
    if note is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="笔记不存在")

    chunks = _vector_store.get_note_chunks(note_id)
    content = "".join(c.content for c in chunks)
    return {
        "note_id": note_id,
        "title": note.title,
        "content": content,
        "ingested_at": note.ingested_at,
    }


@app.post("/api/ingest", response_model=NoteResponse)
def ingest_files(file: UploadFile = File(...)):
    """上传 Markdown 文件摄入。"""
    if not file.filename or not file.filename.endswith(".md"):
        return NoteResponse(note_id="", message="仅支持 .md 文件")

    _init()
    content = file.file.read()
    tmp_path = Path(tempfile.gettempdir()) / f"brain_upload_{uuid.uuid4().hex[:8]}.md"
    tmp_path.write_bytes(content)

    try:
        note_id = _pipeline.ingest_file_sync(tmp_path)
        return NoteResponse(note_id=note_id, message=f"已摄入: {file.filename}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/search", response_model=SearchResponse)
def search_notes(
    query: str = Query(..., min_length=1),
    tag: str | None = Query(None),
    top_k: int = Query(5, ge=1, le=20),
):
    """语义搜索 + 标签过滤。"""
    _init()

    tag_note_ids: set | None = None
    if tag:
        all_notes = _metadata_store.list_notes(limit=10000)
        tag_note_ids = set()
        for note in all_notes:
            note_tags = _metadata_store.get_note_tags(note.id)
            if any(tag.lower() in t.name.lower() for t in note_tags):
                tag_note_ids.add(note.id)

    results = _vector_store.search(query, top_k=max(top_k * 2, 20))

    items = []
    seen = set()
    for r in results:
        if tag_note_ids is not None and r.note_id not in tag_note_ids:
            continue
        if r.note_id in seen:
            continue
        seen.add(r.note_id)
        if len(items) >= top_k:
            break

        note_tags = _metadata_store.get_note_tags(r.note_id)
        tag_names = [t.name for t in note_tags]

        items.append(SearchResultItem(
            rank=len(items) + 1,
            score=round(r.score, 4),
            title=r.note_title,
            content_preview=r.content[:300],
            note_id=r.note_id,
            tags=tag_names,
        ))

    return SearchResponse(query=query, total=len(items), results=items)


@app.post("/api/ask", response_model=AskResponse)
def ask_question(req: AskRequest):
    """DeepAgents 深度问答（非流式）。"""
    _init()

    agent = ResearcherAgent(_vector_store, _metadata_store)
    answer = agent.research_sync(req.question)

    return AskResponse(question=req.question, answer=answer)


@app.post("/api/ask/stream")
def ask_question_stream(req: AskRequest):
    """DeepAgents 深度问答（SSE 流式，自动持久化到会话）。

    事件格式:
      data: {"type": "session", "session_id": "..."}      # 会话 ID（首次创建时）
      data: {"type": "status", "message": "..."}          # 状态提示
      data: {"type": "tool_start", "name": "...", "args": {...}}  # 工具调用开始
      data: {"type": "tool_end", "name": "..."}           # 工具调用完成
      data: {"type": "token", "content": "..."}           # 答案 token
      data: {"type": "done", "content": ""}               # 完成
    """
    session_id = req.session_id
    import json
    import uuid

    from fastapi.responses import StreamingResponse

    _init()

    agent = ResearcherAgent(_vector_store, _metadata_store)

    # 会话处理：未指定则自动创建
    created_new_session = False
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
        created_new_session = True
    elif _metadata_store.get_session(session_id) is None:
        # 前端传来的会话不存在（可能被删），重建
        created_new_session = True

    if created_new_session:
        # 用问题前 30 字作为会话标题
        title = req.question[:30] + ("..." if len(req.question) > 30 else "")
        _metadata_store.create_session(session_id, title=title)

    # 先取历史消息（不含刚保存的当前问题），组装多轮上下文
    history = _metadata_store.get_messages(session_id)

    # 第二层记忆：检索跨会话的相关历史消息
    memory_hits = _vector_store.search_memory(
        req.question,
        top_k=5,
        current_session=session_id,  # 同会话旧消息加权（FR27）
    )

    # 保存用户消息（同时写入记忆向量）
    user_msg_id = _metadata_store.add_message(session_id, "user", req.question)
    _vector_store.add_memory(user_msg_id, session_id, "user", req.question)
    _metadata_store.touch_session(session_id)

    def event_stream():
        # 收集回答内容和工具轨迹，流结束后落库
        answer_parts: list[str] = []
        timeline: list[dict] = []

        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        for event in agent.research_stream(
            req.question, session_id, history, memory_hits, checkpointer=_checkpointer
        ):
            if event["type"] == "token":
                answer_parts.append(event["content"])
            elif event["type"] == "interrupt":
                # HIL 中断：保存已流出的答案，向用户请求决策
                answer = "".join(answer_parts)
                if answer:
                    _metadata_store.add_message(session_id, "assistant", answer, timeline=timeline)
                    _metadata_store.touch_session(session_id)
                # 提取提议的知识片段（propose_knowledge 的 args）
                request = event.get("request") or {}
                action_requests = request.get("action_requests", [])
                proposal = None
                if action_requests:
                    first = action_requests[0]
                    proposal = {
                        "name": first.get("name", ""),
                        "args": first.get("args", {}),
                        "description": first.get("description", ""),
                    }
                yield f"data: {json.dumps({'type': 'interrupt', 'session_id': session_id, 'proposal': proposal}, ensure_ascii=False)}\n\n"
                return  # 流结束，等待 /api/ask/resume 恢复
            elif event["type"] == "tool_start" and event.get("name"):
                timeline.append(
                    {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                )
            elif event["type"] == "tool_end" and event.get("name"):
                # 从后往前标记同名工具完成
                for item in reversed(timeline):
                    if item["kind"] == "tool" and item["name"] == event["name"] and not item["done"]:
                        item["done"] = True
                        break
            elif event["type"] == "done":
                # 保存 assistant 消息（同时写入记忆向量）
                answer = "".join(answer_parts)
                if answer:
                    assistant_msg_id = _metadata_store.add_message(
                        session_id, "assistant", answer, timeline=timeline
                    )
                    _vector_store.add_memory(
                        assistant_msg_id, session_id, "assistant", answer
                    )
                    _metadata_store.touch_session(session_id)

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class ResumeRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID（thread_id）")
    decisions: list[dict] = Field(
        ...,
        description='HIL 决策列表，如 [{"type": "approve"}] 或 [{"type": "reject", "message": "..."}]',
    )


@app.post("/api/ask/resume")
def ask_question_resume(req: ResumeRequest):
    """HIL 决策后恢复 Agent 执行（SSE 流式）。

    决策格式:
      approve: {"type": "approve"}                       → 原样执行工具
      edit:    {"type": "edit", "edited_action": {"name": ..., "args": {...}}}
      reject:  {"type": "reject", "message": "..."}      → 跳过工具
    """
    import json

    from fastapi.responses import StreamingResponse

    _init()

    agent = ResearcherAgent(_vector_store, _metadata_store)

    def resume_stream():
        answer_parts: list[str] = []
        timeline: list[dict] = []

        for event in agent.resume_stream(
            req.session_id,
            {"decisions": req.decisions},
            checkpointer=_checkpointer,
        ):
            if event["type"] == "token":
                answer_parts.append(event["content"])
            elif event["type"] == "tool_start" and event.get("name"):
                timeline.append(
                    {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                )
            elif event["type"] == "tool_end" and event.get("name"):
                for item in reversed(timeline):
                    if item["kind"] == "tool" and item["name"] == event["name"] and not item["done"]:
                        item["done"] = True
                        break
            elif event["type"] == "done":
                answer = "".join(answer_parts)
                if answer:
                    assistant_msg_id = _metadata_store.add_message(
                        req.session_id, "assistant", answer, timeline=timeline
                    )
                    _vector_store.add_memory(
                        assistant_msg_id, req.session_id, "assistant", answer
                    )
                    _metadata_store.touch_session(req.session_id)

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        resume_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 会话管理 API
# ============================================================


@app.post("/api/sessions", response_model=SessionItem)
def create_session(req: SessionCreateRequest):
    """创建新会话。"""
    import uuid

    _init()
    session_id = uuid.uuid4().hex[:12]
    title = req.title or "新对话"
    _metadata_store.create_session(session_id, title=title)
    session = _metadata_store.get_session(session_id)
    return SessionItem(**session)


@app.get("/api/sessions", response_model=list[SessionItem])
def list_sessions():
    """列出全部会话。"""
    _init()
    sessions = _metadata_store.list_sessions()
    return [SessionItem(**s) for s in sessions]


@app.get("/api/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages(session_id: str):
    """获取会话的消息历史。"""
    _init()
    session = _metadata_store.get_session(session_id)
    if session is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="会话不存在")

    messages = _metadata_store.get_messages(session_id)
    return SessionMessagesResponse(
        session_id=session_id,
        title=session["title"],
        messages=[MessageItem(**m) for m in messages],
    )


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话（含全部消息和记忆向量）。"""
    _init()
    _metadata_store.delete_session(session_id)
    _vector_store.delete_session_memory(session_id)
    return {"ok": True}


@app.get("/api/fragments")
def list_fragments(limit: int = Query(50, ge=1, le=200)):
    """列出已保存的知识片段（HIL 确认后的沉淀内容）。"""
    _init()
    fragments = _metadata_store.list_knowledge_fragments(limit=limit)
    return fragments


@app.delete("/api/fragments/{fragment_id}")
def delete_fragment(fragment_id: int):
    """删除知识片段（SQLite + 向量同步删除）。"""
    _init()
    ok = _metadata_store.delete_knowledge_fragment(fragment_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="片段不存在")
    _vector_store.delete_fragment(fragment_id)
    return {"ok": True}


# ============================================================
# 文件监听 API
# ============================================================


class WatchStatusResponse(BaseModel):
    running: bool
    watch_dir: str
    recent_events: list[dict]


@app.get("/api/watch", response_model=WatchStatusResponse)
def watch_status():
    """查询文件监听状态。"""
    _init()
    global _watcher

    cfg = get_config()
    if _watcher is not None and _watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(_watcher.watch_dir),
            recent_events=_watcher.get_recent_events(),
        )
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


@app.post("/api/watch/start", response_model=WatchStatusResponse)
def watch_start():
    """启动文件监听（后台线程）。"""
    _init()
    global _watcher

    from brain.ingestion.watcher import FileWatcher

    if _watcher is not None and _watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(_watcher.watch_dir),
            recent_events=_watcher.get_recent_events(),
        )

    cfg = get_config()
    watch_dir = cfg.storage.notes_dir
    watch_dir.mkdir(parents=True, exist_ok=True)

    def _on_file(file_path):
        try:
            note_id = _pipeline.ingest_file_sync(file_path)
            _watcher.record_event(file_path.name, note_id)
            logger.info(f"[watch] ✅ {file_path.name} → {note_id}")
        except Exception as e:
            logger.warning(f"[watch] ❌ {file_path.name}: {e}")

    _watcher = FileWatcher(
        watch_dir=watch_dir,
        ingest_callback=_on_file,
        debounce_seconds=cfg.ingestion.debounce_seconds,
    )
    _watcher.start()

    return WatchStatusResponse(
        running=True,
        watch_dir=str(watch_dir),
        recent_events=[],
    )


@app.post("/api/watch/stop", response_model=WatchStatusResponse)
def watch_stop():
    """停止文件监听。"""
    _init()
    global _watcher

    if _watcher is not None:
        _watcher.stop()
        _watcher = None

    cfg = get_config()
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


# ============================================================
# RSS 订阅 API
# ============================================================


class RssAddRequest(BaseModel):
    url: str = Field(..., min_length=1, description="RSS/Atom 订阅源 URL")


class RssFetchResponse(BaseModel):
    feeds_checked: int
    new_entries: int
    errors: list[str]


@app.get("/api/rss")
def rss_list():
    """列出全部 RSS 订阅源。"""
    _init()
    return _metadata_store.list_rss_feeds()


@app.post("/api/rss", response_model=RssFetchResponse)
def rss_add_and_fetch(req: RssAddRequest):
    """添加订阅源并立即拉取一次。"""
    _init()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(_pipeline, _metadata_store)
    feed_id = source.add_feed(req.url)
    new_count = source.fetch_feed(feed_id)

    return RssFetchResponse(
        feeds_checked=1,
        new_entries=new_count,
        errors=[],
    )


@app.post("/api/rss/fetch", response_model=RssFetchResponse)
def rss_fetch_all():
    """拉取所有订阅源的新文章。"""
    _init()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(_pipeline, _metadata_store)
    summary = source.fetch_all()
    return RssFetchResponse(**summary)


@app.delete("/api/rss/{feed_id}")
def rss_delete(feed_id: int):
    """删除 RSS 订阅源。"""
    _init()
    ok = _metadata_store.delete_rss_feed(feed_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="订阅源不存在")
    return {"ok": True}


# ============================================================
# 定时任务调度 API
# ============================================================


@app.get("/api/scheduler")
def scheduler_status():
    """查询定时任务状态。"""
    _init()
    if _scheduler is None:
        return []
    return _scheduler.get_status()


@app.post("/api/scheduler/run/{task_name}")
def scheduler_run_now(task_name: str):
    """手动立即执行某定时任务。

    task_name: rss_sync | daily_digest | weekly_digest
    """
    _init()
    if _scheduler is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="调度器未初始化")

    result = _scheduler.run_now(task_name)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"任务不存在: {task_name}")
    return {"task": task_name, "result": result}


@app.get("/api/digest/reports")
def digest_reports(limit: int = Query(10, ge=1, le=50)):
    """列出最近生成的摘要报告（定时任务产物）。"""
    _init()
    return _metadata_store.list_digest_reports(limit=limit)


@app.get("/api/graph")
def knowledge_graph():
    """知识图谱数据——笔记节点 + 关联边。

    全部走批量 SQL（一次取关联、一次取度数、一次取标签），
    无 N+1 查询，500+ 笔记时依然毫秒级响应。
    """
    _init()

    # 一次 SQL：全部关联 + 两端标题
    flat_conns = _metadata_store.get_all_connections_flat()

    edges = [
        {
            "source": c["source"],
            "target": c["target"],
            "relation_type": c["relation_type"],
            "strength": c["strength"],
            "description": c["description"],
        }
        for c in flat_conns
    ]

    # 一次 SQL：度数统计
    degree_map = _metadata_store.get_note_degree_map()

    # 一次 SQL：全部笔记 + 批量标签
    all_notes = _metadata_store.list_notes(limit=10000)
    tags_map = _metadata_store.get_tags_batch([n.id for n in all_notes])

    nodes = [
        {
            "id": note.id,
            "title": note.title[:30],
            "tags": [t.name for t in tags_map.get(note.id, [])][:3],
            "degree": degree_map.get(note.id, 0),
            "date": note.ingested_at[:10] if note.ingested_at else "",
        }
        for note in all_notes
    ]

    return {"nodes": nodes, "edges": edges}


@app.get("/api/status", response_model=StatusResponse)
def get_status():
    """知识库统计概览。

    全部走批量 SQL（一次标签统计、一次关联、一次批量标签），
    无 N+1 查询。
    """
    _init()

    chunk_count = _vector_store.count()
    note_count = _metadata_store.count_notes()

    # 一次 SQL：标签统计
    tag_counts = _metadata_store.get_tag_counts()

    # 一次 SQL：全部关联（含标题）
    flat_conns = _metadata_store.get_all_connections_flat()
    total_conns = len(flat_conns)
    all_conns = [
        {
            "source_title": c["source_title"],
            "target_title": c["target_title"],
            "relation_type": c["relation_type"],
            "description": c["description"],
            "strength": c["strength"],
        }
        for c in flat_conns
    ]

    top_tags = [
        {"name": name, "count": count}
        for name, count in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # 一次 SQL：最近笔记 + 批量标签
    recent = _metadata_store.list_notes(limit=5)
    tags_map = _metadata_store.get_tags_batch([n.id for n in recent])
    recent_notes = [
        {
            "note_id": note.id,
            "title": note.title,
            "date": note.ingested_at[:10] if note.ingested_at else "?",
            "tags": [t.name for t in tags_map.get(note.id, [])],
        }
        for note in recent
    ]

    return StatusResponse(
        note_count=note_count, chunk_count=chunk_count,
        tag_count=len(tag_counts), connection_count=total_conns,
        top_tags=top_tags, recent_notes=recent_notes, connections=all_conns,
    )


@app.get("/api/connections", response_model=list[ConnectionItem])
def get_connections():
    """获取所有关联（一次 SQL JOIN 查询）。"""
    _init()

    flat_conns = _metadata_store.get_all_connections_flat()
    return [
        ConnectionItem(
            source_title=c["source_title"],
            target_title=c["target_title"],
            relation_type=c["relation_type"],
            description=c["description"],
            strength=c["strength"],
        )
        for c in flat_conns
    ]


@app.get("/api/digest", response_model=DigestResponse)
def get_digest(weekly: bool = Query(False)):
    """生成知识摘要。"""
    _init()
    svc = DigestService(_metadata_store)
    result = svc.daily_sync() if not weekly else svc.weekly_sync()
    return DigestResponse(content=result)


@app.get("/api/review")
def get_review(limit: int = Query(10, ge=1, le=50)):
    """SM-2 到期复习列表（含未进入系统的新卡片）。"""
    _init()
    svc = ReviewService(_metadata_store)
    due = svc.get_due_items_sync(limit=limit)
    return {"total": len(due), "items": due}


class ReviewRecordRequest(BaseModel):
    note_id: str = Field(..., description="笔记 ID")
    quality: int = Field(..., ge=0, le=5, description="0-5 评分（0-2忘记/3困难/4良好/5简单）")


@app.post("/api/review/record")
def record_review(req: ReviewRecordRequest):
    """记录复习评分，SM-2 计算下次复习时间。"""
    _init()
    svc = ReviewService(_metadata_store)
    return svc.record_review_sync(req.note_id, req.quality)


# ============================================================
# 前端静态文件
# ============================================================

_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/")
def serve_frontend():
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(index_path)
    return {"message": "前端未构建。运行: cd frontend && npm run build"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("brain.api.server:app", host="127.0.0.1", port=7860, reload=True)
