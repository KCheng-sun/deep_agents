# 个人知识管家（第二大脑）— 项目设计文档

> 版本: v0.3.0
> 最后更新: 2024-08-12
> 状态: Phase 3 设计中
> 依赖文档: [需求文档](./requirements.md)

---

## 1. 设计目标

1. **本地优先** — 核心功能不依赖云服务，除 LLM API 调用外
2. **文档驱动** — 需求→设计→实现，每次迭代先更新文档
3. **渐进增强** — Phase 1 做最小可用，每个 Phase 增加一层智能
4. **可测试** — 每个模块可独立测试，核心路径有集成测试

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / API 层                          │
│  brain add | search | ask | digest | config                  │
│  (Click/Typer)                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     服务层 (Services)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ DigestService│  │ReviewService│  │ IngestionOrchestrator│ │
│  │ 每日/周摘要  │  │ 间隔重复    │  │ 摄入编排             │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 智能处理层 (Agents)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │Classifier │ │Connector │ │Synthesizer│ │Researcher   │   │
│  │ 分类 Agent│ │ 关联 Agent│ │ 摘要 Agent│ │ 问答 Agent   │   │
│  │DeepAgents │ │DeepAgents│ │DeepAgents│ │DeepAgents   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                  流水线层 (LangGraph)                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              IngestionPipeline (摄入流水线)              │ │
│  │  解析 → 分块 → 嵌入 → 分类 → 索引 → 关联发现            │ │
│  │  (每个节点是一个 LangGraph Node, 状态可持久化)          │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              QueryRouter (查询路由)                      │ │
│  │  意图识别 → 搜索策略选择 → 执行 → 结果合成              │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    存储层 (Storage)                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ ChromaDB     │ │ SQLite       │ │ NetworkX Graph       │ │
│  │ 向量存储     │ │ 元数据/标签  │ │ 知识图谱（轻量）     │ │
│  │ 语义检索     │ │ CRUD 操作    │ │ 关联关系             │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 接入层 (Ingestion Sources)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 文件监听 │ │CLI 输入  │ │RSS 拉取  │ │ 书签导入     │   │
│  │(watchdog)│ │          │ │(feedparser)│ │(JSON parse) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 技术选型

### 3.1 核心框架

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| **LLM 编排** | LangChain | 成熟的文档加载器、文本分割器、Embeddings 抽象、Tool 定义 |
| **流程控制** | LangGraph | 有状态的图流水线、Checkpoint 持久化、Human-in-the-Loop |
| **多 Agent** | DeepAgents | 层次化 Agent 调度、深度推理、可插拔 Agent 定义 |
| **LLM** | Claude API (claude-fable-5) | 最强推理能力，适合深度分类/关联/问答 |
| **Embedding** | sentence-transformers (all-MiniLM-L6-v2) | 本地运行、轻量、384 维、中文友好 |

### 3.2 存储

| 组件 | 选型 | 用途 | Phase |
|------|------|------|-------|
| **向量数据库** | ChromaDB | 语义检索 | P0 |
| **关系型** | SQLite | 笔记元数据、标签、摄入日志 | P0 |
| **图存储** | NetworkX | 知识图谱关联（内存图，JSON 持久化） | P1 |
| **文件系统** | 本地目录 `data/notes/` | Markdown 笔记原始文件 | P0 |

### 3.3 工具库

| 用途 | 选型 |
|------|------|
| CLI 框架 | Click (轻量，够用) |
| 文件监听 | watchdog |
| Markdown 解析 | markdown-it-py / Python markdown |
| RSS 解析 | feedparser |
| 配置管理 | PyYAML + pydantic-settings |
| 日志 | loguru |
| 测试 | pytest + pytest-asyncio |
| 代码质量 | ruff (lint + format) |

---

## 4. 模块详细设计

### 4.1 存储层 (`brain/storage/`)

#### 4.1.1 VectorStore (`vector_store.py`)

