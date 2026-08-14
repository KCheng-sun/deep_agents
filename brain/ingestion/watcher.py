"""文件监听器 — 监听目录中的 Markdown 文件变化并自动摄入。

基于 watchdog 的 ReadDirectoryChangesWatcher（Windows）。
要点:
  - 防抖 (debounce): 编辑器保存文件会触发多次事件，等文件稳定后才摄入
  - 过滤: 只处理 .md 文件，忽略隐藏文件/目录
  - 并发安全: 摄入在线程中串行执行，避免多个文件同时摄入的竞争
"""

import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from loguru import logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class _DebouncedHandler(FileSystemEventHandler):
    """watchdog 事件处理器——带防抖。

    watchdog 在文件写入过程中会触发多次 on_created/on_modified，
    防抖策略：事件先入队，等待 debounce_seconds 无新事件后才摄入。
    """

    def __init__(self, debounce_seconds: float, callback: Callable[[Path], None]):
        self._debounce = debounce_seconds
        self._callback = callback
        # 待处理队列: path -> 最近一次事件时间
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop = False
        self._worker = threading.Thread(target=self._drain, daemon=True)

    def start_worker(self) -> None:
        self._worker.start()

    def stop_worker(self) -> None:
        self._stop = True
        self._queue.put("")  # 唤醒 worker 退出

    def on_created(self, event: FileSystemEvent) -> None:
        self._record(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._record(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._record(event)

    def _record(self, event: FileSystemEvent) -> None:
        path = event.dest_path if hasattr(event, "dest_path") and event.dest_path else event.src_path
        if not path or not path.endswith(".md"):
            return
        # 忽略隐藏文件/目录
        if any(part.startswith(".") for part in Path(path).parts):
            return
        with self._lock:
            self._pending[str(path)] = time.time()
            self._queue.put(str(path))

    def _drain(self) -> None:
        """后台线程：防抖后执行摄入回调。"""
        while not self._stop:
            try:
                path = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not path or self._stop:
                break

            # 等待防抖窗口：期间同文件的新事件会刷新 pending 时间
            deadline = self._debounce
            while deadline > 0:
                time.sleep(0.2)
                deadline -= 0.2
                with self._lock:
                    last = self._pending.get(path, 0)
                if time.time() - last >= self._debounce:
                    break

            with self._lock:
                self._pending.pop(path, None)

            try:
                self._callback(Path(path))
            except Exception as e:
                logger.warning(f"[watcher] 摄入失败 {path}: {e}")


class FileWatcher:
    """Markdown 文件监听器——文件变化自动摄入知识库。"""

    def __init__(
        self,
        watch_dir: Path,
        ingest_callback: Callable[[Path], None],
        debounce_seconds: float = 2.0,
    ):
        """
        Args:
            watch_dir: 监听目录
            ingest_callback: 摄入回调，签名为 (file_path: Path) -> None
            debounce_seconds: 文件防抖时间（秒）
        """
        self.watch_dir = watch_dir
        self._debounce = debounce_seconds
        self._handler = _DebouncedHandler(debounce_seconds, ingest_callback)
        self._observer: Observer | None = None
        # 最近摄入记录: [(timestamp, file_name, note_id), ...] 供前端展示
        self.recent_events: list[dict] = []
        self._events_lock = threading.Lock()

    def start(self) -> None:
        """启动监听（阻塞直到 stop）。"""
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self.watch_dir), recursive=True)
        self._handler.start_worker()
        self._observer.start()
        logger.info(f"[watcher] 开始监听: {self.watch_dir}")

    def stop(self) -> None:
        """停止监听。"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._handler.stop_worker()
        logger.info("[watcher] 监听已停止")

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    def record_event(self, file_name: str, note_id: str) -> None:
        """记录一次摄入结果（供前端展示）。"""
        with self._events_lock:
            self.recent_events.append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "file": file_name,
                    "note_id": note_id,
                }
            )
            # 只保留最近 20 条
            self.recent_events = self.recent_events[-20:]

    def get_recent_events(self) -> list[dict]:
        with self._events_lock:
            return list(self.recent_events)
