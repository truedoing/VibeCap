"""
VIBECAP SQLite 数据库层
统一管理：剧集、集数据质量、语义索引元数据、任务、分段、质量报告

用法:
    from db import VibeCapDB
    db = VibeCapDB("/Users/zgl/VIBECAP/vibecap.db")
    dramas = db.list_dramas()
"""

import sqlite3
import threading
import time
from pathlib import Path

# ── Schema ──
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS dramas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT,
    created_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_id INTEGER NOT NULL REFERENCES dramas(id) ON DELETE CASCADE,
    ep_number INTEGER NOT NULL,
    -- ASR 统计
    asr_raw_count INTEGER DEFAULT 0,
    asr_raw_chars INTEGER DEFAULT 0,
    asr_clean_count INTEGER DEFAULT 0,
    asr_clean_chars INTEGER DEFAULT 0,
    asr_frag_rate REAL DEFAULT 0,
    -- VLM 统计
    vlm_scene_count INTEGER DEFAULT 0,
    vlm_avg_desc_len REAL DEFAULT 0,
    vlm_avg_depth_len REAL DEFAULT 0,
    vlm_short_desc_count INTEGER DEFAULT 0,
    vlm_shallow_depth_count INTEGER DEFAULT 0,
    vlm_skip_opening_count INTEGER DEFAULT 0,
    -- 字幕
    subtitle_count INTEGER DEFAULT 0,
    -- 索引状态
    indexed BOOLEAN DEFAULT 0,
    indexed_entries INTEGER DEFAULT 0,
    -- 源视频
    has_source_video BOOLEAN DEFAULT 0,
    -- 时间戳
    analyzed_at INTEGER,
    cleaned_at INTEGER,
    UNIQUE(drama_id, ep_number)
);

CREATE TABLE IF NOT EXISTS index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_id INTEGER NOT NULL REFERENCES dramas(id) ON DELETE CASCADE,
    ep_number INTEGER NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('vlm','asr','sub')),
    start REAL NOT NULL,
    end REAL NOT NULL,
    scene_id INTEGER,
    text TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    UNIQUE(drama_id, ep_number, entry_type, start)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_id INTEGER NOT NULL REFERENCES dramas(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'editing' CHECK(status IN ('editing','reviewing','delivered')),
    segments_count INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,
    picks_json TEXT DEFAULT '{}',
    timeline_json TEXT,
    media_cache_json TEXT,
    created_at INTEGER DEFAULT (unixepoch()),
    updated_at INTEGER DEFAULT (unixepoch()),
    UNIQUE(drama_id, name)
);

CREATE TABLE IF NOT EXISTS task_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seg_id INTEGER NOT NULL,
    highlight_text TEXT DEFAULT '',
    narration_text TEXT DEFAULT '',
    episode_marker_ep INTEGER,
    episode_marker_min REAL,
    mode TEXT DEFAULT 'A' CHECK(mode IN ('A','C')),
    sentences_json TEXT,
    UNIQUE(task_id, seg_id)
);

CREATE TABLE IF NOT EXISTS quality_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_id INTEGER NOT NULL REFERENCES dramas(id) ON DELETE CASCADE,
    ep_number INTEGER NOT NULL,
    asr_score REAL DEFAULT 0,
    vlm_score REAL DEFAULT 0,
    subtitle_score REAL DEFAULT 0,
    overall_score REAL DEFAULT 0,
    summary TEXT,
    checked_at INTEGER DEFAULT (unixepoch()),
    UNIQUE(drama_id, ep_number)
);