```python
class VectorStore:
    """ChromaDB 封装"""
    collection: chromadb.Collection
    embedding_fn: Callable  # sentence-transformers

    async def add(notes: list[NoteChunk]) -> list[str]
        # 将分块嵌入后存入 Chroma

    async def search(query: str, top_k: int = 10) -> list[SearchResult]
        # 语义搜索，返回带相似度分数的结果

    async def delete(note_ids: list[str]) -> None
        # 按 ID 删除向量

    async def get_by_ids(ids: list[str]) -> list[NoteChunk]
```

#### 4.1.2 MetadataStore (`metadata.py`)

```python
class MetadataStore:
    """SQLite 元数据管理"""
    
    async def create_note(meta: NoteMetadata) -> str
    async def get_note(note_id: str) -> NoteMetadata | None
    async def update_note(note_id: str, updates: dict) -> None
    async def delete_note(note_id: str) -> None
    async def list_notes(
        tags: list[str] = None,
        date_from: datetime = None,
        date_to: datetime = None,
        limit: int = 50
    ) -> list[NoteMetadata]
    async def add_tags(note_id: str, tags: list[Tag]) -> None
    async def add_connection(conn: Connection) -> None
    async def get_connections(note_id: str) -> list[Connection]
```

**SQLite Schema:**

```sql
-- 笔记元数据表
CREATE TABLE notes (
    id TEXT PRIMARY KEY,          -- UUID
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,    -- 'markdown' | 'cli' | 'rss' | 'bookmark'
    source_path TEXT,             -- 原始文件路径
    file_hash TEXT,               -- SHA256, 用于检测文件变更
    content_preview TEXT,         -- 前 200 字符
    content_length INTEGER,
    chunk_count INTEGER,
    status TEXT DEFAULT 'active', -- 'active' | 'archived' | 'deleted'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ingested_at TEXT
);

-- 标签表
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,       -- 'topic' | 'type' | 'language' | 'difficulty'
    is_ai_generated BOOLEAN DEFAULT 0
);

-- 笔记-标签关联表
CREATE TABLE note_tags (
    note_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    confidence REAL,              -- AI 标签的置信度
    PRIMARY KEY (note_id, tag_id)
);

-- 关联表
CREATE TABLE connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT NOT NULL,
    target_note_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,  -- 'related' | 'extends' | 'contradicts' | 'references'
    strength REAL DEFAULT 0.5,
    description TEXT,             -- AI 生成的关联说明
    created_at TEXT NOT NULL,
    is_ai_generated BOOLEAN DEFAULT 0
);

-- 摄入日志表
CREATE TABLE ingestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT NOT NULL,
    event TEXT NOT NULL,          -- 'parsed' | 'chunked' | 'embedded' | 'classified' | 'connected'
    status TEXT NOT NULL,         -- 'success' | 'error'
    message TEXT,
    duration_ms INTEGER,
    timestamp TEXT NOT NULL
);
```

#### 4.1.3 GraphStore (`graph_store.py`)

```python
class GraphStore:
    """NetworkX 知识图谱 — Phase 2 引入"""
    graph: nx.Graph
    store_path: Path  # JSON 持久化

    def add_note(note_id: str, metadata: dict) -> None
    def add_connection(source: str, target: str, **attrs) -> None
    def get_neighbors(note_id: str, depth: int = 2) -> list[str]
    def find_paths(source: str, target: str) -> list[list[str]]
    def get_subgraph(topic: str) -> nx.Graph
    def save() / def load()
```

### 4.2 接入层 (`brain/ingestion/`)

#### 4.2.1 文件监听器 (`watcher.py`)

```python
class FileWatcher:
    """基于 watchdog 的 Markdown 文件监听"""
    
    def __init__(watched_dir: Path, handler: Callable)
    def start() -> None  # 后台线程
    def stop() -> None
    # 事件: on_created, on_modified, on_deleted
    # 去重: 防抖 (debounce), 文件稳定后才触发
    # 过滤: 只处理 .md 文件, 忽略隐藏文件/目录
```

#### 4.2.2 文档解析器 (`parser.py`)

```python
class DocumentParser:
    """Markdown 解析 + 元数据提取"""
    
    def parse(file_path: Path) -> ParsedDocument:
        # 提取 YAML frontmatter (title, date, tags)
        # 解析 Markdown → 纯文本 (保留结构信息)
        # 计算 file_hash
```

