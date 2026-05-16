import logging
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self):
        self._model_name = getattr(config, "RERANKER_MODEL", "bge-reranker-v2-m3")

    def rerank(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 5,
    ) -> List[Dict]:
        if not documents:
            return []

        if config.DEMO_MODE:
            return self._rule_based_rerank(query, documents, top_k)

        try:
            return self._api_rerank(query, documents, top_k)
        except Exception as e:
            logger.warning(f"API重排失败，降级到规则重排: {e}")
            return self._rule_based_rerank(query, documents, top_k)

    def _api_rerank(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        try:
            import dashscope
            from dashscope import TextEmbedding

            dashscope.api_key = config.DASHSCOPE_API_KEY

            query_emb_resp = TextEmbedding.call(
                model=config.EMBEDDING_MODEL,
                input=[query],
                dimension=1024,
            )
            if query_emb_resp.status_code != 200:
                raise RuntimeError(f"Query embedding失败: {query_emb_resp.message}")
            query_emb = query_emb_resp.output["embeddings"][0]["embedding"]

            doc_texts = [d.get("article_text", "") for d in documents]
            batch_size = 25
            doc_embs = []
            for i in range(0, len(doc_texts), batch_size):
                batch = doc_texts[i:i + batch_size]
                resp = TextEmbedding.call(
                    model=config.EMBEDDING_MODEL,
                    input=batch,
                    dimension=1024,
                )
                if resp.status_code == 200:
                    doc_embs.extend([e["embedding"] for e in resp.output["embeddings"]])
                else:
                    raise RuntimeError(f"Doc embedding失败: {resp.message}")

            scored = []
            for i, (doc, doc_emb) in enumerate(zip(documents, doc_embs)):
                similarity = self._cosine_similarity(query_emb, doc_emb)
                doc_copy = dict(doc)
                doc_copy["rerank_score"] = round(similarity, 4)
                scored.append(doc_copy)

            scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            return scored[:top_k]

        except ImportError:
            raise RuntimeError("dashscope未安装")

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
            scored.append(doc_copy)

        scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return scored[:top_k]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


reranker = Reranker()
