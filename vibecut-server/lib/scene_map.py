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
from lib.names import NAME_MAP, normalize_names
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

★ 铁律（必须遵守）：
1. event 字段绝对不能为空！如果某段时间对话稀疏或无明确事件，event 写 "(少量对话)" 或 "(场景过渡)"，不能留空
2. time_range 必须精确，间隔≤30s。相邻场景结束/开始时间之差不超过15s
3. characters 至少有1人，不能是空数组
4. 人物全名从以下「标准人名」中选择（★ 必须覆盖真实配角，不能因为名单不全就硬塞主角）：
   苏家核心: 苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小咪
   苏家亲属: 苏母/苏母舅/舅舅/舅妈/朱丽母亲/朱丽父亲
   公司配角: 柳青/蒙总(老蒙)/小蒙总/孙副总/张副总/蒙太/毛总监/老毛/老孟
   其他常客: 石天冬/小蔡/老聂/凯莉
   ★ 关键：柳青、蒙总、石天冬、孙副总、小蒙总 都是戏份很重的重要配角，凡对话内容涉及公司/商业/审计/跳槽的，优先判断是不是他们，绝不能因为名单没有就硬塞成苏明成/苏明玉。
   ★ 龙套（中介/保安/护士/医生/员工/民警/售楼员等）直接用职业泛称，不硬套主角名。
   ★★ 人名归一化铁律（ASR 可能有同音字误识别）★★
   输出 characters 时，必须把以下 ASR 误识别写法纠正为标准名，绝不能照抄：
     朱莉/朱利 → 朱丽 | 明诚/明城/明昌 → 明成
     宋明哲/宋明成/宋明玉 → 苏明哲/苏明成/苏明玉（"宋"是"苏"的误识）
     宋大强 → 苏大强 | 小菜 → 小蔡 | 吴飞/吴菲 → 吴非
     苏名成/苏名玉/苏名哲 → 苏明成/苏明玉/苏明哲
     老萌/老梦 → 老蒙(蒙总) | 柳情/刘青 → 柳青
   用剧情常识判断：提到"二哥""给明玉打架""照顾爸"等，人名一律用上述标准全名。
5. 场景按对话话题转换点切分，每段60-120s。对话超过120s连续同话题的，在中间适当位置拆分
6. 覆盖第一句到末句的完整时间线，不得遗漏任何对话段落
7. 通过称呼词推断说话人（"明哲"→吴非在说话,"爸"→子女在说话）
8. location 不能为"未知"——从对话内容推断地点（"吃饭""餐厅""喝酒"→餐厅，"睡觉""回家""房子"→家中，"上班""开会""文件"→办公室）
9. mood 从以下标准情绪中选择：温馨/激烈/紧张/愤怒/悲伤/轻松/焦虑/压抑/尴尬/感动/严肃/平静/无奈/期待/担忧

时间连续性检查: 相邻场景 time_range 不得断开超过30s。若 ASR 有对话必须生成对应场景。"""

SCENE_MAP_SYNOPSIS_PROMPT = """你是电视剧《都挺好》的编剧助理。根据本集 ASR 对话记录（带时间戳），生成这集的「宏观叙事索引」。

★ 职责边界：你只做整集宏观概括，不做逐场景细粒度切分（那是场记的工作）。
  不要输出 location/characters 逐场景字段，只保留 key_events 级别的关键事件 + 时间锚。

★ 人名归一化铁律：输出人物名时，必须把 ASR 同音字误识别纠正为标准名，绝不能照抄：
  朱莉/朱利 → 朱丽 | 明诚/明城/明昌 → 明成
  宋明哲/宋明成/宋明玉 → 苏明哲/苏明成/苏明玉（"宋"是"苏"的误识）
  宋大强 → 苏大强 | 小菜 → 小蔡 | 吴飞/吴菲 → 吴非
  苏名成/苏名玉/苏名哲 → 苏明成/苏明玉/苏明哲

★ key_events 的 time_range 必须能映射到本集场景时间轴（从 ASR 时间戳推断，[start_s, end_s]，
  秒为单位，误差尽量控制在 ±15s 内）。这是连接 synopsis 与 scene_map 的锚点，务必准确。