#### 4.2.3 文本分块器 (`chunker.py`)

```python
class SemanticChunker:
    """基于语义边界的自适应分块"""
    
    def chunk(text: str, max_chunk_size: int = 1000, overlap: int = 200) -> list[Chunk]:
        # 优先在段落/标题边界分割
        # 保持每个 chunk 的语义完整性
        # overlap 保证跨 chunk 的上下文连续性
```

### 4.3 流水线层 (`brain/ingestion/pipeline.py`)

这是 LangGraph 的核心应用——摄入流水线状态机：

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class IngestionState(TypedDict):
    """摄入流水线状态"""
    source: str                    # 来源文件路径 或 CLI 文本
    raw_content: str               # 原始文本
    parsed_doc: ParsedDocument     # 解析后的文档
    chunks: list[Chunk]            # 文本分块（此节点只做规划，不执行嵌入）
    tags: list[Tag]                # AI 分类标签
    connections: list[Connection]  # 发现的关联
    errors: list[str]              # 每步的错误收集
    current_step: str              # 当前步骤名
    status: str                    # 'running' | 'completed' | 'failed'

def build_ingestion_pipeline() -> StateGraph:
    graph = StateGraph(IngestionState)
    
    graph.add_node("parse", parse_node)         # LangChain 解析
    graph.add_node("chunk", chunk_node)         # 文本分块规划
    graph.add_node("embed", embed_node)         # 嵌入 + 存入 Chroma
    graph.add_node("classify", classify_node)   # DeepAgents 分类
    graph.add_node("connect", connect_node)     # DeepAgents 关联发现
    graph.add_node("index", index_node)         # 写入 SQLite 元数据
    
    # 定义流程
    graph.set_entry_point("parse")
    graph.add_edge("parse", "chunk")
    graph.add_edge("chunk", "embed")
    graph.add_edge("embed", "classify")
    graph.add_edge("classify", "connect")
    graph.add_edge("connect", "index")
    graph.add_edge("index", END)
    
    # 错误处理: 每个节点出错时记录错误到 state.errors，继续执行
    # classify 和 connect 可以并行执行（无依赖关系时）
    
    return graph.compile(checkpointer=SqliteSaver)
```

**错误处理策略**：非关键节点失败不阻塞流水线。解析失败→直接终止；分块失败→终止；嵌入失败→终止；分类失败→跳过，记录错误；关联发现失败→跳过，记录错误。

### 4.4 智能代理层 (`brain/agents/`)

#### 4.4.1 分类 Agent (`classifier.py`)

```python
class ClassifierAgent:
    """DeepAgents — 深度分析笔记内容，生成多维标签"""
    
    # 使用 DeepAgents 的层次化 Agent:
    #   - 子 Agent 1: 识别主题标签 (技术/商业/生活/...)
    #   - 子 Agent 2: 识别内容类型 (教程/观点/摘录/问题/...)
    #   - 子 Agent 3: 识别技术栈 (Python/JavaScript/...)
    #   - 汇总 Agent: 合并子 Agent 结果，去重，赋予置信度
    
    async def classify(note: ParsedDocument) -> list[Tag]
```

#### 4.4.2 关联发现 Agent (`connector.py`)

```python
class ConnectorAgent:
    """DeepAgents — 发现新笔记与已有笔记之间的隐性关联"""
    
    # 策略:
    #   1. 向量相似度粗筛 → Top 20 候选
    #   2. DeepAgents 深度分析 → 判断是否真正相关
    #   3. 确定关系类型: related / extends / contradicts / references
    #   4. 生成关联描述
    
    async def discover_connections(note_id: str) -> list[Connection]
```

#### 4.4.3 摘要合成 Agent (`synthesizer.py`)

```python
class SynthesizerAgent:
    """DeepAgents — 生成每日/每周知识摘要"""
    
    async def daily_digest(date: date) -> Digest
    async def weekly_report(start: date, end: date) -> WeeklyReport
```

#### 4.4.4 深度研究 Agent (`researcher.py`)

```python
class ResearcherAgent:
    """DeepAgents — 多跳推理问答"""
    
    # 流程:
    #   1. 理解问题 → 分解为子问题
    #   2. 对每个子问题执行混合检索
    #   3. 跨笔记推理 → 综合答案
    #   4. 附引用来源
    
    async def research(question: str) -> ResearchResult
