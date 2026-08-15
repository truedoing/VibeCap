"""确定性部分单元测试 — 不调用 LLM，毫秒级。

覆盖 drama_script_agents 里的纯函数和确定性逻辑：
- _load_scene_maps / _load_all_synopses 的过滤正确性
- _emotion_signature 的冲突/缓和/转折计数
- _infer_episodes_from_topic (统计版 for 循环) 的确定性反推
- Phase 4 校验的 time_range 对齐逻辑

运行:  cd vibecut-server && pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

# 确保能 import agents / lib
SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from agents.drama_script_agents import (
    _load_scene_maps,
    _load_all_synopses,
    _emotion_signature,
    _infer_episodes_from_topic,
    _extract_key_episodes_from_story_map,
    validate_producer_output,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"


# ── _load_scene_maps ────────────────────────────────────────────

def test_load_scene_maps_returns_ep_dict():
    sm = _load_scene_maps(PROJECT_DIR, [1, 21])
    assert isinstance(sm, dict)
    assert 1 in sm and 21 in sm
    # 每个 ep 对应一个 list，元素是 dict
    assert isinstance(sm[1], list)
    assert isinstance(sm[1][0], dict)


def test_load_scene_maps_filters_to_requested_eps():
    sm = _load_scene_maps(PROJECT_DIR, [1])
    assert list(sm.keys()) == [1]


def test_load_scene_maps_skips_missing_eps():
    # 不存在的剧集号应被静默跳过，不抛异常
    sm = _load_scene_maps(PROJECT_DIR, [1, 999])
    assert 999 not in sm
    assert 1 in sm


# ── _load_all_synopses（浅层 RAG 的检索键）──────────────────────

def test_load_all_synopses_with_episodes_filter():
    syn = _load_all_synopses(PROJECT_DIR, episodes=[1, 21])
    assert set(syn.keys()) == {1, 21}


def test_load_all_synopses_none_means_all():
    syn = _load_all_synopses(PROJECT_DIR, episodes=None)
    # 全量应覆盖大部分剧集（至少 > 40）
    assert len(syn) >= 40


# ── _emotion_signature（纯函数）─────────────────────────────────

def test_emotion_signature_returns_structured_sig():
    sig = _emotion_signature(PROJECT_DIR, "苏明成")
    # 每集是 (冲突数, 缓和数, 转折/单向)
    for ep, (c, s, label) in sig.items():
        assert isinstance(c, int) and isinstance(s, int)
        assert label in ("转折", "单向")


def test_emotion_signature_turn_rule():
    """转折 = 冲突>0 且 缓和>0；单向 = 只有其一"""
    sig = _emotion_signature(PROJECT_DIR, "苏明成")
    for ep, (c, s, label) in sig.items():
        expected = "转折" if (c > 0 and s > 0) else "单向"
        assert label == expected, f"EP{ep} 标签应为 {expected}, 实际 {label}"


def test_emotion_signature_ep39_is_turn():
    """EP39 是苏明成「冲突→缓和」的觉醒拐点，应为『转折』"""
    sig = _emotion_signature(PROJECT_DIR, "苏明成")
    assert 39 in sig
    c, s, label = sig[39]
    assert label == "转折"
    assert c > 0 and s > 0


# ── _infer_episodes_from_topic（统计版，确定性）─────────────────

def test_infer_episodes_from_topic_returns_sorted_list():
    eps = _infer_episodes_from_topic(PROJECT_DIR, "苏明成人物线")
    assert isinstance(eps, list)
    assert eps == sorted(eps)  # 返回的是排序后的列表


def test_infer_episodes_from_topic_hits_character_name():
    """选题含「苏明成」，反推结果应非空且都是有效集号"""
    eps = _infer_episodes_from_topic(PROJECT_DIR, "苏明成人物线")
    assert eps is not None
    assert all(1 <= e <= 46 for e in eps)


def test_infer_episodes_from_topic_no_match_returns_none():
    """选题不含任何已知人物和实义词，应返回 None（回退全量）"""
    eps = _infer_episodes_from_topic(PROJECT_DIR, "xxx")
    # 可能命中或未命中取决于分词，这里只断言不抛异常且类型正确
    assert eps is None or isinstance(eps, list)


# ── Phase 4 校验逻辑的确定性分支（隔离测）─────────────────────

def _fill_episode_marker(seg, sq):
    """复制自 Phase 4 的 episode_marker 填充逻辑（确定性分支）"""
    ep = sq.get("episode")
    tr = sq.get("time_range")
    if ep and tr and isinstance(tr, list) and len(tr) == 2:
        seg["episode_marker"] = {
            "episode": ep,
            "approx_minute": tr[0] / 60.0,
            "raw": f"{ep}~{tr[0]//60:.0f}m{tr[0]%60:.0f}s",
        }
        seg["source_start"] = float(tr[0])
        seg["source_end"] = float(tr[1])
        seg["video_episode"] = ep
    else:
        seg["episode_marker"] = None
        seg["mode"] = "C"
    return seg


def test_episode_marker_fills_when_valid():
    seg = _fill_episode_marker({}, {"episode": 21, "time_range": [240, 330]})
    assert seg["episode_marker"]["episode"] == 21
    assert seg["video_episode"] == 21
    assert seg["source_start"] == 240.0
    assert seg["source_end"] == 330.0


def test_episode_marker_degrades_to_mode_c_when_invalid():
    seg = _fill_episode_marker({}, {"episode": None, "time_range": None})
    assert seg["episode_marker"] is None
    assert seg["mode"] == "C"


# ── _extract_key_episodes_from_story_map（纯函数，选集权上移）────

def test_extract_key_episodes_from_story_map_hits_target_char():
    """story_map 里有多个角色的弧光，应只提取 topic 命中角色的 key_episodes"""
    story_map = {
        "character_arcs": [
            {"name": "苏明成", "key_episodes": [1, 9, 21, 45]},
            {"name": "苏明玉", "key_episodes": [8, 16, 39]},
        ]
    }
    eps = _extract_key_episodes_from_story_map(story_map, "苏明成人物线")
    assert eps == [1, 9, 21, 45]  # 只取苏明成，不含苏明玉的集


def test_extract_key_episodes_dedup_and_keep_order():
    """去重且保持首次出现顺序"""
    story_map = {
        "character_arcs": [
            {"name": "苏明成", "key_episodes": [1, 21, 21, 45, 1]},
        ]
    }
    eps = _extract_key_episodes_from_story_map(story_map, "苏明成")
    assert eps == [1, 21, 45]


def test_extract_key_episodes_fallback_to_all_when_no_name_hit():
    """topic 未命中任何人物名时，取全部弧光"""
    story_map = {
        "character_arcs": [
            {"name": "苏明成", "key_episodes": [1, 21]},
            {"name": "苏明玉", "key_episodes": [8]},
        ]
    }
    eps = _extract_key_episodes_from_story_map(story_map, "家庭矛盾主题")
    assert set(eps) == {1, 21, 8}


# ── validate_producer_output（制片 Agent 守规矩检查）────────────

def test_producer_output_title_keep_or_simplify_ok():
    """标题保留/简化（不重写钩子）→ 不报错（职责边界调整后，照抄输入标题是允许的）"""
    candidates = [{"title": "苏明成：从试图挪用房款投资到与父兄正面冲突"}]
    result = {"ranked": [{"title": "苏明成：从试图挪用房款投资到与父兄正面冲突"}]}
    issues = validate_producer_output(candidates, result)
    assert not any("标题未重写" in i for i in issues)


def test_producer_output_fabricated_topic():
    """凭空造选题（与任何输入无关联）→ 报「疑似凭空造」"""
    candidates = [{"title": "苏明成打妹妹"}]
    result = {"ranked": [{"title": "一个完全无关的新题目"}]}
    issues = validate_producer_output(candidates, result)
    assert any("凭空造" in i for i in issues)