输出严格 JSON（不要 markdown 代码块、不要任何多余文字）：
{
  "theme": "本集核心主题（一句话，≤30字）",
  "plot_arc": "起承转合概括（≤100字）",
  "character_arcs": [
    {"character": "苏明成", "arc": "从...到...的转变", "relations_change": ["与苏明玉和解"]}
  ],
  "key_conflicts": ["父子冲突", "兄妹误会"],
  "emotional_curve": ["紧张", "冲突", "和解", "温情"],
  "key_events": [
    {"event": "苏明成持刀阻婚", "time_range": [450, 570]}
  ]
}

规则：
- 人物从「标准人名」中选（本集未出场的不写）：苏家核心 苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小咪；苏家亲属 苏母/苏母舅/舅舅/舅妈/朱丽母亲；公司配角 柳青/蒙总(老蒙)/小蒙总/孙副总/张副总/蒙太；其他常客 石天冬/小蔡/老聂。★ 柳青/蒙总/石天冬/孙副总 是重要配角，凡涉及公司/商业/审计的，优先判断是不是他们，别硬塞成主角。
- character_arcs 只写本集内发生实质转变的人物，无转变可留空数组
- key_events 3-6 个，按时间顺序；每个 event ≤20字
- emotional_curve 2-5 个情绪标签，反映本集情绪起伏"""


class SceneMapAgent:
    """场记 Agent — 生成 scene_map + ep_synopsis"""

    def __init__(self):
        self._fallback_rules = _build_fallback_rules()

    # ── 公开 API ──

    def build_synopsis(self, asr_segments, ep: int) -> dict:
        """DeepSeek 读取 ASR 生成结构化宏观叙事索引 (ep_synopsis 新结构)

        返回 dict（theme/plot_arc/character_arcs/key_conflicts/emotional_curve/key_events），
        失败时返回 {}。写入侧由 cli 决定序列化。
        """
        asr_text = ' '.join(seg['text'] for seg in asr_segments)[:6000]
        # ASR 人名标准化 (消除同音字误识别对生成结果的污染)
        asr_text = normalize_names(asr_text)

        # 含时间戳的 ASR，供 key_events 推断 time_range
        asr_timed = self._format_asr(asr_segments)

        result = call_deepseek(
            SCENE_MAP_SYNOPSIS_PROMPT,
            f"第{ep}集对话记录:\n{asr_text}\n\n带时间戳的 ASR (推断 key_events 时间锚):\n{asr_timed}",
            max_tokens=1600, label="synopsis",
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return {}

        content = _strip_markdown(result.get("content", ""))
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            return {}
        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return {}
        return self._normalize_synopsis(data)

    @staticmethod
    def _normalize_synopsis(data) -> dict:
        """校验 + 补全结构化字段，并对人物名再做一次归一化兜底。"""
        if not isinstance(data, dict):
            return {}
        out = {
            "theme": str(data.get("theme", "")).strip(),
            "plot_arc": str(data.get("plot_arc", "")).strip(),
            "character_arcs": [],
            "key_conflicts": [],
            "emotional_curve": [],
            "key_events": [],
        }
        for a in data.get("character_arcs") or []:
            if not isinstance(a, dict):
                continue
            char = normalize_names(str(a.get("character", "")).strip())
            if not char:
                continue
            arc = str(a.get("arc", "")).strip()
            rc = [str(x).strip() for x in (a.get("relations_change") or [])
                  if str(x).strip()]
            out["character_arcs"].append({
                "character": char, "arc": arc, "relations_change": rc,
            })
        for k in ("key_conflicts", "emotional_curve"):
            raw = data.get(k) or []
            vals = [normalize_names(str(x).strip()) for x in raw if str(x).strip()]
            out[k] = vals
        for e in data.get("key_events") or []:
            if not isinstance(e, dict):
                continue
            event = normalize_names(str(e.get("event", "")).strip())
            tr = e.get("time_range")
            if (not event or not isinstance(tr, (list, tuple)) or len(tr) != 2):
                continue
            try:
                start, end = int(tr[0]), int(tr[1])
            except (TypeError, ValueError):
                continue
            if start >= end:
                continue
            out["key_events"].append({"event": event, "time_range": [start, end]})
        return out

    def build(self, asr_segments, synopsis) -> list:
        """从 ASR + 概要生成 scene_map 数组

        synopsis 可为 dict (新结构化) 或 str (旧纯文本)，统一转成纯文本注入 prompt。
        """
        asr_text = self._format_asr(asr_segments)
        synopsis_text = _synopsis_to_text(synopsis)
        user_prompt = f"剧情概要:\n{synopsis_text}\n\nASR (带时间戳):\n{asr_text}\n\n输出场景分段 JSON。"

        print("  DeepSeek 生成 scene_map...")
        result = call_deepseek(SCENE_MAP_PROMPT, user_prompt,
                               max_tokens=3000, label="scene_map")

        if not isinstance(result, dict) or not result.get("ok"):
            print(f"  DeepSeek 失败, 重试一次...")
            result = call_deepseek(SCENE_MAP_PROMPT, user_prompt,
                                   max_tokens=3000, label="scene_map-retry")
            if not isinstance(result, dict) or not result.get("ok"):
                print(f"  重试仍失败, 使用 fallback")
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
                     if 15 < sm['time_range'][1] - sm['time_range'][0] < 400]
        scene_map.sort(key=lambda x: x['time_range'][0])

        # 后处理: 确保 event/mood 不为空, location 不为"未知"
        for sm in scene_map:
            if not sm.get('event') or not sm['event'].strip():
                sm['event'] = '(场景过渡)'
            if not sm.get('mood') or not sm['mood'].strip():
                sm['mood'] = '平静'
            if not sm.get('location') or sm['location'].strip() in ('未知', ''):
                sm['location'] = _infer_location(sm)
            if not sm.get('characters'):
                # 从 scene_map 其他场景推断可能的人物
                sm['characters'] = ['苏大强']  # fallback

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
                        "event": "(ASR对话间隙)",
                        "mood": "平静"
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


def _strip_markdown(text: str) -> str:
    """去掉 LLM 输出外层可能包裹的 markdown 代码块。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def _synopsis_to_text(synopsis) -> str:
    """把 synopsis (dict 新结构 / str 旧纯文本) 转成纯文本，供 scene_map prompt 注入。"""
    if isinstance(synopsis, dict):
        from lib.synopsis import to_text
        return to_text(synopsis)
    return (synopsis or "").strip()


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