```

### 4.5 服务层 (`brain/services/`)

```python
class DigestService:
    """每日摘要服务"""
    async def generate(date: date = today) -> str
    # 收集昨日摄入的笔记 → SynthesizerAgent 生成摘要

class ReviewService:
    """间隔重复服务"""
    async def get_due_items() -> list[Note]
    # 基于 SM-2 算法的复习调度
    async def record_review(note_id: str, quality: int) -> None
```

### 4.6 CLI 层 (`brain/cli/main.py`)

```
Usage: brain [OPTIONS] COMMAND [ARGS]...

Commands:
  add     快速添加一条笔记
  search  语义搜索知识库
  ask     基于知识库的深度问答
  ingest  批量摄入文件/目录
  digest  生成每日/每周知识摘要
  status  查看知识库统计信息
  config  管理配置
  watch   启动文件监听服务（后台运行）
```

---

## 5. 数据流

### 5.1 摄入流程

```
用户输入 (文件/CLI/RSS/书签)
    │
    ▼
┌──────────────────┐
│ 1. 接收 & 预处理  │  判断来源类型 → 统一解析为 ParsedDocument
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 2. 解析          │  Markdown → 纯文本 + frontmatter 元数据
└──────┬───────────┘  (LangChain: UnstructuredMarkdownLoader 或自研)
       │
       ▼
┌──────────────────┐
│ 3. 分块          │  语义分块，保留段落/标题边界
└──────┬───────────┘  (LangChain: 自定义 SemanticChunker)
       │
       ▼
┌──────────────────┐
│ 4. 嵌入 + 向量存储│  sentence-transformers → ChromaDB
└──────┬───────────┘  (LangChain: HuggingFaceEmbeddings + Chroma)
       │
       ▼
┌──────────────────┐
│ 5. 分类          │  DeepAgents → 多维标签
└──────┬───────────┘  写入 SQLite note_tags
       │
       ▼
┌──────────────────┐
│ 6. 关联发现      │  DeepAgents → 发现关联 → 写入 SQLite connections
└──────┬───────────┘  同时更新 NetworkX 图
       │
       ▼
┌──────────────────┐
│ 7. 元数据索引    │  写入 SQLite notes 表
└──────┬───────────┘
       │
       ▼
    完成 ✓
```

### 5.2 查询流程

```
用户问题
    │
    ▼
┌──────────────────┐
│ 1. 意图识别      │  搜索型? 问答型? 浏览型?
└──────┬───────────┘  (LangGraph QueryRouter)
       │
       ├─ 搜索型 ──────────┐
       │                    ▼
       │            ┌──────────────┐
       │            │ 混合检索     │  ChromaDB 向量 + SQLite 关键词
       │            │ → 排名 → 返回│
       │            └──────────────┘
       │
       ├─ 问答型 ──────────┐
       │                    ▼
       │            ┌──────────────────┐
       │            │ RAG 流水线       │
       │            │ 检索 → 重排 →    │
       │            │ DeepAgents 推理→ │
       │            │ 合成答案+引用    │
       │            └──────────────────┘
       │
       └─ 浏览型 ──────────┐
                            ▼
                    ┌──────────────┐
                    │ 按标签/时间  │
                    │ 浏览 → 返回  │
                    └──────────────┘
```

---

## 6. 配置设计 (`~/.brain/config.yaml`)

```yaml
# 存储路径
storage:
  data_dir: "~/.brain/data"
  notes_dir: "~/.brain/notes"       # 被监听的 Markdown 文件夹
  chroma_dir: "~/.brain/data/chroma"
  db_path: "~/.brain/data/metadata.db"

# LLM 配置
llm:
  provider: "anthropic"
  model: "claude-fable-5"
  api_key: "${ANTHROPIC_API_KEY}"   # 环境变量引用
  max_tokens: 4096
  temperature: 0.3

# Embedding 配置
embedding:
  provider: "local"
  model: "all-MiniLM-L6-v2"
  device: "cpu"                      # cpu | cuda

