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
        self.vectorize_progress = {"status": "idle", "current": 0, "total": 0, "message": ""}

    def build_index(
        self,
        force_rebuild: bool = False,
        strategy: ChunkStrategyType = ChunkStrategyType.ARTICLE,
    ):
        self.chunks = self.processor.load_all_regulations(strategy=strategy)
        self._deduplicate_chunks()

        if len(self.chunks) == 0:
            logger.warning("文件解析未获得任何条款，尝试从数据库加载")
            self._load_chunks_from_database()

        if len(self.chunks) == 0:
            logger.error("无法获取任何法规条款（文件解析和数据库均为空）")

        self._index_version = hashlib.md5(
            "|".join(c.content_hash for c in self.chunks).encode()
        ).hexdigest()[:8]
        logger.info(f"索引版本: {self._index_version}, 条文数: {len(self.chunks)}")

        try:
            from src.database import Database
            db = Database()
            db.sync_chunks(self.chunks)
        except Exception as e:
            logger.warning(f"同步条款到数据库失败: {e}")

        if not config.has_api_key():
            logger.warning("未检测到 DASHSCOPE_API_KEY，使用关键词检索模式")
            self.use_vector = False
            return

        if force_rebuild:
            try:
                self._build_vector_index()
                self.use_vector = True
            except Exception as e:
                logger.error(f"向量索引构建失败: {e}")
                logger.info("回退到关键词检索模式")
                self.use_vector = False
            return

        if self._try_incremental_update():
            self.use_vector = True
            return

        try:
            self._build_vector_index()
            self.use_vector = True
        except Exception as e:
            logger.error(f"向量索引构建失败: {e}")
            logger.info("回退到关键词检索模式")
            self.use_vector = False

    def _load_chunks_from_database(self):
        try:
            from src.database import Database
            db = Database()
            rows = db.get_chunks()
            if not rows:
                logger.warning("数据库中也没有条款数据")
                return
            for row in rows:
                chunk = RegulationChunk(
                    doc_name=row["doc_name"],
                    chapter=row.get("chapter", ""),
                    article_number=row["article_number"],
                    article_text=row["article_text"],
                    chunk_id=row.get("chunk_id", f"{row['doc_name']}_{row['article_number']}"),
                    content_hash=row.get("content_hash", ""),
                    source_format=row.get("source_format", ""),
                )
                if not chunk.content_hash:
                    chunk.content_hash = chunk.compute_hash()
                self.chunks.append(chunk)
            logger.info(f"从数据库加载了 {len(self.chunks)} 条法规条款")
        except Exception as e:
            logger.error(f"从数据库加载条款失败: {e}")

    def _deduplicate_chunks(self):
        seen = {}
        for c in self.chunks:
            key = (c.doc_name, c.article_number)
            if key not in seen:
                seen[key] = c
            else:
                existing = seen[key]
                if len(c.article_text) > len(existing.article_text):
                    seen[key] = c
        original_count = len(self.chunks)
        self.chunks = list(seen.values())
        if len(self.chunks) < original_count:
            logger.info(f"条款去重: {original_count} → {len(self.chunks)}（移除 {original_count - len(self.chunks)} 条重复/空条款）")

    def enable_vector_search(self):
        if self.use_vector:
            return True
        if not config.DASHSCOPE_API_KEY:
            logger.error("无法启用向量检索: DASHSCOPE_API_KEY 未配置")
            return False
        if len(self.chunks) == 0:
            logger.error("无法启用向量检索: 没有可向量化的法规条款")
            return False
        try:
            import dashscope
            dashscope.api_key = config.DASHSCOPE_API_KEY
            self._build_vector_index()
            self.use_vector = True
            logger.info(f"向量检索已启用，索引版本: {self._index_version}，条文数: {len(self.chunks)}")
            return True
        except Exception as e:
            logger.error(f"向量索引构建失败: {e}")
            self.use_vector = False
            return False

    def _compute_doc_hashes(self, chunks: List[RegulationChunk]) -> Dict[str, str]:
        doc_chunk_hashes: Dict[str, List[str]] = {}
        for chunk in chunks:
            doc_chunk_hashes.setdefault(chunk.doc_name, []).append(chunk.content_hash)
        doc_hashes = {}
        for doc_name, hashes in doc_chunk_hashes.items():
            combined = "|".join(sorted(hashes))
            doc_hashes[doc_name] = hashlib.md5(combined.encode()).hexdigest()[:16]
        return doc_hashes

    def _get_stored_doc_hashes(self) -> Dict[str, str]:
        if self.collection is None or self.collection.count() == 0:
            return {}
        results = self.collection.get(include=["metadatas"])
        doc_hashes = {}
        for meta in results["metadatas"]:
            doc_name = meta["doc_name"]
            doc_hash = meta.get("doc_content_hash", "")
            if doc_name not in doc_hashes and doc_hash:
                doc_hashes[doc_name] = doc_hash
        return doc_hashes

    def _try_incremental_update(self) -> bool:
        try:
            import chromadb
            from chromadb.config import Settings

            if not os.path.exists(config.VECTOR_STORE_DIR):
                return False

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

            current_doc_hashes = self._compute_doc_hashes(self.chunks)
            stored_doc_hashes = self._get_stored_doc_hashes()

            changed_docs = set()
            new_docs = set()
            removed_docs = set()

            for doc_name, doc_hash in current_doc_hashes.items():
                if doc_name not in stored_doc_hashes:
                    new_docs.add(doc_name)
                elif stored_doc_hashes[doc_name] != doc_hash:
                    changed_docs.add(doc_name)

            for doc_name in stored_doc_hashes:
                if doc_name not in current_doc_hashes:
                    removed_docs.add(doc_name)

            if not changed_docs and not new_docs and not removed_docs:
                self._load_chunks_from_collection()
                logger.info("所有文档未变化，已加载现有向量索引")
                return True

            docs_to_remove = changed_docs | removed_docs
            for doc_name in docs_to_remove:
                self.collection.delete(where={"doc_name": doc_name})
                logger.info(f"已删除文档向量: {doc_name}")

            docs_to_add = new_docs | changed_docs
            chunks_to_add = [c for c in self.chunks if c.doc_name in docs_to_add]

            if chunks_to_add:
                self._add_chunks_to_collection(chunks_to_add)

            self._load_chunks_from_collection()

            logger.info(
                f"增量更新: 新增={len(new_docs)}, 变更={len(changed_docs)}, "
                f"删除={len(removed_docs)}, 新增向量={len(chunks_to_add)}"
            )
            return True

        except Exception as e:
            logger.error(f"增量更新失败: {e}")
            return False

    def _add_chunks_to_collection(self, chunks: List[RegulationChunk]):
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = config.DASHSCOPE_API_KEY

        doc_hashes = self._compute_doc_hashes(chunks)

        texts = [chunk.article_text for chunk in chunks]
        metadatas = [
            {
                "doc_name": chunk.doc_name,
                "chapter": chunk.chapter,
                "article_number": chunk.article_number,
                "chunk_id": chunk.chunk_id,
                "content_hash": chunk.content_hash,
                "doc_content_hash": doc_hashes.get(chunk.doc_name, ""),
                "index_version": self._index_version,
            }
            for chunk in chunks
        ]
        ids = [chunk.chunk_id for chunk in chunks]

        logger.info(f"正在生成 {len(texts)} 条文本的向量...")
        embeddings = self._get_embeddings_with_retry(texts)

        batch_size = 100
        for i in range(0, len(ids), batch_size):
            end = min(i + batch_size, len(ids))
            self.collection.add(
                ids=ids[i:end],
                embeddings=embeddings[i:end],
                documents=texts[i:end],
                metadatas=metadatas[i:end],
            )

    def _load_chunks_from_collection(self):
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

    def _build_vector_index(self):
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = config.DASHSCOPE_API_KEY

        logger.info("开始构建向量索引...")
        texts = [chunk.article_text for chunk in self.chunks]
        doc_hashes = self._compute_doc_hashes(self.chunks)
        metadatas = [
            {
                "doc_name": chunk.doc_name,
                "chapter": chunk.chapter,
                "article_number": chunk.article_number,
                "chunk_id": chunk.chunk_id,
                "content_hash": chunk.content_hash,
                "doc_content_hash": doc_hashes.get(chunk.doc_name, ""),
                "index_version": self._index_version,
            }
            for chunk in self.chunks
        ]
        ids = [chunk.chunk_id for chunk in self.chunks]

        total = len(texts)
        self.vectorize_progress = {"status": "embedding", "current": 0, "total": total, "message": f"正在生成向量 (0/{total})"}
        logger.info(f"正在生成 {total} 条文本的向量...")

        all_embeddings = []
        batch_size = config.EMBEDDING_BATCH_SIZE
        _embed_start = __import__('time').time()
        _embed_success = True
        for i in range(0, total, batch_size):
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
                _embed_success = False
                raise RuntimeError(
                    f"Embedding API调用失败: {resp.status_code} - {resp.message}"
                )
            current = min(i + batch_size, total)
            self.vectorize_progress = {"status": "embedding", "current": current, "total": total, "message": f"正在生成向量 ({current}/{total})"}

        _embed_lat = (__import__('time').time() - _embed_start) * 1000
        try:
            from src.llm_gateway import _write_audit_log
            _write_audit_log(
                config.EMBEDDING_MODEL,
                f"向量化 {total} 条法规条款",
                f"batch_size={batch_size}, dimension=1024",
                f"成功生成 {len(all_embeddings)} 条向量" if _embed_success else "失败",
                _embed_lat, _embed_success,
                error_type=None if _embed_success else "EmbeddingError",
            )
        except Exception:
            pass

        self.vectorize_progress = {"status": "storing", "current": total, "total": total, "message": "正在存储向量..."}

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

        add_batch_size = 100
        for i in range(0, len(ids), add_batch_size):
            end = min(i + add_batch_size, len(ids))
            self.collection.add(
                ids=ids[i:end],
                embeddings=all_embeddings[i:end],
                documents=texts[i:end],
                metadatas=metadatas[i:end],
            )

        logger.info(f"向量索引构建完成，共 {self.collection.count()} 条")
        self.vectorize_progress = {"status": "done", "current": total, "total": total, "message": "向量化完成"}

    @with_retry(
        policy=RetryPolicy(max_retries=3, base_delay=1.0),
        circuit_breaker=embedding_circuit_breaker,
    )
    def _get_embeddings_with_retry(self, texts: List[str]) -> List[List[float]]:
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = config.DASHSCOPE_API_KEY

        all_embeddings = []
        batch_size = config.EMBEDDING_BATCH_SIZE
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
        _start = time.time()
        _success = True
        _count = len(texts)
        try:
            result = self._get_embeddings_with_retry(texts)
            return result
        except Exception as e:
            _success = False
            raise
        finally:
            _lat = (time.time() - _start) * 1000
            try:
                from src.llm_gateway import _write_audit_log
                _write_audit_log(
                    config.EMBEDDING_MODEL,
                    f"Embedding查询 ({_count}条文本)",
                    texts[0][:200] if texts else "",
                    f"成功生成 {_count} 条向量" if _success else "失败",
                    _lat, _success,
                    error_type=None if _success else "EmbeddingError",
                )
            except Exception:
                pass

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

    def rebuild_vector_index(self, strategy: ChunkStrategyType = ChunkStrategyType.ARTICLE):
        logger.info("强制重建向量索引...")
        self.build_index(force_rebuild=True, strategy=strategy)

    def get_vectorization_status(self) -> Dict:
        total_chunks = len(self.chunks)
        vectorized_count = 0
        if self.collection is not None:
            try:
                vectorized_count = self.collection.count()
            except Exception:
                vectorized_count = 0

        status = {
            "use_vector": self.use_vector,
            "total_chunks": total_chunks,
            "vectorized_count": vectorized_count,
            "not_vectorized_count": max(0, total_chunks - vectorized_count),
            "index_version": self._index_version,
            "documents": {},
        }

        if self.collection is not None and vectorized_count > 0:
            results = self.collection.get(include=["metadatas"])
            for meta in results["metadatas"]:
                doc_name = meta["doc_name"]
                if doc_name not in status["documents"]:
                    status["documents"][doc_name] = {
                        "content_hash": meta.get("doc_content_hash", ""),
                        "chunk_count": 0,
                    }
                status["documents"][doc_name]["chunk_count"] += 1
        elif self.chunks:
            doc_hashes = self._compute_doc_hashes(self.chunks)
            doc_chunk_counts: Dict[str, int] = {}
            for chunk in self.chunks:
                doc_chunk_counts[chunk.doc_name] = doc_chunk_counts.get(chunk.doc_name, 0) + 1
            for doc_name, count in doc_chunk_counts.items():
                status["documents"][doc_name] = {
                    "content_hash": doc_hashes.get(doc_name, ""),
                    "chunk_count": count,
                }

        return status

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
            article_text = item['article_text']
            if len(article_text) > 300:
                article_text = article_text[:300] + "..."
            context_parts.append(
                f"[{i}] 《{item['doc_name']}》{item['chapter']} - "
                f"第{item['article_number']}条 (相关度: {item['similarity']})\n"
                f"原文: {article_text}"
            )
        return "\n\n".join(context_parts)

    def get_all_chunks(self):
        if not self.collection:
            return []
        try:
            results = self.collection.get(include=["metadatas", "documents"])
            chunks = []
            for i, doc in enumerate(results['documents']):
                meta = results['metadatas'][i] if results['metadatas'] else {}
                chunks.append({
                    'doc_name': meta.get('doc_name', ''),
                    'article_number': meta.get('article_number', ''),
                    'article_text': doc or '',
                })
            return chunks
        except Exception as e:
            logger.warning(f"获取所有chunks失败: {e}")
            return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = RAGEngine()
    engine.build_index()
    results = engine.retrieve("保险产品承诺保本保息")
    context = engine.format_retrieved_context(results)
    print(context)
