import os
import json
import time
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

_schema_version = 3

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
        conn.commit()

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
                 suggestions, review_mode, latency_ms, client_id, threats)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            return cursor.lastrowid

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
            f"SELECT id, input_hash, input_length, compliant, violation_type, "
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
        feedback = self.get_feedback_stats()
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        return {
            "total_reviews": total_reviews,
            "violation_reviews": violation_reviews,
            "compliant_reviews": total_reviews - violation_reviews,
            "violation_rate": violation_reviews / total_reviews if total_reviews > 0 else 0,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_confidence": round(avg_confidence, 4),
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
