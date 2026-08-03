#!/usr/bin/env python3
"""
自动剪辑导出 — segments.json → 剪映草稿 (CapCut Draft v2)
完全对照工作草稿的精确格式生成
"""
import json, os, subprocess, uuid, argparse, time
from pathlib import Path

BASE_DIR = Path("/Users/zgl/VIBECAP")
DRAFT_BASE = Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
FPS = 30


def load_project(project_name):
    cfg_path = BASE_DIR / "projects" / f"{project_name}.json"
    return json.load(open(cfg_path))


def load_segments(project_name, task_name):
    seg_path = BASE_DIR / project_name / "tasks" / task_name / "segments.json"
    return json.load(open(seg_path))


def find_source_video(project_cfg, seg_source_file):
    src_dir = Path(project_cfg.get("source_videos", ""))
    candidates = [
        src_dir / f"{seg_source_file}.mp4",
        src_dir / f"{seg_source_file}",
        *sorted(src_dir.glob(f"*{seg_source_file}*")),
    ]
    for c in candidates:
        if c.exists(): return c
    return None


def extract_clip(src_video, start_sec, end_sec, output_path):
    dur = end_sec - start_sec
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_sec), "-t", str(dur),
        "-i", str(src_video),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart",
        str(output_path)
    ], capture_output=True, text=True, check=True)
    return output_path


def _uid(): return str(uuid.uuid4()).upper()


def _make_video_material(mid, path, dur_us, width, height):
    """精确匹配剪映 video material 结构"""
    return {
        "aigc_type": "none", "audio_fade": None, "cartoon_path": "",
        "category_id": "", "category_name": "", "check_flag": 63487,
        "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                 "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
        "crop_ratio": "free", "crop_scale": 1.0, "duration": dur_us,
        "extra_type_option": 1, "formula_id": "", "freeze": None, "gameplay": None,
        "has_audio": True, "height": height, "id": mid,
        "intensifies_audio_path": "", "intensifies_path": "",
        "is_ai_generate_content": False, "is_copyright": False, "is_unified_beauty_mode": False,
        "local_id": "", "local_material_id": "", "material_id": "",
        "material_name": os.path.basename(path),
        "material_url": "", "media_path": "",
        "matting": {"flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False,
                    "interactiveTime": [], "path": "", "strokes": []},
        "object_locked": None, "origin_material_id": "",
        "path": str(path.resolve()),
        "picture_from": "none", "picture_set_category_id": "", "picture_set_category_name": "",
        "request_id": "", "reverse_intensifies_path": "", "reverse_path": "",
        "smart_motion": None, "source": 0, "source_platform": 0,
        "stable": {"matrix_path": "", "stable_level": 0, "time_range": {"duration": 0, "start": 0}},
        "team_id": "", "type": "video",
        "video_algorithm": {"algorithms": [], "deflicker": None, "motion_blur_config": None,
                           "noise_reduction": None, "path": "", "quality_enhance": None, "time_range": None},
        "width": width,
    }


def _make_audio_material(aid, path, dur_us, video_id=""):
    """精确匹配剪映 audio material 结构（原声提取）"""
    return {
        "app_id": 0, "category_id": "", "category_name": "", "check_flag": 0,
        "duration": dur_us, "effect_id": "", "formula_id": "", "id": aid,
        "intensifies_path": "", "is_ai_clone_tone": False, "is_ugc": False,
        "local_material_id": "", "music_id": "", "name": os.path.basename(path),
        "path": str(path.resolve()), "query": "", "request_id": "",
        "resource_id": "", "search_id": "", "source_platform": 0,
        "team_id": "", "text_id": "",
        "tone_category_id": "", "tone_category_name": "",
        "tone_effect_id": "", "tone_effect_name": "",
        "tone_second_category_id": "", "tone_second_category_name": "",
        "tone_speaker": "", "tone_type": "",
        "type": "video_original_sound",
        "video_id": video_id,
        "wave_points": [],
    }


def _make_segment(mid, start_us, dur_us, source_start_us=0):
    """精确匹配剪映 segment 结构
    source_start_us: 源视频中的绝对起始时间（微秒），0=从素材开头开始
    """
    return {
        "cartoon": False,
        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
                 "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0},
                 "transform": {"x": 0.0, "y": 0.0}},
        "common_keyframes": [],
        "enable_adjust": True, "enable_color_curves": True, "enable_color_match_adjust": False,
        "enable_color_wheels": True, "enable_lut": True, "enable_smart_color_adjust": False,
        "extra_material_refs": [],
        "group_id": "",
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
        "id": _uid(),
        "intensifies_audio": False, "is_placeholder": False, "is_tone_modify": False,
        "keyframe_refs": [],
        "last_nonzero_volume": 1.0,
        "material_id": mid,
        "render_index": 0,
        "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0,
                              "target_follow": "", "vertical_pos_layout": 0},
        "reverse": False,
        "source_timerange": {"duration": dur_us, "start": source_start_us},
        "speed": 1.0,
        "target_timerange": {"duration": dur_us, "start": start_us},
        "template_id": "", "template_scene": "default",
        "track_attribute": 0, "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0},
        "visible": True, "volume": 1.0,
    }


