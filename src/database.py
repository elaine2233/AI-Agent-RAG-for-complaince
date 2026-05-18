import os
import json
import time
import uuid
import sqlite3
import logging
import shutil
import hashlib
import hmac
import threading
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

_PASSWORD_SALT = config.PASSWORD_SALT

DB_PATH = config.DB_PATH
BACKUP_DIR = config.DB_BACKUP_DIR
MAX_BACKUPS = config.MAX_BACKUPS
DATA_RETENTION_DAYS = config.DATA_RETENTION_DAYS

_schema_version = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'reviewer',
    api_key TEXT UNIQUE,
    api_key_created_at TEXT,
    api_key_expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS review_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    input_content TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    input_length INTEGER NOT NULL,
    compliant TEXT NOT NULL,
    violation_type TEXT NOT NULL DEFAULT '',
    violated_articles TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.0,
    reasoning TEXT NOT NULL DEFAULT '',
    suggestions TEXT NOT NULL DEFAULT '',
    review_mode TEXT NOT NULL DEFAULT 'llm',
    latency_ms REAL NOT NULL DEFAULT 0.0,
    client_id TEXT NOT NULL DEFAULT 'anonymous',
    threats TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    decision TEXT NOT NULL DEFAULT 'auto_pass',
    risk_score REAL NOT NULL DEFAULT 0.0,
    risk_level TEXT NOT NULL DEFAULT 'low',
    reviewer_id INTEGER,
    review_comment TEXT,
    model_used TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS review_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    user_id INTEGER,
    is_correct INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_id) REFERENCES review_records(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS regulation_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    effective_date TEXT,
    is_current INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    user_id INTEGER,
    client_id TEXT NOT NULL DEFAULT 'anonymous',
    detail TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_review_records_input_hash ON review_records(input_hash);
CREATE INDEX IF NOT EXISTS idx_review_records_compliant ON review_records(compliant);
CREATE INDEX IF NOT EXISTS idx_review_records_created_at ON review_records(created_at);
CREATE INDEX IF NOT EXISTS idx_review_records_is_deleted ON review_records(is_deleted);
CREATE INDEX IF NOT EXISTS idx_review_records_user_id ON review_records(user_id);
CREATE INDEX IF NOT EXISTS idx_review_feedback_review_id ON review_feedback(review_id);
CREATE INDEX IF NOT EXISTS idx_regulation_versions_doc_name ON regulation_versions(doc_name);
CREATE INDEX IF NOT EXISTS idx_regulation_versions_is_current ON regulation_versions(is_current);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);

CREATE TABLE IF NOT EXISTS violation_types (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 2,
    parent_id TEXT,
    severity REAL NOT NULL DEFAULT 0.5,
    description TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    suggestions TEXT NOT NULL DEFAULT '',
    is_system INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'regulation',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clause_type_mappings (
    id TEXT PRIMARY KEY,
    violation_type_id TEXT NOT NULL,
    doc_name TEXT NOT NULL,
    article_number TEXT NOT NULL,
    mapping_logic TEXT NOT NULL DEFAULT 'primary',
    effective_date TEXT NOT NULL DEFAULT (datetime('now')),
    expiration_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (violation_type_id) REFERENCES violation_types(id)
);

CREATE INDEX IF NOT EXISTS idx_violation_types_level ON violation_types(level);
CREATE INDEX IF NOT EXISTS idx_violation_types_parent ON violation_types(parent_id);
CREATE INDEX IF NOT EXISTS idx_violation_types_status ON violation_types(status);
CREATE INDEX IF NOT EXISTS idx_clause_mappings_type ON clause_type_mappings(violation_type_id);
CREATE INDEX IF NOT EXISTS idx_clause_mappings_article ON clause_type_mappings(doc_name, article_number);

CREATE TABLE IF NOT EXISTS regulation_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_name TEXT NOT NULL,
    chapter TEXT NOT NULL DEFAULT '',
    article_number TEXT NOT NULL,
    article_text TEXT NOT NULL DEFAULT '',
    chunk_id TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    source_format TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(doc_name, article_number)
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON regulation_chunks(doc_name);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON regulation_chunks(doc_name, article_number);

CREATE TABLE IF NOT EXISTS review_violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    violation_type_id TEXT NOT NULL,
    violation_type_name TEXT NOT NULL,
    violated_articles TEXT NOT NULL DEFAULT '[]',
    reasoning TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'system',
    is_deprecated INTEGER NOT NULL DEFAULT 0,
    is_modified INTEGER NOT NULL DEFAULT 0,
    modification_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_id) REFERENCES review_records(id),
    FOREIGN KEY (violation_type_id) REFERENCES violation_types(id)
);
CREATE INDEX IF NOT EXISTS idx_review_violations_review_id ON review_violations(review_id);
CREATE INDEX IF NOT EXISTS idx_review_violations_type_id ON review_violations(violation_type_id);

