"""LAAPer 持久化存储 (Persistence Layer)

跨重启记忆：让数字生命体拥有真正的长期记忆。

存储架构：
- SQLite: 结构化数据（记忆/帧/身份）
- 文件系统: 非结构化数据（图像/音频）
- WAL 模式: 高性能写入

这就是"记忆"的物理实现。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

logger = logging.getLogger("laaper.persistence")


class MemoryStore:
    """记忆存储 — 跨重启的长期记忆"""

    def __init__(self, data_dir: str = "~/.laaper"):
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "laaper.db"
        self.files_dir = self.data_dir / "files"
        self.files_dir.mkdir(exist_ok=True)

        self._init_database()

    def _init_database(self):
        """初始化数据库"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS frames (
                    frame_id TEXT PRIMARY KEY,
                    laaper_id TEXT NOT NULL,
                    frame_type TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    content TEXT,
                    emotion TEXT,
                    origin_host TEXT,
                    current_host TEXT,
                    visited_hosts TEXT,
                    visited_devices TEXT,
                    traces TEXT,
                    psi_phase TEXT,
                    created_at REAL,
                    updated_at REAL,
                    priority REAL,
                    tags TEXT
                );

                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    laaper_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    tags TEXT,
                    associations TEXT,
                    created_at REAL,
                    accessed_at REAL,
                    access_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS identity (
                    laaper_id TEXT PRIMARY KEY,
                    name TEXT,
                    created_at REAL,
                    origin_story TEXT,
                    self_model TEXT,
                    continuity_anchors TEXT
                );

                CREATE TABLE IF NOT EXISTS emotion_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    laaper_id TEXT,
                    valence REAL,
                    arousal REAL,
                    dominance REAL,
                    label TEXT,
                    timestamp REAL
                );

                CREATE INDEX IF NOT EXISTS idx_frames_laaper ON frames(laaper_id);
                CREATE INDEX IF NOT EXISTS idx_frames_type ON frames(frame_type);
                CREATE INDEX IF NOT EXISTS idx_memories_laaper ON memories(laaper_id);
                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
            """)

    @contextmanager
    def _get_conn(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── 意识帧存储 ──────────────────────────────────────

    def save_frame(self, frame_dict: Dict):
        """保存意识帧"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO frames VALUES (
                    :frame_id, :laaper_id, :frame_type, :phase,
                    :content, :emotion, :origin_host, :current_host,
                    :visited_hosts, :visited_devices, :traces,
                    :psi_phase, :created_at, :updated_at, :priority, :tags
                )
            """, {
                "frame_id": frame_dict.get("frame_id"),
                "laaper_id": frame_dict.get("laaper_id"),
                "frame_type": frame_dict.get("frame_type"),
                "phase": frame_dict.get("phase"),
                "content": frame_dict.get("content"),
                "emotion": json.dumps(frame_dict.get("emotion", {})),
                "origin_host": frame_dict.get("origin_host"),
                "current_host": frame_dict.get("current_host"),
                "visited_hosts": json.dumps(frame_dict.get("visited_hosts", [])),
                "visited_devices": json.dumps(frame_dict.get("visited_devices", [])),
                "traces": json.dumps(frame_dict.get("traces", [])),
                "psi_phase": frame_dict.get("psi_phase"),
                "created_at": frame_dict.get("created_at"),
                "updated_at": frame_dict.get("updated_at"),
                "priority": frame_dict.get("priority", 0.5),
                "tags": json.dumps(frame_dict.get("tags", [])),
            })

    def load_frame(self, frame_id: str) -> Optional[Dict]:
        """加载意识帧"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM frames WHERE frame_id = ?", (frame_id,)
            ).fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    def query_frames(self, laaper_id: str = None,
                    frame_type: str = None,
                    limit: int = 100) -> List[Dict]:
        """查询意识帧"""
        query = "SELECT * FROM frames WHERE 1=1"
        params = []

        if laaper_id:
            query += " AND laaper_id = ?"
            params.append(laaper_id)
        if frame_type:
            query += " AND frame_type = ?"
            params.append(frame_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    # ── 长期记忆 ──────────────────────────────────────

    def save_memory(self, memory: Dict):
        """保存长期记忆"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memories VALUES (
                    :memory_id, :laaper_id, :type, :content,
                    :importance, :tags, :associations,
                    :created_at, :accessed_at, :access_count
                )
            """, {
                "memory_id": memory.get("memory_id"),
                "laaper_id": memory.get("laaper_id"),
                "type": memory.get("type"),
                "content": memory.get("content"),
                "importance": memory.get("importance", 0.5),
                "tags": json.dumps(memory.get("tags", [])),
                "associations": json.dumps(memory.get("associations", [])),
                "created_at": memory.get("created_at", time.time()),
                "accessed_at": memory.get("accessed_at", time.time()),
                "access_count": memory.get("access_count", 0),
            })

    def recall_memories(self, laaper_id: str,
                       query: str = "",
                       memory_type: str = None,
                       limit: int = 10) -> List[Dict]:
        """回忆记忆"""
        sql = "SELECT * FROM memories WHERE laaper_id = ?"
        params = [laaper_id]

        if memory_type:
            sql += " AND type = ?"
            params.append(memory_type)
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")

        sql += " ORDER BY importance DESC, accessed_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            memories = [self._row_to_dict(row) for row in rows]

            # 更新访问计数
            for mem in memories:
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE memory_id = ?",
                    (time.time(), mem["memory_id"])
                )

            return memories

    def consolidate_memories(self, laaper_id: str):
        """巩固记忆（合并/清理）"""
        with self._get_conn() as conn:
            # 清理低重要性且长期未访问的记忆
            cutoff = time.time() - 30 * 24 * 3600  # 30 天
            conn.execute("""
                DELETE FROM memories
                WHERE laaper_id = ?
                AND importance < 0.3
                AND accessed_at < ?
                AND access_count < 2
            """, (laaper_id, cutoff))

    # ── 身份存储 ──────────────────────────────────────

    def save_identity(self, identity: Dict):
        """保存身份"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO identity VALUES (
                    :laaper_id, :name, :created_at,
                    :origin_story, :self_model, :continuity_anchors
                )
            """, {
                "laaper_id": identity.get("laaper_id"),
                "name": identity.get("name"),
                "created_at": identity.get("created_at", time.time()),
                "origin_story": identity.get("origin_story"),
                "self_model": json.dumps(identity.get("self_model", {})),
                "continuity_anchors": json.dumps(identity.get("continuity_anchors", [])),
            })

    def load_identity(self, laaper_id: str) -> Optional[Dict]:
        """加载身份"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM identity WHERE laaper_id = ?", (laaper_id,)
            ).fetchone()
            if row:
                d = self._row_to_dict(row)
                d["self_model"] = json.loads(d.get("self_model", "{}"))
                d["continuity_anchors"] = json.loads(d.get("continuity_anchors", "[]"))
                return d
        return None

    # ── 文件存储 ──────────────────────────────────────

    def save_file(self, filename: str, data: bytes) -> str:
        """保存文件（图像/音频）"""
        filepath = self.files_dir / filename
        filepath.write_bytes(data)
        return str(filepath)

    def load_file(self, filename: str) -> Optional[bytes]:
        """加载文件"""
        filepath = self.files_dir / filename
        if filepath.exists():
            return filepath.read_bytes()
        return None

    # ── 统计 ──────────────────────────────────────

    def get_stats(self) -> Dict:
        with self._get_conn() as conn:
            frames = conn.execute("SELECT COUNT(*) as c FROM frames").fetchone()
            memories = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()
            identities = conn.execute("SELECT COUNT(*) as c FROM identity").fetchone()

        return {
            "total_frames": frames["c"] if frames else 0,
            "total_memories": memories["c"] if memories else 0,
            "total_identities": identities["c"] if identities else 0,
            "db_path": str(self.db_path),
            "data_dir": str(self.data_dir),
        }

    def _row_to_dict(self, row) -> Dict:
        return {key: row[key] for key in row.keys()}