"""DeepAgents 官方中间件系统 — 基于 AgentMiddleware 实现。

AgentMiddleware 提供 6 个钩子：
  - before_agent / after_agent     → Agent 生命周期的前后
  - wrap_model_call / awrap_model_call → 拦截每次 LLM 调用
  - wrap_tool_call / awrap_tool_call   → 拦截每次工具执行

用法（通过 create_deep_agent 的 middleware 参数注入）:
    agent = create_deep_agent(
        model=llm,
        tools=[...],
        middleware=[LoggingMiddleware(), TimeoutMiddleware(30.0)],
    )
"""

import time
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.errors import GraphInterrupt
from loguru import logger


class LoggingMiddleware(AgentMiddleware):
    """日志中间件 — 拦截每次 Agent 的 LLM 调用和工具执行并记录。

    通过 wrap_model_call 记录 LLM 推理步骤。
    通过 wrap_tool_call 记录每次工具调用的入参、返回值、耗时。
    同时利用 before_agent / after_agent 记录 Agent 启动和停止。

    用法:
        create_deep_agent(..., middleware=[LoggingMiddleware()])
    """

    def __init__(self, agent_name: str = "agent"):
        self._agent_name = agent_name
        self._step_count = 0
        self._agent_start_time: float | None = None

    # ---- Agent 生命周期 ----

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._agent_start_time = time.perf_counter()
        self._step_count = 0
        logger.info(f"[{self._agent_name}] 🚀 Agent 启动")
        return None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if self._agent_start_time:
            elapsed = time.perf_counter() - self._agent_start_time
            logger.info(f"[{self._agent_name}] 🏁 Agent 完成 ({elapsed:.1f}s, {self._step_count} 步)")
        return None

    # ---- LLM 调用拦截 ----

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        self._step_count += 1

        # 提取最后一条用户消息作为摘要
        messages = request.messages
        last_msg = messages[-1].content if messages else ""
        preview = str(last_msg)[:120].replace("\n", " ")
        if len(str(last_msg)) > 120:
            preview += "..."

        logger.info(f"[{self._agent_name}] 💭 LLM #{self._step_count}: {preview}")

        t0 = time.perf_counter()
        try:
            response = handler(request)
            elapsed = (time.perf_counter() - t0) * 1000

            # 检查是否有工具调用
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_names = [tc.get("name", "?") for tc in response.tool_calls]
                logger.info(
                    f"[{self._agent_name}] 🔨 LLM #{self._step_count} → "
                    f"选择工具: {', '.join(tool_names)} ({elapsed:.0f}ms)"
                )
            else:
                logger.info(
                    f"[{self._agent_name}] 📝 LLM #{self._step_count} → "
                    f"输出文本 ({elapsed:.0f}ms)"
                )

            return response
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.error(f"[{self._agent_name}] ❌ LLM #{self._step_count} 失败 ({elapsed:.0f}ms): {e}")
            raise

    # ---- 工具调用拦截 ----

    def wrap_tool_call(self, request, handler):
        tool_name = request.tool_call.get("name", "unknown") if hasattr(request, "tool_call") else "unknown"

        # 提取工具参数
        args = request.tool_call.get("args", {}) if hasattr(request, "tool_call") else {}
        args_parts = [f"{k}={str(v)[:80]}" for k, v in args.items()]
        args_str = ", ".join(args_parts) if args_parts else "—"

        logger.info(f"[{self._agent_name}] 🔧 {tool_name}({args_str})")

        t0 = time.perf_counter()
        try:
            result = handler(request)
            elapsed = (time.perf_counter() - t0) * 1000

            result_content = getattr(result, "content", str(result)) if result else ""
            result_len = len(result_content) if result_content else 0

            logger.info(
                f"[{self._agent_name}] ✅ {tool_name} → "
                f"{result_len} 字符 ({elapsed:.0f}ms)"
            )
            return result
        # HIL 中断不是错误：LangGraph 抛出 GraphInterrupt 挂起流程，
        # 等待用户审批后经 resume 恢复，故单独记录为"等待审批"而非"失败"
        except GraphInterrupt:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                f"[{self._agent_name}] ⏸ {tool_name} 等待用户审批 ({elapsed:.0f}ms)"
            )
            raise
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.error(
                f"[{self._agent_name}] ❌ {tool_name} 失败 ({elapsed:.0f}ms): {e}"
            )
            raise
