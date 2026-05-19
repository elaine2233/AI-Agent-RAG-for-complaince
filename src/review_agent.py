import json
import os
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
from src.database import Database

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
    violation_types: List[Dict] = None
    expanded_relations: List[Dict] = None
    violations: List[Dict] = None
    review_id: int = None
    metadata: Dict = None
    confidence_source: Dict = None
    risk_breakdown: Dict = None

    def to_dict(self):
        d = asdict(self)
        if d["workflow_steps"] is None:
            d["workflow_steps"] = []
        if d["violations"] is None:
            d["violations"] = []
        return d


VIOLATION_RULES_DEPRECATED = True


def _get_violation_rules() -> List[Dict]:
    return violation_registry.get_active_rules()


class ReviewAgent:
    def __init__(self, rag_engine: RAGEngine = None):
        self.rag_engine = rag_engine or RAGEngine()
        self.validator = InputValidator()
        self._workflow = self._build_workflow()
        self.extract_model = config.EXTRACT_MODEL
        self.reason_model = config.REASON_MODEL
        self.crosscheck_model = config.CROSSCHECK_MODEL
        has_real_llm = any(m.provider == "openai_compatible" for m in llm_gateway._models.values())
        if not has_real_llm:
            self.extract_model = "rule-engine"
            self.reason_model = "rule-engine"
            self.crosscheck_model = "rule-engine"

    def _build_workflow(self) -> WorkflowEngine:
        engine = WorkflowEngine()
        engine.register_step("extract", self._step_extract)
        engine.register_step("rule_check", self._step_rule_check)
        engine.register_step("rag_retrieve", self._step_rag_retrieve)
        engine.register_step("rerank", self._step_rerank)
        engine.register_step("expand_relations", self._step_expand_relations)
        engine.register_step("llm_reason", self._step_llm_reason)
        engine.register_step("format", self._step_format)
        engine.register_step("validate", self._step_validate)
        engine.register_step("crosscheck", self._step_crosscheck)
        engine.register_step("risk_assess", self._step_risk_assess)
        return engine

    def _step_extract(self, state: WorkflowState):
        rules = _get_violation_rules()
        has_real_llm = any(m.provider == "openai_compatible" for m in llm_gateway._models.values())
        if not has_real_llm:
            claims = []
            keywords = []
            for rule in rules:
                for kw in rule["keywords"]:
                    if kw in state.original_text:
                        claims.append({"claim": kw, "type": rule["violation_type"]})
                        keywords.append(kw)

            state.extracted_claims = claims
            state.metadata["keywords"] = list(set(keywords))
            state.effective_text = state.original_text
            return

        try:
            extract_prompt = f"请从以下营销内容中提取关键要素：\n\n{state.original_text}"

            image_urls = None
            if state.image_paths:
                import base64 as _b64
                image_urls = []
                for path in state.image_paths:
                    if not os.path.exists(path):
                        continue
                    try:
                        processed_path = self._preprocess_image(path)
                        with open(processed_path, "rb") as _f:
                            _data = _b64.b64encode(_f.read()).decode()
                        image_urls.append(f"data:image/jpeg;base64,{_data}")
                        if processed_path != path:
                            try:
                                os.unlink(processed_path)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.warning(f"图片读取失败 {path}: {e}")
                if image_urls:
                    extract_prompt += "\n\n以上包含图片，请结合图片内容一起提取信息。"

            resp = llm_gateway.generate(
                system_prompt=EXTRACT_SYSTEM_PROMPT,
                user_prompt=extract_prompt,
                model_name=self.extract_model,
                image_urls=image_urls,
            )
            parsed = self._parse_json(resp.content)
            if parsed:
                state.extracted_claims = [{"claim": c, "type": ""} for c in parsed.get("claims", [])]
                state.metadata["keywords"] = parsed.get("keywords", [])
                state.metadata["has_risk_disclosure"] = parsed.get("has_risk_disclosure", False)
                state.metadata["has_return_promise"] = parsed.get("has_return_promise", False)
                state.metadata["has_absolute_language"] = parsed.get("has_absolute_language", False)
                image_text = parsed.get("image_text", "")
                image_desc = parsed.get("image_description", "")
                if image_text or image_desc:
                    state.metadata["image_text"] = image_text
                    state.metadata["image_description"] = image_desc
                    if image_text:
                        state.metadata["keywords"].extend([w for w in image_text.split() if len(w) > 1])
                        state.metadata["keywords"] = list(set(state.metadata["keywords"]))
            else:
                raw = resp.content or ""
                import re as _re
                it_match = _re.search(r'"image_text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
                id_match = _re.search(r'"image_description"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
                if it_match:
                    state.metadata["image_text"] = it_match.group(1).encode().decode('unicode_escape')
                if id_match:
                    state.metadata["image_description"] = id_match.group(1).encode().decode('unicode_escape')
                kw_match = _re.search(r'"keywords"\s*:\s*\[([^\]]*)\]', raw)
                if kw_match:
                    kw_str = kw_match.group(1)
                    kws = _re.findall(r'"([^"]+)"', kw_str)
                    if kws:
                        state.metadata["keywords"] = kws
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

        state.effective_text = self._build_effective_text(state)

    def _build_effective_text(self, state: WorkflowState) -> str:
        base_text = state.original_text
        image_text = state.metadata.get("image_text", "")
        image_desc = state.metadata.get("image_description", "")

        image_placeholder = ""
        if state.image_descriptions:
            image_placeholder = "\n\n[图片描述信息]\n" + "\n".join(
                f"图片{i+1}: {desc}" for i, desc in enumerate(state.image_descriptions)
            )

        if image_placeholder and image_placeholder in base_text:
            base_text = base_text.replace(image_placeholder, "")

        base_text = base_text.strip()

        parts = [base_text] if base_text else []
        if image_text:
            parts.append(f"[图片文字] {image_text}")
        if image_desc:
            parts.append(f"[图片描述] {image_desc}")

        if not parts and state.image_paths:
            parts.append("[包含图片内容，请结合图片信息审核]")

        effective = "\n".join(parts) if parts else state.original_text
        state.metadata["effective_text"] = effective
        return effective

    def _step_rule_check(self, state: WorkflowState):
        rules = _get_violation_rules()
        violations = []
        violation_types = []
        matched_keywords = []

        check_text = state.effective_text or state.original_text

        for rule in rules:
            for kw in rule["keywords"]:
                if kw in check_text:
                    matched_keywords.append(kw)
                    violation_types.append(rule["violation_type"])
                    for article_info in rule["articles"]:
                        reason = article_info.get("reason", "")
                        if not reason:
                            vt = violation_registry.get_type(rule.get("type_id", ""))
                            if vt:
                                reason = vt.description
                        violations.append({
                            "doc_name": article_info["doc_name"],
                            "article_number": article_info["article_number"],
                            "violation_reason": f"{reason}（匹配: {kw}）" if reason else f"违规（匹配: {kw}）",
                            "violation_type": rule["violation_type"],
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
            state.metadata["rule_check_result"] = state.rule_check_result
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
            state.metadata["rule_check_result"] = state.rule_check_result

    def _step_rag_retrieve(self, state: WorkflowState):
        query = state.effective_text or state.original_text
        if state.metadata.get("keywords"):
            query = query + " " + " ".join(state.metadata["keywords"])

        raw_results = self.rag_engine.retrieve(query, top_k=20)
        state.retrieved_laws = raw_results
        rag_meta = []
        for r in raw_results[:10]:
            rag_meta.append({
                "doc_name": r.doc_name if hasattr(r, 'doc_name') else r.get('doc_name', ''),
                "article_number": r.article_number if hasattr(r, 'article_number') else r.get('article_number', ''),
                "similarity": r.similarity if hasattr(r, 'similarity') else r.get('similarity', 0),
            })
        state.metadata["rag_results"] = rag_meta

    def _step_rerank(self, state: WorkflowState):
        if not state.retrieved_laws:
            state.reranked_laws = []
            state.metadata["reranked_laws"] = []
            return

        state.reranked_laws = reranker.rerank(
            query=state.effective_text or state.original_text,
            documents=state.retrieved_laws,
            top_k=5,
        )
        rerank_meta = []
        for r in state.reranked_laws[:5]:
            rerank_meta.append({
                "doc_name": r.doc_name if hasattr(r, 'doc_name') else r.get('doc_name', ''),
                "article_number": r.article_number if hasattr(r, 'article_number') else r.get('article_number', ''),
                "relevance_score": r.relevance_score if hasattr(r, 'relevance_score') else r.get('relevance_score', 0),
            })
        state.metadata["reranked_laws"] = rerank_meta

    def _step_expand_relations(self, state: WorkflowState):
        if not state.reranked_laws:
            state.expanded_relations = []
            return

        try:
            database = Database()
        except Exception:
            state.expanded_relations = []
            return

        visited = set()
        all_related = []

        for law in state.reranked_laws:
            doc_name = law.doc_name if hasattr(law, 'doc_name') else law.get('doc_name', '')
            article_number = law.article_number if hasattr(law, 'article_number') else law.get('article_number', '')
            if not doc_name or not article_number:
                continue

            key = (doc_name, article_number)
            if key in visited:
                continue
            visited.add(key)

            try:
                rels = database.get_clause_relations(doc_name=doc_name, article_number=article_number)
                for rel in rels:
                    target_key = (rel['to_doc'], rel['to_article'])
                    if target_key in visited or not rel['to_article']:
                        continue
                    visited.add(target_key)

                    target_text = ''
                    for chunk in self.rag_engine.chunks:
                        if chunk.doc_name == rel['to_doc'] and chunk.article_number == rel['to_article']:
                            target_text = chunk.article_text
                            break

                    all_related.append({
                        'from_doc': rel['from_doc'],
                        'from_article': rel['from_article'],
                        'to_doc': rel['to_doc'],
                        'to_article': rel['to_article'],
                        'relation_type': rel['relation_type'],
                        'confidence': rel['confidence'],
                        'evidence_text': rel.get('evidence_text', ''),
                        'target_article_text': target_text,
                    })

                    sub_rels = database.get_clause_relations(doc_name=rel['to_doc'], article_number=rel['to_article'])
                    for sub in sub_rels:
                        sub_key = (sub['to_doc'], sub['to_article'])
                        if sub_key not in visited and sub['to_article']:
                            visited.add(sub_key)
                            sub_text = ''
                            for chunk in self.rag_engine.chunks:
                                if chunk.doc_name == sub['to_doc'] and chunk.article_number == sub['to_article']:
                                    sub_text = chunk.article_text
                                    break
                            all_related.append({
                                'from_doc': sub['from_doc'],
                                'from_article': sub['from_article'],
                                'to_doc': sub['to_doc'],
                                'to_article': sub['to_article'],
                                'relation_type': sub['relation_type'],
                                'confidence': sub['confidence'],
                                'evidence_text': sub.get('evidence_text', ''),
                                'target_article_text': sub_text,
                            })
            except Exception as e:
                logger.warning(f"条款关系扩展失败 doc={doc_name} article={article_number}: {e}")

        state.expanded_relations = all_related
        state.metadata["expanded_relations"] = [
            {
                "from_doc": r.get("from_doc", ""),
                "from_article": r.get("from_article", ""),
                "to_doc": r.get("to_doc", ""),
                "to_article": r.get("to_article", ""),
                "relation_type": r.get("relation_type", ""),
            }
            for r in all_related[:10]
        ]
        logger.info(f"条款关系扩展: 找到 {len(all_related)} 条关联条款")

    def _step_llm_reason(self, state: WorkflowState):
        active_prompt = prompt_manager.get_active_prompt()
        state.prompt_version = active_prompt.version if active_prompt else "v1"

        has_real_llm = any(
            m.provider == "openai_compatible"
            for m in llm_gateway._models.values()
        )
        if not has_real_llm and state.rule_check_result and state.rule_check_result.get("hit"):
            raw_types = state.rule_check_result["violation_type"].split("、")
            resolved_types = []
            for vt_name in raw_types:
                vt_name = vt_name.strip()
                if not vt_name:
                    continue
                matched = violation_registry.get_type_by_name(vt_name)
                if matched and matched.level == 1:
                    for child in violation_registry._types.values():
                        if child.parent_id == matched.id and child.status == "active" and child.keywords:
                            resolved_types.append(child.name)
                            break
                    else:
                        resolved_types.append(vt_name)
                else:
                    resolved_types.append(vt_name)
            resolved_type_str = "、".join(resolved_types) if resolved_types else state.rule_check_result["violation_type"]
            rule_violations = self._build_violations_from_rule(
                resolved_types, state.rule_check_result["violated_articles"]
            )
            state.reasoning_result = {
                "compliant": state.rule_check_result["compliant"],
                "violations": rule_violations,
                "confidence": state.rule_check_result["confidence"],
                "reasoning": f"规则引擎命中: {', '.join(state.rule_check_result.get('matched_keywords', []))}",
                "suggestions": self._generate_suggestions(resolved_types),
            }
            return

        context = self.rag_engine.format_retrieved_context(state.reranked_laws)

        few_shots = prompt_manager.get_few_shots(
            violation_type=state.rule_check_result.get("violation_type") if state.rule_check_result else None,
            limit=2,
        )
        few_shot_text = prompt_manager.format_few_shots(few_shots)

        rule_hint = ""
        if state.rule_check_result and state.rule_check_result.get("hit"):
            rule_articles = []
            for a in state.rule_check_result.get('violated_articles', []):
                rule_articles.append(f"《{a.get('doc_name', '')}》第{a.get('article_number', '')}条")
            rule_hint = (
                f"\n\n## 规则引擎预检结果（仅供参考，请独立判断）\n"
                f"- 规则引擎命中的违规类型: {state.rule_check_result.get('violation_type', '')}\n"
                f"- 规则引擎命中的关键词: {', '.join(state.rule_check_result.get('matched_keywords', []))}\n"
                f"- 规则引擎命中的条文: {', '.join(rule_articles)}\n"
                f"**重要**: 以上为规则引擎的参考结果，请独立判断内容是否违规，包括规则命中的和多路召回的所有条款。你可以确认、否定或补充规则引擎的结果，最终以你的判断为准。\n"
            )

        relation_hint = ""
        if state.expanded_relations:
            relation_lines = []
            for rel in state.expanded_relations:
                line = f"- {rel['from_doc']}第{rel['from_article']}条 → {rel['to_doc']}第{rel['to_article']}条（关系: {rel['relation_type']}）"
                if rel.get('target_article_text'):
                    line += f"\n  关联条文原文: {rel['target_article_text'][:200]}"
                if rel.get('evidence_text'):
                    line += f"\n  依据: {rel['evidence_text'][:100]}"
                relation_lines.append(line)
            relation_hint = (
                f"\n\n## 条款隐含关联（以下条款之间存在引用、例外、补充等隐含逻辑关系，请综合考量）\n"
                + "\n".join(relation_lines)
                + "\n**重要**: 请注意条款间的关联关系，某些条款的适用可能受关联条款的例外、补充或前提条件影响。\n"
            )

        review_content = state.effective_text or state.original_text

        if active_prompt and active_prompt.user_prompt_template:
            user_prompt = active_prompt.user_prompt_template.format(
                content=review_content,
                context=context,
                few_shots=few_shot_text,
            ) + rule_hint + relation_hint
            system_prompt = active_prompt.system_prompt
        else:
            user_prompt = f"## 待审核内容\n{review_content}\n\n## 相关法规\n{context}\n\n## 参考案例\n{few_shot_text}\n{rule_hint}\n{relation_hint}\n请进行合规审核，按JSON格式输出。"
            system_prompt = REASON_SYSTEM_PROMPT

        try:
            resp = llm_gateway.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_name=self.reason_model,
                step_name="llm_reason",
            )
            raw_content = resp.content
            state.reasoning_result = self._parse_json(raw_content)
            state.model_used = resp.model
            state.metadata["reasoning_result"] = state.reasoning_result
            state.metadata["model_used"] = resp.model
            if not state.reasoning_result and raw_content:
                logger.warning(f"LLM输出JSON解析失败，可能是输出被截断(长度={len(raw_content)})")
            if state.reasoning_result:
                self._resolve_violation_type_ids(state.reasoning_result)
        except Exception as e:
            logger.error(f"LLM推理失败: {e}")
            error_msg = str(e)
            for step in state.steps:
                if step.name == "llm_reason" and step.status.value == "running":
                    from src.workflow import StepStatus
                    step.status = StepStatus.SKIPPED
                    step.error = error_msg[:200]
                    break
            if "401" in error_msg or "Incorrect API key" in error_msg or "invalid_api_key" in error_msg:
                error_hint = "API Key无效或已过期，请检查DashScope API Key是否正确"
            elif "403" in error_msg or "free tier" in error_msg.lower() or "exhausted" in error_msg.lower():
                error_hint = f"模型配额已耗尽: {error_msg[:150]}"
            elif "400" in error_msg or "invalid_value" in error_msg:
                error_hint = f"API参数错误: {error_msg[:100]}"
            elif "429" in error_msg or "rate" in error_msg.lower():
                error_hint = f"API调用限流: {error_msg[:100]}"
            else:
                error_hint = f"LLM服务暂时不可用: {error_msg[:150]}"
            if state.rule_check_result and state.rule_check_result.get("hit"):
                fallback_violations = self._build_violations_from_rule(
                    state.rule_check_result["violation_type"].split("、"),
                    state.rule_check_result["violated_articles"]
                )
                state.reasoning_result = {
                    "compliant": state.rule_check_result["compliant"],
                    "violations": fallback_violations,
                    "confidence": state.rule_check_result["confidence"],
                    "reasoning": f"LLM不可用（{error_hint}），基于规则引擎结果",
                    "suggestions": self._generate_suggestions(
                        state.rule_check_result["violation_type"].split("、")
                    ) + f"\n\n⚠️ LLM错误: {error_hint}",
                }
            else:
                state.reasoning_result = {
                    "compliant": "unknown",
                    "violations": [],
                    "confidence": 0.0,
                    "reasoning": f"LLM推理失败: {error_msg[:200]}",
                    "suggestions": error_hint,
                }

    def _step_format(self, state: WorkflowState):
        if state.reasoning_result:
            result = dict(state.reasoning_result)
            result = self._normalize_to_violations(result)
            for v in result.get("violations", []):
                articles = v.get("violated_articles", [])
                v["violated_articles"] = [a for a in articles if isinstance(a, dict)]
            if state.rule_check_result and state.rule_check_result.get("hit"):
                rule_kw = ', '.join(state.rule_check_result.get('matched_keywords', []))
                orig_reasoning = result.get("reasoning", "")
                if rule_kw and rule_kw not in orig_reasoning:
                    result["reasoning"] = f"[规则引擎参考命中: {rule_kw}] {orig_reasoning}"
        elif state.rule_check_result and state.rule_check_result.get("hit"):
            rule_violations = self._build_violations_from_rule(
                state.rule_check_result["violation_type"].split("、"),
                state.rule_check_result["violated_articles"]
            )
            result = {
                "compliant": state.rule_check_result["compliant"],
                "violations": rule_violations,
                "confidence": state.rule_check_result["confidence"],
                "reasoning": f"LLM不可用，仅规则引擎命中: {', '.join(state.rule_check_result.get('matched_keywords', []))}",
                "suggestions": self._generate_suggestions(
                    state.rule_check_result["violation_type"].split("、")
                ),
            }
        else:
            result = {
                "compliant": "unknown",
                "violations": [],
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

        if "confidence_source" not in state.metadata:
            state.metadata["confidence_source"] = {
                "llm_raw": round(confidence, 4),
                "adjustments": [],
                "final": round(result["confidence"], 4),
            }
        else:
            state.metadata["confidence_source"]["llm_raw"] = round(confidence, 4)
            state.metadata["confidence_source"]["final"] = round(result["confidence"], 4)

        violations = result.get("violations", [])
        if not isinstance(violations, list):
            violations = []
        for v in violations:
            if not isinstance(v.get("violated_articles"), list):
                v["violated_articles"] = []
        result["violations"] = violations

        state.formatted_result = result

    def _step_validate(self, state: WorkflowState):
        result = state.formatted_result
        all_articles = []
        for v in result.get("violations", []):
            all_articles.extend(v.get("violated_articles", []))

        validated_articles = []
        hallucinated_articles = []

        for article in all_articles:
            doc_name = article.get("doc_name", "")
            article_number = article.get("article_number", "")

            verified = False
            for chunk in self.rag_engine.chunks:
                if self._fuzzy_doc_match(chunk.doc_name, doc_name) and self._fuzzy_article_match(chunk.article_number, article_number):
                    verified = True
                    article["doc_name"] = chunk.doc_name
                    article["article_number"] = chunk.article_number
                    article["article_text"] = chunk.article_text
                    break

            if verified:
                validated_articles.append(article)
            else:
                fuzzy_match = None
                if doc_name:
                    for chunk in self.rag_engine.chunks:
                        if self._fuzzy_doc_match(chunk.doc_name, doc_name):
                            if self._fuzzy_article_match(chunk.article_number, article_number):
                                fuzzy_match = chunk
                                break
                if fuzzy_match:
                    article["article_number"] = fuzzy_match.article_number
                    article["article_text"] = fuzzy_match.article_text
                    article["fuzzy_matched"] = True
                    validated_articles.append(article)
                    logger.info(
                        f"幻觉修正: {doc_name} {article_number} → {fuzzy_match.article_number}（模糊匹配）"
                    )
                else:
                    logger.warning(
                        f"幻觉检测: 引用条文不存在 doc={doc_name} article={article_number}，已移除"
                    )
                    article["hallucination_detected"] = True
                    hallucinated_articles.append(article)

        removed_count = len(hallucinated_articles)
        if removed_count > 0:
            result["reasoning"] = f"[注意: {removed_count}条引用经验证不存在，已移除] " + result.get("reasoning", "")

        for v in result.get("violations", []):
            va = v.get("violated_articles", [])
            v["violated_articles"] = [a for a in va if not a.get("hallucination_detected")]

        total_remaining = sum(len(v.get("violated_articles", [])) for v in result.get("violations", []))
        if total_remaining == 0 and result["compliant"] == "no":
            if state.rule_check_result and state.rule_check_result.get("hit"):
                rule_articles = state.rule_check_result.get("violated_articles", [])
                if rule_articles:
                    for chunk in self.rag_engine.chunks:
                        for ra in rule_articles:
                            if self._fuzzy_doc_match(chunk.doc_name, ra.get("doc_name", "")) and self._fuzzy_article_match(chunk.article_number, ra.get("article_number", "")):
                                ra["doc_name"] = chunk.doc_name
                                ra["article_number"] = chunk.article_number
                                ra["article_text"] = chunk.article_text
                    verified_articles = [a for a in rule_articles if a.get("article_text")]
                    seen_keys = set()
                    deduped = []
                    for a in verified_articles:
                        key = f"{a.get('doc_name','')}_{a.get('article_number','')}"
                        if key not in seen_keys:
                            seen_keys.add(key)
                            deduped.append(a)
                    rule_vt = state.rule_check_result.get("violation_type", "")
                    rule_vt_names = [t.strip() for t in rule_vt.split("、") if t.strip()]
                    if len(rule_vt_names) <= 1 or len(deduped) <= 3:
                        result["violations"] = [{
                            "violation_type_id": "",
                            "violation_type_name": rule_vt,
                            "reasoning": f"规则引擎命中{rule_vt}（LLM引用验证失败，回退规则引擎结果）",
                            "violated_articles": deduped[:5],
                        }]
                    else:
                        per_type = max(1, 5 // len(rule_vt_names))
                        rule_violations = []
                        assigned = set()
                        for vt_name in rule_vt_names:
                            vt_articles = []
                            for idx, a in enumerate(deduped):
                                if idx in assigned:
                                    continue
                                if a.get("violation_type") == vt_name:
                                    vt_articles.append(a)
                                    assigned.add(idx)
                                if len(vt_articles) >= per_type:
                                    break
                            if vt_articles:
                                rule_violations.append({
                                    "violation_type_id": "",
                                    "violation_type_name": vt_name,
                                    "reasoning": f"规则引擎命中{vt_name}（LLM引用验证失败，回退规则引擎结果）",
                                    "violated_articles": vt_articles,
                                })
                        unassigned = [a for idx, a in enumerate(deduped) if idx not in assigned]
                        if unassigned and rule_violations:
                            rule_violations[0]["violated_articles"].extend(unassigned[:2])
                        result["violations"] = rule_violations if rule_violations else [{
                            "violation_type_id": "",
                            "violation_type_name": rule_vt,
                            "reasoning": f"规则引擎命中{rule_vt}（LLM引用验证失败，回退规则引擎结果）",
                            "violated_articles": deduped[:5],
                        }]
                    result["reasoning"] = f"[LLM引用条文验证失败，已回退到规则引擎结果] " + result.get("reasoning", "")
                    old_conf = result.get("confidence", 0.5)
                    result["confidence"] = min(result.get("confidence", 0.5), 0.7)
                    self._record_confidence_adj(state, "validate", old_conf, result["confidence"], "LLM引用验证失败→回退规则引擎，cap到0.7")
                else:
                    result["compliant"] = "unknown"
                    old_conf = result.get("confidence", 0.5)
                    result["confidence"] = min(result.get("confidence", 0.5), 0.4)
                    self._record_confidence_adj(state, "validate", old_conf, result["confidence"], "引用条文验证失败，合规状态未知，cap到0.4")
                    result["reasoning"] = "[引用条文验证失败，无法确认违规] " + result.get("reasoning", "")
            else:
                result["compliant"] = "unknown"
                old_conf = result.get("confidence", 0.5)
                result["confidence"] = min(result.get("confidence", 0.5), 0.4)
                self._record_confidence_adj(state, "validate", old_conf, result["confidence"], "引用条文验证失败，合规状态未知，cap到0.4")
                result["reasoning"] = "[引用条文验证失败，无法确认违规] " + result.get("reasoning", "")

        state.validation_result = result

    @staticmethod
    def _fuzzy_doc_match(doc_a: str, doc_b: str) -> bool:
        if not doc_a or not doc_b:
            return False
        if doc_a == doc_b:
            return True
        a_clean = re.sub(r'[《》\s]', '', doc_a)
        b_clean = re.sub(r'[《》\s]', '', doc_b)
        return a_clean == b_clean

    @staticmethod
    def _fuzzy_article_match(num_a: str, num_b: str) -> bool:
        if not num_a or not num_b:
            return False
        if num_a == num_b:
            return True
        def normalize(num: str) -> str:
            num = num.strip()
            num = re.sub(r'^第\s*', '', num)
            num = re.sub(r'\s*条$', '', num)
            cn_digits = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
                         "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
                         "十一": "11", "十二": "12", "十三": "13", "十四": "14", "十五": "15",
                         "十六": "16", "十七": "17", "十八": "18", "十九": "19", "二十": "20",
                         "二十一": "21", "二十二": "22", "二十三": "23", "二十四": "24", "二十五": "25",
                         "二十六": "26", "二十七": "27", "二十八": "28", "二十九": "29", "三十": "30",
                         "三十一": "31", "三十二": "32", "三十三": "33", "三十四": "34", "三十五": "35",
                         "三十六": "36", "三十七": "37", "三十八": "38", "三十九": "39", "四十": "40",
                         "四十一": "41", "四十二": "42", "四十三": "43", "四十四": "44", "四十五": "45",
                         "四十六": "46", "四十七": "47", "四十八": "48", "四十九": "49", "五十": "50",
                         "五十一": "51", "五十二": "52", "五十三": "53", "五十四": "54", "五十五": "55",
                         "五十六": "56", "五十七": "57", "五十八": "58", "五十九": "59", "六十": "60",
                         "六十一": "61", "六十二": "62", "六十三": "63", "六十四": "64", "六十五": "65",
                         "六十六": "66", "六十七": "67", "六十八": "68", "六十九": "69", "七十": "70"}
            return cn_digits.get(num, num)
        return normalize(num_a) == normalize(num_b)

    def _step_crosscheck(self, state: WorkflowState):
        result = state.validation_result

        if result.get("compliant") != "no":
            state.crosscheck_result = {"passed": True, "reason": "合规内容无需复核"}
            state.metadata["crosscheck_result"] = state.crosscheck_result
            for step in state.steps:
                if step.name == "crosscheck" and step.status.value == "running":
                    from src.workflow import StepStatus
                    step.status = StepStatus.SKIPPED
                    break
            return

        has_real_llm_cc = any(m.provider == "openai_compatible" for m in llm_gateway._models.values())
        if not has_real_llm_cc:
            state.crosscheck_result = {"passed": True, "reason": "无LLM可用，跳过复核"}
            state.metadata["crosscheck_result"] = state.crosscheck_result
            for step in state.steps:
                if step.name == "crosscheck" and step.status.value == "running":
                    from src.workflow import StepStatus
                    step.status = StepStatus.SKIPPED
                    break
            return

        violated_articles = []
        for v in result.get("violations", []):
            for a in v.get("violated_articles", []):
                violated_articles.append({
                    "doc_name": a.get("doc_name", ""),
                    "article_number": a.get("article_number", ""),
                    "violation_reason": a.get("violation_reason", ""),
                })
        violation_type_str = "、".join(v.get("violation_type_name", "") for v in result.get("violations", []) if v.get("violation_type_name"))
        input_text = state.effective_text or state.original_text
        crosscheck_prompt = f"""请对以下审核结论进行交叉验证，判断结论是否合理。

## 原始营销内容
{input_text}

## 审核结论
- 合规判定: {result.get('compliant', 'unknown')}
- 违规类型: {violation_type_str}
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
                model_name=self.crosscheck_model,
                step_name="crosscheck",
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
                        old_conf = result.get("confidence", 0.5)
                        result["confidence"] = max(0.0, min(1.0, result.get("confidence", 0.5) + adj))
                        self._record_confidence_adj(state, "crosscheck", old_conf, result["confidence"], f"CrossCheck调整: {adj:+.2f} (passed={passed}, issues={issues})")
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
                state.metadata["crosscheck_result"] = state.crosscheck_result
            else:
                state.crosscheck_result = {"passed": True, "reason": "复核解析失败，默认通过"}
            state.metadata["crosscheck_result"] = state.crosscheck_result
        except Exception as e:
            logger.warning(f"CrossCheck步骤失败，跳过复核: {e}")
            state.crosscheck_result = {"passed": True, "reason": f"复核失败: {str(e)}"}
            state.metadata["crosscheck_result"] = state.crosscheck_result
            for step in state.steps:
                if step.name == "crosscheck" and step.status.value == "running":
                    from src.workflow import StepStatus
                    step.status = StepStatus.SKIPPED
                    step.error = str(e)[:200]
                    break

    def _step_risk_assess(self, state: WorkflowState):
        result = state.validation_result
        rule_hit = state.rule_check_result.get("hit", False) if state.rule_check_result else False

        all_violated_articles = []
        for v in result.get("violations", []):
            all_violated_articles.extend(v.get("violated_articles", []))
        violation_type_str = "、".join(v.get("violation_type_name", "") for v in result.get("violations", []) if v.get("violation_type_name"))

        assessment = risk_engine.assess(
            compliant=result.get("compliant", "unknown"),
            violation_type=violation_type_str,
            violated_articles=all_violated_articles,
            confidence=result.get("confidence", 0.5),
            rule_hit=rule_hit,
        )

        state.risk_score = assessment.risk_score
        state.risk_level = assessment.risk_level.value
        state.decision = assessment.decision.value
        state.metadata["risk_assessment"] = assessment.to_dict()

        if "confidence_source" in state.metadata:
            state.metadata["confidence_source"]["final"] = round(result.get("confidence", 0.5), 4)

    @staticmethod
    def _record_confidence_adj(state, step: str, old_val: float, new_val: float, reason: str):
        if "confidence_source" not in state.metadata:
            state.metadata["confidence_source"] = {"llm_raw": None, "adjustments": [], "final": None}
        state.metadata["confidence_source"]["adjustments"].append({
            "step": step,
            "from": round(old_val, 4),
            "to": round(new_val, 4),
            "delta": round(new_val - old_val, 4),
            "reason": reason,
        })

    def review(
        self,
        content: str,
        image_descriptions: List[str] = None,
        image_paths: List[str] = None,
        client_id: str = "anonymous",
        model_name: str = None,
        api_key: str = None,
        skip_cache: bool = False,
    ) -> ReviewResult:
        start_time = time.time()

        _demo_keys = {"demo-key", "demo-key-insurance-review-2024", "test", ""}
        if api_key and api_key not in _demo_keys and (api_key.startswith("sk-") or len(api_key) >= 20):
            config.DASHSCOPE_API_KEY = api_key
            config.save_user_config(api_key=api_key)
            if model_name and model_name.strip():
                config.LLM_MODEL = model_name.strip()
                config.EXTRACT_MODEL = model_name.strip()
                config.REASON_MODEL = model_name.strip()
                config.CROSSCHECK_MODEL = model_name.strip()
                config.save_user_config(model_name=model_name.strip())
            llm_gateway._register_default_models()
            if hasattr(self, 'rag_engine') and self.rag_engine:
                self.rag_engine.enable_vector_search()

        if model_name and config.has_api_key():
            llm_gateway.ensure_model(model_name)
            self.extract_model = model_name
            self.reason_model = model_name
            self.crosscheck_model = model_name
            if model_name not in (config.LLM_MODEL, config.EXTRACT_MODEL, config.REASON_MODEL, config.CROSSCHECK_MODEL):
                config.LLM_MODEL = model_name
                config.EXTRACT_MODEL = model_name
                config.REASON_MODEL = model_name
                config.CROSSCHECK_MODEL = model_name
                config.save_user_config(model_name=model_name)
        elif config.has_api_key():
            self.extract_model = config.EXTRACT_MODEL
            self.reason_model = config.REASON_MODEL
            self.crosscheck_model = config.CROSSCHECK_MODEL

        validation = security_middleware.validate_and_sanitize(content, client_id)
        if not validation.is_valid:
            if not image_paths and not image_descriptions:
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
            validation = type(validation)(
                is_valid=True,
                sanitized_input=content or "",
                threats=[],
                risk_level="low",
            )

        sanitized_content = validation.sanitized_input

        if model_name and config.has_api_key():
            llm_gateway.ensure_model(model_name)
            self.extract_model = model_name
            self.reason_model = model_name
            self.crosscheck_model = model_name

        if image_descriptions:
            full_content = sanitized_content + "\n\n[图片描述信息]\n" + "\n".join(
                f"图片{i+1}: {desc}" for i, desc in enumerate(image_descriptions)
            )
        else:
            full_content = sanitized_content

        cache_key_content = full_content
        if image_paths:
            cache_key_content += "\n[图片文件]" + "|".join(sorted(image_paths))
        cache_key = hashlib.sha256(cache_key_content.encode()).hexdigest()
        if not skip_cache:
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
            image_paths=image_paths or [],
        )

        _trace = trace_operation or _noop_trace
        with _trace("review_workflow", {"client": client_id}):
            state = self._workflow.run(state)

        result_data = state.validation_result or {}
        llm_actually_worked = bool(state.model_used) and "rule" not in state.model_used
        if not config.has_api_key():
            review_mode = "rule" if (state.rule_check_result and state.rule_check_result.get("hit")) else "no_api"
        elif llm_actually_worked:
            review_mode = "rule+llm" if (state.rule_check_result and state.rule_check_result.get("hit")) else "llm"
        else:
            review_mode = "rule(fallback)" if (state.rule_check_result and state.rule_check_result.get("hit")) else "fallback"
        state.metadata["review_mode"] = review_mode

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

        violations = result_data.get("violations", [])
        violation_type_str = "、".join(v.get("violation_type_name", "") for v in violations if v.get("violation_type_name"))
        all_violated_articles = []
        for v in violations:
            all_violated_articles.extend(v.get("violated_articles", []))
        violation_types_list = [
            {
                "violation_type_id": v.get("violation_type_id", ""),
                "violation_type_name": v.get("violation_type_name", ""),
            }
            for v in violations
            if v.get("violation_type_name")
        ]

        raw_confidence = result_data.get("confidence", 0.0)
        try:
            raw_confidence = round(float(raw_confidence), 2)
        except (ValueError, TypeError):
            raw_confidence = 0.5

        result = ReviewResult(
            compliant=result_data.get("compliant", "unknown"),
            violation_type=violation_type_str,
            violated_articles=all_violated_articles,
            confidence=raw_confidence,
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
            expanded_relations=state.expanded_relations,
            violation_types=violation_types_list if violation_types_list else None,
            violations=violations if violations else None,
            metadata=dict(state.metadata),
            confidence_source=state.metadata.get("confidence_source"),
            risk_breakdown=state.metadata.get("risk_assessment", {}).get("score_breakdown"),
        )

        if not result.violation_types and result.violation_type:
            result.violation_types = self._build_violation_types_for_save(result.violation_type)
            deprecated_names = self._mark_deprecated_types(result.violation_type)
            if deprecated_names:
                result.violation_type = self._append_deprecated_marks(result.violation_type, deprecated_names)

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

    def _mark_deprecated_types(self, violation_type_str: str) -> Dict[str, bool]:
        deprecated_names = {}
        type_names = [t.strip() for t in violation_type_str.split("、") if t.strip()]
        for name in type_names:
            for vt in violation_registry._types.values():
                if vt.name == name and vt.status == "deprecated":
                    deprecated_names[name] = True
                    break
        return deprecated_names

    def _append_deprecated_marks(self, violation_type_str: str, deprecated_names: Dict[str, bool]) -> str:
        type_names = [t.strip() for t in violation_type_str.split("、") if t.strip()]
        marked = []
        for name in type_names:
            if deprecated_names.get(name):
                marked.append(f"{name}[该类型已废弃]")
            else:
                marked.append(name)
        return "、".join(marked)

    def _build_violation_types_for_save(self, violation_type_str: str) -> List[Dict]:
        result = []
        type_names = [t.strip() for t in violation_type_str.split("、") if t.strip()]
        for name in type_names:
            matched = None
            for vt in violation_registry._types.values():
                if vt.name == name:
                    matched = vt
                    break
            if matched:
                result.append({
                    "violation_type_id": matched.id,
                    "violation_type_name": matched.name,
                    "is_deprecated": matched.status == "deprecated",
                })
            else:
                result.append({
                    "violation_type_id": "other_violation",
                    "violation_type_name": name,
                    "is_deprecated": False,
                })
        return result

    def _preprocess_image(self, image_path: str) -> str:
        try:
            from PIL import Image
            img = Image.open(image_path)
            if img.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if "A" in img.mode:
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            w, h = img.size
            scale = 3
            new_w, new_h = w * scale, h * scale
            img = img.resize((new_w, new_h), Image.LANCZOS)
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir=os.path.dirname(image_path))
            img.save(tmp.name, "JPEG", quality=95)
            tmp.close()
            logger.info(f"图片预处理: {image_path} ({w}x{h}) -> JPG {new_w}x{new_h}")
            return tmp.name
        except ImportError:
            logger.warning("PIL未安装，跳过图片预处理")
            return image_path
        except Exception as e:
            logger.warning(f"图片预处理失败 {image_path}: {e}")
            return image_path

    def _parse_json(self, text: str) -> Dict:
        text = text.strip()
        try:
            json_str = text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', json_str)
            json_str = re.sub(r'\t', ' ', json_str)
            json_str = re.sub(r' +', ' ', json_str)
            return json.loads(json_str)
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.warning(f"JSON解析失败，尝试修复: {e}")

        try:
            json_str = text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()

            json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', json_str)
            json_str = re.sub(r'\t', ' ', json_str)
            json_str = re.sub(r' +', ' ', json_str)

            if not json_str.strip().startswith("{"):
                idx = json_str.find("{")
                if idx >= 0:
                    json_str = json_str[idx:]

            json_str = self._repair_truncated_json(json_str)

            result = json.loads(json_str)
            logger.info(f"JSON修复成功")
            return result
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.error(f"JSON修复也失败: {e}")
            return {}

    def _repair_truncated_json(self, json_str: str) -> str:
        json_str = json_str.rstrip()
        if json_str.endswith(","):
            json_str = json_str[:-1]

        open_braces = json_str.count("{") - json_str.count("}")
        open_brackets = json_str.count("[") - json_str.count("]")
        suffix = ""
        if open_brackets > 0:
            suffix += "]" * open_brackets
        if open_braces > 0:
            suffix += "}" * open_braces

        try:
            json.loads(json_str + suffix)
            return json_str + suffix
        except (json.JSONDecodeError, ValueError):
            pass

        close_positions = []
        for i in range(len(json_str) - 1, -1, -1):
            if json_str[i] in '}]':
                close_positions.append(i)
            if len(close_positions) >= 20:
                break

        for pos in close_positions:
            prefix = json_str[:pos + 1]
            prefix = prefix.rstrip()
            if prefix.endswith(","):
                prefix = prefix[:-1]

            ob = prefix.count("{") - prefix.count("}")
            ok = prefix.count("[") - prefix.count("]")
            s = ""
            if ok > 0:
                s += "]" * ok
            if ob > 0:
                s += "}" * ob

            try:
                json.loads(prefix + s)
                return prefix + s
            except (json.JSONDecodeError, ValueError):
                continue

        return json_str + suffix

    def _generate_suggestions(self, violation_types: List[str]) -> str:
        suggestions = [violation_registry.get_suggestion(vt) for vt in violation_types]
        return "；".join(suggestions) if suggestions else "请修改营销内容。"

    def _resolve_violation_type_ids(self, result: Dict):
        violations = result.get("violations", [])
        if violations and isinstance(violations, list):
            for v in violations:
                if not isinstance(v, dict):
                    continue
                type_id = v.get("violation_type_id", "")
                type_name = v.get("violation_type_name", "")
                if type_id:
                    matched = violation_registry.get_type(type_id)
                    if matched and matched.status == "active":
                        v["violation_type_name"] = matched.name
                    elif not type_name:
                        v["violation_type_name"] = type_id
            return

        violation_types_raw = result.get("violation_types", [])
        if not violation_types_raw or not isinstance(violation_types_raw, list):
            return
        resolved_names = []
        for vt_item in violation_types_raw:
            if not isinstance(vt_item, dict):
                continue
            type_id = vt_item.get("violation_type_id", "")
            type_name = vt_item.get("violation_type_name", "")
            if type_id:
                matched = violation_registry.get_type(type_id)
                if matched and matched.status == "active":
                    resolved_names.append(matched.name)
                elif type_name:
                    resolved_names.append(type_name)
            elif type_name:
                resolved_names.append(type_name)
        if resolved_names:
            result["violation_type"] = "、".join(resolved_names)

    def _normalize_to_violations(self, result: Dict) -> Dict:
        if result.get("violations") and isinstance(result["violations"], list):
            return result

        violations = []
        violation_type_str = result.get("violation_type", "")
        violation_types_raw = result.get("violation_types", [])
        violated_articles_raw = result.get("violated_articles", [])

        if violation_types_raw and isinstance(violation_types_raw, list):
            for vt_item in violation_types_raw:
                if not isinstance(vt_item, dict):
                    continue
                vt_name = vt_item.get("violation_type_name", "")
                vt_id = vt_item.get("violation_type_id", "")
                vt_reasoning = vt_item.get("reasoning", "")
                matched_articles = []
                for a in violated_articles_raw:
                    if not isinstance(a, dict):
                        continue
                    a_vt = a.get("violation_type", a.get("violation_type_name", ""))
                    if a_vt == vt_name or (not a_vt and not matched_articles):
                        matched_articles.append(a)
                if not matched_articles and len(violation_types_raw) == 1:
                    matched_articles = [a for a in violated_articles_raw if isinstance(a, dict)]
                v_entry = {
                    "violation_type_id": vt_id,
                    "violation_type_name": vt_name,
                    "violated_articles": matched_articles,
                }
                if vt_reasoning:
                    v_entry["reasoning"] = vt_reasoning
                violations.append(v_entry)
        elif violation_type_str:
            type_names = [t.strip() for t in violation_type_str.split("、") if t.strip()]
            if len(type_names) <= 1:
                vt_name = type_names[0] if type_names else violation_type_str
                vt_id = ""
                matched = violation_registry.get_type_by_name(vt_name)
                if matched:
                    vt_id = matched.id
                violations.append({
                    "violation_type_id": vt_id,
                    "violation_type_name": vt_name,
                    "violated_articles": [a for a in violated_articles_raw if isinstance(a, dict)],
                })
            else:
                for vt_name in type_names:
                    vt_id = ""
                    matched = violation_registry.get_type_by_name(vt_name)
                    if matched:
                        vt_id = matched.id
                    vt_articles = [
                        a for a in violated_articles_raw
                        if isinstance(a, dict) and (a.get("violation_type", a.get("violation_type_name", "")) == vt_name)
                    ]
                    violations.append({
                        "violation_type_id": vt_id,
                        "violation_type_name": vt_name,
                        "violated_articles": vt_articles,
                    })
                unassigned = [
                    a for a in violated_articles_raw
                    if isinstance(a, dict)
                    and not any(a.get("violation_type", a.get("violation_type_name", "")) == v.get("violation_type_name") for v in violations)
                ]
                if unassigned and violations:
                    violations[0]["violated_articles"].extend(unassigned)
        elif violated_articles_raw:
            violations.append({
                "violation_type_id": "other_violation",
                "violation_type_name": "其他违规",
                "violated_articles": [a for a in violated_articles_raw if isinstance(a, dict)],
            })

        for key in ("violation_type", "violation_types", "violated_articles"):
            result.pop(key, None)
        result["violations"] = violations
        return result

    def _build_violations_from_rule(self, type_names: List[str], violated_articles: List[Dict]) -> List[Dict]:
        violations = []
        assigned_indices = set()
        for vt_name in type_names:
            vt_name = vt_name.strip()
            if not vt_name:
                continue
            vt_id = ""
            vt_desc = ""
            matched = violation_registry.get_type_by_name(vt_name)
            if matched:
                vt_id = matched.id
                vt_desc = matched.description or ""
            vt_articles = []
            for idx, a in enumerate(violated_articles):
                if idx in assigned_indices:
                    continue
                if a.get("violation_type", a.get("violation_type_name", "")) == vt_name:
                    vt_articles.append(a)
                    assigned_indices.add(idx)
            if not vt_articles and len(type_names) == 1:
                vt_articles = list(violated_articles)
            if vt_articles:
                kw_list = [a.get("violation_reason", "") for a in vt_articles if a.get("violation_reason")]
                reasoning = vt_desc or f"规则引擎命中{vt_name}"
                if kw_list:
                    reasoning += f"（{'; '.join(kw_list[:3])}）"
                violations.append({
                    "violation_type_id": vt_id,
                    "violation_type_name": vt_name,
                    "reasoning": reasoning,
                    "violated_articles": vt_articles,
                })
        unassigned = [a for idx, a in enumerate(violated_articles) if idx not in assigned_indices]
        if unassigned and violations:
            violations[0]["violated_articles"].extend(unassigned)
        if not violations and violated_articles:
            violations.append({
                "violation_type_id": "other_violation",
                "violation_type_name": "其他违规",
                "violated_articles": list(violated_articles),
            })
        return violations


def _noop_trace(operation, attributes=None):
    from contextlib import nullcontext
    return nullcontext()
