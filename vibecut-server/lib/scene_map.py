"""场记Agent — 剧本分析 + 场景分段生成

从 ASR 对话 + 剧情概要 → DeepSeek 推理 → scene_map JSON 数组。

职责:
  1. 生成剧情概要 (ep_synopsis)
  2. 生成场景分段 (scene_map)
  3. 时间连续性检查 + 空隙自动补漏
  4. 降级 fallback: 关键词规则

用法:
  from lib.scene_map import SceneMapAgent
  agent = SceneMapAgent()
  scene_map = agent.build(asr_segments, synopsis)
"""

import json
import re
import os

from lib.llm import call_deepseek
from lib.vlm_cache import KNOWN_CHARACTERS

# ── Prompt ──

SCENE_MAP_PROMPT = """你是《都挺好》的场记。根据 ASR 对话和剧情概要，推断本集的场景分段。

输出 JSON 数组，每个元素:
{
  "time_range": [start_s, end_s],
  "location": "地点",
  "characters": ["在场人物"],
  "event": "事件（≤20字）",
  "mood": "情绪"
}

规则:
1. 人物全名: 苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡/老聂
2. 按对话话题转换点切分, 每段 60-90s
3. 覆盖第一句到末句的完整时间线，不得遗漏任何对话段落
4. 通过称呼词推断说话人（"明哲"→吴非在说话,"爸"→子女在说话）
5. ★ 时间连续性检查: 相邻场景时间不得断开超过 60s，若 ASR 有对话必须生成对应场景"""

SCENE_MAP_SYNOPSIS_PROMPT = """你是电视剧《都挺好》的编剧助理。根据对话记录，概括这集的核心剧情，
按时间顺序列出 3-5 个关键情节段落。人物用全名（苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡等）。"""


class SceneMapAgent:
    """场记 Agent — 生成 scene_map + ep_synopsis"""

    def __init__(self):
        self._fallback_rules = _build_fallback_rules()

    # ── 公开 API ──

    def build_synopsis(self, asr_segments, ep: int) -> str:
        """DeepSeek 读取 ASR 生成剧情概要"""
        asr_text = ' '.join(seg['text'] for seg in asr_segments)[:6000]
        result = call_deepseek(
            SCENE_MAP_SYNOPSIS_PROMPT,
            f"第{ep}集对话记录:\n{asr_text}",
            max_tokens=800, label="synopsis",
        )
        if isinstance(result, dict) and result.get("ok"):
            return result.get("content", "").strip()
        return ""

    def build(self, asr_segments, synopsis: str) -> list:
        """从 ASR + 概要生成 scene_map 数组"""
        asr_text = self._format_asr(asr_segments)
        user_prompt = f"剧情概要:\n{synopsis}\n\nASR (带时间戳):\n{asr_text}\n\n输出场景分段 JSON。"

        print("  DeepSeek 生成 scene_map...")
        result = call_deepseek(SCENE_MAP_PROMPT, user_prompt,
                               max_tokens=2000, label="scene_map")

        if not isinstance(result, dict) or not result.get("ok"):
            print(f"  DeepSeek 失败, 使用 fallback")
            return self._fallback(asr_segments)

        content = result.get("content", "")
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            print("  JSON 解析失败, 使用 fallback")
            return self._fallback(asr_segments)

        try:
            scene_map = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            print("  JSON 解析失败, 使用 fallback")
            return self._fallback(asr_segments)

        # 过滤 + 排序
        scene_map = [sm for sm in scene_map
                     if 15 < sm['time_range'][1] - sm['time_range'][0] < 300]
        scene_map.sort(key=lambda x: x['time_range'][0])

        # 时间连续性补漏
        scene_map = self._fill_gaps(scene_map)

        return scene_map

    # ── 内部方法 ──

    def _format_asr(self, asr_segments) -> str:
        lines = []
        current_win = None
        for seg in asr_segments:
            win = int(seg['start'] // 30) * 30
            if win != current_win:
                lines.append(f"\n[{win}s]")
                current_win = win
            lines.append(seg['text'])
        return ' '.join(lines)[:8000]

    def _fill_gaps(self, scene_map: list) -> list:
        """检测 >120s 空隙并插入补漏场景"""
        filled = []
        last_end = scene_map[0]['time_range'][0] if scene_map else 0
        for sm in scene_map:
            gap = sm['time_range'][0] - last_end
            if gap > 120:
                mid_start = last_end + 30
                mid_end = sm['time_range'][0] - 30
                if mid_end - mid_start > 15:
                    filled.append({
                        "time_range": [mid_start, mid_end],
                        "location": "未知",
                        "characters": [],
                        "event": "(ASR有对话, DeepSeek遗漏的场景)",
                        "mood": "待确认"
                    })
                    print(f"  ⚠ 补漏: {gap}s 空隙 [{last_end}-{sm['time_range'][0]}]")
            filled.append(sm)
            last_end = sm['time_range'][1]
        return filled

    def _fallback(self, asr_segments) -> list:
        """降级: 关键词规则"""
        windows = {}
        for seg in asr_segments:
            win = int(seg['start'] // 30) * 30
            windows.setdefault(win, []).append(seg['text'])

        scenes = []
        current = None
        for win in sorted(windows.keys()):
            text = ' '.join(windows[win])
            loc, chars = self._classify_window(text)
            if current and current['location'] == loc and \
               set(current['characters']) == set(chars):
                current['time_range'][1] = win + 30
            else:
                if current:
                    scenes.append(current)
                current = {"time_range": [win, win + 30], "location": loc,
                           "characters": chars, "event": "", "mood": ""}
        if current:
            scenes.append(current)

        # 合并相邻同类段
        merged = []
        for s in scenes:
            if merged and merged[-1]['location'] == s['location'] and \
               set(merged[-1]['characters']) == set(s['characters']) and \
               s['time_range'][0] - merged[-1]['time_range'][1] < 60:
                merged[-1]['time_range'][1] = s['time_range'][1]
            else:
                merged.append(s)
        print(f"  → fallback: {len(merged)} 段")
        return merged

    def _classify_window(self, text: str) -> tuple:
        """关键词分类 → (location, characters)"""
        for keywords, loc, chars in self._fallback_rules:
            if any(kw in text for kw in keywords):
                return loc, chars
        return "未知", []


def _build_fallback_rules() -> list:
    """构建 fallback 关键词规则（优先级从高到低）"""
    return [
        (['菜刀', '谁敢', '不让结婚', '我看谁敢', '你让开'],
         "苏大强家", ["苏大强", "苏明成", "小蔡"]),
        (['贷款', '还十年', '一家人不说两家话', '聊聊', '谈判'],
         "苏大强家", ["苏明玉", "小蔡", "苏大强"]),
        (['打官司', '卖房', '不孝', '赌气'],
         "苏大强家", ["苏大强", "苏明玉"]),
        (['明哲', '吴非', '回美国', '房产证', '你怎么还不睡'],
         "苏明哲家(美国)", ["苏明哲", "吴非"]),
        (['老聂', '劝', '喝酒'],
         "苏大强家", ["苏大强", "老聂"]),
        (['明月', '大嫂', '明成', '办公室'],
         "苏明玉办公室", ["苏明玉"]),
        (['明成', '朱丽', '小蔡家'],
         "苏明成家", ["苏明成", "朱丽"]),
    ]
