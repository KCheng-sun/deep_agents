# CLAUDE.md — 个人知识管家（第二大脑）

> 最后更新: 2024-08-12

---

## 项目概述

**Brain（个人知识管家）** 是一个本地优先、AI 驱动的个人知识管理系统。
核心目标：把碎片信息变成可检索、可关联、可生长的知识网络。

- **项目根目录**: `D:\projects\deep_agents`
- **主包名**: `brain`
- **Python 版本**: 3.11+
- **平台**: Windows 11 (PowerShell 5.1)

---

## 架构概要

```
CLI (Click) → Services → Agents (DeepAgents) → Pipeline (LangGraph) → Storage (ChromaDB + SQLite)
                              ↓
                        LLM (Claude API)
                        Embedding (sentence-transformers, local)
```

四个核心框架的分工：
- **LangChain**: 文档加载、文本分割、Embeddings 封装、Tool 定义
- **LangGraph**: 有状态流水线（摄入/查询）、Checkpoint 持久化
- **DeepAgents**: 多 Agent 深度推理（分类/关联/摘要/问答）
- **Claude API**: 核心推理引擎

---

## 开发原则（必须遵守）

### 文档驱动开发
1. **先更新文档，再写代码。** 任何功能变更、新增模块、架构调整，必须先更新 `docs/requirements.md` 和/或 `docs/design.md`
2. 两个文档的角色：
   - `requirements.md`: 回答"做什么"——用户场景、功能需求、非功能需求
   - `design.md`: 回答"怎么做"——架构、模块设计、数据流、技术选型
3. 每个 Phase 开始时，在需求文档中明确本 Phase 的范围
4. 每个 Phase 结束时，在 `CLAUDE.md` 中记录经验教训

### 渐进式开发
- Phase 1 只做最小可用：文件监听 + 语义搜索 + CLI
- 每个 Phase 加一层智能，不超前设计
- 代码保持简单，不为"未来可能需要"而写

### 代码风格
- 类型标注：所有公共函数必须有完整的类型标注
- 文档字符串：使用 Google style docstring
- 异步优先：IO 操作（文件、数据库、API）使用 async/await
- 错误处理：明确区分可恢复错误和致命错误，不使用裸 `except:`
- 日志：使用 `loguru`，关键路径必须记录 INFO 级别日志
- 命名：遵循 PEP 8，文件名用 snake_case，类名用 PascalCase

### 测试策略
- 存储层必须有单元测试（用临时目录，不依赖真实数据库）
- 核心流水线必须有集成测试（可以 mock LLM 调用）
- Agent 输出格式必须有单元测试（mock LLM 响应）
- CLI 命令必须有集成测试（Click CliRunner）
- 测试文件镜像源码目录结构：`tests/test_storage/test_vector_store.py`

---

## 环境与工具

### Python 环境
```powershell
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 关键依赖
```
langchain
langgraph
deepagents
chromadb
sentence-transformers
click
loguru
pydantic
pydantic-settings
pyyaml
watchdog
markdown
feedparser        # P2
networkx          # P2
```

### 开发工具
- **Lint/Format**: ruff（配置在 pyproject.toml）
- **测试**: pytest + pytest-asyncio
- **环境变量**: `.env` 文件（通过 python-dotenv 加载）

### 运行命令
```powershell
# 激活环境
.venv\Scripts\Activate.ps1

# 运行 CLI
python -m brain.cli.main --help

# 运行测试
pytest tests/ -v

