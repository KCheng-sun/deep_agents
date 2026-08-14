"""复习提醒服务。

基于摄入时间的简单衰减算法，提示用户重温旧笔记。
"""

from datetime import date, datetime

from brain.storage.metadata import MetadataStore


class ReviewService:
    """复习提醒服务 — 找出太久没回顾的笔记。"""

    def __init__(self, metadata_store: MetadataStore):
        self._store = metadata_store

    def get_due_items_sync(self, limit: int = 10) -> list[tuple]:
        return self._get_due_items(limit)

    async def get_due_items(self, limit: int = 10) -> list[tuple]:
        return self._get_due_items(limit)

    def _get_due_items(self, limit: int = 10) -> list[tuple]:
        """返回需要复习的笔记列表。

        衰减公式: freshness = 1 / (1 + days_since_ingest / decay_days)
        """
        all_notes = self._store.list_notes(limit=10000)
        today = date.today()
        decay_days = 7

        due: list[tuple] = []
        for note in all_notes:
            if not note.ingested_at:
                continue
            try:
                ingest_date = datetime.fromisoformat(note.ingested_at).date()
            except ValueError:
                continue

            days = (today - ingest_date).days
            if days < 1:
                continue

            freshness = 1.0 / (1.0 + days / decay_days)
            if freshness < 0.4:
                tags = self._store.get_note_tags(note.id)
                tag_names = [t.name for t in tags]
                due.append((note, freshness, tag_names))

        due.sort(key=lambda x: x[1])
        return due[:limit]
