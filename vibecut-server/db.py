"""
VibeCut SQLite 数据库层
统一管理：剧集、集数据质量、语义索引元数据、任务、分段、质量报告

用法:
    from db import VibeCutDB
    db = VibeCutDB("path/to/vibecut.db")
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
    description TEXT DEFAULT '',
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
    source_start REAL,                -- v0.11: 素材起始时间(秒), 口播直达用
    source_end REAL,                  -- v0.11: 素材结束时间(秒)
    section_role TEXT DEFAULT '',     -- v0.11: 叙事角色 (hook_tension/evidence/...)
    note TEXT DEFAULT '',             -- v0.11: 注释
    mode TEXT DEFAULT 'A' CHECK(mode IN ('A','C')),
    sentences_json TEXT,
    UNIQUE(task_id, seg_id)
);

-- v0.11: 迁移由 Python 代码执行 (见 __init__ 中 MIGRATIONS)

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

# v0.11 迁移: 为旧 task_segments 表补充时序列
MIGRATIONS = [
    "ALTER TABLE task_segments ADD COLUMN source_start REAL",
    "ALTER TABLE task_segments ADD COLUMN source_end REAL",
    "ALTER TABLE task_segments ADD COLUMN section_role TEXT DEFAULT ''",
    "ALTER TABLE task_segments ADD COLUMN note TEXT DEFAULT ''",
    "ALTER TABLE tasks ADD COLUMN description TEXT DEFAULT ''",
    "ALTER TABLE task_segments ADD COLUMN video_episode INTEGER",
    "ALTER TABLE task_segments ADD COLUMN highlight_ep INTEGER",
    "ALTER TABLE task_segments ADD COLUMN highlight_start REAL",
    "ALTER TABLE task_segments ADD COLUMN highlight_end REAL",
]


class VibeCutDB:
    """SQLite 数据库访问层，线程安全"""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)
        self._local = threading.local()
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        # v0.11: 执行增量迁移 (忽略已存在的列)
        for sql in MIGRATIONS:
            try:
                conn.execute(sql)
            except Exception:
                pass  # 列已存在
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

    def list_tasks(self, drama_id: int) -> list[dict]:
        """返回剧集下所有任务（API: /tasks）"""
        c = self._cursor()
        rows = c.execute("""
            SELECT name, status, segments_count, duration, picks_json, created_at, updated_at, description
            FROM tasks WHERE drama_id = ? ORDER BY created_at DESC
        """, (drama_id,)).fetchall()
        return [
            {
                "name": r["name"],
                "segments": r["segments_count"],
                "status": r["status"],
                "duration": r["duration"],
                "description": r["description"] or "",
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

    def create_task(self, drama_id: int, name: str, description: str = "") -> int:
        """创建任务，返回 task_id。已有任务时更新 description。"""
        c = self._cursor()
        c.execute(
            "INSERT INTO tasks (drama_id, name, description) VALUES (?, ?, ?) "
            "ON CONFLICT(drama_id, name) DO UPDATE SET description=excluded.description",
            (drama_id, name, description or ""),
        )
        self.commit()
        task = self.get_task(drama_id, name)
        if task:
            return task["id"]
        row = c.execute(
            "SELECT id FROM tasks WHERE drama_id = ? AND name = ?",
            (drama_id, name),
        ).fetchone()
        return row["id"] if row else 0

    def update_task_description(self, drama_id: int, name: str, description: str) -> None:
        """更新任务描述"""
        c = self._cursor()
        c.execute(
            "UPDATE tasks SET description = ?, updated_at = unixepoch() WHERE drama_id = ? AND name = ?",
            (description, drama_id, name),
        )
        self.commit()

    def update_task_status(self, drama_id: int, name: str, status: str) -> None:
        c = self._cursor()
        c.execute(
            "UPDATE tasks SET status = ?, updated_at = unixepoch() WHERE drama_id = ? AND name = ?",
            (status, drama_id, name),
        )
        self.commit()

    def delete_task(self, drama_id: int, name: str) -> bool:
        """删除任务及其分段数据，返回是否成功"""
        c = self._cursor()
        task = self.get_task(drama_id, name)
        if not task:
            return False
        # 先删分段
        c.execute("DELETE FROM task_segments WHERE task_id = ?", (task["id"],))
        # 再删任务
        c.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        self.commit()
        return True

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
            # 兼容两种 episode_marker 形态：嵌套 dict {episode, approx_minute, raw}
            # 与扁平键 episode_marker_ep / episode_marker_min。
            marker = seg.get("episode_marker") or {}
            ep = seg.get("episode_marker_ep", marker.get("episode") if isinstance(marker, dict) else None)
            minute = seg.get("episode_marker_min", marker.get("approx_minute") if isinstance(marker, dict) else None)
            video_ep = seg.get("video_episode") or (ep if ep is not None else None)
            c.execute(
                "INSERT OR REPLACE INTO task_segments "
                "(task_id, seg_id, highlight_text, narration_text, episode_marker_ep, "
                "episode_marker_min, source_start, source_end, section_role, note, mode, "
                "sentences_json, video_episode, highlight_ep, highlight_start, highlight_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    seg.get("seg_id", 0),
                    seg.get("highlight_text", seg.get("highlight", "")),
                    seg.get("narration_text", seg.get("narration", "")),
                    ep,
                    minute,
                    seg.get("source_start"),
                    seg.get("source_end"),
                    seg.get("section_role", seg.get("narrative_role", "")),
                    seg.get("note", ""),
                    seg.get("mode", "A"),
                    seg.get("sentences_json"),
                    video_ep,
                    seg.get("highlight_ep"),
                    seg.get("highlight_start"),
                    seg.get("highlight_end"),
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
        result = []
        for r in rows:
            seg = {
                "seg_id": r["seg_id"],
                "highlight_text": r["highlight_text"],
                "narration_text": r["narration_text"],
                "episode_marker": (
                    {"episode": r["episode_marker_ep"], "approx_minute": r["episode_marker_min"]}
                    if r["episode_marker_ep"] is not None
                    else None
                ),
                "source_start": r["source_start"],       # v0.11
                "source_end": r["source_end"],             # v0.11
                "section_role": r["section_role"] or "",   # v0.11
                "note": r["note"] or "",                   # v0.11
                "mode": r["mode"],
                "sentences": (
                    __import__("json").loads(r["sentences_json"])
                    if r["sentences_json"]
                    else None
                ),
            }
            # video_episode 列存在时补回（旧表迁移后可能为 None）
            if "video_episode" in r.keys():
                seg["video_episode"] = r["video_episode"]
            # highlight 锚定字段（原剧台词 ASR 时间戳）
            if "highlight_ep" in r.keys():
                seg["highlight_ep"] = r["highlight_ep"]
                seg["highlight_start"] = r["highlight_start"]
                seg["highlight_end"] = r["highlight_end"]
            result.append(seg)
        return result

    def compute_quality_report(self, drama_id: int, ep: int, drama_dir: str = None) -> dict:
        """基于 episodes 数据 + 原始 ASR 文件计算质量评分"""
        import statistics as _stat

        ep_data = self.get_episode(drama_id, ep)
        if not ep_data:
            return {"error": "episode not found", "overall_score": 0}

        # 零数据 → 0分
        raw = ep_data["asr_raw_count"] or 0
        vlm_scenes = ep_data["vlm_scene_count"] or 0
        if raw == 0 and vlm_scenes == 0:
            c = self._cursor()
            c.execute(
                "INSERT OR REPLACE INTO quality_reports "
                "(drama_id, ep_number, asr_score, vlm_score, subtitle_score, overall_score, summary) "
                "VALUES (?, ?, 0, 0, 0, 0, '未分析')",
                (drama_id, ep),
            )
            self.commit()
            return {"ep": ep, "asr_score": 0, "vlm_score": 0,
                    "subtitle_score": 0, "overall_score": 0, "summary": "未分析"}

        raw = raw or 1
        clean = ep_data["asr_clean_count"] or raw
        scene_count = ep_data["vlm_scene_count"] or 1
        raw_chars = ep_data["asr_raw_chars"] or 0

        # ── ASR 质量检测 ──
        is_fixed_interval = False
        asr_score = 50.0  # 默认

        if drama_dir:
            # 读取原始 ASR 检测固定间隔
            asr_file = Path(drama_dir) / "sources" / f"ep{ep}" / "subtitle_result.json"
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
            # 正常 VAD ASR: 评估最终可用文本质量
            # 1. 内容密度 (40%): 每集约45分钟，正常对白 4000-8000字 → 100字/分钟为满分
            content_chars = ep_data.get("asr_clean_chars", raw_chars) or raw_chars
            chars_per_min = content_chars / 45
            content_score = min(100, chars_per_min / 100 * 80)

            # 2. 段质量 (40%): 替代碎片率，用平均段长和字密度衡量模型能力
            # 平均 raw 段长 (秒) — 反映 VAD + 模型质量，越长越好
            avg_raw_dur = (45 * 60) / max(raw, 1)
            # 平均 raw 段字数 — 反映模型转写完整度
            avg_chars_per_seg = raw_chars / max(raw, 1)
            # 综合段质量: 段长权重 0.5 + 字密度权重 0.5
            dur_score = min(100, avg_raw_dur / 5.0 * 100)       # 5秒/段 = 100分
            char_score = min(100, avg_chars_per_seg / 10 * 100)  # 10字/段 = 100分
            seg_quality = dur_score * 0.5 + char_score * 0.5

            # 3. 模型规模检测加分 (10%): 段越长、字越多 → 模型越大
            # tiny: ~2s/段 3字, small: ~3s/段 6字, medium: ~3.5s/段 8字
            model_bonus = min(15, max(0, (avg_raw_dur - 2.2) * 5 + (avg_chars_per_seg - 3) * 1.5))

            # 4. 字幕校准加分 (10%)
            sub_count = ep_data.get("subtitle_count", 0) or 0
            sub_bonus = min(10, sub_count / max(scene_count, 1) * 8)

            asr_score = round(content_score * 0.40 + seg_quality * 0.40 + model_bonus + sub_bonus, 1)

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
            avg_raw_dur = (45 * 60) / max(raw, 1)
            avg_chars = raw_chars / max(raw, 1)
            if avg_raw_dur < 2.5:
                issues.append(f"ASR 段长偏短({avg_raw_dur:.1f}s)，疑似低质量模型")
            elif avg_chars < 3:
                issues.append(f"ASR 内容稀疏({avg_chars:.0f}字/段)")
            elif asr_score < 40:
                issues.append(f"ASR 内容偏少")
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
