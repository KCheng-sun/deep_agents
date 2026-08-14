"""RSS 源适配器 — 拉取订阅源并摄入知识库。

职责:
  1. feedparser 拉取并解析 RSS/Atom
  2. 条目去重（rss_entries 表按 entry_id 判重）
  3. 通过 IngestionPipeline 把新条目摄入知识库（走完整流水线: 解析→分块→嵌入→分类→关联）
"""


import feedparser
from loguru import logger

from brain.ingestion.pipeline import IngestionPipeline
from brain.storage.metadata import MetadataStore


class RssSource:
    """RSS 订阅源——定时拉取文章并自动摄入。"""

    def __init__(self, pipeline: IngestionPipeline, metadata_store: MetadataStore):
        self._pipeline = pipeline
        self._store = metadata_store

    def add_feed(self, url: str) -> int:
        """添加订阅源。返回 feed_id。"""
        feed_id = self._store.add_rss_feed(url)
        logger.info(f"[rss] 已添加订阅源: {url}")
        return feed_id

    def fetch_all(self, limit_per_feed: int = 10) -> dict:
        """拉取所有订阅源的新条目。

        Returns:
            {"feeds_checked": n, "new_entries": n, "errors": [...]}
        """
        feeds = self._store.list_rss_feeds()
        summary = {"feeds_checked": len(feeds), "new_entries": 0, "errors": []}

        for feed in feeds:
            try:
                count = self.fetch_feed(feed["id"], limit=limit_per_feed)
                summary["new_entries"] += count
            except Exception as e:
                logger.warning(f"[rss] 源 {feed['url']} 拉取失败: {e}")
                summary["errors"].append(f"{feed['url']}: {e}")

        return summary

    def fetch_feed(self, feed_id: int, limit: int = 10) -> int:
        """拉取单个订阅源的新条目并摄入。返回新条目数。"""
        feed = self._store.get_rss_feed(feed_id)
        if feed is None:
            raise ValueError(f"订阅源不存在: {feed_id}")

        logger.info(f"[rss] 拉取: {feed['url']}")
        parsed = feedparser.parse(feed["url"])

        if parsed.bozo and not parsed.entries:
            raise ValueError(f"解析失败: {parsed.bozo_exception}")

        feed_title = parsed.feed.get("title", "")[:100]
        new_count = 0

        for entry in parsed.entries[:limit]:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id:
                continue

            # 去重：已处理过的条目跳过
            if self._store.rss_entry_exists(feed_id, entry_id):
                continue

            title = entry.get("title", "无标题").strip()
            link = entry.get("link", "")
            published = entry.get("published", "") or entry.get("updated", "")

            # 构建笔记文本
            summary_text = entry.get("summary", "")
            # 去掉 HTML 标签（简单清理）
            import re

            summary_text = re.sub(r"<[^>]+>", "", summary_text).strip()

            content_parts = [title]
            if summary_text:
                content_parts.append(summary_text)
            if link:
                content_parts.append(f"原文链接: {link}")
            content = "\n\n".join(content_parts)

            # 摄入知识库（走完整流水线）
            try:
                note_id = self._pipeline.ingest_text_sync(
                    content,
                    title=f"[RSS] {title[:50]}",
                )
                self._store.add_rss_entry(
                    feed_id, entry_id, title, link, published, note_id
                )
                new_count += 1
                logger.info(f"[rss] ✅ {title[:40]} → {note_id}")
            except Exception as e:
                logger.warning(f"[rss] 条目摄入失败 {title[:40]}: {e}")

        self._store.update_rss_feed_after_fetch(feed_id, feed_title, new_count)
        return new_count

    def list_feeds(self) -> list[dict]:
        return self._store.list_rss_feeds()

    def remove_feed(self, feed_id: int) -> bool:
        return self._store.delete_rss_feed(feed_id)