CREATE INDEX IF NOT EXISTS idx_episodes_drama ON episodes(drama_id, ep_number);
CREATE INDEX IF NOT EXISTS idx_index_entries_drama ON index_entries(drama_id, ep_number, entry_type);
CREATE INDEX IF NOT EXISTS idx_index_entries_type ON index_entries(drama_id, entry_type);
CREATE INDEX IF NOT EXISTS idx_tasks_drama ON tasks(drama_id);
CREATE INDEX IF NOT EXISTS idx_task_segments_task ON task_segments(task_id, seg_id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_drama ON quality_reports(drama_id);
"""


class VibeCapDB:
    """SQLite 数据库访问层，线程安全"""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)
        self._local = threading.local()
        # 初始化连接以执行 schema
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _cursor(self):
        return self._get_conn().cursor()

    def commit(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.commit()

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ═══════════════════════════════════════════════
    # Dramas
    # ═══════════════════════════════════════════════

    def ensure_drama(self, name: str, slug: str = None) -> int:
        """插入或获取剧集，返回 drama_id"""
        c = self._cursor()
        c.execute(
            "INSERT INTO dramas (name, slug) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET slug=COALESCE(excluded.slug, slug)",
            (name, slug or name),
        )
        self.commit()
        return c.lastrowid or self.get_drama_id(name)

    def get_drama_id(self, name: str) -> int | None:
        c = self._cursor()
        row = c.execute("SELECT id FROM dramas WHERE name = ?", (name,)).fetchone()
        return row["id"] if row else None

    def list_dramas(self) -> list[dict]:
        """返回所有剧集及其任务数"""
        c = self._cursor()
        rows = c.execute("""
            SELECT d.id, d.name, d.slug, d.created_at,
                   COUNT(t.id) as task_count
            FROM dramas d
            LEFT JOIN tasks t ON t.drama_id = d.id
            GROUP BY d.id
            ORDER BY d.name
        """).fetchall()
        return [
            {"name": r["name"], "slug": r["slug"], "tasks": r["task_count"]}
            for r in rows
        ]

    # ═══════════════════════════════════════════════
    # Episodes — 数据质量元信息
    # ═══════════════════════════════════════════════

    def upsert_episode(self, drama_id: int, ep: int, stats: dict) -> None:
        """插入或更新单集质量统计 — 只更新传入的字段"""
        c = self._cursor()
        allowed = {
            "asr_raw_count", "asr_raw_chars", "asr_clean_count", "asr_clean_chars",
            "asr_frag_rate", "vlm_scene_count", "vlm_avg_desc_len", "vlm_avg_depth_len",
            "vlm_short_desc_count", "vlm_shallow_depth_count", "vlm_skip_opening_count",
            "subtitle_count", "indexed", "indexed_entries", "has_source_video",
            "analyzed_at", "cleaned_at",
        }
        # 只取 allowed 中存在的字段
        values = {"drama_id": drama_id, "ep_number": ep}
        for k in allowed:
            if k in stats:
                values[k] = stats[k]

        placeholders = ", ".join(values.keys())
        qs = ", ".join("?" * len(values))
        updates = ", ".join(f"{k}=excluded.{k}" for k in values if k not in ("drama_id", "ep_number"))
        sql = f"INSERT INTO episodes ({placeholders}) VALUES ({qs}) ON CONFLICT(drama_id, ep_number) DO UPDATE SET {updates}"
        c.execute(sql, list(values.values()))
        self.commit()

    def get_episode(self, drama_id: int, ep: int) -> dict | None:
        c = self._cursor()
        row = c.execute(
            "SELECT * FROM episodes WHERE drama_id = ? AND ep_number = ?",
            (drama_id, ep),
        ).fetchone()
        return dict(row) if row else None

    def get_all_episodes(self, drama_id: int) -> list[dict]:
        """返回剧集质量列表（数据台用）"""
        c = self._cursor()
        rows = c.execute(
            "SELECT * FROM episodes WHERE drama_id = ? ORDER BY ep_number",
            (drama_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def init_drama_episodes(self, drama_id: int, total_eps: int) -> int:
        """初始化剧集的所有集数条目（未分析状态），返回新增数"""
        c = self._cursor()
        count = 0
        for ep in range(1, total_eps + 1):
            c.execute(
                "INSERT OR IGNORE INTO episodes (drama_id, ep_number) VALUES (?, ?)",
                (drama_id, ep),
            )
            if c.rowcount > 0:
                count += 1
        self.commit()
        return count

    def get_episodes_summary(self, drama_id: int) -> dict:
        """汇总统计"""
        c = self._cursor()
        row = c.execute("""
            SELECT
                COUNT(*) as total_eps,
                SUM(CASE WHEN indexed THEN 1 ELSE 0 END) as indexed_eps,
                SUM(CASE WHEN asr_raw_count > 0 THEN 1 ELSE 0 END) as asr_eps,
                SUM(CASE WHEN vlm_scene_count > 0 THEN 1 ELSE 0 END) as vlm_eps,
                SUM(asr_raw_count) as total_asr_raw,
                SUM(asr_clean_count) as total_asr_clean,
                SUM(vlm_scene_count) as total_vlm_scenes,
                AVG(asr_frag_rate) as avg_frag_rate,
                SUM(subtitle_count) as total_subtitles,
                SUM(indexed_entries) as total_indexed
            FROM episodes WHERE drama_id = ?
        """, (drama_id,)).fetchone()
        return dict(row) if row else {}

    # ═══════════════════════════════════════════════
    # Index Entries — 语义索引元数据
    # ═══════════════════════════════════════════════

    def bulk_insert_index_entries(self, drama_id: int, entries: list[dict]) -> int:
        """批量插入索引元数据，返回插入数"""
        c = self._cursor()
        count = 0
        for e in entries:
            c.execute(
                "INSERT OR REPLACE INTO index_entries "
                "(drama_id, ep_number, entry_type, start, end, scene_id, text, weight) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    drama_id,
                    e.get("ep", 0),
                    e.get("type", "vlm"),
                    e.get("start", 0),
                    e.get("end", 0),
                    e.get("scene_id", 0),
                    e.get("text", ""),
                    e.get("weight", 1.0),
                ),
            )
            count += 1
        self.commit()
        return count

    def get_index_stats(self, drama_id: int) -> dict:
        """索引类型分布"""
        c = self._cursor()
        rows = c.execute("""
            SELECT entry_type, COUNT(*) as cnt, SUM(weight) as total_weight
            FROM index_entries WHERE drama_id = ?
            GROUP BY entry_type
        """, (drama_id,)).fetchall()
        stats = {r["entry_type"]: r["cnt"] for r in rows}
        stats["total"] = sum(stats.values())
        return stats

    def count_indexed_eps(self, drama_id: int) -> int:
        c = self._cursor()
        row = c.execute(
            "SELECT COUNT(DISTINCT ep_number) as cnt FROM index_entries WHERE drama_id = ?",
            (drama_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_indexed_eps(self, drama_id: int) -> list[int]:
        """返回已索引的集数列表"""
        c = self._cursor()
        rows = c.execute(
            "SELECT DISTINCT ep_number FROM index_entries WHERE drama_id = ? ORDER BY ep_number",
            (drama_id,),
        ).fetchall()
        return [r["ep_number"] for r in rows]

    # ═══════════════════════════════════════════════
    # Tasks
    # ═══════════════════════════════════════════════

    def list_tasks(self, drama_id: int) -> list[dict]:
        """返回剧集下所有任务（API: /tasks）"""
        c = self._cursor()
        rows = c.execute("""
            SELECT name, status, segments_count, duration, picks_json, created_at, updated_at
            FROM tasks WHERE drama_id = ? ORDER BY created_at DESC
        """, (drama_id,)).fetchall()
        return [
            {
                "name": r["name"],
                "segments": r["segments_count"],
                "status": r["status"],
                "duration": r["duration"],
            }
            for r in rows
        ]

    def get_task(self, drama_id: int, name: str) -> dict | None:
        c = self._cursor()
        row = c.execute(
            "SELECT * FROM tasks WHERE drama_id = ? AND name = ?",
            (drama_id, name),
        ).fetchone()
        return dict(row) if row else None

    def get_task_by_id(self, task_id: int) -> dict | None:
        c = self._cursor()
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def create_task(self, drama_id: int, name: str) -> int:
        """创建任务，返回 task_id"""
        c = self._cursor()
        c.execute(
            "INSERT OR IGNORE INTO tasks (drama_id, name) VALUES (?, ?)",
            (drama_id, name),
        )
        self.commit()
        task = self.get_task(drama_id, name)
        if task:
            return task["id"]
        # 如果已存在，返回现有 ID
        row = c.execute(
            "SELECT id FROM tasks WHERE drama_id = ? AND name = ?",
            (drama_id, name),
        ).fetchone()
        return row["id"] if row else 0

    def update_task_picks(self, task_id: int, picks_json: str) -> None:
        c = self._cursor()
        c.execute(
            "UPDATE tasks SET picks_json = ?, updated_at = unixepoch() WHERE id = ?",
            (picks_json, task_id),
        )
        self.commit()

    def update_task_timeline(self, task_id: int, timeline_json: str, media_cache_json: str = None) -> None:
        c = self._cursor()
        if media_cache_json:
            c.execute(
                "UPDATE tasks SET timeline_json = ?, media_cache_json = ?, updated_at = unixepoch() WHERE id = ?",
                (timeline_json, media_cache_json, task_id),
            )
        else:
            c.execute(
                "UPDATE tasks SET timeline_json = ?, updated_at = unixepoch() WHERE id = ?",
                (timeline_json, task_id),
            )
        self.commit()

    def update_task_status(self, drama_id: int, name: str, status: str) -> None:
        c = self._cursor()
        c.execute(
            "UPDATE tasks SET status = ?, updated_at = unixepoch() WHERE drama_id = ? AND name = ?",
            (status, drama_id, name),
        )
        self.commit()

    def update_task_meta(self, task_id: int, segments_count: int = None, duration: float = None) -> None:
        """更新任务元信息"""
        c = self._cursor()
        fields = []
        vals = []
        if segments_count is not None:
            fields.append("segments_count = ?")
            vals.append(segments_count)
        if duration is not None:
            fields.append("duration = ?")
            vals.append(duration)
        if fields:
            fields.append("updated_at = unixepoch()")
            vals.append(task_id)
            c.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", vals)
            self.commit()

    # ═══════════════════════════════════════════════
    # Task Segments
    # ═══════════════════════════════════════════════

    def save_task_segments(self, task_id: int, segments: list[dict]) -> None:
        """保存任务的分段列表"""
        c = self._cursor()
        for seg in segments:
            c.execute(
                "INSERT OR REPLACE INTO task_segments "
                "(task_id, seg_id, highlight_text, narration_text, episode_marker_ep, "
                "episode_marker_min, mode, sentences_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    seg.get("seg_id", 0),
                    seg.get("highlight_text", seg.get("highlight", "")),
                    seg.get("narration_text", seg.get("narration", "")),
                    seg.get("episode_marker_ep"),
                    seg.get("episode_marker_min"),
                    seg.get("mode", "A"),
                    seg.get("sentences_json"),
                ),
            )
        self.commit()
        # 更新任务元信息
        c.execute(
            "UPDATE tasks SET segments_count = ?, updated_at = unixepoch() WHERE id = ?",
            (len(segments), task_id),
        )
        self.commit()

    def get_task_segments(self, task_id: int) -> list[dict]:
        """获取任务分段（API: /segments.json）"""
        c = self._cursor()
        rows = c.execute(
            "SELECT * FROM task_segments WHERE task_id = ? ORDER BY seg_id",
            (task_id,),
        ).fetchall()
        return [
            {
                "seg_id": r["seg_id"],
                "highlight_text": r["highlight_text"],
                "narration_text": r["narration_text"],
                "episode_marker": (
                    {"episode": r["episode_marker_ep"], "approx_minute": r["episode_marker_min"]}
                    if r["episode_marker_ep"] is not None
                    else None
                ),
                "mode": r["mode"],
                "sentences": (
                    __import__("json").loads(r["sentences_json"])
                    if r["sentences_json"]
                    else None
                ),
            }
            for r in rows
        ]

    def validate_episode_markers(self, task_id: int) -> list[dict]:
        """校验分段 episode markers（数据台用）"""
        c = self._cursor()
        segments = self.get_task_segments(task_id)
        task = self.get_task_by_id(task_id)
        if not task:
            return []
        drama_id = task["drama_id"]
        indexed_eps = set(self.get_indexed_eps(drama_id))
        results = []
        for seg in segments:
            marker = seg.get("episode_marker")
            ep = marker.get("episode") if marker else None
            has_data = ep in indexed_eps if ep is not None else None
            results.append({
                "seg_id": seg["seg_id"],
                "marker_ep": ep,
                "has_index": has_data,
                "status": "ok" if has_data else ("unknown" if ep is None else "missing"),
            })
        return results

    # ═══════════════════════════════════════════════
    # Quality Reports
    # ═══════════════════════════════════════════════

    def compute_quality_report(self, drama_id: int, ep: int, drama_dir: str = None) -> dict:
        """基于 episodes 数据 + 原始 ASR 文件计算质量评分"""
        import statistics as _stat

        ep_data = self.get_episode(drama_id, ep)
        if not ep_data:
            return {"error": "episode not found", "overall_score": 0}

        raw = ep_data["asr_raw_count"] or 1
        clean = ep_data["asr_clean_count"] or raw
        scene_count = ep_data["vlm_scene_count"] or 1
        raw_chars = ep_data["asr_raw_chars"] or 0

        # ── ASR 质量检测 ──
        is_fixed_interval = False
        asr_score = 50.0  # 默认

        if drama_dir:
            # 读取原始 ASR 检测固定间隔
            asr_file = Path(drama_dir) / "sources" / f"ep{ep}" / "asr_result.json"
            if asr_file.exists():
                try:
                    import json as _json
                    asr_raw = _json.load(open(asr_file))
                    if len(asr_raw) > 3:
                        durs = [a["end"] - a["start"] for a in asr_raw if a["end"] > a["start"]]
                        if len(durs) > 10:
                            # 排除最后一段（片尾可能不整除导致偏短）
                            durs_trimmed = durs[:-1] if len(durs) > 11 else durs
                            std = _stat.stdev(durs_trimmed)
                            avg_dur = sum(durs_trimmed) / len(durs_trimmed)
                            # 标准差接近0 + 长间隔 → 固定分块（不是真正的 VAD ASR）
                            if std < 0.5 and avg_dur > 8:
                                is_fixed_interval = True
                except Exception:
                    pass

        if is_fixed_interval:
            # 固定间隔 ASR → 质量极差，不管碎片率看起来多好
            asr_score = 15.0
            # 尝试从 VLM 描述中估计实际语音内容
            # 有效内容密度 = raw_chars 中真正有意义的比例（粗略估算）
            effective_ratio = min(1.0, raw_chars / max(raw * 30, 1))  # 正常每段应有 ~30字
            asr_score = round(15.0 + effective_ratio * 20, 1)  # 范围 15-35
        else:
            # 正常 VAD ASR: 碎片率低 = 质量好
            frag_rate = max(0, (raw - clean) / raw) if raw > 0 else 0
            # 内容密度修正: 每段平均字数太少也扣分
            avg_chars_per_seg = raw_chars / max(raw, 1)
            density_factor = min(1.0, avg_chars_per_seg / 8.0)  # 8字/段为正常线
            asr_score = round((1 - frag_rate) * density_factor * 100, 1)

        # ── VLM 评分 ──
        short_ratio = (ep_data["vlm_short_desc_count"] or 0) / scene_count
        shallow_ratio = (ep_data["vlm_shallow_depth_count"] or 0) / scene_count
        skip_ratio = (ep_data["vlm_skip_opening_count"] or 0) / scene_count
        vlm_score = round(max(0, (1 - short_ratio * 0.5 - shallow_ratio * 0.3 - skip_ratio * 0.1)) * 100, 1)

        # ── 字幕评分 ──
        subtitle_score = round(min(100, (ep_data["subtitle_count"] or 0) / max(scene_count, 1) * 50), 1)

        # ── 总分加权 ──
        overall = round(asr_score * 0.35 + vlm_score * 0.4 + subtitle_score * 0.1 + (50 if ep_data["indexed"] else 0) * 0.15, 1)

        # ── 诊断 ──
        issues = []
        if is_fixed_interval:
            issues.append("ASR 固定分块(非VAD)，有效内容极低")
        else:
            frag_rate = max(0, (raw - clean) / raw) if raw > 0 else 0
            if frag_rate > 0.4:
                issues.append(f"ASR 碎片率 {frag_rate:.0%}")
        if short_ratio > 0.2:
            issues.append(f"VLM 短描述 {short_ratio:.0%}")
        if not ep_data["indexed"]:
            issues.append("未纳入索引")
        summary = "数据质量良好" if not issues else "; ".join(issues)

        # 存入缓存
        c = self._cursor()
        c.execute(
            "INSERT OR REPLACE INTO quality_reports "
            "(drama_id, ep_number, asr_score, vlm_score, subtitle_score, overall_score, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (drama_id, ep, asr_score, vlm_score, subtitle_score, overall, summary),
        )
        self.commit()

        return {
            "ep": ep, "asr_score": asr_score, "vlm_score": vlm_score,
            "subtitle_score": subtitle_score, "overall_score": overall,
            "summary": summary,
        }

    def get_quality_report(self, drama_id: int, ep: int) -> dict | None:
        c = self._cursor()
        row = c.execute(
            "SELECT * FROM quality_reports WHERE drama_id = ? AND ep_number = ?",
            (drama_id, ep),
        ).fetchone()
        return dict(row) if row else None

    def get_all_quality_reports(self, drama_id: int) -> list[dict]:
        c = self._cursor()
        rows = c.execute(
            "SELECT * FROM quality_reports WHERE drama_id = ? ORDER BY ep_number",
            (drama_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ═══════════════════════════════════════════════
    # Picks (便捷 API)
    # ═══════════════════════════════════════════════

    def get_picks(self, drama_id: int, task_name: str) -> dict:
        task = self.get_task(drama_id, task_name)
        if not task or not task.get("picks_json"):
            return {}
        import json
        try:
            return json.loads(task["picks_json"])
        except (json.JSONDecodeError, TypeError):
            return {}

    def save_picks(self, drama_id: int, task_name: str, picks: dict) -> None:
        import json
        task = self.get_task(drama_id, task_name)
        if not task:
            task_id = self.create_task(drama_id, task_name)
        else:
            task_id = task["id"]
        self.update_task_picks(task_id, json.dumps(picks, ensure_ascii=False))

    def get_timeline(self, drama_id: int, task_name: str) -> dict | None:
        task = self.get_task(drama_id, task_name)
        if not task or not task.get("timeline_json"):
            return None
        import json
        try:
            return json.loads(task["timeline_json"])
        except (json.JSONDecodeError, TypeError):
            return None

    def save_timeline(self, drama_id: int, task_name: str, timeline: dict, media_cache: dict = None) -> None:
        import json
        task = self.get_task(drama_id, task_name)
        if not task:
            return
        mc_json = json.dumps(media_cache, ensure_ascii=False) if media_cache else None
        self.update_task_timeline(
            task["id"],
            json.dumps(timeline, ensure_ascii=False),
            mc_json,
        )
