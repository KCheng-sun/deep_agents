"""Markdown 文档解析器。

解析 Markdown 文件，提取 YAML frontmatter 和纯文本内容。
同时支持纯文本输入（CLI 直接添加的场景）。
"""

import hashlib
import re
from pathlib import Path

import yaml
from loguru import logger

from brain.models import ParsedDocument


class DocumentParser:
    """Markdown 解析 + 元数据提取。

    支持的输入:
      - Markdown 文件（.md）
      - 纯文本字符串（CLI 快速输入）
    """

    # YAML frontmatter 的分隔符: 以 --- 开头和结尾
    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

    def parse_file(self, file_path: Path) -> ParsedDocument:
        """解析 Markdown 文件。

        Args:
            file_path: Markdown 文件的路径

        Returns:
            ParsedDocument: 包含标题、纯文本内容和 frontmatter
        """
        raw = file_path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(raw)

        # 标题推断优先级: frontmatter.title > 第一个 # 标题 > 文件名
        title = frontmatter.get("title", "")
        if not title:
            title = self._extract_first_heading(body)
        if not title:
            title = file_path.stem

        content = self._markdown_to_text(body)

        file_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        logger.debug(f"解析文件: {file_path.name} → 标题: {title}, {len(content)} 字符")
        return ParsedDocument(
            file_path=str(file_path),
            title=title,
            content=content,
            frontmatter=frontmatter,
            file_hash=file_hash,
        )

    def parse_text(self, text: str, title: str | None = None) -> ParsedDocument:
        """解析纯文本输入（CLI 快速输入场景）。

        Args:
            text: 原始文本内容
            title: 可选的标题，未提供时取文本第一行

        Returns:
            ParsedDocument
        """
        raw = text.strip()
        frontmatter: dict = {}

        # 标题提取：指定标题 > 第一行（多行时） > 首段截取（单行时）
        if title is None:
            lines = raw.split("\n", 1)
            first_line = lines[0].strip().lstrip("#").strip()
            if len(lines) > 1:
                # 多行：第一行是标题，其余是内容
                title = first_line
                content = lines[1].strip()
            else:
                # 单行：标题截取前 50 字，全文作为内容
                title = first_line[:50]
                content = raw
        else:
            # 指定标题：全文都是内容
            content = raw

        # Markdown 转纯文本（去链接 URL、粗体标记等）
        content = self._markdown_to_text(content)

        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        logger.debug(f"解析文本: 标题: {title}, {len(content)} 字符")
        return ParsedDocument(
            title=title or "未命名笔记",
            content=content,
            frontmatter=frontmatter,
            file_hash=file_hash,
        )

    # ---- 内部方法 ----

    def _split_frontmatter(self, raw: str) -> tuple[dict, str]:
        """分离 YAML frontmatter 和正文。"""
        match = self.FRONTMATTER_PATTERN.match(raw)
        if not match:
            return {}, raw

        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            logger.warning(f"YAML frontmatter 解析失败: {e}")
            frontmatter = {}

        body = raw[match.end() :]
        return frontmatter, body

    @staticmethod
    def _extract_first_heading(text: str) -> str:
        """从文本中提取第一个 # 标题。"""
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _markdown_to_text(text: str) -> str:
        """将 Markdown 转为纯文本（简化版，保留结构）。

        策略：
          1. 移除代码块内容中的干扰（也可以保留，取决于场景）
          2. 保留标题结构（去掉 # 符号，保留标题文字）
          3. 保留列表结构
        """
        # 去掉 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)

        # 去掉 Markdown 链接的 URL 部分，保留文字: [text](url) → text
        text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)

        # 去掉图片: ![alt](url) → [图片: alt]
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[图片: \1]", text)

        # 粗体/斜体标记去掉（保留文字）
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)

        # 行内代码标记去掉
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # 标题符号去掉
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # 列表标记保留（- / * / 1.）
        # 不需要改

        # 压缩多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
