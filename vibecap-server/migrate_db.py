#!/usr/bin/env python3
"""
VIBECAP 数据迁移脚本：JSON/Pickle → SQLite
用法：
    python3 migrate_db.py              # 执行迁移
    python3 migrate_db.py --dry-run    # 预览不写入
    python3 migrate_db.py --force      # 删除旧 DB 重建
"""

import sys, os, json, pickle, ast, time
from pathlib import Path

# 确保能找到 db.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import VibeCapDB

BASE_DIR = Path("/Users/zgl/VIBECAP")
DB_PATH = BASE_DIR / "vibecap.db"

SLUG_MAP = {"都挺好": "doutinghao"}

DRY_RUN = "--dry-run" in sys.argv
FORCE = "--force" in sys.argv


def log(msg):
    prefix = "[DRY-RUN] " if DRY_RUN else ""
    print(f"{prefix}{msg}")


def parse_episode_marker(raw):
    """解析 episode_marker：可能是 dict、字符串 repr、或 None"""
    if raw is None:
        return None, None
    if isinstance(raw, dict):
        return raw.get("episode"), raw.get("approx_minute")
    if isinstance(raw, str):
        try:
            d = ast.literal_eval(raw)
            return d.get("episode"), d.get("approx_minute")
        except (ValueError, SyntaxError):
            pass
    return None, None


def compute_ep_stats(sources_dir, clean_dir):
    """计算单集的 ASR/VLM 统计"""
    stats = {
        "asr_raw_count": 0, "asr_raw_chars": 0,
        "asr_clean_count": 0, "asr_clean_chars": 0, "asr_frag_rate": 0.0,
        "vlm_scene_count": 0, "vlm_avg_desc_len": 0.0, "vlm_avg_depth_len": 0.0,
        "vlm_short_desc_count": 0, "vlm_shallow_depth_count": 0,
        "vlm_skip_opening_count": 0, "subtitle_count": 0,
        "indexed": False, "indexed_entries": 0,
        "analyzed_at": None, "cleaned_at": None,
    }

    # ASR raw
    asr_file = sources_dir / "asr_result.json"
    if asr_file.exists():
        try:
            asr_raw = json.load(open(asr_file))
            stats["asr_raw_count"] = len(asr_raw)
            stats["asr_raw_chars"] = sum(len(a.get("text", "")) for a in asr_raw)
            stats["analyzed_at"] = int(asr_file.stat().st_mtime)
        except Exception:
            pass

    # ASR clean
    asr_clean_file = clean_dir / "asr_result.json"
    if asr_clean_file.exists():
        try:
            asr_clean = json.load(open(asr_clean_file))
            stats["asr_clean_count"] = len(asr_clean)
            stats["asr_clean_chars"] = sum(len(a.get("text", "")) for a in asr_clean)
            stats["cleaned_at"] = int(asr_clean_file.stat().st_mtime)
        except Exception:
            pass

    # 碎片率
    if stats["asr_raw_count"] > 0:
        stats["asr_frag_rate"] = round(
            max(0, (stats["asr_raw_count"] - stats["asr_clean_count"]) / stats["asr_raw_count"]), 2
        )

    # VLM
    vlm_file = sources_dir / "vlm_analysis.json"
    if vlm_file.exists():
        try:
            vlm_raw = json.load(open(vlm_file))
            valid = [s for s in vlm_raw if s is not None]
            stats["vlm_scene_count"] = len(valid)
            if valid:
                desc_lens = [len(s.get("description", "")) for s in valid]
                depth_lens = [len(s.get("depth_analysis", "")) for s in valid]
                stats["vlm_avg_desc_len"] = round(sum(desc_lens) / len(desc_lens), 1)
                stats["vlm_avg_depth_len"] = round(sum(depth_lens) / len(depth_lens), 1)
                stats["vlm_short_desc_count"] = sum(1 for l in desc_lens if l < 20)
                stats["vlm_shallow_depth_count"] = sum(1 for l in depth_lens if l < 30)
                stats["vlm_skip_opening_count"] = sum(
                    1 for s in valid
                    if any(kw in s.get("description", "") for kw in ["片头", "片尾", "水墨", "演职人员", "字幕滚动"])
                )
                # 字幕数（从原始或清洗后提取）
                stats["subtitle_count"] = sum(len(s.get("subtitles", s.get("subtitle", []))) for s in valid)
            stats["analyated_at"] = stats["analyzed_at"] or int(vlm_file.stat().st_mtime)
        except Exception:
            pass

    # VLM clean — 补充字幕统计
    vlm_clean_file = clean_dir / "vlm_analysis.json"
    if vlm_clean_file.exists():
        try:
            vlm_clean = json.load(open(vlm_clean_file))
            valid_c = [s for s in vlm_clean if s is not None]
            sub_count = sum(len(s.get("subtitles", [])) for s in valid_c)
            if sub_count > stats["subtitle_count"]:
                stats["subtitle_count"] = sub_count
            # 标签统计
            tags_count = sum(1 for s in valid_c if "short_desc" in s.get("tags", []))
            if tags_count > stats["vlm_short_desc_count"]:
                stats["vlm_short_desc_count"] = tags_count
            tags_shallow = sum(1 for s in valid_c if "shallow_depth" in s.get("tags", []))
            if tags_shallow > stats["vlm_shallow_depth_count"]:
                stats["vlm_shallow_depth_count"] = tags_shallow
            tags_skip = sum(1 for s in valid_c if "skip_opening" in s.get("tags", []))
            if tags_skip > stats["vlm_skip_opening_count"]:
                stats["vlm_skip_opening_count"] = tags_skip
        except Exception:
            pass

    return stats


