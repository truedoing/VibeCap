#!/usr/bin/env python3
"""
v3: VLM + ASR 联合匹配 + HTML 展示场景描述和台词
"""

import json, re, subprocess
import os
from pathlib import Path
from difflib import SequenceMatcher

BASE_DIR = Path("/Users/zgl/VIBECAP")
DRAMA_DIR = BASE_DIR / os.environ.get("VIBECAP_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VIBECAP_TASK", "Task7024")
WORK_DIR = TASK_DIR / "work_dir"
CLIP_DIR = TASK_DIR / "素材clips"

SRC = {
    1: Path("/Users/zgl/解说剪辑/都挺好原剧/都挺好 01_1080p.mp4"),
    2: Path("/Users/zgl/解说剪辑/都挺好原剧/都挺好 02_1080p.mp4"),
    3: Path("/Users/zgl/解说剪辑/都挺好原剧/都挺好 03_1080p.mp4"),
}
CHARS = [
    "苏大强", "苏母", "赵美兰",
    "苏明哲", "苏明成", "苏明玉", "明玉",
    "朱丽", "吴非", "小咪",
    "石天冬", "蒙总", "老蒙", "蒙太", "沈浩",
    "柳青", "小蒙", "洪总", "小新", "老聂",
]
# 关系代称 → 实际人物 (匹配前替换)
RELATION_MAP = {
    # 苏大强
    "苏父": "苏大强", "爸": "苏大强", "父亲": "苏大强", "老爷子": "苏大强",
    # 苏母
    "苏母": "赵美兰", "妈妈": "赵美兰", "母亲": "赵美兰",
    # 苏明哲
    "大哥": "苏明哲", "老大": "苏明哲", "长子": "苏明哲",
    # 苏明成
    "二哥": "苏明成",
    # 苏明玉
    "小妹": "苏明玉",
    # 朱丽
    "二嫂": "朱丽",
    # 吴非
    "大嫂": "吴非",
    # 石天冬
    "小石": "石天冬", "石老板": "石天冬",
    # 蒙总
    "师父": "蒙总", "师傅": "蒙总", "董事长": "蒙总", "蒙董事长": "蒙总",
    "老蒙": "蒙总", "蒙志远": "蒙总",
    # 蒙太
    "师母": "蒙太", "蒙太太": "蒙太", "蒙总老婆": "蒙太", "老蒙老婆": "蒙太",
    "他老婆": "蒙太", "老婆": "蒙太", "你师母": "蒙太",
    # 沈浩
    "蒙太弟弟": "沈浩", "蒙太的弟弟": "沈浩", "她弟弟": "沈浩", "她弟": "沈浩",
    "小舅子": "沈浩", "大舅子": "沈浩", "你那小舅子": "沈浩", "弟弟": "沈浩",
    "蒙太她弟": "沈浩", "光头": "沈浩",
}
CHAR_ALIASES = {
    "苏大强": ["苏大强", "苏父", "爸", "父亲", "老爷子"],
    "赵美兰": ["赵美兰", "苏母", "妈妈", "母亲"],
    "苏明哲": ["苏明哲", "明哲", "大哥", "老大", "长子"],
    "苏明成": ["苏明成", "明成", "二哥"],
    "苏明玉": ["苏明玉", "明玉", "小妹"],
    "明玉": ["明玉", "苏明玉"],
    "朱丽": ["朱丽", "二嫂"],
    "吴非": ["吴非", "大嫂"],
    "小咪": ["小咪"],
    "石天冬": ["石天冬", "小石", "石老板"],
    "蒙总": ["蒙总", "老蒙", "师父", "董事长", "蒙志远"],
    "老蒙": ["蒙总", "老蒙"],
    "蒙太": ["蒙太", "师母", "蒙太太", "老婆"],
    "沈浩": ["沈浩", "光头", "小舅子"],
    "柳青": ["柳青"],
    "小蒙": ["小蒙"],
    "洪总": ["洪总"],
    "小新": ["小新"],
    "老聂": ["老聂"],
}

def chars_in_text(names, text):
    """检查人物是否在文本中出现（含别名）"""
    found = []
    for name in names:
        aliases = CHAR_ALIASES.get(name, [name])
        for alias in aliases:
            if alias in text:
                found.append(name)
                break
    return found


