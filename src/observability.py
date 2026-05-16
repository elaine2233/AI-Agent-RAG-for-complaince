import time
import logging
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from collections import defaultdict

import config

logger = logging.getLogger(__name__)


try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client 未安装，metrics 功能不可用")


if PROMETHEUS_AVAILABLE:
    REVIEW_TOTAL = Counter(
        "review_requests_total",
        "Total review requests",
        ["status", "violation_type", "review_mode"],
    )
    REVIEW_DURATION = Histogram(
        "review_duration_seconds",
        "Review duration in seconds",
        ["review_mode"],
        buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    )
    REVIEW_IN_PROGRESS = Gauge(
        "review_in_progress",
        "Number of reviews currently in progress",
    )
    RAG_RETRIEVE_DURATION = Histogram(
        "rag_retrieve_duration_seconds",
        "RAG retrieval duration",
        ["mode"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
    )
    RAG_RETRIEVE_RESULTS = Histogram(
        "rag_retrieve_results_count",
        "Number of results returned by RAG",
        buckets=[0, 1, 3, 5, 10, 20],
    )
    LLM_CALL_TOTAL = Counter(
        "llm_call_total",
        "Total LLM API calls",
        ["status"],
    )
    LLM_CALL_DURATION = Histogram(
        "llm_call_duration_seconds",
        "LLM API call duration",
        buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )
    CACHE_HITS = Counter(
        "cache_hits_total",
        "Total cache hits",
        ["cache_type"],
    )
    CACHE_MISSES = Counter(
        "cache_misses_total",
        "Total cache misses",
        ["cache_type"],
    )
    SECURITY_BLOCKED = Counter(
        "security_blocked_total",
        "Total requests blocked by security",
        ["reason"],
    )
    CIRCUIT_BREAKER_STATE = Gauge(
        "circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 0.5=half_open)",
        ["name"],
    )
    DB_QUERY_DURATION = Histogram(
        "db_query_duration_seconds",
        "Database query duration",
        ["operation"],
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
    )
    TASK_QUEUE_SIZE = Gauge(
        "task_queue_size",
        "Current task queue size",
    )
    APP_INFO = Info(
        "app",
        "Application information",
    )
else:
    REVIEW_TOTAL = None
    REVIEW_DURATION = None
    REVIEW_IN_PROGRESS = None
    RAG_RETRIEVE_DURATION = None
    RAG_RETRIEVE_RESULTS = None
    LLM_CALL_TOTAL = None
    LLM_CALL_DURATION = None
    CACHE_HITS = None
    CACHE_MISSES = None
    SECURITY_BLOCKED = None
    CIRCUIT_BREAKER_STATE = None
    DB_QUERY_DURATION = None
    TASK_QUEUE_SIZE = None
    APP_INFO = None


def metrics_middleware(func: Callable) -> Callable:
    def wrapper(*args, **kwargs):
        if not PROMETHEUS_AVAILABLE:
            return func(*args, **kwargs)

        if REVIEW_IN_PROGRESS:
            REVIEW_IN_PROGRESS.inc()

        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            status = result.compliant if hasattr(result, 'compliant') else 'unknown'
            mode = 'rule' if hasattr(result, 'review_mode') else 'unknown'

            if REVIEW_TOTAL:
                REVIEW_TOTAL.labels(status=status, violation_type=getattr(result, 'violation_type', ''), review_mode=mode).inc()
            if REVIEW_DURATION:
                REVIEW_DURATION.labels(review_mode=mode).observe(time.time() - start_time)

            return result

        except Exception as e:
            if REVIEW_TOTAL:
                REVIEW_TOTAL.labels(status='error', violation_type='', review_mode='unknown').inc()
            raise

        finally:
            if REVIEW_IN_PROGRESS:
                REVIEW_IN_PROGRESS.dec()

    return wrapper


@contextmanager
def trace_operation(operation: str, attributes: Dict = None):
    start_time = time.time()
    span = TraceSpan(
        operation=operation,
        start_time=start_time,
        attributes=attributes or {},
    )
    try:
        yield span
    except Exception as e:
        span.set_error(str(e))
        raise
    finally:
        span.end_time = time.time()
        span.duration_ms = (span.end_time - span.start_time) * 1000

        if span.duration_ms > 1000:
            logger.warning(f"慢操作: {operation}, duration={span.duration_ms:.0f}ms, attrs={attributes}")

        if operation.startswith("rag") and PROMETHEUS_AVAILABLE and RAG_RETRIEVE_DURATION:
            RAG_RETRIEVE_DURATION.labels(mode=attributes.get("mode", "unknown") if attributes else "unknown").observe(
                span.duration_ms / 1000
            )
        elif operation.startswith("llm") and PROMETHEUS_AVAILABLE and LLM_CALL_DURATION:
            LLM_CALL_DURATION.observe(span.duration_ms / 1000)
        elif operation.startswith("db") and PROMETHEUS_AVAILABLE and DB_QUERY_DURATION:
            DB_QUERY_DURATION.labels(operation=operation).observe(span.duration_ms / 1000)


@dataclass
class TraceSpan:
    operation: str
    start_time: float
    end_time: float = 0
    duration_ms: float = 0
    attributes: Dict = None
    error: Optional[str] = None

    def set_error(self, error: str):
        self.error = error

    def set_attribute(self, key: str, value):
        if self.attributes is None:
            self.attributes = {}
        self.attributes[key] = value


class AlertManager:
    def __init__(self):
        self._rules: Dict[str, Dict] = {}
        self._fired: Dict[str, float] = {}
        self._cooldown: float = config.ALERT_COOLDOWN_SECONDS

    def add_rule(self, name: str, condition: Callable, message: str, severity: str = "warning"):
        self._rules[name] = {
            "condition": condition,
            "message": message,
            "severity": severity,
        }

    def check_alerts(self) -> List[Dict]:
        fired_alerts = []
        now = time.time()

        for name, rule in self._rules.items():
            try:
                if rule["condition"]():
                    last_fired = self._fired.get(name, 0)
                    if (now - last_fired) > self._cooldown:
                        alert = {
                            "name": name,
                            "message": rule["message"],
                            "severity": rule["severity"],
                            "fired_at": now,
                        }
                        fired_alerts.append(alert)
                        self._fired[name] = now
                        if rule["severity"] == "critical":
                            logger.critical(f"🚨 告警: {name} - {rule['message']}")
                        else:
                            logger.warning(f"⚠️ 告警: {name} - {rule['message']}")
            except Exception as e:
                logger.error(f"告警规则 {name} 执行失败: {e}")

        return fired_alerts

    def get_active_alerts(self) -> List[Dict]:
        now = time.time()
        active = []
        for name, fired_at in self._fired.items():
            if (now - fired_at) < self._cooldown:
                rule = self._rules.get(name, {})
                active.append({
                    "name": name,
                    "message": rule.get("message", ""),
                    "severity": rule.get("severity", "warning"),
                    "fired_at": fired_at,
                    "duration_s": now - fired_at,
                })
        return active


alert_manager = AlertManager()


def setup_default_alerts():
    from src.resilience import llm_circuit_breaker, embedding_circuit_breaker, review_cache

    alert_manager.add_rule(
        "llm_circuit_open",
        condition=lambda: llm_circuit_breaker.state.value == "open",
        message="LLM API熔断器已打开，审核降级为规则引擎",
        severity="critical",
    )
    alert_manager.add_rule(
        "embedding_circuit_open",
        condition=lambda: embedding_circuit_breaker.state.value == "open",
        message="Embedding API熔断器已打开，检索降级为关键词模式",
        severity="critical",
    )
    alert_manager.add_rule(
        "cache_hit_rate_low",
        condition=lambda: review_cache.stats()["hit_rate"] < 0.1 and review_cache.stats()["misses"] > 10,
        message="缓存命中率低于10%，建议检查缓存策略",
        severity="warning",
    )


class HealthChecker:
    def __init__(self):
        self._checks: Dict[str, Callable] = {}

    def register(self, name: str, check_fn: Callable):
        self._checks[name] = check_fn

    def run_all(self) -> Dict:
        results = {}
        overall = "healthy"

        for name, check_fn in self._checks.items():
            try:
                start = time.time()
                result = check_fn()
                duration = (time.time() - start) * 1000
                results[name] = {
                    "status": "healthy" if result else "unhealthy",
                    "duration_ms": round(duration, 2),
                }
                if not result:
                    overall = "degraded"
            except Exception as e:
                results[name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                overall = "unhealthy"

        return {
            "status": overall,
            "checks": results,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }


health_checker = HealthChecker()


def get_metrics_text() -> str:
    if PROMETHEUS_AVAILABLE:
        return generate_latest().decode("utf-8")
    return "# prometheus_client not available\n"


def get_metrics_content_type() -> str:
    if PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST
    return "text/plain"