# 摄入配置
ingestion:
  watch_dir: "~/.brain/notes"        # 监听目录
  chunk_size: 1000                   # 分块大小（字符数）
  chunk_overlap: 200                 # 重叠长度
  debounce_seconds: 2                # 文件防抖时间
  
# Agent 配置
agents:
  classifier:
    enabled: true
    min_confidence: 0.6
  connector:
    enabled: true
    top_k_candidates: 20
    min_strength: 0.5
  synthesizer:
    daily_digest_time: "08:00"      # 每日摘要生成时间

# 数据源配置
sources:
  rss:
    enabled: false
    feeds: []                        # RSS 源列表
    sync_interval_minutes: 60
  bookmarks:
    enabled: false

# 日志
logging:
  level: "INFO"                      # DEBUG | INFO | WARNING | ERROR
  file: "~/.brain/logs/brain.log"
```

---

## 7. 目录结构

```
deep_agents/                        # 项目根目录
├── docs/
│   ├── requirements.md             # 需求文档（每次迭代前更新）
│   └── design.md                   # 项目设计文档（本文件，每次迭代前更新）
├── brain/                          # 主包
│   ├── __init__.py
│   ├── config.py                   # 配置加载 (pydantic-settings)
│   ├── models.py                   # 核心数据模型 (Pydantic)
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── watcher.py              # watchdog 文件监听
│   │   ├── parser.py               # Markdown 解析器
│   │   ├── sources/
│   │   │   ├── __init__.py
│   │   │   ├── markdown.py         # Markdown 文件源
│   │   │   ├── cli_input.py        # CLI 直接输入
│   │   │   ├── rss.py              # RSS 源 (P2)
│   │   │   └── bookmark.py         # 书签源 (P2)
│   │   ├── chunker.py              # 语义分块器
│   │   └── pipeline.py             # LangGraph 摄入流水线
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── vector_store.py         # ChromaDB 封装
│   │   ├── metadata.py             # SQLite 封装
│   │   └── graph_store.py          # NetworkX 图存储 (P2)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # Agent 基类
│   │   ├── classifier.py           # 分类 Agent (DeepAgents)
│   │   ├── connector.py            # 关联发现 Agent (DeepAgents)
│   │   ├── synthesizer.py          # 摘要合成 Agent (DeepAgents)
│   │   └── researcher.py           # 深度问答 Agent (DeepAgents)
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── hybrid_search.py        # 混合检索（向量+关键词）
│   │   └── query_router.py         # LangGraph 查询路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── digest.py               # 每日摘要服务
│   │   └── review.py               # 间隔重复服务 (P2)
│   └── cli/
│       ├── __init__.py
│       └── main.py                 # Click CLI 入口
├── tests/                          # 测试目录
│   ├── conftest.py                 # pytest fixtures
│   ├── test_ingestion/
│   ├── test_storage/
│   ├── test_agents/
│   └── test_retrieval/
├── data/                           # 开发用测试数据（gitignore）
│   └── sample_notes/
├── CLAUDE.md                       # Claude Code 项目指南
├── .env.example
├── .gitignore
├── pyproject.toml                  # 项目元数据 + ruff 配置
└── README.md
```

---

## 8. 错误处理策略

```
层级          | 策略
-------------|--------------------------------------------------
接入层       | 解析失败 → 记录日志，返回错误，不阻塞后续文件
流水线层     | 非关键节点失败 → 记录 state.errors，继续执行
Agent 层     | LLM 调用失败 → 指数退避重试 3 次 → 降级返回
存储层       | 写入失败 → 抛异常，由上层决定是否重试
CLI 层       | 捕获所有异常 → 友好的错误信息 + 日志路径提示
```

---

## 9. 测试策略

| 层级 | 测试类型 | 覆盖目标 |
|------|----------|----------|
| 存储层 | 单元测试 | SQLite CRUD、ChromaDB 读写（用临时目录） |
| 接入层 | 单元测试 | Markdown 解析、分块逻辑 |
| 流水线 | 集成测试 | 端到端摄入流程（用测试 LLM/Embedding mock） |
| Agent | 单元测试 | Mock LLM 响应，验证 Agent 输出格式 |
| CLI | 集成测试 | Click CliRunner 端到端 |

---

## 10. Phase 1 开发任务清单 ✅

- [x] 项目骨架搭建：`pyproject.toml`、目录结构、`.gitignore`
- [x] 数据模型定义：`brain/models.py`（NoteMetadata, Chunk, Tag, Connection）
- [x] 配置系统：`brain/config.py`（pydantic-settings + 环境变量）
- [x] 存储层：VectorStore + MetadataStore
- [x] 接入层：Markdown 解析器 + 分块器
- [x] LangGraph 摄入流水线：parse → chunk → embed → index
- [x] CLI：`add`、`search`、`ask`、`ingest`、`status` 命令
- [x] 测试：存储层测试、解析器测试
- [x] 文档：README.md 使用指南
- [x] LLM 统一入口：`brain/llm.py`（支持 DeepSeek / Anthropic 切换）
- [x] 数据路径改为项目目录下 `data/`

---

## 11. Phase 2 开发任务清单（当前进行中）

- [ ] Agent 基类：`brain/agents/base.py` — DeepAgents 配置 + 通用执行器
- [ ] 分类 Agent：`brain/agents/classifier.py` — 分析笔记生成多维标签
- [ ] 关联 Agent：`brain/agents/connector.py` — 向量粗筛 + DeepAgents 深度分析
- [ ] 流水线扩展：`classify` 和 `connect` 节点，并行执行后写入 SQLite
- [ ] CLI 扩展：`search --tag` 按标签过滤
- [ ] 测试：Agent 输出格式验证（mock LLM 响应）

### 11.1 Phase 2 核心设计

**分类 Agent 流程：**
```
笔记内容 → get_chat_model()
    │
    ▼