def load_all():
    data = {"vlm": [], "asr": {}}
    for ep in [1, 2, 3]:
        for key, fname in [("vlm", "vlm_analysis.json"), ("asr", "asr_result.json")]:
            p = WORK_DIR / "sources" / f"ep{ep}" / fname
            if p.exists():
                items = json.load(open(p))
                for it in items:
                    it["_ep"] = ep
                if key == "vlm":
                    data["vlm"].extend(items)
                else:
                    data["asr"][ep] = items
    return data


def match_scene(sentence, vlm_all, asr_all, prefer_ep=None, time_hint=None, next_anchor=None, first_sentence=False):
    """VLM + ASR 联合评分, 返回 (scene, score, vlm_desc, asr_text, breakdown, need_split, chars_visible)"""
    # 关系代称替换: "蒙太弟弟" → "沈浩"
    sentence_expanded = sentence
    for rel, char in RELATION_MAP.items():
        if rel in sentence_expanded:
            sentence_expanded = sentence_expanded.replace(rel, char)
    # 提取人物 + 合并别名 (蒙总=老蒙)
    raw = [c for c in CHARS if c in sentence_expanded]
    # 用 CHAR_ALIASES 合并同人: 老蒙→蒙总, 苏明玉→明玉
    merged = []
    for c in raw:
        canonical = c
        for main_name, aliases in CHAR_ALIASES.items():
            if c in aliases and main_name != c:
                canonical = main_name; break
        if canonical not in merged: merged.append(canonical)
    chars_in = merged
    best = None; best_score = -100; best_vlm = ""; best_asr = ""; best_breakdown = ""

    # visible_in_desc 前置定义
    def visible_in_desc(char_name, desc):
        after_patterns = ["的","的事","虚开","一直在","为别的"]
        for alias in CHAR_ALIASES.get(char_name, [char_name]):
            if alias not in desc: continue
            idx = desc.find(alias)
            after = desc[idx+len(alias):idx+len(alias)+8]
            if any(after.startswith(p) for p in after_patterns):
                return False
            return True
        return False

    for s in vlm_all:
        ep = s["_ep"]
        desc = s.get("description", "") + s.get("depth_analysis", "")
        asr_text = ""
        for a in asr_all.get(ep, []):
            if a["start"] < s["end"] and a["end"] > s["start"]:
                asr_text += a["text"]

        score = 0; lines = []

        # 人物评分: 用 visible_in_desc (真正的出镜判断)
        chars_vis = [c for c in chars_in if visible_in_desc(c, desc)]
        if len(chars_in) >= 2:
            if len(chars_vis) >= 2: score += 17; lines.append(f"人物+17({','.join(chars_vis)}同场)")
            elif len(chars_vis) == 1: score += 4; lines.append(f"人物+4(仅{chars_vis[0]}出镜)")
            else: score -= 8; lines.append("人物-8(无人出镜)")
        elif len(chars_in) == 1:
            if chars_vis: score += 10; lines.append(f"人物+10({chars_vis[0]}出镜)")
            else: score -= 8; lines.append("人物-8(未出镜)")

        # ASR 交叉验证: ASR 里的人称关系是否与 VLM 矛盾
        if asr_text and desc:
            asr_vlm_conflict = 0
            # "您那小舅子"→说话人是明玉(或蒙总),但VLM说蒙总对蒙太→矛盾
            if "您那小舅子" in asr_text or "你师母" in asr_text or "我老婆" in asr_text:
                # 这些是明玉/蒙总视角的称谓 → speaker不可能是蒙太
                if "蒙太" in desc and ("对蒙太说" in desc or "告诉蒙太" in desc or "递给蒙太" in desc):
                    asr_vlm_conflict = -12; lines.append("ASR冲突-12(人称矛盾)")
            score += asr_vlm_conflict

        # 转述
        third = ["刚才老蒙跟蒙太", "蒙太都提出", "你师傅", "听说了"]
        if any(m in asr_text for m in third):
            score -= 15; lines.append("转述-15")

        # 关键词: 用 2-3 字 sliding window (使用展开后的句子)
        sent_clean = re.sub(r'[，。！？、\s　]', '', sentence_expanded)
        keywords = set()
        for n in [2, 3]:
            for i in range(len(sent_clean) - n + 1):
                keywords.add(sent_clean[i:i+n])
        stopwords = {'的是','这一','那个','到了','上了','也是','不会','不是','什么','怎么','可以',
                     '已经','这个','这样','一下','一个','所以','因为','但是','而且','不过',
                     '还不','只是','不只','一旦','不了','上有','她的','因为','所以','于是'}
        keywords = [k for k in keywords if len(k)>=2 and k not in stopwords]
        if keywords and asr_text:
            hit_words = [k for k in keywords if k in asr_text]
            hits = len(hit_words)
            asr_score = hits / len(keywords) * 15
            score += asr_score
            lines.append(f"关键词+{asr_score:.1f}({hits}/{len(keywords)}:{','.join(hit_words[:5])})")
            core = ["离婚","股权","上市","一半","虚开","发票","证据","签名","文件",
                    "双簧","求情","道歉","起身","送人","夹菜","沈浩","明玉"]
            core_hits = [w for w in core if w in asr_text and w in sentence_expanded]
            if core_hits:
                bonus = len(core_hits) * 10
                score += bonus
                lines.append(f"核心词+{bonus}({','.join(core_hits)})")

        # 第一句解说紧贴锚点
        if first_sentence and time_hint is not None:
            dist = abs(s["start"] - time_hint)
            if dist < 30: score += 15; lines.append("首句贴锚+15")
            elif dist < 60: score += 8; lines.append("首句近锚+8")

        # 场景类型
        if any(w in sentence for w in ["办公室","公司"]):
            if any(w in desc for w in ["办公","公司"]): score += 5; lines.append("场景+5(office)")
        if any(w in sentence for w in ["晚宴","餐厅","包间","吃饭","摆一桌","早餐"]):
            if any(w in desc for w in ["餐厅","餐桌","包间","吃饭","早餐"]): score += 5; lines.append("场景+5(dinner)")

        # 时间方向: 超过下一锚点的场景扣分
        if time_hint is not None:
            if next_anchor is not None and s["_ep"] == prefer_ep and s["start"] > next_anchor:
                score -= (s["start"] - next_anchor) / 5; lines.append(f"超下锚-{(s['start']-next_anchor)/5:.0f}")
            # 跨集小罚 (补充不受限)
            if s["_ep"] != prefer_ep:
                score -= 15; lines.append("跨集-15")

        # 排除
        if any(kw in desc for kw in ["片头","片尾","水墨","动画","演职人员"]):
            score -= 100; lines.append("排除-100(片头片尾)")
        # EP1-3主线是苏家，蒙总/柳青/沈浩此时尚未登场或极少出场
        if any(c in desc for c in ["蒙总","蒙太","沈浩","柳青","小蒙","洪总"]) and not any(c in sentence for c in ["蒙总","蒙太","沈浩","柳青","小蒙","洪总"]):
            score -= 10; lines.append("排除-10(EP1-3无关人物)")

        if score > best_score:
            best_score = score; best = s
            best_vlm = desc[:150]; best_asr = asr_text[:150]
            best_breakdown = "; ".join(lines)
            best_chars_found = chars_vis

    chars_visible = [c for c in chars_in if visible_in_desc(c, best_vlm)] if best else []
    # 对话场景: 只找到1人但描述暗示有对话对象 → 不补
    dialogue_hints = ["对峙","对话","质问","争吵","对坐","商谈","谈论","告知","交谈","聊","说"]
    is_dialogue = any(h in best_vlm for h in dialogue_hints) if best else False
    # 对话豁免: 仅缺1人 + 场景为二人对话 + 缺的人没在描述里被提及
    # 如果缺的人在VLM里出现了 → 他是被讨论对象, 不是对话方 → 不豁免
    missing_chars = [c for c in chars_in if c not in chars_visible]
    missing_mentioned = any(c in best_vlm for c in missing_chars) if best else False
    dialogue_exempt = (is_dialogue and len(missing_chars) == 1
                       and len(chars_visible) >= 1 and not missing_mentioned)
    need_split = (len(chars_in) >= 2 and len(chars_visible) < len(chars_in)
                  and not dialogue_exempt)

    return best, best_score, best_vlm, best_asr, best_breakdown, need_split, chars_visible


