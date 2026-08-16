#!/usr/bin/env python3
"""
A1b: 解析外部生成的解说 JSON → segments.json

支持两种外部格式（扣子/WorkBuddy 等产出）：
  1. mode=original/narration + clips[{episode,start_time,end_time,line}]（带精确锚定）
  2. type=dialogue/narration + episode + timecode（带集号+时间码，可能不精确）

用 SRT 字幕数据（sources/epN/subtitle_result.json）做台词反查，
把 dialogue 段对齐到真实 source_start/source_end。

用法:
  cd vibecut-server
  VibeCut_DRAMA=都挺好 VibeCut_TASK=TaskXXX \
    /opt/anaconda3/bin/python3 cli/parse_external_json.py <input.json>
"""
import json
import os
import re
import sys
from pathlib import Path

# 项目根：VIBECAP/<project>，由环境变量 VibeCut_DRAMA 指定（默认 都挺好）
# 注意：不 import config，因为它带 argparse 副作用（会消费 sys.argv）
_SERVER_DIR = Path(__file__).resolve().parent.parent   # vibecut-server/
_BASE_DIR = _SERVER_DIR.parent                          # VIBECAP/
DRAMA_NAME = os.environ.get("VibeCut_DRAMA") or os.environ.get("VibeCut_PROJECT") or "都挺好"
DRAMA_DIR = _BASE_DIR / DRAMA_NAME
TASK_DIR = DRAMA_DIR / "tasks" / (os.environ.get("VibeCut_TASK") or "Task7024")
SOURCES_DIR = DRAMA_DIR / "sources"


def hms_to_sec(hms: str) -> float:
    """'00:04:16' 或 '00:04:16,067' → 秒"""
    hms = hms.strip().replace(",", ".")
    parts = hms.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0


def load_subtitle(ep: int, sources_dir: Path) -> list:
    """加载某集字幕 [{start,end,text}]"""
    for name in (f"ep{ep}", f"ep{ep:02d}"):
        f = sources_dir / name / "subtitle_result.json"
        if f.exists():
            try:
                return json.load(open(f))
            except Exception:
                return []
    return []


def find_by_keyword(ep: int, kw: str, sources_dir: Path, around_sec: float = None) -> dict | None:
    """在字幕里按关键词找台词，返回 {start,end,text}。有 around_sec 则优先时间附近。"""
    subs = load_subtitle(ep, sources_dir)
    if not subs:
        return None
    kw = kw.strip()
    if not kw:
        return None
    # 用前 6 字做锚（去除说话人前缀/标点）
    anchor = re.sub(r"[，。！？、\s\"'「」『』：:]", "", kw)[:6]
    if len(anchor) < 2:
        return None
    hits = [s for s in subs if anchor in re.sub(r"\s", "", s["text"])]
    if not hits:
        return None
    if around_sec is not None:
        hits.sort(key=lambda s: abs(s["start"] - around_sec))
    return {"start": hits[0]["start"], "end": hits[0]["end"], "text": hits[0]["text"]}


def normalize_external(data: dict, sources_dir: Path = None) -> dict:
    """把外部 JSON 归一化成 segments.json 契约

    sources_dir: 项目 sources 目录（含 epN/subtitle_result.json），用于 SRT 反查校准。
    """
    raw_segments = data.get("segments", [])
    segments = []

    for i, s in enumerate(raw_segments):
        # 段类型
        mode = s.get("mode") or s.get("type") or "narration"
        is_original = mode in ("original", "dialogue")
        is_narration = mode in ("narration",)

        content = (s.get("content") or "").strip()
        function = s.get("function")
        note = s.get("note") or s.get("scene_note") or ""

        seg = {
            "seg_id": i,
            "narration_text": content if is_narration else "",
            "highlight_text": content if is_original else "",
            "mode": "A",
            "function": function,
            "note": note,
        }

        # episode
        ep = s.get("episode") or s.get("ep")
        clips = s.get("clips", [])

        if ep:
            seg["video_episode"] = ep
            seg["episode_marker"] = {"episode": ep, "approx_minute": None, "raw": f"EP{ep}"}

        # 精确锚定：clips（第一份格式）或 timecode（第二份格式）
        if is_original:
            if clips and isinstance(clips, list) and clips[0].get("start_time"):
                # 第一份：clips 已带精确 start_time/end_time
                first = clips[0]
                last = clips[-1]
                cep = first.get("episode", ep)
                start = hms_to_sec(first.get("start_time", "0"))
                end = hms_to_sec(last.get("end_time", first.get("start_time", "0")))
                seg["video_episode"] = cep
                seg["episode_marker"] = {"episode": cep, "approx_minute": start / 60, "raw": f"{cep}~{start//60:.0f}m"}
                seg["source_start"] = round(start, 2)
                seg["source_end"] = round(end, 2)
            elif ep and s.get("timecode"):
                # 第二份：timecode + 关键词反查 SRT 校准
                tgt = hms_to_sec(s["timecode"])
                # 用台词关键词反查精确位置
                kw = re.sub(r"^[^：:]{0,8}[：:]", "", content)  # 去说话人前缀
                hit = find_by_keyword(ep, content, sources_dir or SOURCES_DIR, around_sec=tgt)
                if hit:
                    seg["source_start"] = round(hit["start"], 2)
                    seg["source_end"] = round(hit["end"], 2)
                    seg["episode_marker"] = {"episode": ep, "approx_minute": hit["start"] / 60, "raw": f"{ep}~{hit['start']//60:.0f}m"}
                else:
                    # 反查失败，用 timecode 兜底
                    seg["source_start"] = round(tgt, 2)
                    seg["source_end"] = round(tgt + 3, 2)

        segments.append(seg)

    # 提取 cover / theme / 元信息（方案全文，供左侧面板展示）
    cover = data.get("title") or data.get("theme") or ""
    if isinstance(cover, list):
        cover = cover[0] if cover else ""
    theme = data.get("theme") or ""
    if isinstance(theme, list):
        theme = theme  # theme 可能是 list，保留原样给前端
    core_insight = data.get("core_insight") or ""

    return {
        "task_type": "drama",
        "source": "external-json",
        "pipeline": "external",
        "project_type": "drama",
        "total_segments": len(segments),
        "cover": cover,
        "hook_line": cover[:60],
        "closing_line": "",
        "theme": theme,
        "core_insight": core_insight,
        # 方案全文元信息（左侧面板展示用）
        "meta": {
            "title": data.get("title", ""),
            "series": data.get("series", ""),
            "type": data.get("type", ""),
            "theme": theme,
            "arc_episodes": data.get("arc_episodes", ""),
            "core_insight": core_insight,
            "rhythm_check": data.get("rhythm_check", {}),
            "revision_log": data.get("revision_log", {}),
        },
        "audio_verified": False,
        "segments": segments,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: parse_external_json.py <input.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"输入文件不存在: {input_path}")
        sys.exit(1)

    data = json.load(open(input_path, encoding="utf-8"))
    result = normalize_external(data, SOURCES_DIR)

    out_file = TASK_DIR / "segments.json"
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    segs = result["segments"]
    orig = sum(1 for s in segs if s["highlight_text"])
    narr = sum(1 for s in segs if s["narration_text"])
    anchored = sum(1 for s in segs if s.get("source_start"))
    print(f"✅ 解析完成: {len(segs)} 段 (解说{narr} / 原声{orig} / 已锚定{anchored})")
    print(f"   输出: {out_file}")


if __name__ == "__main__":
    main()