# 运行 lint
ruff check brain/
```

---

## 项目约定

### Git 约定（未来启用）
- 分支命名：`phase/N-short-desc` 或 `feature/short-desc`
- Commit 信息：中文描述，格式 `[模块] 简短描述`
- 不提交：`.venv/`、`data/`、`.env`、`__pycache__/`、`*.db`

### 文件组织
- `brain/models.py` 是所有数据模型（Pydantic）的唯一定义处
- 每个模块暴露的公共接口通过 `__init__.py` 控制
- 配置项统一在 `brain/config.py` 中定义，不允许在业务代码中直接读环境变量

### 数据模型约定
- 所有 ID 使用 UUID4 字符串
- 时间戳统一使用 ISO 8601 格式字符串（SQLite 兼容）
- 置信度/强度使用 0.0 ~ 1.0 的 float

---

## 个人偏好

### 编程习惯
- 函数优先于类：纯函数能解决的不用类，有状态的才封装为类
- 异步优先：涉及 IO 的操作一律写 async 函数
- 依赖注入：不在类内部创建外部依赖（如数据库连接），通过构造函数传入
- 结构化输出：AI 调用的输出尽量用 Pydantic 模型约束，不用自由文本

### 注释风格
- 注释用中文，变量/函数名用英文
- "为什么这样做"的注释比"做了什么"更重要
- 复杂的算法逻辑必须注释解释思路

### 命名偏好
- 避免缩写：`metadata_store` 而不是 `meta_store`
- Boolean 变量用 `is_` / `has_` / `should_` 前缀
- 集合变量用复数形式：`notes`、`tags`、`connections`

---

## 注意事项

### 平台注意（Windows）
- 文件路径使用 `pathlib.Path`，不要硬编码 `/` 或 `\`
- ChromaDB 在 Windows 上需要 `chromadb` 的 SQLite 绑定正常
- watchdog 在 Windows 上使用 `ReadDirectoryChangesWatcher`
- PowerShell 不支持 `&&` 链式操作，用 `; if ($?) { ... }` 替代
- 虚拟环境的 Python 路径: `.venv\Scripts\python.exe` 而非 `bin/python`

### API 调用注意
- Anthropic API Key 通过环境变量 `ANTHROPIC_API_KEY` 传入
- 不要将 API Key 硬编码到代码或配置文件中
- 开发阶段注意 API 调用成本，避免不必要的重复调用

### 数据安全
- `data/` 目录包含用户的真实笔记，已加入 `.gitignore`
- 测试时使用临时目录 (`tempfile.TemporaryDirectory`)，不操作真实数据
- 删除操作实现软删除（`status='deleted'`），保留原始数据

---

## 迭代记录

### Phase 1 ✅ (2024-08-12 完成)
- 目标：核心 MVP — 文件摄入 + 语义搜索 + CLI 问答
- 范围：FR1-FR5
- 成果：5 个 CLI 命令可用，LangGraph 流水线 parse→chunk→embed→index
- 经验：
  - `pip install -e .` 需要 `[tool.setuptools.packages.find]` 排除 `data/` 目录
  - ChromaDB + sentence-transformers 非 daemon 线程导致进程不退，用 `os._exit(0)` 解决
  - HuggingFace 被墙，设置 `HF_ENDPOINT=https://hf-mirror.com` 或写入 `.env`
  - LLM 调用统一走 `brain/llm.py`，不直接调原生 SDK
  - 数据路径用 `Path(__file__).resolve().parent.parent` 动态定位项目根目录

### Phase 2 ✅ (2024-08-12 完成)
- 目标：DeepAgents 智能处理 — 自动分类 + 关联发现
- 范围：FR6-FR10
- 成果：classify + connect 节点集成到 LangGraph 流水线
- 经验：
  - DeepSeek 对结构化 JSON Schema 的理解需要具体示例，不能只给格式描述
  - note_id 必须在流水线第一步就确定（UUID），不能在中间改变（会导致外键不一致）
  - Agent 的 Pydantic 输出模型要简单明了，嵌套不宜过深
  - 标签搜索用模糊匹配（substring）比精确匹配实用得多

### Phase 3 ✅ (2024-08-13 完成)
- 目标：主动服务 + Web UI + 智能问答 + 会话记忆
- 范围：FR11-FR23
- 成果：FastAPI + Vue3 前后端分离；SSE 流式问答（思考/工具/答案分区）；会话管理；
  三层记忆（工作窗口/向量检索/HIL 知识沉淀）；文件监听；RSS 订阅；83 个测试全绿
- 经验：
  - BGE 模型最大 512 token，长文本 embedding 必须分块或截断（embedding 层做兜底）
  - Gradio 6 破坏性变更多（show_copy_button 移除、launch 不阻塞），换 FastAPI+Vue 更稳
  - LangGraph 流式模式下 tool_calls 分片到达（name 和 args 分开），需按 index 累积合并
  - stream_mode="messages" 会混入 ToolMessage，需按 class 名 + tool_call_id 过滤
  - Vue 3 流式更新必须用 reactive() 包装消息对象，普通对象 push 进数组后改属性不触发渲染
  - DeepAgents 的 interrupt_on + SqliteSaver checkpointer 实现 HIL：中断事件经 __interrupt__ 透出，用 Command(resume=decisions) 恢复，thread_id 必须等于 session_id
  - DeepSeek 对"条件性委派子智能体"（"如果值得就做"）经常跳过，指令要写成"必须执行"
  - SQLite 连接跨线程共享必须加锁（LangGraph 工具并行执行会并发访问）
  - MetadataStore 从 aiosqlite 改同步 sqlite3 后，测试 fixture 和全部 await 调用要同步改
  - os._exit(0) 解决 ChromaDB 非 daemon 线程卡进程退出，但测试临时目录清理用 ignore_cleanup_errors

---

## 常见问题

### 如何添加一个新的数据源？
1. 在 `brain/ingestion/sources/` 下新建文件
2. 实现 `SourceProtocol` 接口（定义在 `brain/models.py`）
3. 在 `IngestionPipeline` 中添加对应的解析节点
4. 在 `config.yaml` 的 `sources` 段添加配置
5. 更新 `requirements.md` 和 `design.md`

### 如何添加一个新的 Agent？
1. 在 `brain/agents/` 下新建文件，继承 `BaseAgent`
2. 实现 `async def execute(self, input: X) -> Y` 方法
3. 在 `brain/agents/__init__.py` 中注册
4. 在流水线或服务中调用
5. 更新 `design.md` 的 Agent 层描述

### 如何在开发中避免消耗 API 额度？
- 设置环境变量 `BRAIN_DRY_RUN=true` 使用 mock LLM 响应
- 单元测试中始终 mock LLM 调用
- 使用 `--dry-run` CLI flag 跳过 LLM 调用
