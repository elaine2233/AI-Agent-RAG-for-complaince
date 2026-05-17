import os
from dotenv import load_dotenv

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "./data/vector_store")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
TOP_K = int(os.getenv("TOP_K", "5"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.3"))
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "7860"))

REGULATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "regulations")

DEMO_MODE = not bool(DASHSCOPE_API_KEY)

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "insurance_review.db"))
DB_BACKUP_DIR = os.getenv("DB_BACKUP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "db_backups"))
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "365"))
MAX_INPUT_LENGTH = int(os.getenv("MAX_INPUT_LENGTH", "10000"))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "50"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:7860,http://localhost:7861")

PASSWORD_SALT = os.getenv("PASSWORD_SALT", "insurance_review_2024_salt")
API_KEY_EXPIRE_DAYS = int(os.getenv("API_KEY_EXPIRE_DAYS", "90"))
AUDIT_SIGNING_KEY = os.getenv("AUDIT_SIGNING_KEY", "insurance_audit_signing_key_2024")
AUDIT_MAX_LOG_DAYS = int(os.getenv("AUDIT_MAX_LOG_DAYS", "90"))
AUDIT_LOG_DIR = os.getenv("AUDIT_LOG_DIR", "./data/audit_logs")

MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "7"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_PER_IP = int(os.getenv("RATE_LIMIT_MAX_PER_IP", "20"))

TASK_QUEUE_MAX_WORKERS = int(os.getenv("TASK_QUEUE_MAX_WORKERS", "4"))
TASK_QUEUE_MAX_SIZE = int(os.getenv("TASK_QUEUE_MAX_SIZE", "100"))
REVIEW_MAX_CONCURRENT = int(os.getenv("REVIEW_MAX_CONCURRENT", "10"))
REVIEW_SEMAPHORE_TIMEOUT = float(os.getenv("REVIEW_SEMAPHORE_TIMEOUT", "10.0"))

CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "500"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))

LLM_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "5"))
LLM_CIRCUIT_RECOVERY_TIMEOUT = float(os.getenv("LLM_CIRCUIT_RECOVERY_TIMEOUT", "30.0"))
EMBEDDING_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("EMBEDDING_CIRCUIT_FAILURE_THRESHOLD", "3"))
EMBEDDING_CIRCUIT_RECOVERY_TIMEOUT = float(os.getenv("EMBEDDING_CIRCUIT_RECOVERY_TIMEOUT", "20.0"))

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))

RISK_AUTO_PASS_MAX = float(os.getenv("RISK_AUTO_PASS_MAX", "0.1"))
RISK_HUMAN_REVIEW_MAX = float(os.getenv("RISK_HUMAN_REVIEW_MAX", "0.7"))

EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "qwen3.5-plus")
REASON_MODEL = os.getenv("REASON_MODEL", "qwen3.5-plus")
CROSSCHECK_MODEL = os.getenv("CROSSCHECK_MODEL", "qwen3.5-plus")

VL_MODEL = os.getenv("VL_MODEL", LLM_MODEL)

LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_RETRY_MAX = int(os.getenv("LLM_RETRY_MAX", "1"))
LLM_RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "1.0"))

RERANKER_TOP_K = int(os.getenv("RERANKER_TOP_K", "5"))
RERANKER_ADJACENT_SCORE_FACTOR = float(os.getenv("RERANKER_ADJACENT_SCORE_FACTOR", "0.7"))
RERANKER_RETRY_MAX = int(os.getenv("RERANKER_RETRY_MAX", "3"))
RERANKER_RETRY_DELAY = float(os.getenv("RERANKER_RETRY_DELAY", "1.0"))

EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "25"))
