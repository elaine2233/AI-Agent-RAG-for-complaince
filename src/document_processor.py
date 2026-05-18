import os
import re
import json
import hashlib
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum

import config
from src.interfaces import DocumentFormat, ParsedDocument
from src.document_parsers import parser_registry

logger = logging.getLogger(__name__)


class ChunkStrategyType(Enum):
    ARTICLE = "article"
    CHAPTER = "chapter"
    SEMANTIC = "semantic"
    FIXED = "fixed"


@dataclass
class RegulationChunk:
    doc_name: str
    chapter: str
    article_number: str
    article_text: str
    chunk_id: str
    chunk_index: int = 0
    token_count: int = 0
    parent_chapter: str = ""
    has_table: bool = False
    table_data: Optional[List[List[str]]] = None
    has_image: bool = False
    image_descriptions: Optional[List[str]] = None
    content_hash: str = ""
    source_format: str = ""

    def to_dict(self):
        d = asdict(self)
        if d["table_data"] is None:
            del d["table_data"]
        if d["image_descriptions"] is None:
            del d["image_descriptions"]
        return d

    def compute_hash(self) -> str:
        raw = f"{self.doc_name}:{self.article_number}:{self.article_text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text))


class DocumentProcessor:
    def __init__(self, regulations_dir: str = None):
        self.regulations_dir = regulations_dir or config.REGULATIONS_DIR
        self._chunk_cache: Dict[str, List[RegulationChunk]] = {}

    def load_all_regulations(
        self,
        strategy: ChunkStrategyType = ChunkStrategyType.ARTICLE,
        max_chunk_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> List[RegulationChunk]:
        cache_key = f"{strategy.value}_{max_chunk_tokens}_{overlap_tokens}"
        if cache_key in self._chunk_cache:
            return self._chunk_cache[cache_key]

        all_chunks = []
        if not os.path.exists(self.regulations_dir):
            raise FileNotFoundError(f"监管文档目录不存在: {self.regulations_dir}")

        for filename in sorted(os.listdir(self.regulations_dir)):
            filepath = os.path.join(self.regulations_dir, filename)
            if not os.path.isfile(filepath):
                continue

            try:
                parsed = parser_registry.parse(filepath)
            except ValueError:
                logger.warning(f"跳过不支持的文件格式: {filename}")
                continue

            if not parsed.raw_text:
                logger.warning(f"文件为空或解析失败: {filename}")
                continue

            doc_name = parsed.title or os.path.splitext(filename)[0]

            if strategy == ChunkStrategyType.ARTICLE:
                chunks = self._chunk_by_sections(parsed, doc_name, max_chunk_tokens, overlap_tokens)
            elif strategy == ChunkStrategyType.CHAPTER:
                chunks = self._chunk_by_chapter(parsed, doc_name, max_chunk_tokens, overlap_tokens)
            elif strategy == ChunkStrategyType.SEMANTIC:
                chunks = self._chunk_by_sections(parsed, doc_name, max_chunk_tokens, overlap_tokens)
            else:
                chunks = self._chunk_fixed(parsed, doc_name, max_chunk_tokens, overlap_tokens)

            all_chunks.extend(chunks)
            logger.info(f"已解析: {doc_name}, 格式={parsed.source_format.value}, 策略={strategy.value}, 共 {len(chunks)} 条")

        logger.info(f"总计解析 {len(all_chunks)} 条法规条文")
        self._chunk_cache[cache_key] = all_chunks
        return all_chunks

    def load_document(self, filepath: str, strategy: ChunkStrategyType = ChunkStrategyType.ARTICLE,
                      max_chunk_tokens: int = 800, overlap_tokens: int = 100) -> List[RegulationChunk]:
        parsed = parser_registry.parse(filepath)
        doc_name = parsed.title or os.path.splitext(os.path.basename(filepath))[0]

        if strategy == ChunkStrategyType.ARTICLE:
            return self._chunk_by_sections(parsed, doc_name, max_chunk_tokens, overlap_tokens)
        elif strategy == ChunkStrategyType.CHAPTER:
            return self._chunk_by_chapter(parsed, doc_name, max_chunk_tokens, overlap_tokens)
        else:
            return self._chunk_fixed(parsed, doc_name, max_chunk_tokens, overlap_tokens)

    def _chunk_by_sections(self, parsed: ParsedDocument, doc_name: str,
                           max_chunk_tokens: int = 800, overlap_tokens: int = 100) -> List[RegulationChunk]:
        sections = parsed.sections if parsed.sections else self._fallback_sections(parsed.raw_text)
        chunks = []
        idx = 0

        for item in sections:
            article_num = item.get("article_number", f"section_{idx}")
            article_text = item.get("article_text", "")
            chapter = item.get("chapter", "")
            token_count = _estimate_tokens(article_text)

            if token_count <= max_chunk_tokens:
                chunk = RegulationChunk(
                    doc_name=doc_name, chapter=chapter, article_number=article_num,
                    article_text=article_text, chunk_id=f"{doc_name}_{article_num}",
                    chunk_index=idx, token_count=token_count, parent_chapter=chapter,
                    source_format=parsed.source_format.value,
                )
                chunk.content_hash = chunk.compute_hash()
                chunks.append(chunk)
                idx += 1
            else:
                sub_chunks = self._split_long_text(article_text, max_chunk_tokens, overlap_tokens)
                for sub_idx, sub_text in enumerate(sub_chunks):
                    chunk = RegulationChunk(
                        doc_name=doc_name, chapter=chapter, article_number=f"{article_num}_{sub_idx + 1}",
                        article_text=sub_text, chunk_id=f"{doc_name}_{article_num}_{sub_idx + 1}",
                        chunk_index=idx, token_count=_estimate_tokens(sub_text),
                        parent_chapter=chapter, source_format=parsed.source_format.value,
                    )
                    chunk.content_hash = chunk.compute_hash()
                    chunks.append(chunk)
                    idx += 1

        if parsed.tables:
            for t_idx, table in enumerate(parsed.tables):
                table_text = self._table_to_text(table)
                if not table_text or len(table_text.strip()) < 20:
                    continue
                article_refs = re.findall(r"第[一二三四五六七八九十百]+条", table_text)
                if len(article_refs) > 3:
                    continue
                has_regulation_keyword = any(kw in table_text for kw in ["保险", "金融", "监管", "法规", "条款"])
                if not article_refs and not has_regulation_keyword:
                    continue
                chunk = RegulationChunk(
                    doc_name=doc_name, chapter="", article_number=f"table_{t_idx}",
                    article_text=table_text, chunk_id=f"{doc_name}_table_{t_idx}",
                    chunk_index=idx, token_count=_estimate_tokens(table_text),
                    has_table=True, table_data=table, source_format=parsed.source_format.value,
                )
                chunk.content_hash = chunk.compute_hash()
                chunks.append(chunk)
                idx += 1

        if parsed.images:
            chunk.has_image = True
            chunk.image_descriptions = [img.get("ocr_text", "") for img in parsed.images if img.get("ocr_text")]

        return chunks

    def _chunk_by_chapter(self, parsed: ParsedDocument, doc_name: str,
                          max_chunk_tokens: int = 1500, overlap_tokens: int = 100) -> List[RegulationChunk]:
        sections = parsed.sections if parsed.sections else self._fallback_sections(parsed.raw_text)
        chapter_groups: Dict[str, List[Dict]] = {}
        chapter_order = []
        for item in sections:
            ch = item.get("chapter") or "总则"
            if ch not in chapter_groups:
                chapter_groups[ch] = []
                chapter_order.append(ch)
            chapter_groups[ch].append(item)

        chunks = []
        idx = 0
        for ch_name in chapter_order:
            articles = chapter_groups[ch_name]
            combined_text = "\n".join(
                f"第{a.get('article_number', '')}条 {a.get('article_text', '')}" for a in articles
            )
            token_count = _estimate_tokens(combined_text)

            if token_count <= max_chunk_tokens:
                article_nums = "、".join(a.get("article_number", "") for a in articles)
                chunk = RegulationChunk(
                    doc_name=doc_name, chapter=ch_name, article_number=article_nums,
                    article_text=combined_text, chunk_id=f"{doc_name}_ch_{idx}",
                    chunk_index=idx, token_count=token_count, parent_chapter=ch_name,
                    source_format=parsed.source_format.value,
                )
                chunk.content_hash = chunk.compute_hash()
                chunks.append(chunk)
                idx += 1
            else:
                for a in articles:
                    chunk = RegulationChunk(
                        doc_name=doc_name, chapter=ch_name, article_number=a.get("article_number", ""),
                        article_text=a.get("article_text", ""), chunk_id=f"{doc_name}_{a.get('article_number', '')}",
                        chunk_index=idx, token_count=_estimate_tokens(a.get("article_text", "")),
                        parent_chapter=ch_name, source_format=parsed.source_format.value,
                    )
                    chunk.content_hash = chunk.compute_hash()
                    chunks.append(chunk)
                    idx += 1
        return chunks

    def _chunk_fixed(self, parsed: ParsedDocument, doc_name: str,
                     max_chunk_tokens: int = 500, overlap_tokens: int = 100) -> List[RegulationChunk]:
        paragraphs = [p.strip() for p in parsed.raw_text.split("\n\n") if p.strip()]
        chunks = []
        idx = 0
        buffer = ""

        for para in paragraphs:
            if _estimate_tokens(buffer + "\n" + para) > max_chunk_tokens and buffer:
                chunk = RegulationChunk(
                    doc_name=doc_name, chapter="", article_number=f"chunk_{idx}",
                    article_text=buffer.strip(), chunk_id=f"{doc_name}_fixed_{idx}",
                    chunk_index=idx, token_count=_estimate_tokens(buffer),
                    source_format=parsed.source_format.value,
                )
                chunk.content_hash = chunk.compute_hash()
                chunks.append(chunk)
                idx += 1
                buffer = buffer[-overlap_tokens:] + "\n" + para if overlap_tokens > 0 and len(buffer) > overlap_tokens else para
            else:
                buffer = (buffer + "\n" + para).strip()

        if buffer.strip():
            chunk = RegulationChunk(
                doc_name=doc_name, chapter="", article_number=f"chunk_{idx}",
                article_text=buffer.strip(), chunk_id=f"{doc_name}_fixed_{idx}",
                chunk_index=idx, token_count=_estimate_tokens(buffer),
                source_format=parsed.source_format.value,
            )
            chunk.content_hash = chunk.compute_hash()
            chunks.append(chunk)
        return chunks

    def _fallback_sections(self, text: str) -> List[Dict]:
        sections = []
        current_chapter = ""
        current_article_num = None
        buffer = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            chapter_match = re.match(r"^第[一二三四五六七八九十百]+章\s+(.+)$", stripped)
            if chapter_match:
                if current_article_num and buffer:
                    text_content = "".join(buffer).strip()
                    if text_content:
                        sections.append({"chapter": current_chapter, "article_number": current_article_num, "article_text": text_content})
                current_chapter = stripped
                current_article_num = None
                buffer = []
                continue

            article_match = re.match(r"^第([一二三四五六七八九十百]+)条\s*(.*)$", stripped)
            if article_match:
                article_text_part = article_match.group(2).strip().replace("\u3000", " ").strip()
                if not article_text_part:
                    continue
                if current_article_num and buffer:
                    text_content = "".join(buffer).strip()
                    if text_content:
                        sections.append({"chapter": current_chapter, "article_number": current_article_num, "article_text": text_content})
                current_article_num = article_match.group(1)
                buffer = [article_text_part]
                continue

            if current_article_num:
                buffer.append(stripped)

        if current_article_num and buffer:
            text_content = "".join(buffer).strip()
            if text_content:
                sections.append({"chapter": current_chapter, "article_number": current_article_num, "article_text": text_content})
        return sections

    def _split_long_text(self, text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
        sentences = re.split(r"(?<=[。！？；\n])", text)
        sub_chunks = []
        current = ""
        for sentence in sentences:
            if not sentence.strip():
                continue
            if _estimate_tokens(current + sentence) > max_tokens and current:
                sub_chunks.append(current.strip())
                current = current[-overlap_tokens:] + sentence if overlap_tokens > 0 and len(current) > overlap_tokens else sentence
            else:
                current += sentence
        if current.strip():
            sub_chunks.append(current.strip())
        return sub_chunks if sub_chunks else [text]

    def _table_to_text(self, table: List[List[str]]) -> str:
        if not table:
            return ""
        if len(table) < 2:
            return " | ".join(str(c) for c in table[0]) if table else ""
        header = table[0]
        separator = ["---"] * len(header)
        lines = []
        lines.append("| " + " | ".join(str(c) for c in header) + " |")
        lines.append("| " + " | ".join(separator) + " |")
        for row in table[1:]:
            padded = row + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(str(c) for c in padded[:len(header)]) + " |")
        return "\n".join(lines)

    @staticmethod
    def save_chunks_to_json(chunks: List[RegulationChunk], output_path: str):
        data = [chunk.to_dict() for chunk in chunks]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_chunks_from_json(input_path: str) -> List[RegulationChunk]:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [RegulationChunk(**item) for item in data]

    def detect_changes(self, new_chunks: List[RegulationChunk], old_path: str) -> Dict:
        if not os.path.exists(old_path):
            return {"added": len(new_chunks), "removed": 0, "modified": 0, "unchanged": 0}
        old_chunks = self.load_chunks_from_json(old_path)
        old_map = {c.chunk_id: c.content_hash for c in old_chunks}
        new_map = {c.chunk_id: c.content_hash for c in new_chunks}
        added = len(set(new_map.keys()) - set(old_map.keys()))
        removed = len(set(old_map.keys()) - set(new_map.keys()))
        modified = sum(1 for cid in set(old_map.keys()) & set(new_map.keys()) if old_map[cid] != new_map[cid])
        unchanged = sum(1 for cid in set(old_map.keys()) & set(new_map.keys()) if old_map[cid] == new_map[cid])
        return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}
