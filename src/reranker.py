import logging
import time
import json as _json
import os as _os
from datetime import datetime as _datetime
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_rerank_audit_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "llm_audit")
_os.makedirs(_rerank_audit_dir, exist_ok=True)

def _write_rerank_audit_log(model_name, query_preview, doc_count, doc_names, reranked_results, latency_ms, success, error_type=None, review_id=None):
    try:
        ts = _datetime.now().strftime("%Y%m%d")
        log_file = _os.path.join(_rerank_audit_dir, f"llm_audit_{ts}.jsonl")
        doc_info = "; ".join(doc_names[:10]) if doc_names else f"{doc_count}条条款"
        if reranked_results:
            result_lines = []
            for d in reranked_results[:10]:
                name = f"{d.get('doc_name','')}第{d.get('article_number','')}条"
                score = d.get("rerank_score", 0)
                result_lines.append(f"{name}(score={score})")
            response_text = "重排结果: " + "; ".join(result_lines)
        else:
            response_text = f"查询: {query_preview[:150]}"
        entry = {
            "timestamp": _datetime.now().isoformat(),
            "model": model_name,
            "step_name": "rerank",
            "user_prompt": f"[Rerank] 对{doc_count}条法规条款重排序: {doc_info}",
            "response": response_text,
            "latency_ms": round(latency_ms, 1),
            "success": success,
        }
        if error_type:
            entry["error_type"] = error_type
        if review_id is not None:
            entry["review_id"] = review_id
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


