"""语义分块器。

在段落/句子边界处分割文本，保持每个分块的语义完整性，
相邻分块之间有 overlap 以保证跨块上下文连续性。
"""

import re

from loguru import logger

from brain.models import Chunk


class SemanticChunker:
    """基于语义边界的自适应文本分块。

    分块策略（优先级从高到低）：
      1. 段落边界（双换行 \\n\\n）
      2. 标题边界（以 # 开头的行）
      3. 句子边界（。！？\\n）
      4. 强制截断（达到 max_size 时在最近的分割点切开）

    小段落 (< min_size/2) 会合并到前一个块，避免碎片化。
    """

    # 句子结束标记（中文+英文）
    SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?\n])\s*")

    def __init__(self, max_chunk_size: int = 1000, overlap_size: int = 200):
        """
        Args:
            max_chunk_size: 每个分块的最大字符数
            overlap_size: 相邻分块的重叠字符数
        """
        self.max_size = max_chunk_size
        self.overlap_size = overlap_size
        self.min_size = max_chunk_size // 3  # 分块最小大小，小于此值会合并

    def chunk(self, note_id: str, text: str) -> list[Chunk]:
        """将文本分割为语义分块。

        Args:
            note_id: 所属笔记的 ID
            text: 要分割的纯文本内容

        Returns:
            按顺序排列的分块列表
        """
        if not text.strip():
            return []

        # 第一步: 按段落分割
        paragraphs = self._split_paragraphs(text)

        # 第二步: 合并/分割段落为合适大小的 chunk
        chunks = self._build_chunks(note_id, paragraphs)

        logger.debug(f"分块完成: {len(chunks)} 个块, 文本长度 {len(text)}")
        return chunks

    # ---- 内部方法 ----

    def _split_paragraphs(self, text: str) -> list[str]:
        """按段落边界（双换行）分割文本。过长的段落会进一步按句子边界分割。"""
        raw_paragraphs = text.split("\n\n")
        result = []

        for para in raw_paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self.max_size:
                result.append(para)
            else:
                # 长段落 → 按句子边界继续分割
                sub_paras = self._split_long_paragraph(para)
                result.extend(sub_paras)

        return result

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        """将超长段落按句子边界分割为多个不超过 max_size 的子段。"""
        # 找到所有句子边界
        parts = self.SENTENCE_BOUNDARY.split(paragraph)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            # 没有找到句子边界 → 强制按字符截断
            return self._force_split(paragraph)

        sub_paras = []
        current = ""

        for part in parts:
            if len(current) + len(part) <= self.max_size:
                current = (current + " " + part).strip() if current else part
            else:
                if current:
                    sub_paras.append(current)
                # 如果单个句子超过 max_size，强制截断
                if len(part) > self.max_size:
                    sub_paras.extend(self._force_split(part))
                    current = ""
                else:
                    current = part

        if current:
            sub_paras.append(current)

        return sub_paras

    @staticmethod
    def _force_split(text: str, size: int = 1000) -> list[str]:
        """终极方案：按固定大小强制截断（在空格处断开以减少断裂感）。"""
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                # 回退到最近的空格
                space_idx = text.rfind(" ", start, end)
                if space_idx > start + size // 2:
                    end = space_idx
            chunks.append(text[start:end].strip())
            start = end
        return chunks

    def _build_chunks(self, note_id: str, paragraphs: list[str]) -> list[Chunk]:
        """将段落列表组合成分块，控制大小并添加 overlap。"""
        chunks: list[Chunk] = []
        current_text = ""
        chunk_index = 0

        for para in paragraphs:
            candidate = (current_text + "\n\n" + para).strip() if current_text else para

            if len(candidate) <= self.max_size:
                current_text = candidate
            else:
                # 当前块已满 → 输出当前块并开始新块
                if current_text:
                    chunks.append(self._make_chunk(note_id, chunk_index, current_text))
                    chunk_index += 1
                    # 带 overlap 的新块：取当前块末尾 overlap_size 字符作为新块开头
                    overlap_text = current_text[-self.overlap_size :] if self.overlap_size > 0 else ""
                    current_text = (overlap_text + "\n\n" + para).strip()
                else:
                    # 单个段落超过 max_size（已由 _split_long_paragraph 处理，不应到这里）
                    # 但为了安全，强行截断
                    chunks.append(self._make_chunk(note_id, chunk_index, para[: self.max_size]))
                    chunk_index += 1
                    current_text = para[-self.overlap_size :] if self.overlap_size > 0 else ""

        # 最后一个块
        if current_text:
            chunks.append(self._make_chunk(note_id, chunk_index, current_text))

        # 合并过小的 chunk 到前一个
        chunks = self._merge_small_chunks(note_id, chunks)

        # 重新编号
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _merge_small_chunks(self, note_id: str, chunks: list[Chunk]) -> list[Chunk]:
        """将过小的 chunk 合并到前一个 chunk，避免碎片化。"""
        if len(chunks) <= 1:
            return chunks

        merged = []
        for chunk in chunks:
            if merged and len(chunk.content) < self.min_size // 2:
                # 合并到前一个
                prev = merged[-1]
                combined = prev.content + "\n\n" + chunk.content
                if len(combined) <= self.max_size * 1.2:  # 允许略微超限
                    merged[-1] = self._make_chunk(note_id, prev.index, combined)
                    continue
            merged.append(chunk)

        return merged

    @staticmethod
    def _make_chunk(note_id: str, index: int, content: str) -> Chunk:
        return Chunk(note_id=note_id, index=index, content=content, token_count=len(content))
