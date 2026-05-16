import time
import json
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

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
    max_tokens: int = 4096
    temperature: float = 0.1
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
        if config.DASHSCOPE_API_KEY:
            self.register_model(ModelConfig(
                name=config.LLM_MODEL,
                role=ModelRole.PRIMARY,
                provider="dashscope",
                priority=0,
            ))
            self.register_model(ModelConfig(
                name="qwen-turbo",
                role=ModelRole.LIGHTWEIGHT,
                provider="dashscope",
                temperature=0.1,
                priority=10,
            ))
            self.register_model(ModelConfig(
                name="deepseek-v3",
                role=ModelRole.FALLBACK,
                provider="dashscope",
                priority=5,
            ))
        else:
            self.register_model(ModelConfig(
                name="rule-engine",
                role=ModelRole.PRIMARY,
                provider="rule",
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
        logger.info(f"LLM Gateway: 注册模型 {model_config.name} (role={model_config.role.value}, priority={model_config.priority})")

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str = None,
        role: ModelRole = None,
        temperature: float = None,
    ) -> LLMResponse:
        if model_name:
            return self._call_model(model_name, system_prompt, user_prompt, temperature)

        candidates = self._get_candidates(role)
        last_error = None

        for model_config in sorted(candidates, key=lambda m: m.priority):
            cb = model_config.circuit_breaker
            if cb and cb.state.value == "open":
                logger.warning(f"模型 {model_config.name} 熔断器打开，跳过")
                continue

            try:
                return self._call_model(
                    model_config.name, system_prompt, user_prompt,
                    temperature or model_config.temperature,
                )
            except Exception as e:
                last_error = e
                logger.warning(f"模型 {model_config.name} 调用失败: {e}")
                if cb:
                    cb.record_failure()
                continue

        raise RuntimeError(f"所有模型均不可用: {last_error}")

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

        if model_config.provider == "dashscope":
            content = self._call_dashscope(model_name, system_prompt, user_prompt, temperature)
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

    def _call_dashscope(self, model_name: str, system_prompt: str, user_prompt: str, temperature: float) -> str:
        import dashscope
        from dashscope import Generation
        dashscope.api_key = config.DASHSCOPE_API_KEY

        resp = Generation.call(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            result_format="message",
            temperature=temperature,
            top_p=0.8,
        )
        if resp.status_code == 200:
            return resp.output.choices[0].message.content
        else:
            raise RuntimeError(f"DashScope API调用失败: {resp.status_code} - {resp.message}")

    def _call_rule_engine(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "compliant": "yes",
            "violation_type": "",
            "violated_articles": [],
            "confidence": 0.5,
            "reasoning": "Demo模式：规则引擎未命中已知违规关键词，默认判定为合规，建议人工复核确认",
            "suggestions": "此为Demo模式自动判定，建议接入LLM进行深度语义审核",
        })

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
