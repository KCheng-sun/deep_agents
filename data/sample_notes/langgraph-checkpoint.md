---
title: LangGraph Checkpoint 机制深入理解
date: 2024-08-10
tags: [langgraph, agent, checkpoint, state-management]
---

# LangGraph Checkpoint 机制深入理解

## 概述

LangGraph 的 checkpoint 机制是整个框架的核心特性之一，它让 Agent 的状态能够在图执行的每一步被持久化，从而支持：
- 执行中断与恢复
- 时间旅行调试
- Human-in-the-Loop 交互
- 状态分支与回溯

## 核心概念

### 1. Checkpointer 接口

LangGraph 提供了 `BaseCheckpointSaver` 抽象基类，内置实现包括：
- `MemorySaver`: 内存中存储，用于开发调试
- `SqliteSaver`: SQLite 持久化，用于生产环境

### 2. Checkpoint 的存储结构

每个 checkpoint 记录包含：
```python
{
    "v": 1,                    # 版本号
    "id": "checkpoint_id",     # 唯一 ID
    "ts": "2024-08-10T...",   # 时间戳
    "channel_values": {...},   # 各通道的状态快照
    "channel_versions": {...}, # 各通道的版本号
    "versions_seen": {...},    # 节点间依赖追踪
}
```

### 3. 中断与恢复

当图执行到 `interrupt` 节点时会暂停，等待外部输入。这是 Human-in-the-Loop 的基础。

```python
from langgraph.checkpoint import MemorySaver
from langgraph.graph import StateGraph

graph = StateGraph(MyState)
# ... 添加节点和边 ...
app = graph.compile(checkpointer=MemorySaver())

# 执行到 interrupt 节点时暂停
config = {"configurable": {"thread_id": "1"}}
for event in app.stream(input, config):
    print(event)
```

## 最佳实践

1. **选择合适的 Checkpointer**: 开发用 MemorySaver，生产用 SqliteSaver
2. **thread_id 管理**: 每个对话/会话分配独立的 thread_id
3. **不要手动修改 checkpoint**: 用 `graph.update_state()` 来修正状态
4. **清理策略**: 定期清理旧的 checkpoint 避免存储膨胀

## 与 DeepAgents 的配合

DeepAgents 使用了 LangGraph 的 checkpoint 机制来实现层次化的 Agent 状态管理。每个子 Agent 的执行可以被父 Agent 中断和恢复。

## 总结

Checkpoint 机制让 LangGraph 从一个简单的"图执行器"升级为"有状态的 Agent 运行时"。理解它的工作原理对于构建生产级 Agent 系统至关重要。
