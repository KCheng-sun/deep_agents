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
        # 知识片段 collection——HIL 沉淀片段的向量（第三层记忆）
        self._fragment_collection = self._client.get_or_create_collection(
            name="fragment_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"VectorStore 已连接: {self._persist_dir} "
            f"(collections: notes, conversation_memory, fragment_memory)"
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

    def get_note_chunks(self, note_id: str) -> list[SearchResult]:
        """按 note_id 精确取回笔记的全部正文分块。

        用 ChromaDB 的 metadata 过滤（collection.get where），
        不做语义搜索——语义搜索 ID 字符串是碰运气。

        Args:
            note_id: 笔记 ID

        Returns:
            该笔记的全部 chunks，按 chunk_index 升序
        """
        results = self._collection.get(
            where={"note_id": note_id},
            include=["documents", "metadatas"],
        )
        if not results["ids"]:
            return []

        chunks: list[SearchResult] = []
        for i, chunk_id in enumerate(results["ids"]):
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            content = results["documents"][i] if results["documents"] else ""
            chunks.append(
                SearchResult(
                    chunk_id=chunk_id,
                    note_id=note_id,
                    note_title=metadata.get("title", ""),
                    content=content,
                    score=1.0,  # 精确匹配，无相似度概念
                    metadata=metadata,
                )
            )

        # 按 chunk_index 排序，保持原文顺序
        chunks.sort(key=lambda c: c.metadata.get("chunk_index", 0))
        return chunks

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

    def search_memory(
        self,
        query: str,
        top_k: int = 5,
        current_session: str | None = None,
        session_boost: float = 0.15,
    ) -> list[SearchResult]:
        """检索与查询相关的历史对话消息（跨会话）。

        Args:
            query: 当前问题
            top_k: 返回条数
            current_session: 当前会话 ID——同会话消息加分（session_boost），
                保住超过工作窗口（10 轮）的旧消息的对话连续性
            session_boost: 同会话消息的分数加成

        Returns:
            相关历史消息列表
        """
        if not query.strip():
            return []

        # 截断查询，避免超过 BGE 512 token 限制
        query_embedding = self._embedding_fn([query[:300]])
        # 检索更多候选，加权重排后截断
        results = self._memory_collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k * 4, 40),
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        for i, chunk_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}

            distance = results["distances"][0][i]
            score = 1.0 - distance

            # 同会话加权：旧消息（超出工作窗口的）在竞争中优先
            is_current = current_session and metadata.get("session_id") == current_session
            if is_current:
                score += session_boost

            content = results["documents"][0][i] if results["documents"] else ""

            search_results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    note_id=metadata.get("session_id", ""),
                    note_title=f"{metadata.get('role', '?')}消息",
                    content=content,
                    score=round(score, 4),
                    metadata={**metadata, "is_current_session": bool(is_current)},
                )
            )

        # 加权重排后取 top_k（同会话消息因 boost 排序靠前）
        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:top_k]

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

    # ---- 知识片段（第三层记忆：向量化 + 语义检索） ----

    def add_fragment(self, fragment_id: int, title: str, content: str) -> None:
        """知识片段向量化入库。

        标题+内容拼接后整体嵌入（片段通常较短，无需分块）。

        Args:
            fragment_id: 片段在 SQLite 中的自增 ID
            title: 片段标题
            content: 片段内容
        """
        text = f"{title}。{content}".strip()
        if not text:
            return

        embedding = self._embedding_fn([text[:500]])
        # upsert：幂等，可安全用于启动回填（重复写入不会产生重复向量）
        self._fragment_collection.upsert(
            ids=[f"frag_{fragment_id}"],
            embeddings=embedding,
            documents=[text[:500]],
            metadatas=[{"fragment_id": fragment_id, "title": title}],
        )
        logger.debug(f"VectorStore: 片段向量已写入 frag_{fragment_id}")

    def delete_fragment(self, fragment_id: int) -> None:
        """删除片段的向量。"""
        self._fragment_collection.delete(ids=[f"frag_{fragment_id}"])
        logger.debug(f"VectorStore: 片段向量已删除 frag_{fragment_id}")

    def search_fragments(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """语义检索知识片段。"""
        if not query.strip():
            return []

        query_embedding = self._embedding_fn([query[:300]])
        results = self._fragment_collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, 20),
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        for i, chunk_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i]
            score = 1.0 - distance
            content = results["documents"][0][i] if results["documents"] else ""

            search_results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    note_id=str(metadata.get("fragment_id", "")),
                    note_title=metadata.get("title", "知识片段"),
                    content=content,
                    score=round(score, 4),
                    metadata=metadata,
                )
            )

        return search_results

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
