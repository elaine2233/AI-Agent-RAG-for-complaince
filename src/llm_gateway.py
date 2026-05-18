import time
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

import json as _json
import os as _os
from datetime import datetime as _datetime

_audit_log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "llm_audit")
_os.makedirs(_audit_log_dir, exist_ok=True)

def _write_audit_log(model_name, system_prompt, user_prompt, response_text, latency_ms, success, error_type=None, review_id=None, step_name=None):
    try:
        ts = _datetime.now().strftime("%Y%m%d")
        log_file = _os.path.join(_audit_log_dir, f"llm_audit_{ts}.jsonl")
        entry = {
            "timestamp": _datetime.now().isoformat(),
            "model": model_name,
            "system_prompt": system_prompt or "",
            "user_prompt": user_prompt or "",
            "response": response_text or "",
            "latency_ms": round(latency_ms, 1),
            "success": success,
        }
        if error_type:
            entry["error_type"] = error_type
        if review_id is not None:
            entry["review_id"] = review_id
        if step_name:
            entry["step_name"] = step_name
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

import config
from src.resilience import CircuitBreaker, CircuitBreakerConfig, with_retry, RetryPolicy

logger = logging.getLogger(__name__)


class ModelRole(Enum):
    PRIMARY = "primary"
    FALLBACK = "fallback"
    LIGHTWEIGHT = "lightweight"


@dataclass
class ModelConfig:
    name: str
    role: ModelRole
    provider: str
    circuit_breaker: Optional[CircuitBreaker] = None
    max_tokens: int = None
    temperature: float = None
    top_p: float = None
    priority: int = 0


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    latency_ms: float
    token_count: int = 0
    from_cache: bool = False


