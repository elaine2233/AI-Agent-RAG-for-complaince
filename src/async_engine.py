import asyncio
import time
import logging
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future
from collections import defaultdict
import uuid

import config

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    task_id: str
    status: str
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: float = 0
    started_at: float = 0
    completed_at: float = 0
    latency_ms: float = 0

    def to_dict(self):
        return asdict(self)


class AsyncTaskQueue:
    def __init__(self, max_workers: int = 4, max_queue_size: int = 100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: Dict[str, TaskResult] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._queue_size = 0
        self._total_submitted = 0
        self._total_completed = 0
        self._total_failed = 0

    def submit(self, func: Callable, *args, **kwargs) -> str:
        with self._lock:
            if self._queue_size >= self.max_queue_size:
                raise RuntimeError(f"任务队列已满({self.max_queue_size})，请稍后重试")
            self._queue_size += 1
            self._total_submitted += 1

        task_id = str(uuid.uuid4())[:12]
        task_result = TaskResult(
            task_id=task_id,
            status=TaskStatus.PENDING.value,
            created_at=time.time(),
        )
        self._tasks[task_id] = task_result

        def _run_task():
            try:
                self._tasks[task_id].status = TaskStatus.RUNNING.value
                self._tasks[task_id].started_at = time.time()

                result = func(*args, **kwargs)

                self._tasks[task_id].status = TaskStatus.COMPLETED.value
                self._tasks[task_id].result = result
                self._tasks[task_id].completed_at = time.time()
                self._tasks[task_id].latency_ms = (
                    (time.time() - self._tasks[task_id].started_at) * 1000
                )
                with self._lock:
                    self._total_completed += 1
                    self._queue_size -= 1

            except Exception as e:
                self._tasks[task_id].status = TaskStatus.FAILED.value
                self._tasks[task_id].error = str(e)
                self._tasks[task_id].completed_at = time.time()
                with self._lock:
                    self._total_failed += 1
                    self._queue_size -= 1
                logger.error(f"任务 {task_id} 执行失败: {e}")

        future = self._executor.submit(_run_task)
        self._futures[task_id] = future

        return task_id

    def get_task(self, task_id: str) -> Optional[TaskResult]:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        future = self._futures.get(task_id)
        if future and not future.done():
            cancelled = future.cancel()
            if cancelled:
                self._tasks[task_id].status = TaskStatus.CANCELLED.value
                with self._lock:
                    self._queue_size -= 1
            return cancelled
        return False

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "queue_size": self._queue_size,
                "max_queue_size": self.max_queue_size,
                "max_workers": self.max_workers,
                "total_submitted": self._total_submitted,
                "total_completed": self._total_completed,
                "total_failed": self._total_failed,
                "pending_tasks": sum(
                    1 for t in self._tasks.values()
                    if t.status in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
                ),
            }

    def cleanup(self, max_age_seconds: int = 3600):
        now = time.time()
        to_delete = []
        for task_id, task in self._tasks.items():
            if task.completed_at and (now - task.completed_at) > max_age_seconds:
                to_delete.append(task_id)
        for task_id in to_delete:
            del self._tasks[task_id]
            self._futures.pop(task_id, None)
        if to_delete:
            logger.info(f"清理了 {len(to_delete)} 个过期任务")

    def shutdown(self, wait: bool = True):
        logger.info("正在关闭任务队列...")
        self._executor.shutdown(wait=wait)
        logger.info("任务队列已关闭")


task_queue = AsyncTaskQueue(
    max_workers=config.TASK_QUEUE_MAX_WORKERS,
    max_queue_size=config.TASK_QUEUE_MAX_SIZE,
)


class ConnectionPool:
    def __init__(self, factory: Callable, max_size: int = 10, min_size: int = 2,
                 idle_timeout: float = 300, max_lifetime: float = 3600):
        self._factory = factory
        self._max_size = max_size
        self._min_size = min_size
        self._idle_timeout = idle_timeout
        self._max_lifetime = max_lifetime
        self._pool: List = []
        self._in_use: Dict[int, Any] = {}
        self._created_at: Dict[int, float] = {}
        self._last_used: Dict[int, float] = {}
        self._lock = threading.Lock()
        self._total_created = 0
        self._total_reused = 0
        self._total_discarded = 0

    def acquire(self):
        with self._lock:
            now = time.time()
            while self._pool:
                conn = self._pool.pop(0)
                conn_id = id(conn)
                if (now - self._created_at.get(conn_id, 0)) > self._max_lifetime:
                    self._total_discarded += 1
                    continue
                if (now - self._last_used.get(conn_id, 0)) > self._idle_timeout:
                    self._total_discarded += 1
                    continue
                self._in_use[conn_id] = conn
                self._last_used[conn_id] = now
                self._total_reused += 1
                return conn

            if len(self._in_use) < self._max_size:
                conn = self._factory()
                conn_id = id(conn)
                self._in_use[conn_id] = conn
                self._created_at[conn_id] = now
                self._last_used[conn_id] = now
                self._total_created += 1
                return conn

        raise RuntimeError(f"连接池已满(max={self._max_size})，请稍后重试")

    def release(self, conn):
        with self._lock:
            conn_id = id(conn)
            if conn_id in self._in_use:
                del self._in_use[conn_id]
                self._last_used[conn_id] = time.time()
                self._pool.append(conn)

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "in_use": len(self._in_use),
                "max_size": self._max_size,
                "min_size": self._min_size,
                "total_created": self._total_created,
                "total_reused": self._total_reused,
                "total_discarded": self._total_discarded,
            }


class Semaphore:
    def __init__(self, max_concurrent: int = 10):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._current = 0
        self._lock = threading.Lock()
        self._total_acquired = 0
        self._total_rejected = 0

    def acquire(self, timeout: float = 5.0) -> bool:
        acquired = self._semaphore.acquire(timeout=timeout)
        if acquired:
            with self._lock:
                self._current += 1
                self._total_acquired += 1
            return True
        else:
            with self._lock:
                self._total_rejected += 1
            return False

    def release(self):
        self._semaphore.release()
        with self._lock:
            self._current = max(0, self._current - 1)

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "current": self._current,
                "max_concurrent": self._max_concurrent,
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }


review_semaphore = Semaphore(max_concurrent=config.REVIEW_MAX_CONCURRENT)