def build_draft(segments, source_video, materials_dir, draft_name="vibecap-auto", canvas_w=1080, canvas_h=1920):
    """构建完整剪映 draft_info.json
    核心设计：只导入一次完整源视频，每段用 source_timerange 引用不同时间区间
    这样在剪映里可以自由拉长/缩短每一段的入出点
    """
    draft_id = _uid()
    vid_track_id = _uid()

    # 获取源视频参数
    import subprocess
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
        str(source_video)
    ], capture_output=True, text=True)
    info = json.loads(result.stdout)
    total_dur_s = float(info["format"]["duration"])
    total_dur_us = int(total_dur_s * 1_000_000)
    # 获取实际视频分辨率
    src_width, src_height = canvas_w, canvas_h
    for stream in info.get("streams", []):
        if stream["codec_type"] == "video":
            src_width = stream["width"]
            src_height = stream["height"]
            break
    print(f"  源视频: {source_video.name} ({total_dur_s:.0f}s, {src_width}x{src_height})")

    # 复制完整源视频到 materials（只此一份）
    src_copy = materials_dir / f"source_{source_video.name}"
    if not src_copy.exists():
        print(f"  复制源视频...")
        import shutil
        shutil.copy2(source_video, src_copy)

    # 单一 video material — 整个源文件，使用实际分辨率
    vmid = _uid()
    video_materials = [_make_video_material(vmid, src_copy, total_dur_us, src_width, src_height)]

    # 单一 audio material — video_id 关联回视频素材
    amid = _uid()
    audio_materials = [_make_audio_material(amid, src_copy, total_dur_us, vmid)]

    vid_track_id = _uid()
    aud_track_id = _uid()
    vid_segments = []
    aud_segments = []
    vocal_seps = []
    speeds = []
    sound_mappings = []
    canvases = []

    current_us = 0

    for seg in segments.get("segments", []):
        start_s = seg.get("source_start", 0)
        end_s = seg.get("source_end", start_s + 5)
        # ★ 收紧：每段最多 15s raw，留够调整余量但不过分
        dur_s = min(end_s - start_s, 15)
        # 保留原始 end 作为 source 范围（可拉长）
        source_dur_s = end_s - start_s
        dur_us = int(dur_s * 1_000_000)
        source_start_us = int(start_s * 1_000_000)
        source_dur_us = int(source_dur_s * 1_000_000)

        # Video segment
        seg_obj = _make_segment(vmid, current_us, dur_us, source_start_us)
        # source_timerange.duration 保持完整范围（允许拉长）
        seg_obj["source_timerange"]["duration"] = source_dur_us
        seg_obj["extra_material_refs"] = [amid]
        vid_segments.append(seg_obj)

        # Audio segment — 同样位置，引用音频素材
        aud_seg = {
            "id": _uid(), "material_id": amid, "render_index": 0,
            "target_timerange": {"duration": dur_us, "start": current_us},
            "source_timerange": {"duration": source_dur_us, "start": source_start_us},
            "speed": 1.0, "volume": 1.0, "visible": True,
            "cartoon": False, "reverse": False,
            "is_placeholder": False, "is_tone_modify": False,
            "intensifies_audio": False, "last_nonzero_volume": 1.0,
            "group_id": "", "track_attribute": 0, "track_render_index": 0,
            "template_id": "", "template_scene": "default",
            "common_keyframes": [], "keyframe_refs": [], "extra_material_refs": [],
            "uniform_scale": {"on": True, "value": 1.0},
            "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
            "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
            "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}},
        }
        aud_segments.append(aud_seg)

        # 配套对象（每段一个）
        vid_seg_id = seg_obj["id"]
        vocal_seps.append({
            "choice": 0, "id": vid_seg_id,
            "production_path": "", "time_range": {"duration": dur_us, "start": current_us},
            "type": "vocal_separation"
        })
        speeds.append({
            "curve_speed": [], "id": vid_seg_id,
            "mode": 0, "speed": 1.0, "type": "speed"
        })
        sound_mappings.append({
            "audio_channel_mapping": 0, "id": vid_seg_id,
            "is_config_open": False, "type": "none"
        })
        canvases.append({
            "album_image": "", "blur": 0.0, "color": "", "id": vid_seg_id,
            "image": "", "image_id": "", "image_name": "",
            "source_platform": 0, "team_id": "", "type": "canvas_color"
        })

        current_us += dur_us
        print(f"  S{seg['seg_id']}: {start_s:.0f}s-{end_s:.0f}s ({dur_s:.0f}s) → 时间轴@{current_us/1_000_000:.1f}s")

    # 轨道：只一条视频轨，音频随视频素材自带 (has_audio=true)
    tracks = [{
        "attribute": 0, "flag": 0,
        "id": vid_track_id,
        "is_default_name": True, "name": "",
        "type": "video",
        "segments": vid_segments,
    }]

    # 素材字典
    materials = {}
    # 40+ 空数组（匹配剪映结构）
    empty_arrays = [
        "audio_balances", "audio_effects", "audio_fades", "audio_track_indexes",
        "chromas", "color_curves", "digital_humans", "drafts", "effects", "flowers",
        "green_screens", "handwrites", "hsl", "images", "log_color_wheels",
        "loudnesses", "manual_deformations", "masks", "material_animations",
        "material_colors", "placeholders", "plugin_effects", "primary_color_wheels",
        "realtime_denoises", "shapes", "smart_crops", "smart_relights",
        "stickers", "tail_leaders", "text_templates", "texts", "transitions",
        "video_effects", "video_trackings", "vocal_beautifys",
    ]
    for key in empty_arrays:
        materials[key] = []

    materials["audios"] = audio_materials
    materials["videos"] = video_materials
    materials["canvases"] = canvases
    materials["speeds"] = speeds
    materials["vocal_separations"] = vocal_seps
    materials["sound_channel_mappings"] = sound_mappings
    materials["beats"] = []

    draft = {
        "canvas_config": {"height": canvas_h, "ratio": "9:16", "width": canvas_w},
        "color_space": 0,
        "config": {},
        "cover": "",
        "create_time": int(time.time()),
        "duration": current_us,
        "extra_info": {},
        "fps": FPS,
        "free_render_index_mode_on": False,
        "group_container": {},
        "id": draft_id,
        "keyframe_graph_list": [],
        "keyframes": [],
        "last_modified_platform": 0,
        "materials": materials,
        "mutable_config": {},
        "name": draft_name,
        "new_version": True,
        "platform": 0,
        "relationships": {},
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "source": "vibecap-auto",
        "static_cover_image_path": "",
        "tracks": tracks,
        "update_time": int(time.time()),
        "version": 1,
    }
    return draft