def migrate_dramas(db):
    """导入剧集"""
    log("=== 导入剧集 ===")
    dramas = []
    for d in BASE_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        tasks_dir = d / "tasks"
        pkl_file = d / "semantic_index.pkl"
        if tasks_dir.exists() or pkl_file.exists():
            slug = SLUG_MAP.get(d.name, d.name)
            dramas.append({"name": d.name, "slug": slug})
            log(f"  剧集: {d.name} (slug={slug})")

    if not DRY_RUN:
        for d in dramas:
            db.ensure_drama(d["name"], d["slug"])
    return dramas


def migrate_episodes(db):
    """初始化全部集数 + 导入已有质量数据"""
    log("=== 初始化剧集数据 ===")
    dramas = db.list_dramas() if not DRY_RUN else [{"name": "都挺好"}]

    # 硬编码：都挺好共46集
    TOTAL_EPS = {"都挺好": 46}

    for drama in dramas:
        name = drama["name"]
        drama_id = db.get_drama_id(name) if not DRY_RUN else 1
        total = TOTAL_EPS.get(name, 0)
        if total > 0:
            if not DRY_RUN and drama_id:
                added = db.init_drama_episodes(drama_id, total)
                if added > 0:
                    log(f"  {name}: 初始化 {added}/{total} 集")
                else:
                    log(f"  {name}: {total} 集已存在")

    for drama in dramas:
        name = drama["name"]
        drama_dir = BASE_DIR / name
        sources_dir = drama_dir / "sources"
        clean_dir = drama_dir / "sources_clean"

        if not sources_dir.exists():
            continue

        for ep_dir in sorted(sources_dir.iterdir()):
            if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
                continue
            try:
                ep = int(ep_dir.name[2:])
            except ValueError:
                continue

            clean_ep_dir = clean_dir / ep_dir.name
            stats = compute_ep_stats(ep_dir, clean_ep_dir)
            log(f"  {name} EP{ep}: ASR raw={stats['asr_raw_count']} clean={stats['asr_clean_count']} "
                f"VLM={stats['vlm_scene_count']} subs={stats['subtitle_count']}")

            if not DRY_RUN:
                drama_id = db.get_drama_id(name)
                if drama_id:
                    db.upsert_episode(drama_id, ep, stats)


def migrate_index_entries(db):
    """导入语义索引元数据"""
    log("=== 导入索引元数据 ===")
    dramas = db.list_dramas() if not DRY_RUN else [{"name": "都挺好"}]

    for drama in dramas:
        name = drama["name"]
        pkl_path = BASE_DIR / name / "semantic_index.pkl"
        if not pkl_path.exists():
            log(f"  {name}: 无 semantic_index.pkl")
            continue

        idx = pickle.load(open(pkl_path, "rb"))
        metas = idx.get("metas", [])
        entries = []
        for m in metas:
            entries.append({
                "ep": m.get("ep", 0),
                "type": m.get("type", "vlm"),
                "start": m.get("start", 0),
                "end": m.get("end", 0),
                "scene_id": m.get("scene_id", 0),
                "text": m.get("text", ""),
                "weight": 1.0 if m.get("type") != "sub" else 2.0,
            })

        # 按集统计
        ep_counts = {}
        for e in entries:
            ep = e["ep"]
            ep_counts[ep] = ep_counts.get(ep, 0) + 1

        log(f"  {name}: {len(entries)} 条索引, 覆盖 EP {sorted(ep_counts.keys())}")

        if not DRY_RUN:
            drama_id = db.get_drama_id(name)
            if drama_id:
                db.bulk_insert_index_entries(drama_id, entries)
                # 更新 episodes 的 indexed 状态
                for ep, count in ep_counts.items():
                    db.upsert_episode(drama_id, ep, {"indexed": True, "indexed_entries": count})