def _infer_location(scene: dict) -> str:
    """从事件和角色推断场景地点"""
    event = scene.get('event', '')
    chars = scene.get('characters', [])
    # 关键词推断
    if any(kw in event for kw in ['吃饭', '聚餐', '喝酒', '餐厅', '饭局', '食堂']):
        return '餐厅'
    if any(kw in event for kw in ['睡觉', '回家', '在家', '客厅', '卧室', '起床']):
        return '家中'
    if any(kw in event for kw in ['上班', '开会', '办公', '公司', '报告', '汇报', '文件', '辞职', '开除', '面试']):
        return '办公室'
    if any(kw in event for kw in ['派出所', '警察', '打架', '拘留']):
        return '派出所'
    if any(kw in event for kw in ['医院', '看病', '病房', '住院']):
        return '医院'
    if any(kw in event for kw in ['机场', '飞机', '接机', '送机']):
        return '机场'
    if any(kw in event for kw in ['车内', '车上', '开车', '驾驶']):
        return '车内'
    if any(kw in event for kw in ['电话', '打电话', '来电', '接电话']):
        return '电话'
    if any(kw in event for kw in ['法院', '诉讼', '打官司', '律师']):
        return '法院'
    if any(kw in event for kw in ['老宅', '老房子', '苏家老宅']):
        return '苏家老宅'
    if any(kw in event for kw in ['美国', '吴非', '苏明哲家']) and '美国' in str(chars):
        return '美国'
    if any(kw in event for kw in ['工厂', '车间', '做工']):
        return '工厂'
    if any(kw in event for kw in ['商店', '商场', '买东西', '超市']):
        return '商场'
    if any(kw in event for kw in ['公园', '散步', '锻炼']):
        return '公园'
    # 角色推断
    if '苏大强' in chars and '小蔡' in chars:
        return '苏大强家'
    if '苏明哲' in chars and '吴非' in chars:
        return '苏明哲家'
    if '苏明成' in chars and '朱丽' in chars:
        return '苏明成家'
    if '苏明玉' in chars:
        return '苏明玉家/办公室'
    return '未知'
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
