import os
import json
import re
import logging
import hashlib
import time
from typing import List, Dict, Optional
import config
from src.document_processor import DocumentProcessor, RegulationChunk, ChunkStrategyType
from src.resilience import (
    llm_circuit_breaker,
    embedding_circuit_breaker,
    review_cache,
    with_retry,
    RetryPolicy,
    CircuitBreaker,
)

logger = logging.getLogger(__name__)


class RAGEngine:
    def __init__(self):
        self.processor = DocumentProcessor()
        self.chunks: List[RegulationChunk] = []
        self.collection = None
        self.client = None
        self.use_vector = False
        self._index_version = ""

    def build_index(
        self,
        force_rebuild: bool = False,
        strategy: ChunkStrategyType = ChunkStrategyType.ARTICLE,
    ):
        self.chunks = self.processor.load_all_regulations(strategy=strategy)
        self._index_version = hashlib.md5(
            "|".join(c.content_hash for c in self.chunks).encode()
        ).hexdigest()[:8]
        logger.info(f"索引版本: {self._index_version}, 条文数: {len(self.chunks)}")

        if config.DEMO_MODE:
            logger.warning("未检测到 DASHSCOPE_API_KEY，使用关键词检索模式")
            self.use_vector = False
            return

        if not force_rebuild and self._load_existing_index():
            logger.info("已加载现有向量索引")
            self.use_vector = True
            return

        try:
            self._build_vector_index()
            self.use_vector = True
        except Exception as e:
            logger.error(f"向量索引构建失败: {e}")
            logger.info("回退到关键词检索模式")
            self.use_vector = False

    def _build_vector_index(self):
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = config.DASHSCOPE_API_KEY

        logger.info("开始构建向量索引...")
        texts = [chunk.article_text for chunk in self.chunks]
        metadatas = [
            {
                "doc_name": chunk.doc_name,
                "chapter": chunk.chapter,
                "article_number": chunk.article_number,
                "chunk_id": chunk.chunk_id,
                "content_hash": chunk.content_hash,
                "index_version": self._index_version,
            }
            for chunk in self.chunks
        ]
        ids = [chunk.chunk_id for chunk in self.chunks]

        logger.info(f"正在生成 {len(texts)} 条文本的向量...")
        embeddings = self._get_embeddings_with_retry(texts)

        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=config.VECTOR_STORE_DIR,
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name="regulations",
            metadata={
                "hnsw:space": "cosine",
                "index_version": self._index_version,
            },
        )

        if self.collection.count() > 0:
            self.collection.delete(where={})

        batch_size = 100
        for i in range(0, len(ids), batch_size):
            end = min(i + batch_size, len(ids))
            self.collection.add(
                ids=ids[i:end],
                embeddings=embeddings[i:end],
                documents=texts[i:end],
                metadatas=metadatas[i:end],
            )

        logger.info(f"向量索引构建完成，共 {self.collection.count()} 条")

    @with_retry(
        policy=RetryPolicy(max_retries=3, base_delay=1.0),
        circuit_breaker=embedding_circuit_breaker,
    )
    def _get_embeddings_with_retry(self, texts: List[str]) -> List[List[float]]:
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = config.DASHSCOPE_API_KEY

        all_embeddings = []
        batch_size = 25
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = TextEmbedding.call(
                model=config.EMBEDDING_MODEL,
                input=batch,
                dimension=1024,
            )
            if resp.status_code == 200:
                for item in resp.output["embeddings"]:
                    all_embeddings.append(item["embedding"])
            else:
                raise RuntimeError(
                    f"Embedding API调用失败: {resp.status_code} - {resp.message}"
                )
        return all_embeddings

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._get_embeddings_with_retry(texts)

    def _load_existing_index(self) -> bool:
        if not os.path.exists(config.VECTOR_STORE_DIR):
            return False
        try:
            import chromadb
            from chromadb.config import Settings

            self.client = chromadb.PersistentClient(
                path=config.VECTOR_STORE_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
            self.collection = self.client.get_or_create_collection(
                name="regulations",
                metadata={"hnsw:space": "cosine"},
            )
            if self.collection.count() == 0:
                return False

            results = self.collection.get(include=["metadatas", "documents"])
            self.chunks = []
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i]
                self.chunks.append(RegulationChunk(
                    doc_name=meta["doc_name"],
                    chapter=meta["chapter"],
                    article_number=meta["article_number"],
                    article_text=results["documents"][i],
                    chunk_id=meta["chunk_id"],
                ))
            return True
        except Exception as e:
            logger.error(f"加载现有索引失败: {e}")
            return False

    def _keyword_retrieve(self, query: str, top_k: int = None) -> List[Dict]:
        top_k = top_k or config.TOP_K

        violation_keywords = {
            "稳赚不赔": ["二十一", "九", "十六"],
            "保本保息": ["二十一", "九", "十六"],
            "无风险": ["二十一", "九", "十六"],
            "零风险": ["二十一", "九", "十六"],
            "保证收益": ["十", "十二", "十六"],
            "承诺": ["十", "十二", "二十一"],
            "夸大": ["十二", "二十", "二十一", "十六"],
            "存款": ["十三", "十六", "二十三"],
            "理财": ["十三", "十六", "二十三"],
            "基金": ["十三", "十六", "二十三"],
            "代言": ["二十", "二十一"],
            "明星": ["二十"],
            "网红": ["二十"],
            "主播": ["二十"],
            "赠送": ["六", "二十三", "十六"],
            "返利": ["十四"],
            "红包": ["十四"],
            "诱导": ["六", "十二", "十四", "十六"],
            "隐瞒": ["十二", "二十一", "十六"],
            "资质": ["四", "五", "七", "八"],
            "风险提示": ["九", "十一", "十五"],
            "犹豫期": ["十六"],
            "退保": ["十六", "十八"],
            "个人信息": ["二十二", "二十三", "二十四"],
            "强制": ["十二", "十七"],
            "收益": ["十", "十二", "二十一"],
            "混淆": ["十三", "十六", "二十三"],
        }

        scored_chunks = []
        query_lower = query.lower()

        for chunk in self.chunks:
            score = 0.0

            for keyword, related_articles in violation_keywords.items():
                if keyword in query_lower:
                    if chunk.article_number in related_articles:
                        score += 3.0

            query_chars = set(query_lower)
            chunk_chars = set(chunk.article_text)
            overlap = query_chars & chunk_chars
            if len(query_chars) > 0:
                score += len(overlap) / len(query_chars) * 1.0

            for char in query_lower:
                if len(char) > 0 and char in chunk.article_text:
                    score += 0.1

            if score > 0:
                scored_chunks.append((chunk, score))

        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        results = []
        for chunk, score in scored_chunks[:top_k]:
            max_score = scored_chunks[0][1] if scored_chunks else 1
            similarity = min(score / max(max_score, 1), 1.0)
            if similarity < config.SIMILARITY_THRESHOLD:
                continue
            results.append({
                "doc_name": chunk.doc_name,
                "chapter": chunk.chapter,
                "article_number": chunk.article_number,
                "chunk_id": chunk.chunk_id,
                "article_text": chunk.article_text,
                "similarity": round(similarity, 4),
            })

        return results

    def _vector_retrieve(self, query: str, top_k: int = None) -> List[Dict]:
        top_k = top_k or config.TOP_K

        @with_retry(
            policy=RetryPolicy(max_retries=2, base_delay=0.5),
            circuit_breaker=embedding_circuit_breaker,
        )
        def _do_query():
            query_embeddings = self._get_embeddings([query])
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            return results

        results = _do_query()

        retrieved = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            similarity = 1 - distance
            if similarity < config.SIMILARITY_THRESHOLD:
                continue
            retrieved.append({
                "doc_name": results["metadatas"][0][i]["doc_name"],
                "chapter": results["metadatas"][0][i]["chapter"],
                "article_number": results["metadatas"][0][i]["article_number"],
                "chunk_id": results["metadatas"][0][i]["chunk_id"],
                "article_text": results["documents"][0][i],
                "similarity": round(similarity, 4),
            })

        retrieved.sort(key=lambda x: x["similarity"], reverse=True)
        return retrieved

    def retrieve(self, query: str, top_k: int = None) -> List[Dict]:
        if self.use_vector and self.collection is not None:
            try:
                return self._vector_retrieve(query, top_k)
            except Exception as e:
                logger.warning(f"向量检索失败，降级到关键词检索: {e}")
                return self._keyword_retrieve(query, top_k)
        else:
            return self._keyword_retrieve(query, top_k)

    def format_retrieved_context(self, retrieved: List[Dict]) -> str:
        if not retrieved:
            return "未检索到相关法规条文。"

        context_parts = []
        for i, item in enumerate(retrieved, 1):
            context_parts.append(
                f"[{i}] 《{item['doc_name']}》{item['chapter']} - "
                f"第{item['article_number']}条 (相关度: {item['similarity']})\n"
                f"原文: {item['article_text']}"
            )
        return "\n\n".join(context_parts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = RAGEngine()
    engine.build_index()
    results = engine.retrieve("保险产品承诺保本保息")
    context = engine.format_retrieved_context(results)
    print(context)
