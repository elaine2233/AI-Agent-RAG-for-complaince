import time
import logging
import threading
from typing import Callable, Any, Optional, TypeVar, Dict
from dataclasses import dataclass
from enum import Enum
from functools import wraps

import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    success_threshold: int = 3


class CircuitBreaker:
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0
        self._lock = threading.Lock()

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            elif self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.config.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    self.success_count = 0
                    logger.info(f"熔断器 [{self.name}] 进入半开状态")
                    return True
                return False
            elif self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.config.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False
        return False

    def record_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    logger.info(f"熔断器 [{self.name}] 恢复为关闭状态")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                logger.warning(f"熔断器 [{self.name}] 半开状态下失败，重新打开")
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"熔断器 [{self.name}] 达到失败阈值，打开熔断")

    def get_state(self) -> Dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
        }


class RetryPolicy:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (Exception,),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def get_delay(self, attempt: int) -> float:
        import random
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay,
        )
        if self.jitter:
            delay *= (0.5 + random.random() * 0.5)
        return delay


def with_retry(
    policy: RetryPolicy = None,
    circuit_breaker: CircuitBreaker = None,
    fallback: Callable = None,
    timeout: float = 60.0,
):
    policy = policy or RetryPolicy()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器打开，执行降级: {circuit_breaker.name}")
                if fallback:
                    return fallback(*args, **kwargs)
                raise RuntimeError(f"服务不可用: {circuit_breaker.name} 熔断已打开")

            last_exception = None
            for attempt in range(policy.max_retries + 1):
                try:
                    start_time = time.time()

                    result = func(*args, **kwargs)

                    elapsed = time.time() - start_time
                    if elapsed > timeout:
                        logger.warning(f"调用超时: {func.__name__}, elapsed={elapsed:.2f}s")

                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result

                except policy.retryable_exceptions as e:
                    last_exception = e
                    if attempt < policy.max_retries:
                        delay = policy.get_delay(attempt)
                        logger.warning(
                            f"调用失败(第{attempt + 1}次), {delay:.1f}s后重试: "
                            f"{func.__name__}, error={str(e)[:100]}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"调用最终失败(共{policy.max_retries + 1}次): "
                            f"{func.__name__}, error={str(e)[:200]}"
                        )

            if circuit_breaker:
                circuit_breaker.record_failure()

            if fallback:
                logger.info(f"执行降级函数: {func.__name__}")
                return fallback(*args, **kwargs)

            raise last_exception or RuntimeError("未知错误")

        return wrapper
    return decorator


class ResultCache:
    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any):
        with self._lock:
            if len(self._cache) >= self.max_size:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, time.time())

    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0,
        }


llm_circuit_breaker = CircuitBreaker("llm_api", CircuitBreakerConfig(
    failure_threshold=config.LLM_CIRCUIT_FAILURE_THRESHOLD,
    recovery_timeout=config.LLM_CIRCUIT_RECOVERY_TIMEOUT,
))
embedding_circuit_breaker = CircuitBreaker("embedding_api", CircuitBreakerConfig(
    failure_threshold=config.EMBEDDING_CIRCUIT_FAILURE_THRESHOLD,
    recovery_timeout=config.EMBEDDING_CIRCUIT_RECOVERY_TIMEOUT,
))
review_cache = ResultCache(max_size=config.CACHE_MAX_SIZE, ttl_seconds=config.CACHE_TTL_SECONDS)
