import json
import re
import time
import logging
import hashlib
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

import config
from src.rag_engine import RAGEngine
from src.security import security_middleware, InputValidator
from src.resilience import llm_circuit_breaker, review_cache, with_retry, RetryPolicy
from src.workflow import WorkflowEngine, WorkflowState
from src.llm_gateway import llm_gateway, ModelRole
from src.risk_engine import risk_engine, RiskLevel, Decision
from src.reranker import reranker
from src.prompt_manager import prompt_manager, EXTRACT_SYSTEM_PROMPT, REASON_SYSTEM_PROMPT, FORMAT_SYSTEM_PROMPT
from src.violation_registry import violation_registry

try:
    from src.observability import trace_operation, PROMETHEUS_AVAILABLE, CACHE_HITS, CACHE_MISSES
except ImportError:
    trace_operation = None
    PROMETHEUS_AVAILABLE = False
    CACHE_HITS = None
    CACHE_MISSES = None

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    compliant: str
    violation_type: str
    violated_articles: List[Dict]
    confidence: float
    reasoning: str
    suggestions: str
    risk_score: float = 0.0
    risk_level: str = "low"
    decision: str = "auto_pass"
    review_mode: str = ""
    model_used: str = ""
    prompt_version: str = ""
    workflow_steps: List[Dict] = None
    regulation_snapshot: Dict = None
    crosscheck_passed: bool = True

    def to_dict(self):
        d = asdict(self)
        if d["workflow_steps"] is None:
            d["workflow_steps"] = []
        return d


VIOLATION_RULES_DEPRECATED = True


def _get_violation_rules() -> List[Dict]:
    return violation_registry.get_active_rules()