def find_copresent(chars_needed, vlm_all, asr_all=None, skip_ep=None, skip_time=0):
    """找所有需求人物同时出镜的场景(必须是真正出镜, 不是被讨论)"""
    candidates = []
    for s in vlm_all:
        desc = s.get("description", "")
        if any(kw in desc for kw in ["片头","片尾","水墨","动画","演职人员","熟睡","躺在床上"]): continue
        all_visible = True
        for c in chars_needed:
            aliases = CHAR_ALIASES.get(c, [c])
            found = False
            for alias in aliases:
                if alias not in desc: continue
                idx = desc.find(alias)
                after = desc[idx+len(alias):idx+len(alias)+8]
                if any(after.startswith(p) for p in ["的","的事","虚开","一直在","为别的"]):
                    continue
                found = True; break
            if not found:
                all_visible = False; break
        if not all_visible: continue
        # VLM括号标注排除: "蒙总（沈浩）" → 括号里是歧义,不用
        desc_clean = desc
        if re.search(r'[（(][^)）]{1,6}[)）]', desc):
            paren_content = re.findall(r'[（(]([^)）]{1,6})[)）]', desc)
            if any(c in ''.join(paren_content) for c in chars_needed):
                continue
        # ASR存在性验证: 要找的人至少在ASR里出现
        asr_txt = ""
        for a in asr_all.get(s["_ep"], []):
            if a["start"] < s["end"] and a["end"] > s["start"]:
                asr_txt += a["text"]
        # ASR验证: 单人搜索必须ASR有人名, 多人搜索信任VLM
        if asr_txt and len(chars_needed) == 1:
            if chars_needed[0] not in asr_txt:
                continue
        score = len(chars_needed) * 5
        if skip_time:
            score -= abs(s["start"] - skip_time) / 30
        candidates.append((score, s))
    candidates.sort(key=lambda x: -x[0])
    if not candidates: return None
    # 多人搜索: 放宽阈值, 距离远也接受
    if len(chars_needed) >= 2:
        return candidates[0][1]
    return candidates[0][1] if candidates[0][0] > 0 else None

