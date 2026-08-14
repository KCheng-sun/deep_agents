"""ChromaDB 向量存储封装。

负责笔记分块的向量嵌入和语义检索。
ChromaDB 的 Python 客户端是同步的，所以本模块不强行异步包装。
"""

import os
from pathlib import Path

# 抑制 ChromaDB 的日志噪音（必须在 import chromadb 之前设置）
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("CHROMA_SERVER_NOFILE", "65536")

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from brain.models import Chunk, SearchResult


class VectorStore:
    """ChromaDB 封装——管理笔记分块的向量存储和语义检索。"""

    def __init__(self, persist_dir: Path, embedding_fn):
        """
        Args:
            persist_dir: ChromaDB 持久化目录
            embedding_fn: embedding 函数，签名为 (texts: list[str]) -> list[list[float]]
        """
        self._persist_dir = str(persist_dir)
        self._embedding_fn = embedding_fn

        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="notes",
            metadata={"hnsw:space": "cosine"},
        )
        # 对话记忆 collection——存储会话消息的向量（第二层记忆）
        self._memory_collection = self._client.get_or_create_collection(
            name="conversation_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"VectorStore 已连接: {self._persist_dir} "
            f"(collections: notes, conversation_memory)"
        )

    # ---- 写入 ----

    def add(self, chunks: list[Chunk]) -> list[str]:
        """将分块嵌入后存入 ChromaDB。

        Args:
            chunks: 要存储的文本分块列表

        Returns:
            成功存储的 chunk ID 列表
        """
        if not chunks:
            return []

        texts = [chunk.content for chunk in chunks]
        ids = [chunk.id for chunk in chunks]
        metadatas = [
            {
                "note_id": chunk.note_id,
                "chunk_index": chunk.index,
                **chunk.metadata,
            }
            for chunk in chunks
        ]

        embeddings = self._embedding_fn(texts)

        self._collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

        logger.info(f"VectorStore: 已存储 {len(chunks)} 个分块")
        return ids

    # ---- 检索 ----

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """语义搜索——返回与查询最相关的分块。

        Args:
            query: 搜索查询文本
            top_k: 返回结果数量

        Returns:
            按相似度降序排列的搜索结果列表
        """
        if not query.strip():
            return []

        # 截断查询，避免超过 BGE 512 token 限制
        query_embedding = self._embedding_fn([query[:300]])

        results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        for i, chunk_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            # ChromaDB cosine distance → similarity: 1 - distance
            score = 1.0 - distance

            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            note_id = metadata.get("note_id", "")
            content = results["documents"][0][i] if results["documents"] else ""

            search_results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    note_id=note_id,
                    note_title=metadata.get("title", "无标题"),
                    content=content,
                    score=round(score, 4),
                    metadata=metadata,
                )
            )

        return search_results

    # ---- 删除 ----

    def delete_by_note(self, note_id: str) -> None:
        """删除某条笔记的所有分块。

        Args:
            note_id: 要删除的笔记 ID
        """
        # ChromaDB 按 metadata 过滤删除
        results = self._collection.get(
            where={"note_id": note_id},
            include=["metadatas"],
        )
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
            logger.info(f"VectorStore: 已删除笔记 {note_id} 的 {len(ids_to_delete)} 个分块")

    # ---- 对话记忆（第二层记忆：历史消息向量检索） ----

    def add_memory(self, message_id: int, session_id: str, role: str, content: str) -> None:
        """把一条对话消息写入记忆 collection。

        BGE 模型最大 512 token，超长消息按 300 字符分块嵌入，
        每块一个独立向量（id 用 msg_{id}_{chunk_idx} 区分）。

        Args:
            message_id: 消息在 SQLite 中的自增 ID
            session_id: 所属会话 ID
            role: 'user' | 'assistant'
            content: 消息内容
        """
        if not content.strip():
            return

        # 分块：避免超过 BGE 的 512 token 限制
        chunks: list[str] = []
        remaining = content
        while len(remaining) > 300:
            chunks.append(remaining[:300])
            remaining = remaining[300:]
        if remaining:
            chunks.append(remaining)

        for i, chunk_text in enumerate(chunks):
            embedding = self._embedding_fn([chunk_text])
            self._memory_collection.add(
                ids=[f"msg_{message_id}_{i}"],
                embeddings=embedding,
                documents=[chunk_text],
                metadatas=[
                    {
                        "message_id": message_id,
                        "session_id": session_id,
                        "role": role,
                        "chunk_index": i,
                    }
                ],
            )

        logger.debug(
            f"VectorStore: 记忆已写入 msg_{message_id} ({role}, {len(chunks)} 块)"
        )

    def search_memory(self, query: str, top_k: int = 5, exclude_session: str | None = None) -> list[SearchResult]:
        """检索与查询相关的历史对话消息（跨会话）。

        Args:
            query: 当前问题
            top_k: 返回条数
            exclude_session: 排除指定会话（默认排除当前会话，避免"自己查自己"）

        Returns:
            相关历史消息列表
        """
        if not query.strip():
            return []

        # 截断查询，避免超过 BGE 512 token 限制
        query_embedding = self._embedding_fn([query[:300]])
        # 检索更多候选，过滤后再截断
        results = self._memory_collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k * 3, 30),
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        for i, chunk_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            # 排除当前会话的消息（最近窗口已覆盖）
            if exclude_session and metadata.get("session_id") == exclude_session:
                continue

            distance = results["distances"][0][i]
            score = 1.0 - distance
            content = results["documents"][0][i] if results["documents"] else ""

            search_results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    note_id=metadata.get("session_id", ""),
                    note_title=f"{metadata.get('role', '?')}消息",
                    content=content,
                    score=round(score, 4),
                    metadata=metadata,
                )
            )

            if len(search_results) >= top_k:
                break

        return search_results

    def delete_session_memory(self, session_id: str) -> None:
        """删除某会话的全部记忆向量。"""
        results = self._memory_collection.get(
            where={"session_id": session_id},
            include=["metadatas"],
        )
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            self._memory_collection.delete(ids=ids_to_delete)
            logger.info(
                f"VectorStore: 已删除会话 {session_id} 的 {len(ids_to_delete)} 条记忆"
            )

    # ---- 统计 ----

    def count(self) -> int:
        """返回存储的总分块数。"""
        return self._collection.count()

    def list_note_ids(self) -> list[str]:
        """返回所有 note_id 的去重列表。"""
        results = self._collection.get(include=["metadatas"])
        if not results["metadatas"]:
            return []
        note_ids = {m["note_id"] for m in results["metadatas"] if "note_id" in m}
        return list(note_ids)