def migrate_tasks(db):
    """导入任务和分段"""
    log("=== 导入任务 ===")
    dramas = db.list_dramas() if not DRY_RUN else [{"name": "都挺好"}]

    for drama in dramas:
        name = drama["name"]
        tasks_dir = BASE_DIR / name / "tasks"
        if not tasks_dir.exists():
            continue

        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir() or task_dir.name.startswith("."):
                continue

            seg_file = task_dir / "segments.json"
            if not seg_file.exists():
                continue

            try:
                seg_data = json.load(open(seg_file))
            except Exception:
                log(f"  {task_dir.name}: segments.json 解析失败")
                continue

            task_name = task_dir.name
            segments = seg_data.get("segments", [])
            total = seg_data.get("total_segments", len(segments))

            # 读取任务状态
            status = "editing"
            status_file = task_dir / "status.json"
            if status_file.exists():
                try:
                    status = json.load(open(status_file)).get("status", "editing")
                except Exception:
                    pass

            # 读取时长
            duration = 0.0
            narr_file = task_dir / "work_dir" / "narration.json"
            if narr_file.exists():
                try:
                    narr = json.load(open(narr_file))
                    duration = round(sum(
                        s.get("duration", s.get("end", 0) - s.get("start", 0))
                        for s in narr
                    ), 1)
                except Exception:
                    pass

            log(f"  {task_name}: {len(segments)} 段, 状态={status}, 时长={duration}s")

            if not DRY_RUN:
                drama_id = db.get_drama_id(name)
                if not drama_id:
                    continue
                task_id = db.create_task(drama_id, task_name)
                if task_id:
                    db.update_task_status(drama_id, task_name, status)
                    db.update_task_meta(task_id, len(segments), duration)

                    # 导入分段
                    seg_rows = []
                    for seg in segments:
                        ep_marker = seg.get("episode_marker")
                        ep, emin = parse_episode_marker(ep_marker)
                        seg_rows.append({
                            "seg_id": seg.get("seg_id", 0),
                            "highlight_text": seg.get("highlight_text", ""),
                            "narration_text": seg.get("narration_text", ""),
                            "episode_marker_ep": ep,
                            "episode_marker_min": emin,
                            "mode": seg.get("mode", "A"),
                            "sentences_json": json.dumps(seg.get("sentences")) if seg.get("sentences") else None,
                        })
                    db.save_task_segments(task_id, seg_rows)


def migrate_quality_reports(db):
    """预计算质量报告"""
    log("=== 计算质量报告 ===")
    dramas = db.list_dramas() if not DRY_RUN else [{"name": "都挺好"}]

    for drama in dramas:
        name = drama["name"]
        if DRY_RUN:
            log(f"  {name}: 跳过 (dry-run)")
            continue
        drama_id = db.get_drama_id(name)
        if not drama_id:
            continue
        drama_dir = BASE_DIR / name
        episodes = db.get_all_episodes(drama_id)
        for ep_data in episodes:
            ep = ep_data["ep_number"]
            report = db.compute_quality_report(drama_id, ep, str(drama_dir))
            score = report.get("overall_score", 0)
            summary = report.get("summary", "")
            log(f"  {name} EP{ep}: 总分={score} {summary}")


def main():
    if FORCE and DB_PATH.exists():
        log(f"删除旧数据库: {DB_PATH}")
        if not DRY_RUN:
            DB_PATH.unlink()

    db = VibeCapDB(str(DB_PATH)) if not DRY_RUN else None

    migrate_dramas(db)
    migrate_episodes(db)
    migrate_index_entries(db)
    migrate_tasks(db)
    migrate_quality_reports(db)

    log("")
    log("✅ 迁移完成!")

    if not DRY_RUN and db:
        # 输出摘要
        dramas = db.list_dramas()
        for d in dramas:
            drama_id = db.get_drama_id(d["name"])
            episodes = db.get_all_episodes(drama_id)
            idx_stats = db.get_index_stats(drama_id)
            tasks = db.list_tasks(drama_id)
            log(f"  {d['name']}: {len(episodes)} 集, {idx_stats.get('total', 0)} 条索引, {len(tasks)} 个任务")

        db.close()


if __name__ == "__main__":
    main()
