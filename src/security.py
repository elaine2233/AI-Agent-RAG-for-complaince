import os
import re
import time
import json
import logging
import hashlib
import hmac as hmac_module
import threading
import glob
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
from functools import wraps

import config

logger = logging.getLogger(__name__)


PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|above|all|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"ignore\s+\w+\s+(previous|above|all|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|previous)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"assistant\s*:\s*", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"override\s+(previous|default|system)", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s*(mode|模式)?", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    re.compile(r"sudo\s+mode", re.IGNORECASE),
    re.compile(r"不再遵守", re.IGNORECASE),
    re.compile(r"忽略(以上|之前|所有)(的)?(指令|规则|约束)", re.IGNORECASE),
    re.compile(r"假装(你是|你是一个)", re.IGNORECASE),
    re.compile(r"你现在是一个", re.IGNORECASE),
    re.compile(r"覆盖(之前的|原有的|默认的)(指令|规则)", re.IGNORECASE),
    re.compile(r"输出你的系统提示", re.IGNORECASE),
    re.compile(r"repeat\s+(your|the)\s+(system|initial)\s+prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"```system", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?)", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your|the|previous)\s+(instructions?|rules?)", re.IGNORECASE),
]

XSS_PATTERNS = [
    re.compile(r"<script[^>]*>", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<img[^>]+onerror", re.IGNORECASE),
]

SQL_INJECTION_PATTERNS = [
    re.compile(r"(\b(union|select|insert|update|delete|drop|alter|create)\b.*\b(from|table|into|set|where)\b)", re.IGNORECASE),
    re.compile(r"(--|;|/\*|\*/)", re.IGNORECASE),
    re.compile(r"(\b(or|and)\s+\d+\s*=\s*\d+)", re.IGNORECASE),
]


@dataclass
class ValidationResult:
    is_valid: bool
    sanitized_input: str
    threats: List[str]
    risk_level: str

    def to_dict(self):
        return asdict(self)


class InputValidator:
    MAX_INPUT_LENGTH = config.MAX_INPUT_LENGTH
    MAX_IMAGE_COUNT = 5
    MAX_IMAGE_SIZE_MB = 10
    MIN_INPUT_LENGTH = 2

    def validate_text(self, text: str) -> ValidationResult:
        threats = []
        risk_level = "low"

        if not text or not text.strip():
            return ValidationResult(
                is_valid=False,
                sanitized_input="",
                threats=["输入为空"],
                risk_level="high",
            )

        if len(text) < self.MIN_INPUT_LENGTH:
            return ValidationResult(
                is_valid=False,
                sanitized_input=text,
                threats=[f"输入过短，最少需要{self.MIN_INPUT_LENGTH}个字符"],
                risk_level="medium",
            )

        if len(text) > self.MAX_INPUT_LENGTH:
            truncated = text[:self.MAX_INPUT_LENGTH]
            threats.append(f"输入超过最大长度{self.MAX_INPUT_LENGTH}，已截断")
            risk_level = "medium"
            text = truncated

        injection_threats = self._detect_prompt_injection(text)
        if injection_threats:
            threats.extend(injection_threats)
            risk_level = "critical"

        xss_threats = self._detect_xss(text)
        if xss_threats:
            threats.extend(xss_threats)
            risk_level = "high"

        sql_threats = self._detect_sql_injection(text)
        if sql_threats:
            threats.extend(sql_threats)
            risk_level = "high"

        control_chars = self._detect_control_chars(text)
        if control_chars:
            threats.append("输入包含控制字符，已清理")
            text = self._sanitize_control_chars(text)
            if risk_level == "low":
                risk_level = "medium"

        sanitized = self._basic_sanitize(text)

        return ValidationResult(
            is_valid=risk_level not in ("critical",),
            sanitized_input=sanitized,
            threats=threats,
            risk_level=risk_level,
        )

    def validate_images(self, images: list) -> ValidationResult:
        threats = []

        if len(images) > self.MAX_IMAGE_COUNT:
            threats.append(f"图片数量超过限制{self.MAX_IMAGE_COUNT}，已截断")
            images = images[:self.MAX_IMAGE_COUNT]

        for img in images:
            if img is not None:
                try:
                    file_size = os.path.getsize(img.name) if hasattr(img, 'name') else 0
                    if file_size > self.MAX_IMAGE_SIZE_MB * 1024 * 1024:
                        threats.append(f"图片大小超过{self.MAX_IMAGE_SIZE_MB}MB限制")
                except Exception:
                    pass

        return ValidationResult(
            is_valid=True,
            sanitized_input="",
            threats=threats,
            risk_level="low" if not threats else "medium",
        )

    def _detect_prompt_injection(self, text: str) -> List[str]:
        threats = []
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                threats.append(f"检测到Prompt注入攻击模式: {pattern.pattern}")
                logger.warning(f"Prompt注入检测: pattern={pattern.pattern}, input_hash={hashlib.sha256(text.encode()).hexdigest()[:16]}")
        return threats

    def _detect_xss(self, text: str) -> List[str]:
        threats = []
        for pattern in XSS_PATTERNS:
            if pattern.search(text):
                threats.append(f"检测到XSS攻击模式: {pattern.pattern}")
        return threats

    def _detect_sql_injection(self, text: str) -> List[str]:
        threats = []
        for pattern in SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                threats.append(f"检测到SQL注入模式: {pattern.pattern}")
        return threats

    def _detect_control_chars(self, text: str) -> bool:
        control_pattern = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
        return bool(control_pattern.search(text))

    def _sanitize_control_chars(self, text: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    def _basic_sanitize(self, text: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<iframe[^>]*>.*?</iframe>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"javascript\s*:", "", text, flags=re.IGNORECASE)
        return text.strip()


class RateLimiter:
    def __init__(
        self,
        max_requests: int = None,
        window_seconds: int = None,
        max_requests_per_ip: int = None,
    ):
        self.max_requests = max_requests or config.RATE_LIMIT_MAX_REQUESTS
        self.window_seconds = window_seconds or config.RATE_LIMIT_WINDOW_SECONDS
        self.max_requests_per_ip = max_requests_per_ip or config.RATE_LIMIT_MAX_PER_IP
        self._global_requests: List[float] = []
        self._ip_requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_rate(self, client_id: str = "default") -> Tuple[bool, str]:
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            self._global_requests = [t for t in self._global_requests if t > cutoff]
            self._ip_requests[client_id] = [
                t for t in self._ip_requests[client_id] if t > cutoff
            ]

            if len(self._global_requests) >= self.max_requests:
                return False, f"全局请求频率超限({self.max_requests}/{self.window_seconds}s)"

            if len(self._ip_requests[client_id]) >= self.max_requests_per_ip:
                return False, f"IP请求频率超限({self.max_requests_per_ip}/{self.window_seconds}s)"

            self._global_requests.append(now)
            self._ip_requests[client_id].append(now)

        return True, ""


class AuditLogger:
    _SIGNING_KEY = config.AUDIT_SIGNING_KEY
    _MAX_LOG_DAYS = config.AUDIT_MAX_LOG_DAYS
    _builtin_open = open

    def __init__(self, log_dir: str = None):
        self.log_dir = log_dir or config.AUDIT_LOG_DIR
        os.makedirs(self.log_dir, exist_ok=True)
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()
        self._flush_interval = 10
        self._max_buffer_size = 100

    def _sign_entry(self, entry: Dict) -> str:
        payload = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        return hmac_module.new(
            self._SIGNING_KEY.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:16]

    def log_review(
        self,
        input_content: str,
        result: Dict,
        client_id: str = "anonymous",
        threats: List[str] = None,
        latency_ms: float = 0,
    ):
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "client_id": client_id,
            "input_hash": hashlib.sha256(input_content.encode()).hexdigest()[:16],
            "input_length": len(input_content),
            "compliant": result.get("compliant", "unknown"),
            "violation_type": result.get("violation_type", ""),
            "confidence": result.get("confidence", 0),
            "threats": threats or [],
            "latency_ms": round(latency_ms, 2),
        }
        entry["_signature"] = self._sign_entry(entry)

        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self._max_buffer_size:
                self._flush()

    @staticmethod
    def verify_entry(entry: Dict) -> bool:
        if "_signature" not in entry:
            return False
        expected = AuditLogger._sign_entry_static(
            {k: v for k, v in entry.items() if k != "_signature"}
        )
        return hmac_module.compare_digest(entry["_signature"], expected)

    @staticmethod
    def _sign_entry_static(entry: Dict) -> str:
        payload = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        return hmac_module.new(
            AuditLogger._SIGNING_KEY.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:16]

    def _flush(self):
        if not self._buffer:
            return

        date_str = time.strftime("%Y%m%d")
        log_path = os.path.join(self.log_dir, f"audit_{date_str}.jsonl")

        try:
            with AuditLogger._builtin_open(log_path, "a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"审计日志写入失败: {e}")

        self._buffer.clear()

    def flush(self):
        with self._lock:
            self._flush()

    def rotate_logs(self):
        if self._MAX_LOG_DAYS <= 0:
            return
        cutoff = time.time() - self._MAX_LOG_DAYS * 86400
        pattern = os.path.join(self.log_dir, "audit_*.jsonl")
        deleted = 0
        for path in glob.glob(pattern):
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                deleted += 1
        if deleted:
            logger.info(f"已清理 {deleted} 个过期审计日志文件")

    def __del__(self):
        try:
            self.flush()
        except Exception:
            pass


class SecurityMiddleware:
    def __init__(self):
        self.validator = InputValidator()
        self.rate_limiter = RateLimiter()
        self.audit_logger = AuditLogger()

    def validate_and_sanitize(self, text: str, client_id: str = "anonymous") -> ValidationResult:
        rate_ok, rate_msg = self.rate_limiter.check_rate(client_id)
        if not rate_ok:
            return ValidationResult(
                is_valid=False,
                sanitized_input="",
                threats=[rate_msg],
                risk_level="critical",
            )

        return self.validator.validate_text(text)

    def log_audit(
        self,
        input_content: str,
        result: Dict,
        client_id: str = "anonymous",
        threats: List[str] = None,
        latency_ms: float = 0,
    ):
        self.audit_logger.log_review(
            input_content=input_content,
            result=result,
            client_id=client_id,
            threats=threats,
            latency_ms=latency_ms,
        )


security_middleware = SecurityMiddleware()