def write_helper_files(draft_dir, draft):
    """写剪映需要的辅助文件"""
    # draft_meta_info.json
    meta = {"id": draft["id"], "name": draft["name"],
            "create_time": draft["create_time"], "update_time": draft["update_time"],
            "fps": draft["fps"], "ratio": draft["canvas_config"]["ratio"],
            "duration": draft["duration"], "source": "vibecap-auto"}
    json.dump(meta, open(draft_dir / "draft_meta_info.json", 'w'), ensure_ascii=False)

    # draft_agency_config.json
    json.dump({"marterials": None, "use_converter": False, "video_resolution": 720},
              open(draft_dir / "draft_agency_config.json", 'w'))

    # draft_virtual_store.json
    json.dump({"draft_materials": [], "draft_virtual_store": [
        {"type": 0, "value": [{"creation_time": 0, "display_name": "", "filter_type": 0,
          "id": "", "import_time": 0, "import_time_us": 0, "sort_sub_type": 0, "sort_type": 0}]},
        {"type": 1, "value": []}, {"type": 2, "value": []}
    ]}, open(draft_dir / "draft_virtual_store.json", 'w'))

    # draft_settings (empty binary-like file)
    (draft_dir / "draft_settings").write_text("{}")

    # key_value.json (empty object)
    json.dump({}, open(draft_dir / "key_value.json", 'w'))

    # draft.extra (binary placeholder)
    (draft_dir / "draft.extra").write_bytes(b'\x00\x00\x00\x00')

    # Subdirs
    for d in ["Resources", ".backup", "smart_crop", "matting", "common_attachment"]:
        (draft_dir / d).mkdir(exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="segments.json → 剪映草稿")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    args = parser.parse_args()

    cfg = load_project(args.project)
    segments = load_segments(args.project, args.task)

    src_file = segments.get("source") or segments["segments"][0].get("source_file", "")
    src_video = find_source_video(cfg, src_file)
    if not src_video:
        print(f"❌ 找不到源视频: {src_file}")
        return 1

    draft_name = args.name or f"{args.project}_{args.task}"
    draft_dir = DRAFT_BASE / draft_name
    # 清除旧草稿
    if draft_dir.exists():
        import shutil
        shutil.rmtree(draft_dir)
    draft_dir.mkdir(parents=True)
    materials_dir = draft_dir / "materials"
    materials_dir.mkdir()

    print(f"📹 源视频: {src_video.name}")
    print(f"📝 段数: {segments.get('total_segments', len(segments['segments']))}")
    print(f"📁 草稿: {draft_dir}")
    print()

    draft = build_draft(segments, src_video, materials_dir, draft_name, args.width, args.height)
    json.dump(draft, open(draft_dir / "draft_info.json", 'w'), ensure_ascii=False, indent=2)
    write_helper_files(draft_dir, draft)

    total_dur = draft["duration"] / 1_000_000
    print(f"\n✅ 导出完成!")
    print(f"   时长: {total_dur:.0f}s ({total_dur/60:.1f}分)")
    print(f"   分辨率: {args.width}x{args.height}")
    print(f"   在剪映中打开「{draft_name}」即可精调")


if __name__ == "__main__":
    main()
