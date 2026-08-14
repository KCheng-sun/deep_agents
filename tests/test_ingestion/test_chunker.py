"""SemanticChunker 单元测试。"""

import pytest

from brain.ingestion.chunker import SemanticChunker
from brain.models import Chunk


class TestSemanticChunker:
    """SemanticChunker 测试套件"""

    @pytest.fixture
    def chunker(self):
        return SemanticChunker(max_chunk_size=500, overlap_size=100)

    def test_empty_text(self, chunker):
        """空文本返回空列表。"""
        chunks = chunker.chunk("note_1", "")
        assert chunks == []

    def test_whitespace_only(self, chunker):
        """纯空白文本返回空列表。"""
        chunks = chunker.chunk("note_1", "   \n\n  \n  ")
        assert chunks == []

    def test_single_short_paragraph(self, chunker):
        """短文本产生一个分块。"""
        text = "这是一段很短的笔记内容。"
        chunks = chunker.chunk("note_1", text)

        assert len(chunks) == 1
        assert chunks[0].note_id == "note_1"
        assert chunks[0].index == 0
        assert "短" in chunks[0].content

    def test_multiple_paragraphs(self, chunker):
        """多个段落被正确地分到不同块中。"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = chunker.chunk("note_1", text)

        assert len(chunks) >= 1

    def test_chunk_indices_sequential(self, chunker):
        """分块序号连续递增。"""
        # 生成足够长的文本以确保多个分块
        paragraphs = []
        for i in range(20):
            paragraphs.append(f"第 {i} 段: " + "这是一个测试段落。 " * 30)
        text = "\n\n".join(paragraphs)

        chunks = chunker.chunk("note_1", text)
        assert len(chunks) > 1

        indices = [c.index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_all_chunks_same_note_id(self, chunker):
        """所有分块属于同一个 note_id。"""
        paragraphs = []
        for i in range(15):
            paragraphs.append(f"段落 {i}: " + "测试内容。 " * 30)
        text = "\n\n".join(paragraphs)

        chunks = chunker.chunk("my_note_id", text)
        assert len(chunks) > 1
        assert all(c.note_id == "my_note_id" for c in chunks)

    def test_respects_max_size(self, chunker):
        """每个分块不超过 max_chunk_size * 1.2（合并小块的允许上限）。"""
        # 生成长段落来测试
        long_para = "这是一段非常长的内容。" * 200  # ~2000 字符
        chunks = chunker.chunk("note_1", long_para)

        for chunk in chunks:
            # _merge_small_chunks 允许合并到 max_size * 1.2
            assert len(chunk.content) <= 600  # 500 * 1.2

    def test_chunk_content_type(self, chunker):
        """返回的是 Chunk 类型。"""
        text = "测试内容。"
        chunks = chunker.chunk("note_1", text)

        assert isinstance(chunks[0], Chunk)
        assert hasattr(chunks[0], "id")
        assert hasattr(chunks[0], "content")
        assert hasattr(chunks[0], "note_id")
        assert hasattr(chunks[0], "index")

    def test_large_document(self, chunker):
        """大文档不会报错。"""
        # 模拟一篇长文章
        sections = []
        for i in range(10):
            section = f"## 第 {i} 章\n\n"
            for j in range(20):
                section += f"第 {j} 段: 这是一段关于某个主题的详细讨论。深度学习模型在自然语言处理领域取得了显著进展。" * 5 + "\n\n"
            sections.append(section)
        text = "\n".join(sections)

        # 不抛异常
        chunks = chunker.chunk("large_note", text)
        assert len(chunks) > 0
