"""Embedding 函数工厂。

支持 provider 切换:
  - siliconflow → 硅基流动 API（BGE 模型，国内顺畅，推荐）
  - local → 本地 sentence-transformers

用法:
    from brain.embedding import get_embedding_fn
    embed = get_embedding_fn()
    vectors = embed(["文本1", "文本2"])
"""

import os
from collections.abc import Callable
from functools import lru_cache

from loguru import logger

from brain.config import get_config

# embedding 函数签名: (texts: list[str]) -> list[list[float]]
EmbeddingFn = Callable[[list[str]], list[list[float]]]


@lru_cache(maxsize=1)
def get_embedding_fn() -> EmbeddingFn:
    """获取全局 embedding 函数（单例，懒加载）。"""
    cfg = get_config()
    provider = cfg.embedding.provider

    if provider == "siliconflow":
        return _init_siliconflow(cfg)
    elif provider == "local":
        return _init_local(cfg)
    else:
        raise ValueError(f"不支持的 embedding provider: {provider}。可选: siliconflow, local")


def _init_siliconflow(cfg) -> EmbeddingFn:
    """硅基流动 API — OpenAI 兼容协议。

    模型: BAAI/bge-large-zh-v1.5（1024 维，中文优化）
    """
    from openai import OpenAI

    api_key = cfg.embedding.api_key or os.environ.get("SILICONFLOW_API_KEY", "")
    model_name = cfg.embedding.model_name
    base_url = cfg.embedding.base_url

    logger.info(f"初始化 SiliconFlow Embedding: {model_name}")

    client = OpenAI(api_key=api_key, base_url=base_url)

    def _embed(texts: list[str]) -> list[list[float]]:
        # BGE 模型最大 512 token（中文约 1 字 1 token）：截断防 API 400
        safe_texts = [t[:500] for t in texts]
        response = client.embeddings.create(model=model_name, input=safe_texts)
        return [d.embedding for d in response.data]

    return _embed


def _init_local(cfg) -> EmbeddingFn:
    """本地 sentence-transformers 模型。"""
    model_name = cfg.embedding.model_name
    device = cfg.embedding.device

    logger.info(f"加载本地 Embedding 模型: {model_name} (device={device})")

    # 抑制 transformers / huggingface 的日志噪音
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    import transformers

    transformers.logging.set_verbosity_error()

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device=device)

    def _embed(texts: list[str]) -> list[list[float]]:
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    return _embed