def split_narration(text):
    sents = re.split(r'[。！？]', text)
    units, buf = [], ""
    for s in sents:
        s = s.strip()
        if not s: continue
        buf += s + "。"
        if len(buf) > 20:
            units.append(buf); buf = ""
    if buf: units.append(buf)
    return units


def extract(ep, start, end, name):
    out = CLIP_DIR / name
    if out.exists(): return True
    cmd = ["ffmpeg", "-y", "-ss", str(max(0, start - 0.5)), "-i", str(SRC[ep]),
           "-t", str(max(2, end - start)), "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def main():
    data = load_all()
    with open(TASK_DIR / "segments.json") as f:
        segs = json.load(f)["segments"]
    with open(TASK_DIR / "segments_located.json") as f:
        located = {s["seg_id"]: s for s in json.load(f)["segments"]}

    CLIP_DIR.mkdir(exist_ok=True)
    for f in CLIP_DIR.glob("clip_v3_*.mp4"):
        f.unlink()

    narr_dur = {0: 26, 1: 24, 2: 12, 3: 5, 4: 15, 5: 56, 6: 18, 7: 18, 8: 45}
    cid = 0
    results = {}  # sid → {dial: [...], narr: [(unit, file, dur, vlm_desc, asr_text)]}

    for seg in segs:
        sid = seg["seg_id"]
        hl = re.sub(r'\d+\.\d+\s*$', '', seg.get("highlight_text", "")).strip()
        narration = seg.get("narration_text", "")
        results[sid] = {"dial": [], "narr": []}

        # 🟡 台词
        loc = located.get(sid, {})
        if hl and loc.get("match_score", 0) > 0.3:
            vs, ve = loc["video_start"] - 1, loc["video_end"] + 2
            ep = loc["video_episode"]
            name = f"clip_v3_{cid:03d}_S{sid}_dialogue_ep{ep}.mp4"
            extract(ep, vs, ve, name)
            results[sid]["dial"].append((name, ve - vs, ep))
            cid += 1

        # 📝 逐句匹配
        if narration:
            units = split_narration(narration)
            ep_hint = loc.get("video_episode") or (seg.get("episode_marker", {}).get("episode"))
            time_hint = loc.get("video_start") or (seg.get("episode_marker", {}).get("approx_minute", 0) * 60)
            for ui, unit in enumerate(units):
                # 第一句解说紧贴锚点: 锚点附近场景优先
                first_sentence_bonus = (ui == 0)
                scene, score, vlm_desc, asr_text, breakdown, need_split, chars_visible = match_scene(
                    unit, data["vlm"], data["asr"], prefer_ep=ep_hint, time_hint=time_hint,
                    first_sentence=first_sentence_bonus)
                if scene and score > -5:
                    ep = scene["_ep"]
                    dur_needed = max(3, len(unit) / 4.5)
                    clip_end = max(scene["end"], scene["start"] + dur_needed)
                    name = f"clip_v3_{cid:03d}_S{sid}_narr_{ui}_ep{ep}.mp4"
                    ok = extract(ep, scene["start"], clip_end, name)
                    dur = clip_end - scene["start"]
                    supp_name = ""; supp_desc = ""
                    if need_split:
                        unit_expanded = unit
                        for rel, char in RELATION_MAP.items():
                            unit_expanded = unit_expanded.replace(rel, char)
                        unit_chars = list(set(c for c in CHARS if c in unit_expanded))
                        missing = [c for c in unit_chars if c not in chars_visible]
                        # 沈浩优先(光头最难找)

                        if "沈浩" in missing:
                            missing.remove("沈浩"); missing.insert(0, "沈浩")
                        # 先找同场, 找不到逐个找
                        supp = find_copresent(missing, data["vlm"], data["asr"])
                        if supp:
                            supp_ep = supp["_ep"]
                            supp_name = f"clip_v3_{cid:03d}b_S{sid}_narr_{ui}_supp_ep{supp_ep}.mp4"
                            extract(supp_ep, supp["start"], supp["start"]+5, supp_name)
                            supp_desc = supp.get("description","")[:80]
                        elif len(missing) > 1:
                            # 逐人找, 取第一个
                            for mc in missing:
                                supp = find_copresent([mc], data["vlm"], data["asr"])
                                if supp:
                                    supp_ep = supp["_ep"]
                                    supp_name = f"clip_v3_{cid:03d}b_S{sid}_narr_{ui}_supp_ep{supp_ep}.mp4"
                                    extract(supp_ep, supp["start"], supp["start"]+5, supp_name)
                                    supp_desc = supp.get("description","")[:80]
                                    break
                    results[sid]["narr"].append(
                        (unit, name if ok else "FAIL", dur, vlm_desc, asr_text, score, breakdown,
                         need_split, supp_name, supp_desc))
                    cid += 1

    # 导出匹配数据 JSON 供审核台使用
    match_data = {}
    for sid in results:
        match_data[str(sid)] = {"dial": [], "narr": []}
        for item in results[sid]["dial"]:
            match_data[str(sid)]["dial"].append({"file": item[0], "dur": item[1], "ep": item[2]})
        for item in results[sid]["narr"]:
            unit, fname, dur, vlm_desc, asr_text, score, breakdown, need_split, supp_name, supp_desc = item
            match_data[str(sid)]["narr"].append({
                "unit": unit, "file": fname, "dur": dur,
                "vlm": vlm_desc, "asr": asr_text,
                "score": score, "breakdown": breakdown,
                "has_supp": bool(need_split and supp_name),
                "supp_file": supp_name, "supp_desc": supp_desc
            })
    with open(WORK_DIR / "match_data.json", 'w', encoding='utf-8') as f:
        json.dump(match_data, f, ensure_ascii=False, indent=2)

    # HTML
    def esc(t):
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    h = ['<!DOCTYPE html><html><head><meta charset="utf-8"><title>素材对照表 v3</title>',
         '<style>',
         'body{font-family:-apple-system,sans-serif;max-width:1100px;margin:0 auto;padding:20px;background:#1a1a2e;color:#e0e0e0}',
         'h1{color:#e94560} .seg{border:1px solid #333;border-radius:8px;margin:16px 0;padding:16px;background:#16213e}',
         '.seg h2{color:#f0a500;margin:0 0 8px}',
         '.hl-box{background:#2d2d1a;border-left:3px solid #f0a500;padding:10px;margin:8px 0;font-size:13px;color:#f0a500}',
         '.nr-row{border-bottom:2px solid #333;margin:12px 0;padding:8px}',
         '.nr-text{color:#ccc;font-size:14px;line-height:1.5;margin:4px 0}',
         '.nr-meta{font-size:11px;margin:4px 0}',
         '.nr-meta span{display:inline-block;padding:2px 6px;border-radius:3px;margin:2px;font-size:11px}',
         '.tag-ep{background:#0f3460;color:#4fc3f7} .tag-dur{background:#1a3a1a;color:#4caf50}',
         '.tag-score{background:#2a1a3a;color:#ce93d8} .tag-err{background:#3a1a1a;color:#e94560}',
         '.vlm-box{background:#1a1a2e;border:1px solid #333;padding:6px 10px;margin:4px 0;font-size:11px;color:#888;max-height:60px;overflow-y:auto}',
         '.asr-box{background:#1a2a1a;border:1px solid #2a3a2a;padding:6px 10px;margin:4px 0;font-size:11px;color:#6a9;max-height:60px;overflow-y:auto}',
         'a{color:#4fc3f7}',
         '</style></head><body>',
         '<h1>素材对照表 v3 (VLM + ASR 联合匹配)</h1>',
         f'<p><code>{CLIP_DIR}</code></p>']

    for sid in range(9):
        if sid not in results: continue
        seg = segs[sid]
        r = results[sid]

        hl = re.sub(r'\d+\.\d+\s*$', '', seg["highlight_text"]).strip()
        h.append(f'<div class="seg"><h2>seg_{sid}</h2>')
        h.append(f'<div class="hl-box">🟡 {esc(hl)}</div>')

        # 台词素材
        if r["dial"]:
            for name, dur, ep in r["dial"]:
                h.append(f'<div class="nr-meta">📹 <a href="素材clips/{name}">{name}</a> '
                         f'<span class="tag-ep">EP{ep}</span><span class="tag-dur">{dur:.0f}s</span></div>')

        # 逐句解说 + 匹配的 clip
        for item in r["narr"]:
            unit, fname, dur, vlm_desc, asr_text, score, breakdown, need_split, alt_name, alt_desc = item
            chars_in = [c for c in CHARS if c in unit]
            chars_badge = " ".join(f'<span class="tag-ep">{c}</span>' for c in chars_in)

            score_color = "tag-score" if score > 5 else ("tag-err" if score < 0 else "tag-dur")
            h.append(f'<div class="nr-row">')
            h.append(f'<div class="nr-text">{esc(unit)}</div>')
            h.append(f'<div class="nr-meta">'
                     f'{chars_badge} '
                     f'<span class="{score_color}" title="{esc(breakdown)}">score:{score:.1f}</span> '
                     f'<span class="tag-dur">{dur:.0f}s</span> '
                     f'📹 <a href="素材clips/{fname}" target="_blank">{fname}</a>'
                     f'</div>')
            if need_split and alt_name:
                h.append(f'<div class="nr-meta" style="background:#1a2a1a;padding:4px 8px">'
                         f'👤 人物补充: <a href="素材clips/{alt_name}" target="_blank">{alt_name}</a> '
                         f'<span style="color:#888;font-size:11px">{esc(alt_desc[:60])}</span>'
                         f'</div>')
            h.append(f'<div class="vlm-box">🔍 VLM: {esc(vlm_desc[:200])}</div>')
            if asr_text.strip():
                h.append(f'<div class="asr-box">🗣️ ASR: {esc(asr_text[:200])}</div>')
            h.append(f'</div>')

        # 覆盖统计
        dial_dur = sum(d for _, d, _ in r["dial"])
        narr_total = sum(d for _, _, d, _, _, _, _, _, _, _ in r["narr"])
        target = narr_dur.get(sid, 0)
        ok = "✅" if narr_total >= target else f"⚠️ 缺口{target - narr_total:.0f}s"
        h.append(f'<div style="font-size:12px;color:#888;margin-top:8px">'
                 f'🟡{dial_dur:.0f}s 📝{narr_total:.0f}s / 需{target:.0f}s {ok}</div>')
        h.append('</div>')

    h.append('</body></html>')
    with open(TASK_DIR / "素材对照表.html", 'w', encoding='utf-8') as f:
        f.write('\n'.join(h))

    clips = list(CLIP_DIR.glob("clip_v3_*.mp4"))
    total_mb = sum(f.stat().st_size for f in clips) / 1024 / 1024
    print(f"✅ {len(clips)} clips, {total_mb:.0f}MB")
    for sid in sorted(results):
        r = results[sid]
        dd = sum(d for _, d, _ in r["dial"])
        nn = sum(d for _, _, d, _, _, _, _, _, _, _ in r["narr"])
        ok = "✅" if nn >= narr_dur.get(sid, 0) else "⚠️"
        print(f"  seg_{sid}: 🟡{dd:.0f}s 📝{nn:.0f}s / {narr_dur.get(sid,0):.0f}s {ok}")


if __name__ == "__main__":
    main()
