"""复习服务 — SM-2 间隔重复算法。

SM-2 是 Piotr Woźniak 于 1987 年提出的记忆调度算法，Anki 等间隔重复
软件的鼻祖。核心思想：
  - 每次复习后用户自评记忆质量（0-5 分）
  - 答对：复习间隔按熟练度系数指数增长（1天→6天→15天→...）
  - 答错：间隔重置回 1 天，熟练度系数降低
"""

from datetime import date, timedelta

from loguru import logger

from brain.storage.metadata import MetadataStore

# SM-2 参数
MIN_EASE_FACTOR = 1.3  # 熟练度系数下限
DEFAULT_EASE_FACTOR = 2.5
FIRST_INTERVAL_DAYS = 1  # 首次复习间隔
SECOND_INTERVAL_DAYS = 6  # 第二次复习间隔


class ReviewService:
    """SM-2 间隔重复服务。"""

    def __init__(self, metadata_store: MetadataStore):
        self._store = metadata_store

    def get_due_items_sync(self, limit: int = 50) -> list[dict]:
        """获取到期复习列表（含未进入系统的候选笔记）。

        Returns:
            [{"note_id", "title", "due_date", "review_count", "ease_factor",
              "content_preview", "is_new": bool}]
        """
        due = self._store.get_due_reviews(limit=limit)
        items = [{**d, "is_new": False} for d in due]

        # 无到期任务时，从未复习的笔记作为新卡片
        remaining = limit - len(items)
        if remaining > 0:
            for c in self._store.get_review_candidates(limit=remaining):
                items.append({**c, "is_new": True, "review_count": 0, "ease_factor": 2.5})
        return items

    async def get_due_items(self, limit: int = 50) -> list[dict]:
        return self.get_due_items_sync(limit=limit)

    def record_review_sync(self, note_id: str, quality: int) -> dict:
        """记录一次复习评分，返回新的调度状态。

        SM-2 算法:
          quality < 3（忘记）: 间隔重置 1 天，熟练度 -0.2（下限 1.3）
          quality >= 3（记住）: 间隔 = 当前间隔 × 熟练度（首次 1 天，二次 6 天）
                               熟练度按 SM-2 公式微调

        Args:
            note_id: 笔记 ID
            quality: 0-5 评分（0-2 忘记 / 3 困难 / 4 良好 / 5 简单）

        Returns:
            更新后的复习状态 dict
        """
        if not 0 <= quality <= 5:
            raise ValueError(f"评分必须在 0-5 之间，收到: {quality}")

        current = self._store.get_review(note_id) or {
            "ease_factor": DEFAULT_EASE_FACTOR,
            "interval_days": 0,
            "review_count": 0,
        }
        ease = float(current["ease_factor"])
        interval = int(current["interval_days"])
        count = int(current["review_count"])

        if quality < 3:
            # 忘记：间隔重置，熟练度下降
            new_interval = FIRST_INTERVAL_DAYS
            ease = max(MIN_EASE_FACTOR, ease - 0.2)
        else:
            # 记住：间隔增长
            if count == 0:
                new_interval = FIRST_INTERVAL_DAYS
            elif count == 1:
                new_interval = SECOND_INTERVAL_DAYS
            else:
                new_interval = round(interval * ease)
                new_interval = max(new_interval, interval + 1)

            # SM-2 熟练度更新公式
            ease += 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
            ease = max(MIN_EASE_FACTOR, ease)

        due_date = (date.today() + timedelta(days=new_interval)).isoformat()
        count += 1

        self._store.upsert_review(
            note_id=note_id,
            ease_factor=round(ease, 2),
            interval_days=new_interval,
            due_date=due_date,
            review_count=count,
            last_quality=quality,
        )
        logger.info(
            f"[review] {note_id[:8]}... 评分 {quality} → 间隔 {new_interval} 天, "
            f"熟练度 {ease:.2f}"
        )
        return {
            "note_id": note_id,
            "quality": quality,
            "interval_days": new_interval,
            "due_date": due_date,
            "ease_factor": round(ease, 2),
            "review_count": count,
        }

    async def record_review(self, note_id: str, quality: int) -> dict:
        return self.record_review_sync(note_id, quality)