DeepAgents 结构化 Prompt:
  "分析以下笔记，输出 JSON：
   { topics: [{name, confidence}], type: {name, confidence}, difficulty: {name, confidence} }"
    │
    ▼
解析 JSON → Tag 列表 → 写入 SQLite note_tags
```

**关联 Agent 流程：**
```
新笔记 note_id
    │
    ▼
1. ChromaDB 向量搜索 → Top 20 候选笔记
    │
    ▼
2. DeepAgents 深度分析 Prompt:
   "新笔记: {content} / 候选笔记: {candidates} / 判断是否有意义关联"
    │
    ▼
3. 输出 [{target_note_id, relation_type, strength, description}]
    │
    ▼
4. 写入 SQLite connections
```

**流水线变化：**
```
Phase 1: parse → chunk → embed → index
Phase 2: parse → chunk → embed → classify ─┬→ index
                                      connect ─┘
                                        (并行)
```
classify 和 connect 互不依赖，在 embed 后并行执行，都完成后进入 index。

---

## 12. Phase 3 开发任务清单（当前进行中）

- [ ] DigestService：`brain/services/digest.py` — 每日摘要 + 每周趋势
- [ ] ReviewService：`brain/services/review.py` — 复习提醒
- [ ] CLI：`brain digest` / `brain digest --weekly` / `brain review`
- [ ] 测试：服务层测试

### 12.1 Phase 3 核心设计

**每日摘要流程：**
```
brain digest
    │
    ▼
1. 收集昨日摄入的笔记（SQLite）
    │
    ▼
2. 收集昨日的 AI 标签 + AI 关联
    │
    ▼
3. LangChain PromptTemplate 组装上下文
    │
    ▼
4. get_chat_model().invoke() → 结构化摘要
    │
    ▼
5. 终端输出（Markdown 格式）
```

**每周趋势流程：**
```
brain digest --weekly
    │
    ▼
1. 收集本周所有笔记 + 标签分布
    │
    ▼
2. 统计 Top 标签、新增关联数
    │
    ▼
3. LLM 分析："本周你的知识积累呈现什么趋势？"
    │
    ▼
4. 终端输出
```

**复习提醒流程：**
```
brain review
    │
    ▼
1. 查询所有 active 笔记，按 ingested_at 排序
    │
    ▼
2. 衰减公式: score = 1 / (1 + days_since_ingest / 7)
    │
    ▼
3. 返回 score < 0.3 的笔记（超过 2 周未复习）
```