CREATE TABLE IF NOT EXISTS violation_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    violation_type_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_id) REFERENCES review_records(id),
    FOREIGN KEY (violation_type_id) REFERENCES violation_types(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_violation_feedback_review_id ON violation_feedback(review_id);

CREATE TABLE IF NOT EXISTS review_modifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    modification_type TEXT NOT NULL,
    before_value TEXT NOT NULL DEFAULT '',
    after_value TEXT NOT NULL DEFAULT '',
    modification_reason TEXT NOT NULL DEFAULT '',
    is_ai_generated INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_id) REFERENCES review_records(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_review_modifications_review_id ON review_modifications(review_id);
"""


class Database:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: str = None):
        if self._initialized:
            return
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._initialized = True
        logger.info(f"数据库初始化完成: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=30.0)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    @contextmanager
    def transaction(self):
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"事务回滚: {e}")
            raise

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        self._run_migrations(conn)
        conn.execute(f"PRAGMA user_version = {_schema_version}")
        self._ensure_admin_user(conn)
        self._sync_violation_types(conn)
        self._ensure_regulation_versions()
        self._sync_clause_mappings()
        conn.execute("DELETE FROM clause_relations WHERE to_article IS NULL OR to_article = '' OR trim(to_article) = ''")
        conn.execute("DELETE FROM clause_relations WHERE from_doc = to_doc AND from_article = to_article")
        conn.commit()
        self._load_mappings_to_registry()

    def _run_migrations(self, conn):
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version < 2:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN api_key_created_at TEXT")
                conn.execute("ALTER TABLE users ADD COLUMN api_key_expires_at TEXT")
                logger.info("迁移: 添加 api_key_created_at, api_key_expires_at 列")
            except sqlite3.OperationalError:
                pass

        if current_version < 3:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
                logger.info("迁移: 添加 last_login_at 列")
            except sqlite3.OperationalError:
                pass

        if current_version < 4:
            for col, col_type, default in [
                ("decision", "TEXT", "'auto_pass'"),
                ("risk_score", "REAL", "0.0"),
                ("risk_level", "TEXT", "'low'"),
                ("reviewer_id", "INTEGER", "NULL"),
                ("review_comment", "TEXT", "NULL"),
                ("model_used", "TEXT", "''"),
                ("prompt_version", "TEXT", "''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE review_records ADD COLUMN {col} {col_type} DEFAULT {default}")
                    logger.info(f"迁移: 添加 review_records.{col} 列")
                except sqlite3.OperationalError:
                    pass

        if current_version < 6:
            try:
                conn.execute("ALTER TABLE violation_types ADD COLUMN source TEXT NOT NULL DEFAULT 'regulation'")
                logger.info("迁移: 添加 violation_types.source 列")
            except sqlite3.OperationalError:
                pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id INTEGER NOT NULL,
                    violation_type_id TEXT NOT NULL,
                    violation_type_name TEXT NOT NULL,
                    is_deprecated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (review_id) REFERENCES review_records(id),
                    FOREIGN KEY (violation_type_id) REFERENCES violation_types(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_violations_review_id ON review_violations(review_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_violations_type_id ON review_violations(violation_type_id)")
            logger.info("迁移: 创建 review_violations 表")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS violation_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id INTEGER NOT NULL,
                    violation_type_id TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (review_id) REFERENCES review_records(id),
                    FOREIGN KEY (violation_type_id) REFERENCES violation_types(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_violation_feedback_review_id ON violation_feedback(review_id)")
            logger.info("迁移: 创建 violation_feedback 表")

        if current_version < 8:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clause_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_doc TEXT NOT NULL,
                    from_article TEXT NOT NULL,
                    to_doc TEXT NOT NULL,
                    to_article TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    evidence_text TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'regex',
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    verified_by INTEGER,
                    verified_at TEXT,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(from_doc, from_article, to_doc, to_article, relation_type)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clause_relations_from ON clause_relations(from_doc, from_article)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clause_relations_to ON clause_relations(to_doc, to_article)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clause_relations_type ON clause_relations(relation_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clause_relations_source ON clause_relations(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clause_relations_confidence ON clause_relations(confidence)")
            logger.info("迁移: 创建 clause_relations 表")

    def _hash_password(self, password: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _PASSWORD_SALT.encode("utf-8"),
            100000,
        ).hex()

    def _ensure_admin_user(self, conn):
        row = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not row:
            admin_hash = self._hash_password("admin123")
            api_key = hashlib.sha256(f"admin_api_key_{time.time()}{os.urandom(16).hex()}".encode()).hexdigest()[:32]
            now = datetime.now()
            expires = now + timedelta(days=config.API_KEY_EXPIRE_DAYS)
            conn.execute(
                "INSERT INTO users (username, password_hash, role, api_key, api_key_created_at, api_key_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("admin", admin_hash, "admin", api_key, now.isoformat(), expires.isoformat()),
            )
            logger.info("已创建默认管理员账户 (admin/admin123)，API Key有效期90天")

        demo_row = conn.execute("SELECT id FROM users WHERE username = 'demo'").fetchone()
        if not demo_row:
            demo_hash = self._hash_password("demo")
            demo_api_key = "demo-key-insurance-review-2024"
            now = datetime.now()
            expires = now + timedelta(days=365)
            conn.execute(
                "INSERT INTO users (username, password_hash, role, api_key, api_key_created_at, api_key_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("demo", demo_hash, "reviewer", demo_api_key, now.isoformat(), expires.isoformat()),
            )
            logger.info("已创建默认演示账户 (demo)，API Key: demo-key-insurance-review-2024")

    def _sync_violation_types(self, conn):
        try:
            from src.violation_registry import violation_registry
            existing = {row[0] for row in conn.execute("SELECT id FROM violation_types").fetchall()}
            if existing:
                new_count = 0
                for vt in violation_registry._types.values():
                    if vt.id not in existing:
                        conn.execute(
                            "INSERT INTO violation_types (id, name, level, parent_id, severity, description, "
                            "keywords, suggestions, is_system, status, source, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (vt.id, vt.name, vt.level, vt.parent_id, vt.severity, vt.description,
                             json.dumps(vt.keywords, ensure_ascii=False), vt.suggestions,
                             int(vt.is_system), vt.status, vt.source, vt.created_at, vt.updated_at),
                        )
                        new_count += 1
                if new_count > 0:
                    logger.info(f"补充新违规类型: {new_count}条")
                else:
                    logger.info(f"违规类型已存在{len(existing)}条，无需同步")
            else:
                for vt in violation_registry._types.values():
                    conn.execute(
                        "INSERT INTO violation_types (id, name, level, parent_id, severity, description, "
                        "keywords, suggestions, is_system, status, source, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (vt.id, vt.name, vt.level, vt.parent_id, vt.severity, vt.description,
                         json.dumps(vt.keywords, ensure_ascii=False), vt.suggestions,
                         int(vt.is_system), vt.status, vt.source, vt.created_at, vt.updated_at),
                    )
                logger.info(f"首次初始化违规类型: {len(violation_registry._types)}条")
        except Exception as e:
            logger.warning(f"同步违规类型到数据库失败: {e}")

    def _ensure_regulation_versions(self):
        conn = self._get_conn()
        existing = {row[0] for row in conn.execute("SELECT doc_name FROM regulation_versions").fetchall()}

        regulations = [
            {"doc_name": "保险销售行为管理办法", "version": "1.0", "article_count": 50, "effective_date": "2024-01-01"},
            {"doc_name": "互联网保险业务监管办法", "version": "1.0", "article_count": 83, "effective_date": "2021-02-01"},
            {"doc_name": "金融产品网络营销管理办法（征求意见稿）", "version": "1.0", "article_count": 37, "effective_date": "2022-01-01"},
        ]

        for reg in regulations:
            if reg["doc_name"] not in existing:
                chunk_count = self.get_chunk_count(doc_name=reg["doc_name"])
                actual_count = chunk_count if chunk_count > 0 else reg["article_count"]
                content_hash = hashlib.sha256(reg["doc_name"].encode()).hexdigest()[:16]
                conn.execute(
                    "INSERT INTO regulation_versions (doc_name, version, content_hash, article_count, effective_date) VALUES (?, ?, ?, ?, ?)",
                    (reg["doc_name"], reg["version"], content_hash, actual_count, reg["effective_date"]),
                )
                logger.info(f"首次初始化法规版本: {reg['doc_name']}")
        conn.commit()

    def _sync_clause_mappings(self):
        try:
            conn = self._get_conn()
            existing = conn.execute("SELECT violation_type_id, doc_name, article_number FROM clause_type_mappings").fetchall()
            existing_keys = {(r[0], r[1], r[2]) for r in existing}

            if not existing_keys:
                from src.violation_registry import _DEFAULT_MAPPINGS
                count = 0
                for mapping_data in _DEFAULT_MAPPINGS:
                    conn.execute(
                        "INSERT INTO clause_type_mappings (id, violation_type_id, doc_name, article_number, mapping_logic, effective_date) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4())[:8], mapping_data["violation_type_id"], mapping_data["doc_name"], mapping_data["article_number"], mapping_data["mapping_logic"], mapping_data.get("effective_date", "2026-01-01")),
                    )
                    count += 1
                conn.commit()
                total = conn.execute("SELECT COUNT(*) FROM clause_type_mappings").fetchone()[0]
                logger.info(f"首次初始化条款映射: 新增{count}条, 总计{total}条")
            else:
                from src.violation_registry import _DEFAULT_MAPPINGS
                new_count = 0
                for mapping_data in _DEFAULT_MAPPINGS:
                    key = (mapping_data["violation_type_id"], mapping_data["doc_name"], mapping_data["article_number"])
                    if key not in existing_keys:
                        conn.execute(
                            "INSERT INTO clause_type_mappings (id, violation_type_id, doc_name, article_number, mapping_logic, effective_date) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4())[:8], mapping_data["violation_type_id"], mapping_data["doc_name"], mapping_data["article_number"], mapping_data["mapping_logic"], mapping_data.get("effective_date", "2026-01-01")),
                        )
                        new_count += 1
                if new_count > 0:
                    conn.commit()
                    logger.info(f"补充新条款映射: {new_count}条")
                else:
                    logger.info(f"条款映射已存在{len(existing_keys)}条，无需同步")
        except Exception as e:
            logger.warning(f"同步条款映射失败: {e}")

    def _load_mappings_to_registry(self):
        try:
            from src.violation_registry import violation_registry
            conn = self._get_conn()

            rows = conn.execute("SELECT id, name, level, parent_id, severity, description, keywords, suggestions, is_system, status, source, created_at, updated_at FROM violation_types").fetchall()
            if rows:
                from src.violation_registry import ViolationType
                violation_registry._types.clear()
                for row in rows:
                    vt = ViolationType(
                        id=row[0], name=row[1], level=row[2], parent_id=row[3],
                        severity=row[4], description=row[5],
                        keywords=json.loads(row[6]) if row[6] else [],
                        suggestions=row[7], is_system=bool(row[8]),
                        status=row[9], source=row[10],
                        created_at=row[11], updated_at=row[12],
                    )
                    violation_registry._types[vt.id] = vt
                logger.info(f"从数据库加载违规类型到注册表: {len(violation_registry._types)}条")

            mapping_rows = conn.execute("SELECT id, violation_type_id, doc_name, article_number, mapping_logic, effective_date, expiration_date, created_at FROM clause_type_mappings").fetchall()
            if mapping_rows:
                from src.violation_registry import ClauseTypeMapping
                violation_registry._mappings.clear()
                for row in mapping_rows:
                    cm = ClauseTypeMapping(
                        id=row[0], violation_type_id=row[1],
                        doc_name=row[2], article_number=row[3],
                        mapping_logic=row[4], effective_date=row[5],
                        expiration_date=row[6], created_at=row[7],
                    )
                    violation_registry._mappings[cm.id] = cm
                logger.info(f"从数据库加载条款映射到注册表: {len(violation_registry._mappings)}条")
        except Exception as e:
            logger.warning(f"加载数据库数据到注册表失败: {e}")

    def sync_chunks(self, chunks):
        try:
            conn = self._get_conn()
            count = 0
            for c in chunks:
                conn.execute(
                    "INSERT OR REPLACE INTO regulation_chunks (doc_name, chapter, article_number, article_text, chunk_id, content_hash, source_format, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (c.doc_name, c.chapter, c.article_number, c.article_text, c.chunk_id, c.content_hash, c.source_format),
                )
                count += 1
            conn.commit()
            logger.info(f"同步法规条款完成: {count}条")
        except Exception as e:
            logger.warning(f"同步法规条款失败: {e}")

    def get_chunks(self, doc_name=None, article_number=None):
        conn = self._get_conn()
        if doc_name and article_number:
            rows = conn.execute(
                "SELECT doc_name, chapter, article_number, article_text, chunk_id, content_hash, source_format FROM regulation_chunks WHERE doc_name = ? AND article_number = ?",
                (doc_name, article_number),
            ).fetchall()
        elif doc_name:
            rows = conn.execute(
                "SELECT doc_name, chapter, article_number, article_text, chunk_id, content_hash, source_format FROM regulation_chunks WHERE doc_name = ?",
                (doc_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT doc_name, chapter, article_number, article_text, chunk_id, content_hash, source_format FROM regulation_chunks",
            ).fetchall()
        return [
            {
                "doc_name": r[0], "chapter": r[1], "article_number": r[2],
                "article_text": r[3], "chunk_id": r[4], "content_hash": r[5], "source_format": r[6],
            }
            for r in rows
        ]

    def get_chunk_count(self, doc_name=None):
        conn = self._get_conn()
        if doc_name:
            row = conn.execute("SELECT COUNT(*) FROM regulation_chunks WHERE doc_name = ?", (doc_name,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM regulation_chunks").fetchone()
        return row[0] if row else 0

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def backup(self) -> str:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"insurance_review_{timestamp}.db")

        conn = self._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"数据库备份完成: {backup_path}")
        finally:
            conn.rollback()

        self._cleanup_old_backups()
        return backup_path

    def _cleanup_old_backups(self):
        if not os.path.exists(BACKUP_DIR):
            return
        backups = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
            reverse=True,
        )
        for old_backup in backups[MAX_BACKUPS:]:
            old_path = os.path.join(BACKUP_DIR, old_backup)
            os.remove(old_path)
            logger.info(f"清理旧备份: {old_path}")

    def cleanup_expired_data(self, days: int = None) -> Dict:
        days = days or DATA_RETENTION_DAYS
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        stats = {}

        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE review_records SET is_deleted = 1, deleted_at = datetime('now') "
                "WHERE created_at < ? AND is_deleted = 0",
                (cutoff,),
            )
            stats["soft_deleted_reviews"] = cursor.rowcount

            cursor = conn.execute(
                "DELETE FROM review_feedback WHERE review_id IN "
                "(SELECT id FROM review_records WHERE is_deleted = 1 AND deleted_at < ?)",
                ((datetime.now() - timedelta(days=30)).isoformat(),),
            )
            stats["purged_feedback"] = cursor.rowcount

            cursor = conn.execute(
                "DELETE FROM audit_events WHERE created_at < ?",
                (cutoff,),
            )
            stats["purged_audit_events"] = cursor.rowcount

        logger.info(f"数据清理完成: {stats}")
        return stats

    def save_review(self, review_data: Dict) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO review_records
                (user_id, input_content, input_hash, input_length, compliant,
                 violation_type, violated_articles, confidence, reasoning,
                 suggestions, review_mode, latency_ms, client_id, threats,
                 decision, risk_score, risk_level, model_used, prompt_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_data.get("user_id"),
                    review_data["input_content"],
                    review_data["input_hash"],
                    review_data["input_length"],
                    review_data["compliant"],
                    review_data["violation_type"],
                    json.dumps(review_data.get("violated_articles", []), ensure_ascii=False),
                    review_data["confidence"],
                    review_data["reasoning"],
                    review_data["suggestions"],
                    review_data.get("review_mode", "llm"),
                    review_data.get("latency_ms", 0),
                    review_data.get("client_id", "anonymous"),
                    json.dumps(review_data.get("threats", []), ensure_ascii=False),
                    review_data.get("decision", "auto_pass"),
                    review_data.get("risk_score", 0.0),
                    review_data.get("risk_level", "low"),
                    review_data.get("model_used", ""),
                    review_data.get("prompt_version", ""),
                ),
            )
            review_id = cursor.lastrowid

            violation_types = review_data.get("violation_types")
            if violation_types:
                self._save_review_violations_in_txn(conn, review_id, violation_types)

            return review_id

    def get_review(self, review_id: int) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM review_records WHERE id = ? AND is_deleted = 0",
            (review_id,),
        ).fetchone()
        if row:
            d = dict(row)
            d["violated_articles"] = json.loads(d["violated_articles"])
            d["threats"] = json.loads(d["threats"])
            return d
        return None

    def list_reviews(
        self,
        user_id: int = None,
        compliant: str = None,
        limit: int = 50,
        offset: int = 0,
        start_date: str = None,
        end_date: str = None,
    ) -> Tuple[List[Dict], int]:
        conn = self._get_conn()
        conditions = ["is_deleted = 0"]
        params = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if compliant:
            conditions.append("compliant = ?")
            params.append(compliant)
        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)

        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM review_records WHERE {where}", params
        ).fetchone()
        total = count_row["cnt"]

        rows = conn.execute(
            f"SELECT id, input_content, input_hash, input_length, compliant, violation_type, "
            f"confidence, review_mode, latency_ms, client_id, created_at "
            f"FROM review_records WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return [dict(r) for r in rows], total

    def hard_delete_review(self, review_id: int, user_id: int = None) -> bool:
        with self.transaction() as conn:
            conn.execute("DELETE FROM review_feedback WHERE review_id = ?", (review_id,))
            cursor = conn.execute(
                "DELETE FROM review_records WHERE id = ?", (review_id,)
            )
            if cursor.rowcount > 0:
                self._log_audit(conn, "hard_delete_review", user_id, f"review_id={review_id}")
                return True
            return False

    def save_feedback(self, review_id: int, is_correct: bool, comment: str = "", user_id: int = None) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO review_feedback (review_id, user_id, is_correct, comment) "
                "VALUES (?, ?, ?, ?)",
                (review_id, user_id, int(is_correct), comment),
            )
            self._log_audit(conn, "feedback", user_id, f"review_id={review_id}, correct={is_correct}")
            return cursor.lastrowid

    def get_feedback_stats(self) -> Dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as cnt FROM review_feedback").fetchone()["cnt"]
        correct = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_feedback WHERE is_correct = 1"
        ).fetchone()["cnt"]
        incorrect = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_feedback WHERE is_correct = 0"
        ).fetchone()["cnt"]
        return {
            "total_feedback": total,
            "correct_count": correct,
            "incorrect_count": incorrect,
            "accuracy": correct / total if total > 0 else 0,
        }

    def save_regulation_version(self, doc_name: str, version: str, content_hash: str, article_count: int, effective_date: str = None) -> int:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE regulation_versions SET is_current = 0 WHERE doc_name = ? AND is_current = 1",
                (doc_name,),
            )
            cursor = conn.execute(
                "INSERT INTO regulation_versions (doc_name, version, content_hash, article_count, effective_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc_name, version, content_hash, article_count, effective_date),
            )
            self._log_audit(conn, "regulation_update", None, f"doc={doc_name}, version={version}")
            return cursor.lastrowid

    def get_current_regulation_version(self, doc_name: str) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM regulation_versions WHERE doc_name = ? AND is_current = 1",
            (doc_name,),
        ).fetchone()
        return dict(row) if row else None

    def list_regulation_versions(self, doc_name: str = None) -> List[Dict]:
        conn = self._get_conn()
        if doc_name:
            rows = conn.execute(
                "SELECT * FROM regulation_versions WHERE doc_name = ? ORDER BY created_at DESC",
                (doc_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM regulation_versions ORDER BY doc_name, created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        conn = self._get_conn()
        password_hash = self._hash_password(password)
        row = conn.execute(
            "SELECT id, username, role, api_key, is_active FROM users "
            "WHERE username = ? AND password_hash = ? AND is_active = 1",
            (username, password_hash),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            return dict(row)
        return None

    def authenticate_api_key(self, api_key: str) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, username, role, is_active, api_key_expires_at FROM users "
            "WHERE api_key = ? AND is_active = 1",
            (api_key,),
        ).fetchone()
        if not row:
            return None
        if row["api_key_expires_at"]:
            try:
                expires = datetime.fromisoformat(row["api_key_expires_at"])
                if datetime.now() > expires:
                    logger.warning(f"API Key已过期: user={row['username']}")
                    return None
            except (ValueError, TypeError):
                pass
        return {"id": row["id"], "username": row["username"], "role": row["role"], "api_key": api_key}

    def check_permission(self, user_id: int, required_role: str) -> bool:
        role_hierarchy = {"viewer": 0, "reviewer": 1, "admin": 2}
        conn = self._get_conn()
        row = conn.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        if not row:
            return False
        return role_hierarchy.get(row["role"], 0) >= role_hierarchy.get(required_role, 0)

    def _log_audit(self, conn, event_type: str, user_id: int = None, detail: str = ""):
        conn.execute(
            "INSERT INTO audit_events (event_type, user_id, detail) VALUES (?, ?, ?)",
            (event_type, user_id, detail),
        )

    def log_audit_event(self, event_type: str, user_id: int = None, client_id: str = "", detail: str = "", ip_address: str = ""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO audit_events (event_type, user_id, client_id, detail, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_type, user_id, client_id, detail, ip_address),
        )
        conn.commit()

    def get_stats(self) -> Dict:
        conn = self._get_conn()
        total_reviews = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_records WHERE is_deleted = 0"
        ).fetchone()["cnt"]
        violation_reviews = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_records WHERE compliant = 'no' AND is_deleted = 0"
        ).fetchone()["cnt"]
        avg_latency = conn.execute(
            "SELECT AVG(latency_ms) as avg FROM review_records WHERE is_deleted = 0"
        ).fetchone()["avg"] or 0
        avg_confidence = conn.execute(
            "SELECT AVG(confidence) as avg FROM review_records WHERE is_deleted = 0"
        ).fetchone()["avg"] or 0
        pending_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_records WHERE decision = 'human_review' AND is_deleted = 0"
        ).fetchone()["cnt"]
        feedback = self.get_feedback_stats()
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        return {
            "total_reviews": total_reviews,
            "violation_reviews": violation_reviews,
            "compliant_reviews": total_reviews - violation_reviews,
            "pending_count": pending_count,
            "violation_rate": violation_reviews / total_reviews if total_reviews > 0 else 0,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_review_latency": round(avg_latency, 2),
            "avg_confidence": round(avg_confidence, 4),
            "model_status": "active" if config.has_api_key() else "no_api",
            "feedback": feedback,
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
        }

    def health_check(self) -> Dict:
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1").fetchone()
            return {"status": "healthy", "db_path": self.db_path}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _save_review_violations_in_txn(self, conn, review_id: int, violation_types: List[Dict]):
        valid_ids = {r[0] for r in conn.execute("SELECT id FROM violation_types").fetchall()}
        for vt in violation_types:
            type_id = vt["violation_type_id"]
            if type_id not in valid_ids:
                type_id = "other_violation"
            articles = vt.get("violated_articles", [])
            if isinstance(articles, list):
                articles = json.dumps(articles, ensure_ascii=False)
            elif not isinstance(articles, str):
                articles = "[]"
            conn.execute(
                "INSERT INTO review_violations (review_id, violation_type_id, violation_type_name, violated_articles, reasoning, is_deprecated) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (review_id, type_id, vt["violation_type_name"], articles, vt.get("reasoning", ""), int(vt.get("is_deprecated", False))),
            )

    def save_review_violations(self, review_id: int, violation_types: List[Dict]):
        with self.transaction() as conn:
            self._save_review_violations_in_txn(conn, review_id, violation_types)

    def get_review_violations(self, review_id: int) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, review_id, violation_type_id, violation_type_name, violated_articles, reasoning, source, is_deprecated, created_at "
            "FROM review_violations WHERE review_id = ?",
            (review_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("violated_articles") and isinstance(d["violated_articles"], str):
                try:
                    d["violated_articles"] = json.loads(d["violated_articles"])
                except (json.JSONDecodeError, TypeError):
                    d["violated_articles"] = []
            result.append(d)
        return result

    def save_violation_feedback(self, review_id: int, violation_type_id: str, feedback_type: str, comment: str = "", user_id: int = None) -> int:
        with self.transaction() as conn:
            valid_ids = {r[0] for r in conn.execute("SELECT id FROM violation_types").fetchall()}
            if violation_type_id not in valid_ids:
                violation_type_id = "other_violation"
            cursor = conn.execute(
                "INSERT INTO violation_feedback (review_id, violation_type_id, feedback_type, comment, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (review_id, violation_type_id, feedback_type, comment, user_id),
            )
            self._log_audit(conn, "violation_feedback", user_id, f"review_id={review_id}, type={violation_type_id}, fb={feedback_type}")
            return cursor.lastrowid

    def get_violation_feedback_stats(self) -> Dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as cnt FROM violation_feedback").fetchone()["cnt"]
        by_type = {}
        rows = conn.execute(
            "SELECT feedback_type, COUNT(*) as cnt FROM violation_feedback GROUP BY feedback_type"
        ).fetchall()
        for row in rows:
            by_type[row["feedback_type"]] = row["cnt"]

        by_violation = {}
        rows = conn.execute(
            "SELECT violation_type_id, COUNT(*) as cnt FROM violation_feedback GROUP BY violation_type_id"
        ).fetchall()
        for row in rows:
            by_violation[row["violation_type_id"]] = row["cnt"]

        return {
            "total_feedback": total,
            "by_feedback_type": by_type,
            "by_violation_type": by_violation,
        }

    def save_review_modification(self, review_id: int, modification_type: str,
                                  before_value: str = "", after_value: str = "",
                                  modification_reason: str = "", is_ai_generated: bool = False,
                                  user_id: int = None) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO review_modifications "
                "(review_id, modification_type, before_value, after_value, modification_reason, is_ai_generated, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (review_id, modification_type, before_value, after_value,
                 modification_reason, 1 if is_ai_generated else 0, user_id),
            )
            self._log_audit(conn, "review_modification", user_id,
                           f"review_id={review_id}, type={modification_type}")
            return cursor.lastrowid

    def get_review_modifications(self, review_id: int) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM review_modifications WHERE review_id = ? ORDER BY created_at",
            (review_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def save_clause_relation(self, from_doc, from_article, to_doc, to_article, relation_type, confidence=1.0, evidence_text='', source='regex'):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO clause_relations (from_doc, from_article, to_doc, to_article, relation_type, confidence, evidence_text, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (from_doc, from_article, to_doc, to_article, relation_type, confidence, evidence_text, source)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存条款关系失败: {e}")
            return False

    def get_clause_relations(self, doc_name=None, article_number=None, relation_type=None):
        conn = self._get_conn()
        query = "SELECT * FROM clause_relations WHERE 1=1"
        params = []
        if doc_name:
            query += " AND (from_doc = ? OR to_doc = ?)"
            params.extend([doc_name, doc_name])
        if article_number:
            query += " AND (from_article = ? OR to_article = ?)"
            params.extend([article_number, article_number])
        if relation_type:
            query += " AND relation_type = ?"
            params.append(relation_type)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_all_clause_relations(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM clause_relations").fetchall()
        return [dict(r) for r in rows]

    def get_relations_for_articles(self, articles):
        if not articles:
            return []
        conn = self._get_conn()
        results = []
        for doc_name, article_number in articles:
            rows = conn.execute(
                "SELECT * FROM clause_relations WHERE from_doc = ? AND from_article = ?",
                (doc_name, article_number)
            ).fetchall()
            results.extend([dict(r) for r in rows])
        return results