class Reranker:
    def __init__(self):
        self._model_name = getattr(config, "RERANKER_MODEL", "qwen3-rerank")

    def rerank(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = None,
        expand_context: bool = True,
    ) -> List[Dict]:
        if not documents:
            return []

        if top_k is None:
            top_k = config.RERANKER_TOP_K

        if config.DASHSCOPE_API_KEY:
            try:
                result = self._cross_encoder_rerank(query, documents, top_k)
            except Exception as e:
                logger.warning(f"Cross-Encoder重排失败: {e}，降级到规则重排")
                result = self._rule_based_rerank(query, documents, top_k)
        else:
            logger.info("无API Key，使用规则重排")
            result = self._rule_based_rerank(query, documents, top_k)

        if expand_context:
            result = self._expand_adjacent_articles(result, documents)

        return result

    def _cross_encoder_rerank(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        import dashscope
        from dashscope import TextReRank

        dashscope.api_key = config.DASHSCOPE_API_KEY
        doc_texts = [d.get("article_text", "") for d in documents]
        doc_names = [f"{d.get('doc_name','')}第{d.get('article_number','')}条" for d in documents[:10]]
        _start = time.time()

        for attempt in range(config.RERANKER_RETRY_MAX):
            try:
                resp = TextReRank.call(
                    model=self._model_name,
                    query=query,
                    documents=doc_texts,
                    top_n=min(top_k, len(doc_texts)),
                    return_documents=False,
                )
                if resp.status_code == 200:
                    results = resp.output.get("results", [])
                    scored = []
                    for r in results:
                        idx = r.get("index", 0)
                        score = r.get("relevance_score", 0.0)
                        doc_copy = dict(documents[idx])
                        doc_copy["rerank_score"] = round(score, 4)
                        doc_copy["rerank_method"] = "cross_encoder"
                        scored.append(doc_copy)
                    scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
                    _lat = (time.time() - _start) * 1000
                    _write_rerank_audit_log(self._model_name, query[:100], len(documents), doc_names, scored, _lat, True)
                    logger.info(f"Cross-Encoder重排完成: {len(scored)}条结果, 模型={self._model_name}")
                    return scored[:top_k]
                elif resp.status_code == 429:
                    logger.warning(f"Rerank API限流，等待重试 (attempt {attempt+1}/{config.RERANKER_RETRY_MAX})")
                    time.sleep(config.RERANKER_RETRY_DELAY * (attempt + 1))
                    continue
                else:
                    raise RuntimeError(f"Rerank API错误: status={resp.status_code}, code={resp.code}, msg={resp.message}")
            except Exception as e:
                if attempt < config.RERANKER_RETRY_MAX - 1 and ("Connection" in str(e) or "Timeout" in str(e) or "429" in str(e)):
                    logger.warning(f"Rerank API网络错误: {e}，等待重试")
                    time.sleep(config.RERANKER_RETRY_DELAY * (attempt + 1))
                    continue
                _lat = (time.time() - _start) * 1000
                _write_rerank_audit_log(self._model_name, query[:100], len(documents), doc_names, None, _lat, False, error_type=type(e).__name__)
                raise

        raise RuntimeError(f"Rerank API重试{config.RERANKER_RETRY_MAX}次均失败")

    def _rule_based_rerank(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        scored = []
        query_lower = query.lower()

        for doc in documents:
            score = doc.get("similarity", 0.5)
            article_text = doc.get("article_text", "").lower()

            query_words = set(query_lower) - set(" ，。！？、：；""''()（）[]【】")
            text_words = set(article_text) - set(" ，。！？、：；""''()（）[]【】")
            overlap = query_words & text_words
            if query_words:
                char_overlap = len(overlap) / len(query_words)
                score = score * 0.6 + char_overlap * 0.4

            violation_keywords = {
                "稳赚不赔": 1.5, "保本保息": 1.5, "无风险": 1.5, "零风险": 1.5,
                "承诺": 1.3, "保证": 1.3, "夸大": 1.3, "混淆": 1.3,
                "代言": 1.2, "赠送": 1.2, "返利": 1.2, "红包": 1.2,
            }
            for kw, boost in violation_keywords.items():
                if kw in query_lower and kw in article_text:
                    score *= boost

            doc_copy = dict(doc)
            doc_copy["rerank_score"] = round(min(score, 1.0), 4)
            doc_copy["rerank_method"] = "rule"
            scored.append(doc_copy)

        scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return scored[:top_k]

    def _expand_adjacent_articles(self, top_results: List[Dict], all_documents: List[Dict]) -> List[Dict]:
        if not top_results or not all_documents:
            return top_results

        doc_index = {}
        for doc in all_documents:
            doc_name = doc.get("doc_name", "")
            article_number = doc.get("article_number", "")
            if doc_name and article_number:
                key = f"{doc_name}::{article_number}"
                doc_index[key] = doc

        article_number_order = {}
        for doc in all_documents:
            doc_name = doc.get("doc_name", "")
            if doc_name not in article_number_order:
                article_number_order[doc_name] = []
            an = doc.get("article_number", "")
            if an and an not in article_number_order[doc_name]:
                article_number_order[doc_name].append(an)

        expanded = []
        seen_keys = set()
        for doc in top_results:
            doc_name = doc.get("doc_name", "")
            article_number = doc.get("article_number", "")
            key = f"{doc_name}::{article_number}"
            if key not in seen_keys:
                expanded.append(doc)
                seen_keys.add(key)

            if doc_name and article_number:
                articles_in_doc = article_number_order.get(doc_name, [])
                try:
                    idx = articles_in_doc.index(article_number)
                except ValueError:
                    idx = -1

                for offset in [-1, 1]:
                    adj_idx = idx + offset
                    if 0 <= adj_idx < len(articles_in_doc):
                        adj_an = articles_in_doc[adj_idx]
                        adj_key = f"{doc_name}::{adj_an}"
                        if adj_key not in seen_keys and adj_key in doc_index:
                            adj_doc = dict(doc_index[adj_key])
                            adj_doc["rerank_score"] = doc.get("rerank_score", 0) * config.RERANKER_ADJACENT_SCORE_FACTOR
                            adj_doc["context_type"] = "adjacent"
                            expanded.append(adj_doc)
                            seen_keys.add(adj_key)

        return expanded


reranker = Reranker()
