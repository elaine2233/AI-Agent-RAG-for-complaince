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

    def to_dict(self):
        d = asdict(self)
        if d["workflow_steps"] is None:
            d["workflow_steps"] = []
        return d


VIOLATION_RULES = [
    {
        "keywords": ["稳赚不赔", "保本保息", "无风险", "零风险", "绝对安全", "100%保本", "100%安全"],
        "violation_type": "绝对化用语",
        "severity": 0.9,
        "articles": [
            {"doc_name": "保险销售行为管理办法", "article_number": "二十一", "reason": "使用绝对化用语"},
            {"doc_name": "金融产品网络营销管理办法", "article_number": "九", "reason": "使用绝对化用语进行宣传"},
            {"doc_name": "互联网保险业务监管办法", "article_number": "十六", "reason": "使用绝对化用语"},
        ],
    },
    {
        "keywords": ["保证收益", "保证赚钱", "承诺收益", "收益确定", "确定收益", "保证利率", "保证回报"],
        "violation_type": "收益承诺",
        "severity": 0.9,
        "articles": [
            {"doc_name": "保险销售行为管理办法", "article_number": "十二", "reason": "对不确定利益承诺保证收益"},
            {"doc_name": "保险销售行为管理办法", "article_number": "二十一", "reason": "将不确定利益表述为确定利益"},
            {"doc_name": "金融产品网络营销管理办法", "article_number": "九", "reason": "对收益作保证性承诺"},
        ],
    },
    {
        "keywords": ["年化收益", "收益率高达", "收益高达", "回报率"],
        "violation_type": "夸大收益",
        "severity": 0.8,
        "articles": [
            {"doc_name": "保险销售行为管理办法", "article_number": "十二", "reason": "夸大保险产品收益"},
            {"doc_name": "保险销售行为管理办法", "article_number": "二十一", "reason": "对比较收益作不实陈述"},
            {"doc_name": "互联网保险业务监管办法", "article_number": "十六", "reason": "夸大保险产品收益"},
        ],
    },
    {
        "keywords": ["存款", "存钱", "理财", "基金", "比银行", "比存款"],
        "violation_type": "产品混淆",
        "severity": 0.8,
        "articles": [
            {"doc_name": "保险销售行为管理办法", "article_number": "十三", "reason": "将保险与其他金融产品混淆"},
            {"doc_name": "互联网保险业务监管办法", "article_number": "十六", "reason": "以非保险产品名义销售保险"},
            {"doc_name": "金融产品网络营销管理办法", "article_number": "二十三", "reason": "混淆保险与存款/理财/基金"},
        ],
    },
    {
        "keywords": ["明星", "影星", "网红", "主播", "代言", "倾情推荐"],
        "violation_type": "无资质代言",
        "severity": 0.7,
        "articles": [
            {"doc_name": "金融产品网络营销管理办法", "article_number": "二十", "reason": "利用公众人物代言推荐"},
            {"doc_name": "金融产品网络营销管理办法", "article_number": "十三", "reason": "利用专业人士名义推荐"},
        ],
    },
    {
        "keywords": ["赠送", "送礼", "大礼包", "返现", "返利", "红包", "额外赠送", "旅游基金"],
        "violation_type": "诱导销售",
        "severity": 0.7,
        "articles": [
            {"doc_name": "保险销售行为管理办法", "article_number": "六", "reason": "以额外利益诱导购买"},
            {"doc_name": "互联网保险业务监管办法", "article_number": "十六", "reason": "以赠送礼品诱导购买"},
            {"doc_name": "金融产品网络营销管理办法", "article_number": "十四", "reason": "以返利/红包诱导转发"},
        ],
    },
]


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
        engine.register_step("llm_reason", self._step_llm_reason, condition=lambda s: s.rule_check_result is None or not s.rule_check_result.get("definitive", False))
        engine.register_step("format", self._step_format)
        engine.register_step("validate", self._step_validate)
        engine.register_step("risk_assess", self._step_risk_assess)
        return engine

    def _step_extract(self, state: WorkflowState):
        if config.DEMO_MODE:
            claims = []
            keywords = []
            for rule in VIOLATION_RULES:
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
                role=ModelRole.LIGHTWEIGHT,
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
            for rule in VIOLATION_RULES:
                for kw in rule["keywords"]:
                    if kw in state.original_text:
                        claims.append({"claim": kw, "type": rule["violation_type"]})
                        keywords.append(kw)
            state.extracted_claims = claims
            state.metadata["keywords"] = list(set(keywords))

    def _step_rule_check(self, state: WorkflowState):
        violations = []
        violation_types = []
        matched_keywords = []

        for rule in VIOLATION_RULES:
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
                        violations.append({
                            "doc_name": article_info["doc_name"],
                            "article_number": article_info["article_number"],
                            "article_text": article_text,
                            "violation_reason": f"{article_info['reason']}（匹配: {kw}）",
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

        if active_prompt and active_prompt.user_prompt_template:
            user_prompt = active_prompt.user_prompt_template.format(
                content=state.original_text,
                context=context,
                few_shots=few_shot_text,
            )
            system_prompt = active_prompt.system_prompt
        else:
            user_prompt = f"## 待审核内容\n{state.original_text}\n\n## 相关法规\n{context}\n\n## 参考案例\n{few_shot_text}\n\n请进行合规审核，按JSON格式输出。"
            system_prompt = REASON_SYSTEM_PROMPT

        try:
            resp = llm_gateway.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                role=ModelRole.PRIMARY,
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
        if state.reasoning_result:
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
        review_mode = "rule" if (state.rule_check_result and state.rule_check_result.get("definitive")) else "llm"

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
        suggestion_map = {
            "绝对化用语": "删除绝对化用语，替换为合规表述",
            "收益承诺": "不得对不确定利益作保证性承诺",
            "夸大收益": "不得夸大产品收益",
            "产品混淆": "明确标注为保险产品，不得与存款/理财混淆",
            "无资质代言": "不得利用无资质公众人物代言",
            "诱导销售": "不得以额外利益诱导购买",
        }
        suggestions = [suggestion_map.get(vt, "请根据违规类型修改") for vt in violation_types]
        return "；".join(suggestions) if suggestions else "请修改营销内容。"


def _noop_trace(operation, attributes=None):
    from contextlib import nullcontext
    return nullcontext()
