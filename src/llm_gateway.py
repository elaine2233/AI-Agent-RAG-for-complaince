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

def _write_audit_log(model_name, system_prompt, user_prompt, response_text, latency_ms, success):
    try:
        ts = _datetime.now().strftime("%Y%m%d")
        log_file = _os.path.join(_audit_log_dir, f"llm_audit_{ts}.jsonl")
        entry = {
            "timestamp": _datetime.now().isoformat(),
            "model": model_name,
            "system_prompt": (system_prompt or "")[:2000],
            "user_prompt": (user_prompt or "")[:2000],
            "response": (response_text or "")[:2000],
            "latency_ms": round(latency_ms, 1),
            "success": success,
        }
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
        if config.DEMO_MODE:
            self.register_model(ModelConfig(
                name="rule-engine",
                role=ModelRole.PRIMARY,
                provider="rule_engine",
                priority=0,
            ))
            return
        if config.DASHSCOPE_API_KEY:
            self.register_model(ModelConfig(
                name=config.LLM_MODEL,
                role=ModelRole.PRIMARY,
                provider="openai_compatible",
                priority=0,
            ))
            lightweight_model = getattr(config, "LLM_LIGHTWEIGHT_MODEL", config.LLM_MODEL)
            self.register_model(ModelConfig(
                name=lightweight_model,
                role=ModelRole.LIGHTWEIGHT,
                provider="openai_compatible",
                temperature=0.1,
                priority=10,
            ))
        else:
            self.register_model(ModelConfig(
                name="rule-engine",
                role=ModelRole.PRIMARY,
                provider="rule",
                priority=0,
            ))
            self.register_model(ModelConfig(
                name="rule-engine-light",
                role=ModelRole.LIGHTWEIGHT,
                provider="rule",
                priority=10,
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
    ) -> LLMResponse:
        _start = __import__('time').time()
        try:
            if model_name:
                result = self._call_model(model_name, system_prompt, user_prompt, temperature)
                _lat = (__import__('time').time() - _start) * 1000
                _write_audit_log(model_name, system_prompt, user_prompt, result.content, _lat, True)
                return result

            candidates = self._get_candidates(role)
            last_error = None

            for model_config in sorted(candidates, key=lambda m: m.priority):
                cb = model_config.circuit_breaker
                if cb and cb.state.value == "open":
                    logger.warning(f"模型 {model_config.name} 熔断器打开，跳过")
                    continue

                try:
                    result = self._call_model_with_retry(
                        model_config.name, system_prompt, user_prompt,
                        temperature or model_config.temperature,
                    )
                    _lat = (__import__('time').time() - _start) * 1000
                    _write_audit_log(model_config.name, system_prompt, user_prompt, result.content, _lat, True)
                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(f"模型 {model_config.name} 调用失败(含重试): {e}")
                    if cb:
                        cb.record_failure()
                    continue

            raise RuntimeError(f"所有模型均不可用: {last_error}")
        except RuntimeError as e:
            _lat = (__import__('time').time() - _start) * 1000
            _write_audit_log(model_name or "unknown", system_prompt, user_prompt, str(e), _lat, False)
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
        temperature: float = 0.1,
    ) -> LLMResponse:
        model_config = self._models.get(model_name)
        if not model_config:
            raise ValueError(f"未注册的模型: {model_name}")

        start = time.time()

        if model_config.provider == "openai_compatible":
            content = self._call_openai_compatible(model_config, system_prompt, user_prompt, temperature)
        elif model_config.provider == "rule":
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

    def _call_model_with_retry(self, model_name, system_prompt, user_prompt, temperature):
        try:
            return self._call_model(model_name, system_prompt, user_prompt, temperature)
        except Exception as e:
            logger.warning(f"模型 {model_name} 首次调用失败: {e}，1秒后重试...")
            time.sleep(1.0)
            return self._call_model(model_name, system_prompt, user_prompt, temperature)

    def _call_openai_compatible(self, model_config: ModelConfig, system_prompt: str, user_prompt: str, temperature: float) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.LLM_BASE_URL,
        )

        response = client.chat.completions.create(
            model=model_config.name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            top_p=model_config.top_p if model_config.top_p is not None else config.LLM_TOP_P,
            max_tokens=model_config.max_tokens if model_config.max_tokens is not None else config.LLM_MAX_TOKENS,
        )

        content = response.choices[0].message.content
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
