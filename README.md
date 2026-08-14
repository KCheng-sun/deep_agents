# 🧠 Brain — 个人知识管家（第二大脑）

本地优先、AI 驱动的知识管理系统。摄入碎片信息，构建可检索、可关联、可生长的知识网络。

> **Phase 1** — 核心 MVP：文件摄入 + 语义搜索 + CLI 问答

## 快速开始

### 1. 环境准备

```powershell
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 开发依赖（测试/lint）
pip install -r requirements-dev.txt
```

### 2. 配置

```powershell
# 复制配置文件
copy .env.example .env

# 编辑 .env，填入你的 Anthropic API Key
# ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

### 3. 使用

```powershell
# 快速添加一条笔记
brain add "今天读了 LangGraph 的 checkpoint 实现，核心思路是..."

# 导入 Markdown 文件
brain ingest ./notes/article.md

# 导入整个文件夹
brain ingest ./notes/

# 语义搜索
brain search "RAG 优化策略"

# 基于知识库的深度问答
brain ask "我关于 Agent 架构的思考有哪些关键结论？"

# 查看知识库状态
brain status
```

## 项目结构

```
deep_agents/
├── docs/                   # 文档
│   ├── requirements.md     # 需求文档
│   └── design.md           # 设计文档
├── brain/                  # 主包
│   ├── models.py           # 数据模型
│   ├── config.py           # 配置系统
│   ├── embedding.py        # Embedding 管理
│   ├── storage/            # 存储层 (ChromaDB + SQLite)
│   ├── ingestion/          # 接入层 (解析 + 分块 + LangGraph 流水线)
│   ├── agents/             # 智能代理层 (Phase 2)
│   ├── retrieval/          # 检索层 (Phase 2)
│   ├── services/           # 服务层 (Phase 2)
│   └── cli/                # CLI 界面
├── tests/                  # 测试
├── CLAUDE.md               # Claude Code 项目指南
├── requirements.txt        # 依赖
└── pyproject.toml          # 项目配置
```

## 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| LLM 编排 | LangChain | 文档加载、文本分割、Tool 定义 |
| 流程控制 | LangGraph | 摄入流水线状态机 |
| 多 Agent | DeepAgents | 分类/关联/摘要 Agent（Phase 2） |
| LLM | Claude API | 问答推理 |
| 向量存储 | ChromaDB | 语义检索 |
| 元数据 | SQLite | 笔记/标签/关联管理 |
| Embedding | sentence-transformers | 本地向量化 |

## 开发

```powershell
# 运行测试
pytest tests/ -v

# 代码检查
ruff check brain/

# 格式化
ruff format brain/
```

## 迭代计划

- **Phase 1（当前）**: 文件摄入 + 语义搜索 + CLI 问答
- **Phase 2**: DeepAgents 自动分类 + 关联发现
- **Phase 3**: 每日摘要 + 间隔重复 + 主动推送

详见 [需求文档](docs/requirements.md) 和 [设计文档](docs/design.md)。

## License

MIT
