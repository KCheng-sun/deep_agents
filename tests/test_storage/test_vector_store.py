"""VectorStore 单元测试。"""

import pytest

from brain.models import Chunk


class TestVectorStore:
    """VectorStore 测试套件"""

    def test_add_and_count(self, vector_store):
        """测试添加分块和计数。"""
        chunks = [
            Chunk(note_id="n1", index=0, content="这是第一条笔记的内容"),
            Chunk(note_id="n1", index=1, content="这是第一条笔记的第二段"),
        ]

        ids = vector_store.add(chunks)
        assert len(ids) == 2
        assert vector_store.count() == 2

    def test_add_empty_list(self, vector_store):
        """空列表不报错。"""
        ids = vector_store.add([])
        assert ids == []

    def test_search_returns_results(self, vector_store):
        """基本搜索功能。"""
        chunks = [
            Chunk(note_id="n1", index=0, content="LangGraph 是有状态的图执行框架"),
            Chunk(note_id="n2", index=0, content="ChromaDB 是向量数据库"),
        ]
        vector_store.add(chunks)

        results = vector_store.search("图执行", top_k=2)
        assert len(results) > 0
        assert results[0].score > 0

    def test_search_empty_query(self, vector_store):
        """空查询返回空结果。"""
        results = vector_store.search("")
        assert results == []

    def test_search_respects_top_k(self, vector_store):
        """top_k 参数生效。"""
        chunks = [
            Chunk(note_id=f"n{i}", index=0, content=f"笔记 {i} 的内容: Python 编程技巧 {i}")
            for i in range(10)
        ]
        vector_store.add(chunks)

        results = vector_store.search("Python 编程", top_k=3)
        assert len(results) <= 3

    def test_delete_by_note(self, vector_store):
        """按 note_id 删除分块。"""
        chunks = [
            Chunk(note_id="keep", index=0, content="保留的笔记"),
            Chunk(note_id="delete", index=0, content="要删除的笔记"),
            Chunk(note_id="delete", index=1, content="要删除的笔记第二段"),
        ]
        vector_store.add(chunks)
        assert vector_store.count() == 3

        vector_store.delete_by_note("delete")
        assert vector_store.count() == 1

    def test_list_note_ids(self, vector_store):
        """获取所有 note_id。"""
        chunks = [
            Chunk(note_id="a", index=0, content="A"),
            Chunk(note_id="b", index=0, content="B"),
            Chunk(note_id="b", index=1, content="B 续"),
        ]
        vector_store.add(chunks)

        note_ids = vector_store.list_note_ids()
        assert set(note_ids) == {"a", "b"}


class TestConversationMemory:
    """对话记忆 collection（第二层记忆）"""

    def test_add_memory(self, vector_store):
        vector_store.add_memory(1, "s1", "user", "LangGraph checkpoint 是什么")
        # 不抛异常即通过；count 是 notes 的，这里只验证记忆可查
        results = vector_store.search_memory("checkpoint", top_k=5)
        assert len(results) == 1
        assert results[0].metadata["session_id"] == "s1"

    def test_search_memory_excludes_session(self, vector_store):
        vector_store.add_memory(1, "s1", "user", "checkpoint 机制")
        vector_store.add_memory(2, "s2", "user", "checkpoint 持久化")
        # 排除 s1 后只剩 s2 的结果
        results = vector_store.search_memory("checkpoint", top_k=10, exclude_session="s1")
        assert all(r.metadata["session_id"] == "s2" for r in results)
        assert len(results) == 1

    def test_search_memory_respects_top_k(self, vector_store):
        for i in range(5):
            vector_store.add_memory(i + 1, f"s{i}", "user", f"checkpoint 主题 {i}")
        results = vector_store.search_memory("checkpoint", top_k=3)
        assert len(results) <= 3

    def test_long_content_chunked(self, vector_store):
        """超长消息分块嵌入，不报错且可检索。"""
        long_text = "LangGraph checkpoint 机制" + "详细论述" * 100
        vector_store.add_memory(99, "s_long", "assistant", long_text)
        results = vector_store.search_memory("checkpoint", top_k=10)
        assert len(results) > 0

    def test_delete_session_memory(self, vector_store):
        vector_store.add_memory(1, "s1", "user", "checkpoint 内容")
        vector_store.add_memory(2, "s2", "user", "别的主题")
        vector_store.delete_session_memory("s1")
        # mock embedding 无真实语义，只验证被删会话的记忆不再出现
        results = vector_store.search_memory("checkpoint", top_k=10)
        assert all(r.metadata["session_id"] != "s1" for r in results)

    def test_empty_content_skipped(self, vector_store):
        vector_store.add_memory(1, "s1", "user", "   ")
        results = vector_store.search_memory("任意", top_k=5)
        assert results == []