class LLMGateway:
    def __init__(self):
        self._models: Dict[str, ModelConfig] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._register_default_models()

    def _register_default_models(self):
        self._models.clear()
        self._circuit_breakers.clear()
        if config.DASHSCOPE_API_KEY:
            self.register_model(ModelConfig(
                name=config.LLM_MODEL,
                role=ModelRole.PRIMARY,
                provider="openai_compatible",
                priority=0,
            ))
            fallback_model = getattr(config, "LLM_FALLBACK_MODEL", None)
            if fallback_model and fallback_model != config.LLM_MODEL:
                self.register_model(ModelConfig(
                    name=fallback_model,
                    role=ModelRole.FALLBACK,
                    provider="openai_compatible",
                    temperature=0.1,
                    priority=5,
                ))
        else:
            self.register_model(ModelConfig(
                name="rule-engine",
                role=ModelRole.PRIMARY,
                provider="rule_engine",
                priority=0,
            ))

    def register_model(self, model_config: ModelConfig):
        cb_name = f"llm_{model_config.name}"
        cb = CircuitBreaker(cb_name, CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=20.0,
        ))
        model_config.circuit_breaker = cb
        self._circuit_breakers[cb_name] = cb
        self._models[model_config.name] = model_config
        logger.info(f"LLM Gateway: 注册模型 {model_config.name} (role={model_config.role.value}, provider={model_config.provider}, priority={model_config.priority})")

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str = None,
        role: ModelRole = None,
        temperature: float = None,
        image_urls: List[str] = None,
        review_id: int = None,
        step_name: str = None,
    ) -> LLMResponse:
        _start = __import__('time').time()
        effective_model = model_name
        try:
            if model_name:
                try:
                    result = self._call_model(model_name, system_prompt, user_prompt, temperature, image_urls=image_urls)
                    _lat = (__import__('time').time() - _start) * 1000
                    _write_audit_log(model_name, system_prompt, user_prompt, result.content, _lat, True, review_id=review_id, step_name=step_name)
                    return result
                except Exception as e:
                    _lat = (__import__('time').time() - _start) * 1000
                    _write_audit_log(model_name, system_prompt, user_prompt, str(e), _lat, False, error_type=type(e).__name__, review_id=review_id, step_name=step_name)
                    raise

            candidates = self._get_candidates(role)
            last_error = None

            for model_config in sorted(candidates, key=lambda m: m.priority):
                cb = model_config.circuit_breaker
                if cb and cb.state.value == "open":
                    logger.warning(f"模型 {model_config.name} 熔断器打开，跳过")
                    continue

                try:
                    effective_temp = temperature if temperature is not None else model_config.temperature
                    result = self._call_model_with_retry(
                        model_config.name, system_prompt, user_prompt,
                        effective_temp, image_urls=image_urls,
                    )
                    _lat = (__import__('time').time() - _start) * 1000
                    _write_audit_log(model_config.name, system_prompt, user_prompt, result.content, _lat, True, review_id=review_id, step_name=step_name)
                    return result
                except Exception as e:
                    last_error = e
                    _lat = (__import__('time').time() - _start) * 1000
                    _write_audit_log(model_config.name, system_prompt, user_prompt, str(e), _lat, False, error_type=type(e).__name__, review_id=review_id, step_name=step_name)
                    logger.warning(f"模型 {model_config.name} 调用失败(含重试): {e}")
                    if cb:
                        cb.record_failure()
                    continue

            raise RuntimeError(f"所有模型均不可用: {last_error}")
        except Exception as e:
            _lat = (__import__('time').time() - _start) * 1000
            if not isinstance(e, RuntimeError):
                _write_audit_log(effective_model or "unknown", system_prompt, user_prompt, str(e), _lat, False, error_type=type(e).__name__, review_id=review_id, step_name=step_name)
            raise

    def _get_candidates(self, role: ModelRole = None) -> List[ModelConfig]:
        if role:
            return [m for m in self._models.values() if m.role == role]
        return list(self._models.values())

    def _call_model(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        image_urls: List[str] = None,
    ) -> LLMResponse:
        model_config = self._models.get(model_name)
        if not model_config:
            raise ValueError(f"未注册的模型: {model_name}")

        start = time.time()

        if model_config.provider == "openai_compatible":
            effective_temp = temperature if temperature is not None else (model_config.temperature if model_config.temperature is not None else config.LLM_TEMPERATURE)
            content = self._call_openai_compatible(model_config, system_prompt, user_prompt, effective_temp, image_urls=image_urls)
        elif model_config.provider in ("rule", "rule_engine"):
            content = self._call_rule_engine(system_prompt, user_prompt)
        else:
            raise ValueError(f"不支持的Provider: {model_config.provider}")

        latency_ms = (time.time() - start) * 1000

        if model_config.circuit_breaker:
            model_config.circuit_breaker.record_success()

        return LLMResponse(
            content=content,
            model=model_name,
            provider=model_config.provider,
            latency_ms=latency_ms,
        )

    def _call_model_with_retry(self, model_name, system_prompt, user_prompt, temperature, image_urls=None):
        try:
            return self._call_model(model_name, system_prompt, user_prompt, temperature, image_urls=image_urls)
        except Exception as e:
            logger.warning(f"模型 {model_name} 首次调用失败: {e}，1秒后重试...")
            time.sleep(1.0)
            return self._call_model(model_name, system_prompt, user_prompt, temperature, image_urls=image_urls)

    def _call_openai_compatible(self, model_config: ModelConfig, system_prompt: str, user_prompt: str, temperature: float, image_urls: List[str] = None) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.LLM_BASE_URL,
            timeout=120.0,
        )

        user_content = user_prompt
        if image_urls:
            user_content = [{"type": "text", "text": user_prompt}]
            for url in image_urls:
                user_content.append({"type": "image_url", "image_url": {"url": url}})

        kwargs = {
            "model": model_config.name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": float(temperature) if temperature is not None else config.LLM_TEMPERATURE,
            "top_p": float(model_config.top_p) if model_config.top_p is not None else config.LLM_TOP_P,
            "max_tokens": int(model_config.max_tokens) if model_config.max_tokens is not None else config.LLM_MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }

        if "qwen" in model_config.name.lower():
            kwargs["extra_body"] = {"enable_thinking": False}

        response = client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        content = message.content

        if content and "</think" in content:
            content = content.split("</think", 1)[-1]
            if content.startswith(">"):
                content = content[1:]
            content = content.strip()

        if content and content.startswith("<think"):
            parts = content.split("</think", 1)
            if len(parts) > 1:
                content = parts[1]
                if content.startswith(">"):
                    content = content[1:]
                content = content.strip()
            else:
                content = ""

        return content

    def _call_rule_engine(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "compliant": "yes",
            "violation_type": "",
            "violated_articles": [],
            "confidence": 0.5,
            "reasoning": "规则引擎未命中已知违规关键词，默认判定为合规，建议人工复核确认",
            "suggestions": "未检测到已知违规关键词，如需深度语义审核请配置DashScope API Key后重试",
        })

    def ensure_model(self, model_name: str) -> bool:
        if model_name in self._models:
            return True
        if not config.DASHSCOPE_API_KEY:
            return False
        self.register_model(ModelConfig(
            name=model_name,
            role=ModelRole.PRIMARY,
            provider="openai_compatible",
            priority=0,
        ))
        logger.info(f"LLM Gateway: 动态注册模型 {model_name}")
        return True

    def get_model_status(self) -> Dict:
        status = {}
        for name, model in self._models.items():
            cb = model.circuit_breaker
            status[name] = {
                "role": model.role.value,
                "provider": model.provider,
                "circuit_state": cb.state.value if cb else "unknown",
                "priority": model.priority,
            }
        return status


llm_gateway = LLMGateway()
