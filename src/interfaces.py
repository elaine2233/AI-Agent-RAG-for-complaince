from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class DocumentFormat(Enum):
    TXT = "txt"
    MD = "md"
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    IMAGE = "image"
    HTML = "html"


class InputType(Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    MIXED = "mixed"


@dataclass
class ParsedDocument:
    source_path: str
    source_format: DocumentFormat
    title: str
    raw_text: str
    sections: List[Dict] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)
    images: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self):
        import dataclasses
        d = dataclasses.asdict(self)
        d["source_format"] = self.source_format.value
        return d


@dataclass
class UserInput:
    input_type: InputType
    text: str = ""
    images: List[Dict] = field(default_factory=list)
    files: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    @property
    def combined_text(self) -> str:
        parts = []
        if self.text:
            parts.append(self.text)
        for img in self.images:
            if img.get("description"):
                parts.append(f"[图片描述] {img['description']}")
            elif img.get("ocr_text"):
                parts.append(f"[图片OCR] {img['ocr_text']}")
        for f in self.files:
            if f.get("extracted_text"):
                parts.append(f"[文件内容] {f['extracted_text']}")
        return "\n\n".join(parts)


class DocumentParser(ABC):
    @abstractmethod
    def supported_formats(self) -> List[DocumentFormat]:
        pass

    @abstractmethod
    def parse(self, source: str, **kwargs) -> ParsedDocument:
        pass

    @abstractmethod
    def can_parse(self, source: str) -> bool:
        pass


class InputProcessor(ABC):
    @abstractmethod
    def supported_types(self) -> List[InputType]:
        pass

    @abstractmethod
    def process(self, user_input: UserInput) -> UserInput:
        pass


class ChunkStrategy(ABC):
    @abstractmethod
    def chunk(self, document: ParsedDocument, **kwargs) -> List[Dict]:
        pass


class VectorStore(ABC):
    @abstractmethod
    def add_documents(self, documents: List[Dict], embeddings: List[List[float]], ids: List[str], metadatas: List[Dict]):
        pass

    @abstractmethod
    def query(self, embedding: List[float], top_k: int = 5) -> List[Dict]:
        pass

    @abstractmethod
    def delete(self, ids: List[str] = None, where: Dict = None):
        pass

    @abstractmethod
    def count(self) -> int:
        pass


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        pass

    @abstractmethod
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        pass

    @abstractmethod
    def model_name(self) -> str:
        pass


class ReviewStorage(ABC):
    @abstractmethod
    def save_review(self, review_data: Dict) -> int:
        pass

    @abstractmethod
    def get_review(self, review_id: int) -> Optional[Dict]:
        pass

    @abstractmethod
    def list_reviews(self, **kwargs) -> tuple:
        pass

    @abstractmethod
    def save_feedback(self, review_id: int, is_correct: bool, comment: str = "", user_id: int = None) -> int:
        pass