class ReviewAgent:
    def __init__(self, rag_engine: RAGEngine = None):
        self.rag_engine = rag_engine or RAGEngine()
        self.validator = InputValidator()
        self._workflow = self._build_workflow()

    def _build_workflow(self) -> WorkflowEngine:
        engine = WorkflowEngine()
        engine.register_step("extract", self._step_extract)
        engine.register_step("rule_check", self._step_rule_check)
        engine.register_step("rag_retrieve", self._step_rag_retrieve)
        engine.register_step("rerank", self._step_rerank)
        engine.register_step("llm_reason", self._step_llm_reason)
        engine.register_step("format", self._step_format)
        engine.register_step("validate", self._step_validate)
        engine.register_step("crosscheck", self._step_crosscheck)
        engine.register_step("risk_assess", self._step_risk_assess)
        return engine

    def _step_extract(self, state: WorkflowState):
        rules = _get_violation_rules()
        if config.DEMO_MODE:
            claims = []
            keywords = []
            for rule in rules:
                for kw in rule["keywords"]:
                    if kw in state.original_text:
                        claims.append({"claim": kw, "type": rule["violation_type"]})
                        keywords.append(kw)

            state.extracted_claims = claims
            state.metadata["keywords"] = list(set(keywords))
            return

        try:
            resp = llm_gateway.generate(
                system_prompt=EXTRACT_SYSTEM_PROMPT,
                user_prompt=f"请从以下营销内容中提取关键要素：\n\n{state.original_text}",
                model_name=config.EXTRACT_MODEL,
            )
            parsed = self._parse_json(resp.content)
            if parsed:
                state.extracted_claims = [{"claim": c, "type": ""} for c in parsed.get("claims", [])]
                state.metadata["keywords"] = parsed.get("keywords", [])
                state.metadata["has_risk_disclosure"] = parsed.get("has_risk_disclosure", False)
                state.metadata["has_return_promise"] = parsed.get("has_return_promise", False)
                state.metadata["has_absolute_language"] = parsed.get("has_absolute_language", False)
            state.model_used = resp.model
        except Exception as e:
            logger.warning(f"信息提取步骤失败，使用关键词降级: {e}")
            claims = []
            keywords = []
            for rule in rules:
                for kw in rule["keywords"]:
                    if kw in state.original_text:
                        claims.append({"claim": kw, "type": rule["violation_type"]})
                        keywords.append(kw)
            state.extracted_claims = claims
            state.metadata["keywords"] = list(set(keywords))

    def _step_rule_check(self, state: WorkflowState):
        rules = _get_violation_rules()
        violations = []
        violation_types = []
        matched_keywords = []

        for rule in rules:
            for kw in rule["keywords"]:
                if kw in state.original_text:
                    matched_keywords.append(kw)
                    violation_types.append(rule["violation_type"])
                    for article_info in rule["articles"]:
                        article_text = ""
                        for chunk in self.rag_engine.chunks:
                            if (chunk.doc_name == article_info["doc_name"] and
                                    chunk.article_number == article_info["article_number"]):
                                article_text = chunk.article_text
                                break
                        reason = article_info.get("reason", "")
                        if not reason:
                            vt = violation_registry.get_type(rule.get("type_id", ""))
                            if vt:
                                reason = vt.description
                        violations.append({
                            "doc_name": article_info["doc_name"],
                            "article_number": article_info["article_number"],
                            "article_text": article_text,
                            "violation_reason": f"{reason}（匹配: {kw}）" if reason else f"违规（匹配: {kw}）",
                        })
                    break

        if violations:
            seen = set()
            unique = []
            for v in violations:
                key = f"{v['doc_name']}_{v['article_number']}"
                if key not in seen:
                    seen.add(key)
                    unique.append(v)

            state.rule_check_result = {
                "hit": True,
                "definitive": True,
                "compliant": "no",
                "violation_type": "、".join(list(set(violation_types))),
                "violated_articles": unique,
                "matched_keywords": list(set(matched_keywords)),
                "confidence": 0.90,
            }
        else:
            state.rule_check_result = {
                "hit": False,
                "definitive": False,
                "compliant": "unknown",
                "violation_type": "",
                "violated_articles": [],
                "matched_keywords": [],
                "confidence": 0.0,
            }

    def _step_rag_retrieve(self, state: WorkflowState):
        query = state.original_text
        if state.metadata.get("keywords"):
            query = state.original_text + " " + " ".join(state.metadata["keywords"])

        raw_results = self.rag_engine.retrieve(query, top_k=20)
        state.retrieved_laws = raw_results

    def _step_rerank(self, state: WorkflowState):
        if not state.retrieved_laws:
            state.reranked_laws = []
            return

        state.reranked_laws = reranker.rerank(
            query=state.original_text,
            documents=state.retrieved_laws,
            top_k=5,
        )

    def _step_llm_reason(self, state: WorkflowState):
        active_prompt = prompt_manager.get_active_prompt()
        state.prompt_version = active_prompt.version if active_prompt else "v1"

        context = self.rag_engine.format_retrieved_context(state.reranked_laws)

        few_shots = prompt_manager.get_few_shots(
            violation_type=state.rule_check_result.get("violation_type") if state.rule_check_result else None,
            limit=2,
        )
        few_shot_text = prompt_manager.format_few_shots(few_shots)

        rule_hint = ""
        if state.rule_check_result and state.rule_check_result.get("hit"):
            rule_hint = (
                f"\n\n## 规则引擎预检结果（已命中，请在此基础上继续检查是否还有其他违规）\n"
                f"- 已命中违规类型: {state.rule_check_result.get('violation_type', '')}\n"
                f"- 已命中关键词: {', '.join(state.rule_check_result.get('matched_keywords', []))}\n"
                f"- 已命中条文: {json.dumps(state.rule_check_result.get('violated_articles', []), ensure_ascii=False)}\n"
                f"**重要**: 请在确认以上规则命中的基础上，继续检查是否存在规则未覆盖的深层/隐含违规。**不要重复输出规则已命中的违规，只输出额外发现。**\n"
            )

        if active_prompt and active_prompt.user_prompt_template:
            user_prompt = active_prompt.user_prompt_template.format(
                content=state.original_text,
                context=context,
                few_shots=few_shot_text,
            ) + rule_hint
            system_prompt = active_prompt.system_prompt
        else:
            user_prompt = f"## 待审核内容\n{state.original_text}\n\n## 相关法规\n{context}\n\n## 参考案例\n{few_shot_text}\n{rule_hint}\n请进行合规审核，按JSON格式输出。"
            system_prompt = REASON_SYSTEM_PROMPT

        try:
            resp = llm_gateway.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_name=config.REASON_MODEL,
            )
            state.reasoning_result = self._parse_json(resp.content)
            state.model_used = resp.model
        except Exception as e:
            logger.error(f"LLM推理失败: {e}")
            if state.rule_check_result and state.rule_check_result.get("hit"):
                state.reasoning_result = {
                    "compliant": state.rule_check_result["compliant"],
                    "violation_type": state.rule_check_result["violation_type"],
                    "violated_articles": state.rule_check_result["violated_articles"],
                    "confidence": state.rule_check_result["confidence"],
                    "reasoning": "LLM不可用，基于规则引擎结果",
                    "suggestions": self._generate_suggestions(
                        state.rule_check_result["violation_type"].split("、")
                    ),
                }
            else:
                state.reasoning_result = {
                    "compliant": "unknown",
                    "violation_type": "LLM不可用",
                    "violated_articles": [],
                    "confidence": 0.0,
                    "reasoning": f"LLM推理失败: {str(e)}",
                    "suggestions": "请稍后重试或联系管理员",
                }

    def _step_format(self, state: WorkflowState):
        if state.reasoning_result and state.rule_check_result and state.rule_check_result.get("hit"):
            llm_result = state.reasoning_result
            rule_result = state.rule_check_result

            rule_types = set(rule_result.get("violation_type", "").split("、")) if rule_result.get("violation_type") else set()
            rule_types.discard("")
            llm_types = set(llm_result.get("violation_type", "").split("、")) if llm_result.get("violation_type") else set()
            llm_types.discard("")
            merged_types = rule_types | llm_types

            rule_articles = rule_result.get("violated_articles", [])
            llm_articles = llm_result.get("violated_articles", [])
            seen_keys = set()
            merged_articles = []
            for a in rule_articles + llm_articles:
                key = f"{a.get('doc_name', '')}::{a.get('article_number', '')}"
                if key not in seen_keys:
                    merged_articles.append(a)
                    seen_keys.add(key)

            llm_compliant = llm_result.get("compliant", "yes")
            result = {
                "compliant": "no" if (rule_result.get("compliant") == "no" or llm_compliant == "no") else llm_compliant,
                "violation_type": "、".join(merged_types) if merged_types else "",
                "violated_articles": merged_articles,
                "confidence": max(
                    rule_result.get("confidence", 0.5),
                    float(llm_result.get("confidence", 0.5)) if llm_result.get("confidence") else 0.5,
                ),
                "reasoning": f"规则引擎命中: {', '.join(rule_result.get('matched_keywords', []))}。{llm_result.get('reasoning', '')}",
                "suggestions": llm_result.get("suggestions", "") or self._generate_suggestions(list(merged_types)),
            }
        elif state.reasoning_result:
            result = state.reasoning_result
        elif state.rule_check_result and state.rule_check_result.get("hit"):
            result = {
                "compliant": state.rule_check_result["compliant"],
                "violation_type": state.rule_check_result["violation_type"],
                "violated_articles": state.rule_check_result["violated_articles"],
                "confidence": state.rule_check_result["confidence"],
                "reasoning": f"规则引擎命中关键词: {', '.join(state.rule_check_result.get('matched_keywords', []))}",
                "suggestions": self._generate_suggestions(
                    state.rule_check_result["violation_type"].split("、")
                ),
            }
        else:
            result = {
                "compliant": "unknown",
                "violation_type": "",
                "violated_articles": [],
                "confidence": 0.0,
                "reasoning": "规则引擎和LLM均未返回结果",
                "suggestions": "请稍后重试",
            }

        if result.get("compliant") not in ("yes", "no"):
            result["compliant"] = "unknown"

        confidence = result.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.5
        result["confidence"] = max(0.0, min(1.0, confidence))

        if not isinstance(result.get("violated_articles"), list):
            result["violated_articles"] = []

        state.formatted_result = result

    def _step_validate(self, state: WorkflowState):
        result = state.formatted_result
        validated_articles = []

        for article in result.get("violated_articles", []):
            doc_name = article.get("doc_name", "")
            article_number = article.get("article_number", "")
            article_text = article.get("article_text", "")

            verified = False
            for chunk in self.rag_engine.chunks:
                if chunk.doc_name == doc_name and chunk.article_number == article_number:
                    verified = True
                    if not article_text or len(article_text) < 10:
                        article["article_text"] = chunk.article_text
                    break

            if verified:
                validated_articles.append(article)
            else:
                logger.warning(
                    f"幻觉检测: 引用条文不存在 doc={doc_name} article={article_number}，已移除"
                )
                article["hallucination_detected"] = True
                article["violation_reason"] = f"[引用验证失败] {article.get('violation_reason', '')}"

        if len(validated_articles) < len(result.get("violated_articles", [])):
            removed = len(result.get("violated_articles", [])) - len(validated_articles)
            result["reasoning"] = f"[注意: {removed}条引用经验证不存在，已移除] " + result.get("reasoning", "")

        result["violated_articles"] = validated_articles

        if not validated_articles and result["compliant"] == "no":
            result["compliant"] = "unknown"
            result["confidence"] = min(result.get("confidence", 0.5), 0.4)
            result["reasoning"] = "[引用条文验证失败，无法确认违规] " + result.get("reasoning", "")

        state.validation_result = result

    def _step_crosscheck(self, state: WorkflowState):
        result = state.validation_result

        if result.get("compliant") != "no":
            state.crosscheck_result = {"passed": True, "reason": "合规内容无需复核"}
            return

        if config.DEMO_MODE:
            state.crosscheck_result = {"passed": True, "reason": "Demo模式跳过LLM复核"}
            return

        violated_articles = result.get("violated_articles", [])
        input_text = state.original_text
        crosscheck_prompt = f"""请对以下审核结论进行交叉验证，判断结论是否合理。

## 原始营销内容
{input_text}

## 审核结论
- 合规判定: {result.get('compliant', 'unknown')}
- 违规类型: {result.get('violation_type', '')}
- 置信度: {result.get('confidence', 0)}
- 推理过程: {result.get('reasoning', '')}

## 引用条文
{json.dumps(violated_articles, ensure_ascii=False, indent=2)}

## 验证要求
1. 引用条文是否与营销内容语义相关？（防止过度引用）
2. 推理逻辑是否自洽？（防止自圆其说）
3. 违规判定是否合理？（防止误判）

严格按JSON格式输出：
```json
{{
    "passed": true/false,
    "issues": ["问题描述列表"],
    "confidence_adjustment": -0.1到0.1的调整值,
    "recommend_human_review": true/false
}}
```"""

        try:
            resp = llm_gateway.generate(
                system_prompt="你是一位严谨的审核复核专家，只做事实性验证，不做主观判断。",
                user_prompt=crosscheck_prompt,
                model_name=config.CROSSCHECK_MODEL,
            )
            parsed = self._parse_json(resp.content)
            if parsed:
                passed = parsed.get("passed", True)
                issues = parsed.get("issues", [])
                confidence_adj = parsed.get("confidence_adjustment", 0.0)
                recommend_hr = parsed.get("recommend_human_review", False)

                if not passed and issues:
                    result["reasoning"] += f" [复核提示: {'; '.join(issues)}]"

                if confidence_adj:
                    try:
                        adj = float(confidence_adj)
                        result["confidence"] = max(0.0, min(1.0, result.get("confidence", 0.5) + adj))
                    except (ValueError, TypeError):
                        pass

                if recommend_hr:
                    result["reasoning"] += " [复核建议转人工审核]"

                state.crosscheck_result = {
                    "passed": passed,
                    "issues": issues,
                    "confidence_adjustment": confidence_adj,
                    "recommend_human_review": recommend_hr,
                }
            else:
                state.crosscheck_result = {"passed": True, "reason": "复核解析失败，默认通过"}
        except Exception as e:
            logger.warning(f"CrossCheck步骤失败，跳过复核: {e}")
            state.crosscheck_result = {"passed": True, "reason": f"复核失败: {str(e)}"}

    def _step_risk_assess(self, state: WorkflowState):
        result = state.validation_result
        rule_hit = state.rule_check_result.get("hit", False) if state.rule_check_result else False

        assessment = risk_engine.assess(
            compliant=result.get("compliant", "unknown"),
            violation_type=result.get("violation_type", ""),
            violated_articles=result.get("violated_articles", []),
            confidence=result.get("confidence", 0.5),
            rule_hit=rule_hit,
        )

        state.risk_score = assessment.risk_score
        state.risk_level = assessment.risk_level.value
        state.decision = assessment.decision.value
        state.metadata["risk_assessment"] = assessment.to_dict()

    def review(
        self,
        content: str,
        image_descriptions: List[str] = None,
        client_id: str = "anonymous",
    ) -> ReviewResult:
        start_time = time.time()

        validation = security_middleware.validate_and_sanitize(content, client_id)
        if not validation.is_valid:
            return ReviewResult(
                compliant="unknown",
                violation_type="输入校验失败",
                violated_articles=[],
                confidence=0.0,
                reasoning=f"输入未通过安全校验: {'; '.join(validation.threats)}",
                suggestions="请修改输入内容后重新提交。",
                risk_score=0.0,
                risk_level="low",
                decision="auto_block",
                review_mode="security_block",
            )

        sanitized_content = validation.sanitized_input

        if image_descriptions:
            full_content = sanitized_content + "\n\n[图片描述信息]\n" + "\n".join(
                f"图片{i+1}: {desc}" for i, desc in enumerate(image_descriptions)
            )
        else:
            full_content = sanitized_content

        cache_key = hashlib.sha256(full_content.encode()).hexdigest()
        cached = review_cache.get(cache_key)
        if cached is not None:
            if PROMETHEUS_AVAILABLE and CACHE_HITS:
                CACHE_HITS.labels(cache_type="review").inc()
            return cached
        if PROMETHEUS_AVAILABLE and CACHE_MISSES:
            CACHE_MISSES.labels(cache_type="review").inc()

        state = WorkflowState(
            original_text=full_content,
            image_descriptions=image_descriptions or [],
        )

        _trace = trace_operation or _noop_trace
        with _trace("review_workflow", {"client": client_id}):
            state = self._workflow.run(state)

        result_data = state.validation_result or {}
        review_mode = "rule+llm" if (state.rule_check_result and state.rule_check_result.get("hit")) else "llm"

        regulation_snapshot = {}
        try:
            for chunk in self.rag_engine.chunks:
                if chunk.doc_name not in regulation_snapshot:
                    regulation_snapshot[chunk.doc_name] = chunk.content_hash or ""
        except Exception:
            regulation_snapshot = {}

        crosscheck_passed = True
        if state.crosscheck_result:
            crosscheck_passed = state.crosscheck_result.get("passed", True)

        result = ReviewResult(
            compliant=result_data.get("compliant", "unknown"),
            violation_type=result_data.get("violation_type", ""),
            violated_articles=result_data.get("violated_articles", []),
            confidence=result_data.get("confidence", 0.0),
            reasoning=result_data.get("reasoning", ""),
            suggestions=result_data.get("suggestions", ""),
            risk_score=state.risk_score,
            risk_level=state.risk_level,
            decision=state.decision,
            review_mode=review_mode,
            model_used=state.model_used,
            prompt_version=state.prompt_version,
            workflow_steps=[{"name": s.name, "status": s.status.value, "latency_ms": s.latency_ms} for s in state.steps],
            regulation_snapshot=regulation_snapshot,
            crosscheck_passed=crosscheck_passed,
        )

        review_cache.set(cache_key, result)

        latency_ms = (time.time() - start_time) * 1000
        security_middleware.log_audit(
            input_content=full_content,
            result=result.to_dict(),
            client_id=client_id,
            threats=validation.threats,
            latency_ms=latency_ms,
        )

        logger.info(
            f"审核完成: compliant={result.compliant}, "
            f"violation={result.violation_type}, "
            f"risk={result.risk_level}/{result.risk_score:.2f}, "
            f"decision={result.decision}, "
            f"mode={result.review_mode}, "
            f"model={result.model_used}, "
            f"latency={latency_ms:.0f}ms"
        )

        return result

    def _parse_json(self, text: str) -> Dict:
        try:
            json_str = text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.error(f"JSON解析失败: {e}")
            return {}

    def _generate_suggestions(self, violation_types: List[str]) -> str:
        suggestions = [violation_registry.get_suggestion(vt) for vt in violation_types]
        return "；".join(suggestions) if suggestions else "请修改营销内容。"


def _noop_trace(operation, attributes=None):
    from contextlib import nullcontext
    return nullcontext()
