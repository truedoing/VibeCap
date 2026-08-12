"""
文案生成 Agent 系统 v2
优化: 时间约束传递 + Hook/收尾保护 + topic锚点 + 累积式修复

Agent 协议:
  输入: context (共享上下文) + task (具体任务描述)
  输出: {"ok": True, "result": {...}} | {"ok": False, "error": "..."}
"""
import json, time, urllib.request, os, re

# ═══════════════════════════════════════════════
# 口语废句黑名单 — 演讲者元评论，非内容，需在源头拦截
# ═══════════════════════════════════════════════
ORAL_FILLER_PATTERNS = [
    r'(这句|那个|这点).*(不讲|不说|跳过|pass)',
    r'我.*(就讲|先讲|讲吧|试讲|试着讲)',
    r'(讲到哪|讲到哪里|讲到哪儿)',
    r'(自己|稍微|回头).*(组织|整理|捋|梳理)',
    r'(这是|这是不是|都是).*内容',
    r'(我又忘|我忘了|忘记了|记不住)',
    r'差不多.*(行了|就这样|可以|够了)',
    r'随便.*(讲|说|聊|扯)',
    r'(哦|嗯|呃|啊)[，,].*(不讲|跳过)',
    r'不知道.*(是不是|这是不是).*内容',
    r'就先.*(这样|到这|不讲)',
    r'我.*(应该|应该怎么|要怎么).*(说|讲)',  # "我应该怎么说" "我应该这么说"
    r'你.*(可以|试着|尝试).*(说|讲|表达)',   # "你可以讲说"
]

def _clean_embedded_fillers(text):
    """清理嵌入句子中的口语废词, 保留内容主干"""
    # 移除: "对, 回头你看怎么给他揣一下" / "我觉得这个挺好的" / "你能不能举个例子" 等
    embedded = [
        r'[，,]\s*(对|回头|你看|你给我).*?(揣|弄|搞|整|串)[一下]*[，,]*',
        r'[，,]\s*我.*?(觉得|感觉|想).*?(挺好|不错|可以)[，,]*',
        r'[，,]\s*你.*?(能不能|可以不可以|能否).*?(举个|说个|讲个).*?(例子|案例)[，,]*',
        r'[，,]\s*(好|嗯|对|啊|哦)[，,]\s*',
    ]
    for pat in embedded:
        text = re.sub(pat, '，', text)
    # 清理连续逗号
    text = re.sub(r'[，,]\s*[，,]+', '，', text)
    return text.strip('，, ')

def _is_oral_filler(text):
    """检测是否为口语废句(元评论而非内容)"""
    if len(text) < 3: return True
    for pat in ORAL_FILLER_PATTERNS:
        if re.search(pat, text):
            return True
    return False

def _has_numerical_claim(text):
    """检测是否包含数值主张(用于数据一致性检查)"""
    return bool(re.search(r'\d+[万亿千百]', text))


# ── BGE 语义搜索函数注入(由 main.py 设置) ──
_search_fn = None
def set_search_fn(fn):
    global _search_fn
    _search_fn = fn
from lib.llm import call_moonshot_json as _call_llm_json

def _call_llm(system_prompt, user_content, temp=0.4, max_tokens=3000):
    """底层 LLM 调用，兼容旧接口"""
    result = _call_llm_json(system_prompt, user_content,
                            temperature=temp, max_tokens=max_tokens,
                            timeout=180, retries=3, label="agent")
    if result["ok"]:
        data = result["data"]
        if isinstance(data, list):
            data = {"sections": data}
        return {"ok": True, "result": data}
    return {"ok": False, "error": result.get("error", "?")[:200]}


# ═══════════════════════════════════════════════
# Helper: 时间窗口 + 邻近检测 (v3: 滑动窗口,非硬桶)
# ═══════════════════════════════════════════════
def _time_window(ts, bucket_sec=30):
    return int(ts // bucket_sec)

def compute_time_distribution(sentences):
    """返回每个30s窗口的句子数分布"""
    dist = {}
    for s in sentences:
        w = _time_window(s.get('source_start', 0))
        dist[w] = dist.get(w, 0) + 1
    return dist

def _find_time_clusters(sentences, proximity_sec=15, max_cluster_size=3):
    """
    邻近检测: 找出时间上过于接近的句子组。
    不依赖硬桶边界 — 只要相邻句子的时间间隔 < proximity_sec 就视为同一簇。
    返回需要移除的索引集合。
    """
    if len(sentences) <= max_cluster_size:
        return set()

    drop = set()
    # 按 source_start 排序遍历
    indexed = sorted(enumerate(sentences), key=lambda x: x[1].get('source_start', 0))

    i = 0
    while i < len(indexed):
        # 找从 i 开始的密集簇
        cluster = [indexed[i]]
        j = i + 1
        while j < len(indexed):
            gap = indexed[j][1].get('source_start', 0) - cluster[-1][1].get('source_start', 0)
            if gap < proximity_sec:
                cluster.append(indexed[j])
                j += 1
            else:
                break

        # 簇太大 → 保留优先级最高的, 丢弃其余的
        if len(cluster) >= max_cluster_size:
            # 优先级: insight > hook_tension > hook_promise > proof > evidence > empathy > personal_reveal > bridge > turn
            role_rank = {'insight': 9, 'hook_tension': 8, 'hook_promise': 7, 'proof': 6,
                         'evidence': 5, 'empathy': 4, 'personal_reveal': 3, 'bridge': 2, 'turn': 1}
            cluster.sort(key=lambda x: (
                role_rank.get(x[1].get('section_role', ''), 0),
                len(x[1].get('text', '')),  # 更长的句子通常信息更多
            ), reverse=True)
            # 保留前 max_cluster_size 个
            for idx, _ in cluster[max_cluster_size:]:
                drop.add(idx)

        i = j if j > i + 1 else i + 1

    return drop

def enforce_time_diversity(sentences, max_per_window=3, max_nearby=3, proximity_sec=15):
    """
    v3: 双重时间多样性 — 桶限制 + 邻近检测。
    - max_per_window: 每个30s硬桶的最多句子数
    - max_nearby: 邻近簇的最多句子数
    - proximity_sec: 邻近判定的最大间隔(秒)
    不再保护任何句子类型 — 全部平等参与时间多样性。
    """
    # Pass 1: 邻近检测 (解决硬桶边界问题)
    nearby_drops = _find_time_clusters(sentences, proximity_sec, max_nearby)

    # Pass 2: 硬桶限制 (兜底)
    windows = {}
    for i, s in enumerate(sentences):
        if i in nearby_drops: continue
        w = _time_window(s.get('source_start', 0))
        if w not in windows:
            windows[w] = []
        windows[w].append((i, s))

    bucket_drops = set()
    for w, items in windows.items():
        if len(items) <= max_per_window:
            continue
        # 按角色优先级排序
        role_rank = {'insight': 9, 'hook_tension': 8, 'hook_promise': 7, 'proof': 6,
                     'evidence': 5, 'empathy': 4, 'personal_reveal': 3, 'bridge': 2, 'turn': 1}
        items.sort(key=lambda x: (role_rank.get(x[1].get('section_role', ''), 0),
                                   len(x[1].get('text', ''))), reverse=True)
        for idx, _ in items[max_per_window:]:
            bucket_drops.add(idx)

    all_drops = nearby_drops | bucket_drops
    result = [s for i, s in enumerate(sentences) if i not in all_drops]
    # v3: 诊断日志 — 如果什么都没移除,输出时间分布方便排查
    if len(all_drops) == 0 and len(sentences) > 3:
        starts = [s.get('source_start', 0) for s in sentences]
        if max(starts) - min(starts) < 30:
            import sys
            print(f"  [diagnose] {len(sentences)}句密集在{min(starts):.0f}s-{max(starts):.0f}s,但邻近/桶均未触发", file=sys.stderr)
    return result, len(all_drops)

def compute_time_window_summary(sentences):
    """生成时间分布摘要 + 邻近簇告警"""
    dist = compute_time_distribution(sentences)
    clusters = [(w, cnt) for w, cnt in dist.items() if cnt >= 3]
    clusters.sort()

    # 邻近检测
    nearby = _find_time_clusters(sentences, proximity_sec=15, max_cluster_size=3)
    nearby_warn = ""
    if nearby:
        nearby_warn = f"\n⚠️ 邻近检测: {len(nearby)}句在15s间隔内过于密集"

    if not clusters:
        return "时间分布均匀" + nearby_warn
    lines = []
    for w, cnt in clusters:
        start_sec = w * 30
        lines.append(f"  - {start_sec}s-{start_sec+30}s: {cnt}句 (密集)")
    return "桶分布:\n" + "\n".join(lines) + nearby_warn


# ═══════════════════════════════════════════════
# Agent 1: 策划师 — 设计叙事结构 (v2: +topic_keywords)
# ═══════════════════════════════════════════════
def planning_agent(topic, content_text):
    """输入: 主题 + 采访内容精华 → 输出: 5-8段叙事结构 + 每段topic锚点"""
    system = (
        "你是一位资深短视频策划导演。根据采访内容精华，设计一个60-90秒短视频的叙事结构。\n\n"
        "原则:\n"
        "1. 确定核心主题(≤15字)，必须从内容中提炼，不能凭空编造\n"
        "2. 设计5-8个叙事段落，每段有明确的叙事角色和核心论点\n"
        "3. 结构必须有起伏: 激将/反认知开场 → 个人揭示建立信任 → 共情层 → 方法论 → 反转 → 案例 → 洞察收尾\n"
        "4. 给每段预估时长(秒),各段之和在90-110秒(留剪辑余量,最终成片60-90s)\n"
        "5. narrative_role 从以下选: hook_tension / hook_promise / personal_reveal / empathy / evidence / bridge / turn / proof / insight\n"
        "6. ★为每段提供 topic_keywords (3-5个锚点词), 用于搜索时防止主题漂移。最后一段(insight)的关键词应包含总结/升华类词汇\n\n"
        '输出JSON: {"topic":"主题","sections":[{"role":"hook_tension","point":"核心论点","duration":8,"topic_keywords":["关键词1","关键词2"]}]}'
    )
    return _call_llm(system, f"视频主题方向: {topic}\n\n采访内容精华:\n{content_text[:4000]}")


# ═══════════════════════════════════════════════
# Agent 2: 文案师 — 跨时间混编选句
# ═══════════════════════════════════════════════
def writer_agent(section, content_text):
    """输入: 一个段落定义 + 完整ASR → 输出: 该段落的原话选句"""
    system = (
        "你是短视频文案师。从采访ASR中为指定段落选出原话。\n\n"
        "★铁律: 只能从下方ASR中逐字复制,绝对禁止改写/扩写/编造。\n"
        "★目标: 全片最终60-90秒成片,需约180-240秒源素材。请尽量多地选出支撑本段论点的所有相关原话,不限数量。\n"
        "★宁可多选让后续压缩,也不要漏掉好素材。\n"
        "★跨时间选择(不按ASR顺序),同义句取最精炼的。\n"
        "★每句必须带准确的source_start/source_end(从ASR时间戳取)。\n\n"
        '输出JSON: {"sentences":[{"text":"必须和ASR一字不差","source_start":63.0,"source_end":67.0,"reason":"为何选"}]}'
    )
    user = f"段落角色: {section['role']}\n核心论点: {section['point']}\n\n★ASR(只能逐字复制):\n{content_text[:6000]}"
    return _call_llm(system, user, temp=0.3)


# ═══════════════════════════════════════════════
# Agent 3: 审核师 — 按剪辑标准检查文案质量
# ═══════════════════════════════════════════════
def reviewer_agent(topic, sections, rich_script, rich_src_dur):
    """输入: 主题 + 结构 + 脚本 → 输出: 质量报告 + 修改建议"""
    preview = '\n'.join(
        f"[{i}][{s.get('section_role','?')}][t={s.get('source_start',0):.0f}s dur={s.get('source_end',s.get('source_start',0)+3)-s.get('source_start',0):.0f}s] {s['text'][:80]}"
        for i, s in enumerate(rich_script)
    )
    # 计算实际时间分布
    time_dist = compute_time_distribution(rich_script)
    cluster_info = ""
    dense_windows = [(w, cnt) for w, cnt in time_dist.items() if cnt >= 4]
    if dense_windows:
        cluster_info = "当前时间分布:\n"
        for w, cnt in sorted(dense_windows):
            cluster_info += f"  {w*30}s-{w*30+30}s: {cnt}句\n"

    system = (
        "你是短视频质量审核师。根据以下标准审核一份文案草稿:\n\n"
        "【及格标准】\n"
        "1. 一件事讲清楚: 所有句子是否围绕同一个核心主题? 有无跑题?\n"
        "2. 好开头: 前3句是否有激将/反认知/个人揭示? 能抓住注意力吗?\n"
        "3. 节奏: 是否有连续5句以上来自同一30s窗口? (≤3句为正常, 4-5句标medium, ≥6句标high)\n"
        "★注意: 3句连续在同一窗口是正常的(主题聚合)。同主题聚合是优点, 同窗口>5句才标high。\n"
        "★句子间隔超过30s的不要标为堆砌。只关注真正密集在同一时间段的句子。\n\n"
        "【结构标准】\n"
        "4. Hook是否出现≥2次? (开头+收尾至少各1次)\n"
        "5. 是否有共情层?(方法论之前有理解观众痛点的内容)\n"
        "6. 收尾是否用深层洞察而非重复开头? 是否有'我又忘了''不讲那么多了'等口语化废句?\n"
        "7. ★内容断裂: 相邻句之间是否有明显的话题跳转? (如从方法论突然跳到对话场景、从数据跳到个人感叹) → 标为'内容断裂', severity=high\n"
        "8. ★数据一致性: 前后数据是否矛盾? (如前面说1000万后面说5000万、前面说5000万后面说3亿) → 标为'内容', severity=high\n"
        "9. 主题是否一致? 有无从核心主题漂移到无关话题? → 标为'主题', severity=high\n"
        "★注意: 收尾口语废句和重复表述标medium。内容断裂/数据矛盾/主题漂移标high。\n\n"
        f"【时间】当前源素材{rich_src_dur:.0f}s, 预估成片{rich_src_dur*0.5:.0f}s。目标60-90s, 状态: {'偏长' if rich_src_dur>180 else '偏短' if rich_src_dur<120 else '适中'}。\n\n"
        f"{cluster_info}\n"
        "输出JSON:\n"
        '{"scores":{"clarity":5,"opening":4,"rhythm":4,"hook_repetition":3,"empathy":4,"closing":4,"theme_consistency":4},'
        '"issues":[{"type":"节奏","severity":"high","detail":"第5-10句连续来自120-140s区间,造成堆砌感"},'
        '{"type":"收尾","severity":"medium","detail":"收尾口语废句/缺乏洞察"}],'
        '"verdict":"pass"|"revise"|"reject",'
        '"revision_notes":"如果verdict=revise,这里写具体的修改方向"}'
    )
    return _call_llm(system, f"主题: {topic}\n结构: {json.dumps(sections, ensure_ascii=False)}\n\n完整脚本({len(rich_script)}句):\n{preview}")


# ═══════════════════════════════════════════════
# Agent 4: 精编师 v2 — 时间感知 + Hook/收尾保护
# ═══════════════════════════════════════════════
def editor_agent(rich_script, target_sec=(90, 110), hook_indices=None, ending_indices=None):
    """
    输入: 丰富版脚本 + 目标成片时长 + 受保护句索引
    输出: 压缩后的 kept_indices
    """
    if hook_indices is None: hook_indices = set()
    if ending_indices is None: ending_indices = set()

    preview_lines = []
    for i, s in enumerate(rich_script):
        role = s.get('section_role', '?')
        dur = s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0)
        flags = []
        if i in hook_indices: flags.append('🔒HOOK')
        if i in ending_indices: flags.append('🔒收尾')
        flag_str = ' '.join(flags)
        time_w = _time_window(s.get('source_start', 0))
        preview_lines.append(
            f"[{i}][{role}][t={s.get('source_start',0):.0f}s w={time_w}][{dur:.0f}s] {flag_str} {s['text'][:80]}"
        )

    total_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in rich_script)
    time_summary = compute_time_window_summary(rich_script)
    target_src_lo = target_sec[0] * 2
    target_src_hi = target_sec[1] * 2

    hook_info = f"\n🔒 Hook句(必须保留): {sorted(hook_indices)}" if hook_indices else ""
    ending_info = f"\n🔒 收尾句(必须保留至少2句): {sorted(ending_indices)}" if ending_indices else ""

    system = (
        f"你是短视频精编师。压缩一份过于丰富的脚本。\n"
        f"当前源素材{total_src:.0f}s(预估成片{total_src*0.5:.0f}s)。\n"
        f"★目标: 压缩到{target_sec[0]}-{target_sec[1]}秒成片(对应约{target_src_lo}-{target_src_hi}s源素材,留剪辑余量)。\n\n"
        f"【时间分布】\n{time_summary}\n\n"
        "压缩原则(按优先级):\n"
        "1. ★时间多样性(最高优先级): 避免从同一30s窗口选超过3句。如果某窗口已有3句被选,不要再从该窗口选。\n"
        "2. ★保护Hook/收尾: 标记🔒的句子必须保留,除非时长严重超标。收尾至少保留2句有洞察力的句子。\n"
        "3. 保留结构完整性: 每个叙事段至少保留1句核心句\n"
        "4. 删除次要信息: 解释性/铺垫性内容优先删\n"
        "5. 同义合并: 表达同一意思的多句,只留最精炼的\n"
        "6. 保留数据/金句: 数字锚点和标题级表达必须保留\n"
        "7. ★主题连贯: 压缩后各句之间主题一致，不出现话题跳转\n"
        "8. ★收尾质量: 优先删除口语化废句('我又忘了''不讲那么多了'等)，保留有洞察力的收尾。\n\n"
        f"{hook_info}{ending_info}\n"
        '输出JSON: {{"kept_indices":[0,3,5,...],"cut_reasons":{{"3":"与第2句重复","7":"弱相关"}},'
        '"notes":"压缩率/保留逻辑/时间分布/收尾质量说明"}}'
    )

    preview = '\n'.join(preview_lines)
    return _call_llm(system, f"完整脚本({len(rich_script)}句):\n{preview}")


# ═══════════════════════════════════════════════
# Helper: 洞察句搜索 (用于修复收尾薄弱)
# ═══════════════════════════════════════════════
def _search_insight_sentences(content_text, existing_starts, count=5):
    """
    从 content_text 中搜索具有总结/洞察/升华性质的句子。
    不依赖语义搜索，使用启发式规则: 关键词匹配 + 高重要性 + 后半段时间。
    """
    insight_patterns = [
        r'(所以|因此|其实|真正|核心|本质|归根结底|说到底|关键是|重要的是)',
        r'(学会|学到|明白|领悟|意识|发现|认识到)',
        r'(不要|别|千万|永远|一定|必须)',
        r'(最终|最后|总结|归根|说到底|一句话)',
    ]

    candidates = []
    for line in content_text.split('\n'):
        m = re.match(r'\[([\d.]+)s\|(\d)\] (.+)', line)
        if not m:
            # also try other formats
            m2 = re.match(r'\[([\d.]+)s\|imp=(\d)\] (.+)', line)
            if not m2:
                continue
            start_sec, imp, text = float(m2.group(1)), int(m2.group(2)), m2.group(3)
        else:
            start_sec, imp, text = float(m.group(1)), int(m.group(2)), m.group(3)

        if start_sec in existing_starts:
            continue
        if len(text) < 10:
            continue
        if _is_oral_filler(text):
            continue

        # 计算洞察分数
        score = 0
        for i, pat in enumerate(insight_patterns):
            if re.search(pat, text):
                score += 3 - i * 0.5  # 前面的模式加权更高
        score += imp  # 重要性加分

        # 后半段的句子加分(通常是总结部分)
        # 假设总时长约600s，后半段 > 300s
        if start_sec > 300:
            score += 2

        if score >= 4:
            candidates.append({
                "text": text,
                "source_start": start_sec,
                "source_end": start_sec + min(len(text) // 5, 8),
                "reason": f"洞察句(score={score:.0f})",
                "section_role": "insight",
                "topic": "收尾洞察",
                "_insight_score": score,
            })

    candidates.sort(key=lambda s: -s['_insight_score'])
    return candidates[:count]


# ═══════════════════════════════════════════════
# Helper: 主题相关性过滤
# ═══════════════════════════════════════════════
def _topic_keyword_match(text, keywords, min_matches=1):
    """
    检查文本是否匹配 topic keywords。
    min_matches: 最少匹配几个关键词 (evidence/proof 类建议≥2)
    """
    if not keywords:
        return True
    text_lower = text.lower()
    matched = 0
    for kw in keywords:
        if len(kw) <= 2:
            if kw in text_lower:
                matched += 1
        else:
            if kw[:2] in text_lower or kw[-2:] in text_lower or kw in text_lower:
                matched += 1
        if matched >= min_matches:
            return True
    return False


# ═══════════════════════════════════════════════
# 编排器 v2: 协调 Agent 完成完整流程
# ═══════════════════════════════════════════════
def run_pipeline(topic, content_text, emit_progress=None):
    """
    完整文案生成流水线 v2
    核心改进:
    1. 时间约束从过滤阶段传递到压缩阶段(editor_agent感知时间分布)
    2. Hook/收尾句标记+保护(压缩时不可删除)
    3. topic_keywords 锚点防止搜索漂移
    4. 修复循环累积式(非elif互斥, 多种修复同时生效)
    5. 收尾薄弱→洞察句定向搜索
    """
    def progress(step, msg, data=None):
        if emit_progress: emit_progress(step, msg, data)

    # ── Phase 1: 策划 ──
    progress("planning", "策划师: 设计叙事结构...")
    r = planning_agent(topic, content_text)
    if not isinstance(r, dict) or not r.get('ok'):
        return {"ok": False, "error": f"策划师失败: {str(r)[:200]}"}
    sections = r['result']['sections'] if (r['ok'] and isinstance(r.get('result'), dict)) else (
        r['result'] if (r['ok'] and isinstance(r.get('result'), list)) else [])
    budget = sum(s['duration'] for s in sections)
    progress("planning_done", f"结构: {r['result']['topic']} · {len(sections)}段 · 预算{budget}s",
             {"topic": r['result']['topic'], "sections": sections, "budget": budget})

    # ── Phase 2: 搜索选句 (v2: +topic_keywords约束) ──
    progress("writing", "文案师: 语义搜索选句...")
    all_sentences = []
    global_window_usage = {}  # 跟踪每个30s窗口已使用次数, 优先从未用窗口选句
    for i, sec in enumerate(sections):
        query = sec['point']
        keywords = sec.get('topic_keywords', [])
        progress("writing", f"搜索 {i+1}/{len(sections)}: {query[:40]}")
        try:
            if _search_fn:
                import threading, queue
                q = queue.Queue()
                def _do():
                    try:
                        sr = _search_fn(query, limit=10)  # 多取一些用于过滤
                        q.put(sr)
                    except Exception as e:
                        q.put(e)
                t = threading.Thread(target=_do, daemon=True); t.start(); t.join(timeout=120)  # v3: 120s,首次加载模型~8s
                if t.is_alive():
                    # 超时后给第二次机会(可能是冷启动)
                    progress("writing", f"  ⚠️ 搜索超时(120s), 重试一次...")
                    t.join(timeout=30)
                    if t.is_alive():
                        progress("writing", f"  ⚠️ 搜索仍然超时, 使用回退策略")
                        results = []
                else:
                    sr = q.get()
                    if isinstance(sr, Exception): raise sr
                    results = sr
            else:
                results = []

            added = 0
            # v3: 按 (kw_match, 冷门窗口, 语义分) 排序 — 优先从时间冷门区域选句
            scored_results = []
            for rst in results:
                text = rst.get('description', rst.get('asr', ''))
                if len(text.strip()) < 3: continue
                start_ts = rst.get('start', 0)
                w = _time_window(start_ts)
                kw_match = _topic_keyword_match(text, keywords) if keywords else True
                # 冷门窗口加分: 使用次数越少优先级越高
                window_bonus = max(0, 5 - global_window_usage.get(w, 0))
                scored_results.append((text, start_ts, rst, kw_match, window_bonus))
            # 排序: kw_match优先 → 冷门窗口 → 语义分
            scored_results.sort(key=lambda x: (
                not x[3],  # kw_match=True排前面
                -x[4],     # window_bonus高的排前面
                -(x[2].get('score', 0)),  # 语义分高的排前面
            ))
            for text, start_ts, rst, kw_match, _ in scored_results[:5]:
                w = _time_window(start_ts)
                global_window_usage[w] = global_window_usage.get(w, 0) + 1
                all_sentences.append({
                    "text": text,
                    "source_start": start_ts,
                    "source_end": rst.get('end', rst.get('start', 0) + 4),
                    "reason": f"语义{rst.get('score',0):.0f}%" + ("✓" if kw_match else ""),
                    "topic": sec['point'][:30],
                    "section_role": sec['role'],
                    "_kw_match": kw_match,
                })
                added += 1
        except Exception as e:
            progress("writing", f"⚠️ 搜索失败: {e}")
        time.sleep(0.1)

    # 去重 + 口语废句过滤 + 嵌入废词清理 + 初始时间多样性
    seen = set()
    filler_count = 0
    window_count = {}
    rich_raw = [s for s in all_sentences if s.get('source_start', 0) > 0 and len(s.get('text','').strip()) > 3]
    # 口语废句过滤 + 嵌入废词清理 (v3: 源头拦截)
    rich_filtered = []
    for s in rich_raw:
        if _is_oral_filler(s['text']):
            filler_count += 1
            continue
        # 清理嵌入的废词
        cleaned = _clean_embedded_fillers(s['text'])
        if cleaned != s['text']:
            s['text'] = cleaned
        rich_filtered.append(s)
    if filler_count > 0:
        progress("writing", f"  🗑️ 过滤{filler_count}句口语废句")
    rich_raw = rich_filtered
    # 排序: 先按 kw_match，再按 source_start
    rich_raw.sort(key=lambda s: (not s.get('_kw_match', True), s.get('source_start', 0)))
    rich = []
    for s in rich_raw:
        w = _time_window(s.get('source_start', 0))
        key = f"{s.get('source_start',0):.0f}_{s['text'][:20]}"
        if key in seen: continue
        if window_count.get(w, 0) >= 3: continue  # 初始≤3句/窗口
        seen.add(key)
        window_count[w] = window_count.get(w, 0) + 1
        # 清理内部标记
        s.pop('_kw_match', None)
        rich.append(s)
    dropped = len(rich_raw) - len(rich)
    if dropped > 0:
        progress("writing", f"  去重+时间多样性: {len(rich_raw)}→{len(rich)}句 (每30s窗口≤3句)")

    # 如果搜索结果太少, 补充高重要度句子 (v3: 严格限制数量)
    if len(rich) < 20:
        supplements = []
        for line in content_text.split('\n'):
            m = re.match(r'\[([\d.]+)s\|(\d)\] (.+)', line)
            if not m:
                m2 = re.match(r'\[([\d.]+)s\|imp=(\d)\] (.+)', line)
                if not m2: continue
                start_sec, imp, text = float(m2.group(1)), int(m2.group(2)), m2.group(3)
            else:
                start_sec, imp, text = float(m.group(1)), int(m.group(2)), m.group(3)
            if imp >= 4 and len(text) > 8 and not _is_oral_filler(text):
                s = {"text": text, "source_start": start_sec, "source_end": start_sec + min(len(text)//5, 8),
                     "reason": "high_imp", "section_role": "evidence", "topic": "补充素材"}
                k = f"{s['source_start']:.0f}_{s['text'][:20]}"
                if k not in seen:
                    seen.add(k); supplements.append(s)
        # 只选时间最多样的15句
        supplements.sort(key=lambda s: s['source_start'])
        # 均匀采样
        if len(supplements) > 15:
            step = len(supplements) / 15
            supplements = [supplements[int(i * step)] for i in range(15)]
        for s in supplements:
            rich.append(s)
        rich.sort(key=lambda s: s['source_start'])
        if supplements:
            progress("writing", f"  补充{len(supplements)}句高重要度素材")
    # v3: hard cap rich at 40 sentences — editor LLM can't effectively choose from more
    if len(rich) > 40:
        # 按 kw_match + role priority + time diversity 选前40
        role_rank = {'insight': 9, 'hook_tension': 8, 'hook_promise': 7, 'proof': 6,
                     'evidence': 5, 'empathy': 4, 'personal_reveal': 3, 'bridge': 2, 'turn': 1}
        rich.sort(key=lambda s: (
            role_rank.get(s.get('section_role', ''), 0),
            len(s.get('text', '')),
        ), reverse=True)
        # 均匀保留时间多样性
        capped = []
        wc = {}
        for s in rich:
            w = _time_window(s.get('source_start', 0))
            if wc.get(w, 0) >= 2: continue
            wc[w] = wc.get(w, 0) + 1
            capped.append(s)
            if len(capped) >= 40: break
        rich = capped
        rich.sort(key=lambda s: s['source_start'])
        progress("writing", f"  ⚡ rich硬限制: {len(capped)}句 (最多40句,防编辑器过载)")
    rich.sort(key=lambda s: s['source_start'])
    rich_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in rich)
    progress("writing_done", f"丰富版: {len(rich)}句 · 源{rich_src:.0f}s · 预估{rich_src*0.5:.0f}s",
             {"count": len(rich), "source": round(rich_src, 1)})

    # ── v2: 标记 Hook 和 Ending 句 ──
    # Hook: 前3句 (按时间排序)
    hook_indices = set()
    if len(rich) >= 3:
        hook_indices = {0, 1, 2}
    # Ending: 最后一段 (insight role) 的所有句子
    ending_indices = set()
    insight_role_sentences = [i for i, s in enumerate(rich) if s.get('section_role') == 'insight']
    if insight_role_sentences:
        # 标记 insight role 的所有句子
        ending_indices = set(insight_role_sentences)
    else:
        # fallback: 标记最后 1/5 的句子
        ending_count = max(3, len(rich) // 5)
        ending_indices = set(range(max(0, len(rich) - ending_count), len(rich)))

    progress("writing", f"  🔒 Hook句: {sorted(hook_indices)}, 收尾句: {sorted(ending_indices)}")

    # ── Phase 3: 精编 v2 (时间感知 + 保护标记) ──
    progress("editing", f"精编师: 压缩到{90}-{110}s(留剪辑余量)...")
    edit = editor_agent(rich, target_sec=(90, 110),
                        hook_indices=hook_indices, ending_indices=ending_indices)
    if edit['ok']:
        kept = edit['result'].get('kept_indices', list(range(len(rich))))
        final = [rich[i] for i in kept if 0 <= i < len(rich)]

        # v3: 后编辑时间强制 — 邻近检测(8s) + 桶限制(≤2/窗口), 不保护任何角色
        final, time_dropped = enforce_time_diversity(final, max_per_window=2, max_nearby=3, proximity_sec=8)
        progress("editing", f"  ⚡ 后编辑时间强制: {'移除'+str(time_dropped)+'句堆砌' if time_dropped > 0 else '已均匀'}")

        # v2: 收尾保护 — 确保至少有2句 insight/ending 存活
        surviving_ending = sum(1 for i, s in enumerate(final)
                               if s.get('section_role') == 'insight')
        if surviving_ending < 2:
            progress("editing", f"  ⚠️ 收尾仅{surviving_ending}句, 补充洞察句...")
            existing_starts = set(s['source_start'] for s in final)
            insight_candidates = _search_insight_sentences(content_text, existing_starts, count=3)
            if insight_candidates:
                # 加到末尾
                final = final + insight_candidates[:2]
                progress("editing", f"  ✅ 补充{len(insight_candidates[:2])}句洞察收尾")
    else:
        final = rich

    final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
    est = final_src * 0.5
    progress("editing_done",
        f"压缩: {len(rich)}→{len(final)}句 · 源{final_src:.0f}s · 预估成片{est:.0f}s",
        {"rich": len(rich), "final": len(final), "cut": len(rich)-len(final),
         "notes": edit['result'].get('notes', '') if edit['ok'] else '',
         "time_enforced": True, "ending_protected": True})

    # ── Phase 4: 审核 + 智能修复 v2 (累积式, 非互斥) ──
    MAX_RETRIES = 2
    review = None
    for retry in range(MAX_RETRIES + 1):
        label = f"审核{'' if retry == 0 else f'·重审#{retry}'}"
        progress("review", f"审核师: {label}...")
        review = reviewer_agent(topic, sections, final, final_src)
        if not isinstance(review, dict) or not review.get('ok'):
            progress("review_done", f"⚠️ 审核师调用失败")
            break

        review_result = review.get('result', {})
        if isinstance(review_result, list):
            review_result = {"verdict": "revise", "issues": [], "scores": {}}
        v = review_result.get('verdict', '?')
        scores = review_result.get('scores', {})
        avg_score = sum(scores.values()) / max(len(scores), 1) if scores else 0
        issues = review_result.get('issues', [])
        high_issues = [i for i in issues if i.get('severity') == 'high']
        notes = review_result.get('revision_notes', '')

        for iss in issues[:5]:
            progress("review_issue", f"  {'🔴' if iss.get('severity')=='high' else '🟡'} [{iss.get('severity','?')}] {iss.get('detail','')[:80]}")

        # 过关判断 (v2: 程序判断,LLM的verdict仅供参考,不覆盖)
        no_high = len(high_issues) == 0
        duration_ok = 35 <= est <= 140
        if retry == 0:
            passed = avg_score >= 4 and no_high and duration_ok
        else:
            # 修正后: 必须无high问题+时长OK (不放松)
            passed = no_high and duration_ok
        if passed:
            progress("review_done", f"✅ {label}通过 · 均分{avg_score:.0f} · 问题{len(issues)}个({len(high_issues)}个严重) · 时长{est:.0f}s",
                     {"verdict": v, "scores": scores, "issues": issues, "notes": notes})
            break

        # 没过: 输出原因
        reasons = []
        if not no_high: reasons.append(f"{len(high_issues)}个严重问题")
        if not duration_ok: reasons.append(f"时长{est:.0f}s超范围")
        if retry == 0 and avg_score < 4: reasons.append(f"均分{avg_score:.0f}<4")
        fail_reason = ", ".join(reasons)

        if retry >= MAX_RETRIES:
            progress("review_done", f"⚠️ 已达最大重试, 需人工判断 · 均分{avg_score:.0f}",
                     {"verdict": v, "scores": scores, "issues": issues, "notes": notes})
            break

        # ── v2: 累积式修复 (多个 if 而非 elif) ──
        progress("review_retry", f"🔁 未过关, 总调度分析问题归属...")
        fixes_applied = []

        # 分类问题 (v2: 更细粒度, 内容断裂归入rhythm/drift)
        structure_issues = [i for i in issues if i.get('type') in ['结构','开头','标题','共情层','案例位置']]
        rhythm_issues    = [i for i in issues if i.get('type') in ['节奏','堆砌','重复','断裂','内容断裂','跳转']]
        content_issues   = [i for i in issues if i.get('type') in ['内容','素材']]
        ending_issues    = [i for i in issues if i.get('type') in ['收尾','结尾','洞察','重复表述']]
        drift_issues     = [i for i in issues if i.get('type') in ['主题','跑题','游离','漂移','不一致','数据','矛盾']]

        # Fix 1: 时间堆砌/内容断裂 → v3双检测(邻近+桶), 无保护
        if rhythm_issues:
            progress("review_retry", f"  🎵 时间堆砌/断裂({len(rhythm_issues)}个) → 邻近检测+桶限制...")
            # 先清理口语废句(断裂的常见原因)
            cleaned = [s for s in final if not _is_oral_filler(s['text'])]
            filler_dropped = len(final) - len(cleaned)
            if filler_dropped > 0:
                final = cleaned
                progress("review_retry", f"  🗑️ 清理{filler_dropped}句口语废句")
            final, dropped = enforce_time_diversity(final, max_per_window=2, max_nearby=3, proximity_sec=8)
            final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
            est = final_src * 0.5
            fixes_applied.append(f"去堆砌/断裂{dropped}句" + (f"+清{filler_dropped}废句" if filler_dropped else ""))
            progress("review_retry", f"  ✅ 移除{dropped}句 · 现{len(final)}句 · 预估{est:.0f}s")

        # Fix 2: 收尾薄弱 → 定向搜索洞察句 + 用通用filler检测清理口语废句
        if ending_issues:
            progress("review_retry", f"  🎯 收尾薄弱({len(ending_issues)}个) → 搜索洞察句+清理口语废句...")
            cleaned = []
            removed_count = 0
            for s in final:
                if _is_oral_filler(s['text']) and s.get('section_role') not in ('hook_tension', 'hook_promise'):
                    removed_count += 1
                    continue
                cleaned.append(s)
            if removed_count > 0:
                final = cleaned
                progress("review_retry", f"  🗑️ 清理{removed_count}句口语废句")

            # 补充洞察句
            existing_starts = set(s['source_start'] for s in final)
            insight_candidates = _search_insight_sentences(content_text, existing_starts, count=5)
            if insight_candidates:
                # 替换末尾: 保留最后2句原有, 其余用洞察句替换
                final = final[:-2] + insight_candidates[:3] if len(final) > 4 else final + insight_candidates[:2]
                final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
                est = final_src * 0.5
                fixes_applied.append(f"+{len(insight_candidates[:3])}句洞察收尾")
                progress("review_retry", f"  ✅ 补充洞察收尾 · 现{len(final)}句 · 预估{est:.0f}s")

        # Fix 3: 主题漂移 → v3强锚点过滤 (evidence/proof需≥2关键词)
        if drift_issues:
            progress("review_retry", f"  🧭 主题漂移({len(drift_issues)}个) → 强topic锚点过滤...")
            all_keywords = []
            for sec in sections:
                all_keywords.extend(sec.get('topic_keywords', []))
            all_keywords = list(set(all_keywords))

            if all_keywords:
                filtered = []
                dropped_drift = 0
                for s in final:
                    role = s.get('section_role', '')
                    if role in ('hook_tension', 'hook_promise', 'insight'):
                        # Hook/insight 句宽松匹配(≥1关键词)
                        if _topic_keyword_match(s['text'], all_keywords, min_matches=1):
                            filtered.append(s)
                        else:
                            dropped_drift += 1
                    else:
                        # evidence/proof/personal_reveal 需≥2关键词 (防漂移)
                        if _topic_keyword_match(s['text'], all_keywords, min_matches=2):
                            filtered.append(s)
                        else:
                            dropped_drift += 1
                if dropped_drift > 0 and len(filtered) >= len(final) * 0.5:
                    final = filtered
                    final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
                    est = final_src * 0.5
                    fixes_applied.append(f"过滤{dropped_drift}句跑题")
                    progress("review_retry", f"  ✅ 过滤{dropped_drift}句跑题 · 现{len(final)}句")

        # Fix 4: 素材不足 → 补充高重要度句
        if content_issues or len(final) < 12:
            progress("review_retry", f"  ✍️ 素材不足 → 补充高重要度/多样性句...")
            existing_starts = set(s['source_start'] for s in final)
            extra = []
            for line in content_text.split('\n'):
                m = re.match(r'\[([\d.]+)s\|(\d)\] (.+)', line)
                if not m:
                    m2 = re.match(r'\[([\d.]+)s\|imp=(\d)\] (.+)', line)
                    if not m2: continue
                    start_sec, imp, text = float(m2.group(1)), int(m2.group(2)), m2.group(3)
                else:
                    start_sec, imp, text = float(m.group(1)), int(m.group(2)), m.group(3)
                if start_sec in existing_starts: continue
                if imp >= 4 and len(text) > 8:
                    extra.append({"text": text, "source_start": start_sec,
                                  "source_end": start_sec + min(len(text)//5, 8),
                                  "reason": "补素材", "section_role": "evidence"})
            # 时间多样性: 优先选冷门窗口的句子
            existing_windows = set(_time_window(s['source_start']) for s in final)
            extra_cold = [s for s in extra if _time_window(s['source_start']) not in existing_windows]
            extra_hot = [s for s in extra if _time_window(s['source_start']) in existing_windows]
            new_s = (extra_cold + extra_hot)[:10]
            if new_s:
                final = final + new_s
                final.sort(key=lambda s: s['source_start'])
                final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
                est = final_src * 0.5
                fixes_applied.append(f"+{len(new_s)}句素材")
                progress("review_retry", f"  ✅ 补充{len(new_s)}句 · 现{len(final)}句 · 预估{est:.0f}s")

        # Fix 5: 结构问题 → 调策划师
        if structure_issues:
            progress("review_retry", f"  📐 结构问题({len(structure_issues)}个) → 调度策划师修正...")
            feedback = '; '.join(i['detail'][:60] for i in structure_issues)
            r2 = planning_agent(f"{topic}。修正: {feedback}", content_text)
            if r2['ok'] and r2['result'].get('sections'):
                sections = r2['result']['sections']
                fixes_applied.append("结构调整")

        if not fixes_applied:
            # Fallback: 如果问题无法归类，做一次时间多样性强制 + 素材补充
            progress("review_retry", "  🔧 无明确分类, 执行通用修复(邻近检测+桶限制)...")
            final, dropped = enforce_time_diversity(final, max_per_window=2, max_nearby=3, proximity_sec=8)
            final_src = sum(s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0) for s in final)
            est = final_src * 0.5
            fixes_applied.append(f"通用修复{dropped}句")

        progress("review_retry", f"  ✅ 修复完成: {' + '.join(fixes_applied)} · 现{len(final)}句 · 预估{est:.0f}s")

    # ── 组装 segments ──
    segments = []
    for s in final:
        segments.append({
            "seg_id": len(segments),
            "highlight_text": s['text'],
            "source_start": s.get('source_start', 0),
            "source_end": s.get('source_end', s.get('source_start', 0) + 5),
            "topic": s.get('topic', ''),
            "section_role": s.get('section_role', ''),
            "edit_type": "trim",
            "narration_text": "",
            "note": s.get('reason', ''),
        })

    # 安全提取 topic (LLM 可能返回 list 而非 dict)
    result_data = r.get('result', {}) if r.get('ok') else {}
    if isinstance(result_data, list):
        # LLM 返回了纯 sections 数组, 无 topic 字段
        result_topic = topic
    elif isinstance(result_data, dict):
        result_topic = result_data.get('topic', topic)
    else:
        result_topic = topic

    return {
        "ok": True,
        "topic": result_topic,
        "sections": sections,
        "segments": segments,
        "total": len(segments),
        "rich_count": len(rich),
        "final_count": len(final),
        "review": review['result'] if (review and review['ok']) else {},
        "review_issues": review['result'].get('issues', []) if (review and review['ok']) else [],
        "review_verdict": review['result'].get('verdict', '?') if (review and review['ok']) else '?',
        "revision_notes": review['result'].get('revision_notes', '') if (review and review['ok']) else '',
        "edit_notes": edit['result'].get('notes', '') if edit['ok'] else '',
        "checks": review['result'].get('checks', {}) if (review and review['ok']) else {},
        "bridges": [],
        "ai_generated_count": 0,
        "time_estimate": {
            "budget": budget,
            "rich_source": round(rich_src, 1),
            "source_total": round(final_src, 1),
            "estimated_final": round(est, 1),
            "target": "60-90s",
            "status": "ok" if 50 <= est <= 110 else ("over" if est > 110 else "under"),
        }
    }


# ═══════════════════════════════════════════════
# Story-First Pipeline v4
# 策略: LLM通读全ASR → 理解完整故事 → 一次性输出连贯脚本
# 适用: 口播采访 (非电视剧), 原素材天然不线性
# ═══════════════════════════════════════════════
def story_first_pipeline(topic, content_text, emit_progress=None):
    """
    v4: 故事优先流水线。
    不做逐段搜索, 而是让 LLM 通读全部 ASR 后一次性设计故事 + 选片段。

    content_text: 完整 ASR 文本, 格式 "[start_sec|imp] text"
    输出: {"ok": True, "segments": [...], "story": "..."}
    """
    def progress(step, msg, data=None):
        if emit_progress: emit_progress(step, msg, data)

    # 截取 ASR (DeepSeek 128K 上下文, 留足够余量)
    max_chars = 60000
    if len(content_text) > max_chars:
        # 优先保留高 importance 的句子
        lines = content_text.split('\n')
        high = [l for l in lines if '|5]' in l or '|4]' in l]
        low = [l for l in lines if '|3]' in l or '|2]' in l or '|1]' in l]
        content_text = '\n'.join(high) + '\n' + '\n'.join(low[:len(low)//2])
        content_text = content_text[:max_chars]
        progress("story", f"  ASR截断至{max_chars}字符 (优先高重要度)")

    progress("story", "📖 故事师: 通读全部ASR, 理解完整故事...")

    system = (
        "你是一位资深剪辑师和故事编辑。\n\n"
        "下面是一段采访的完整ASR转写(带时间戳)。你的任务:\n\n"
        "★第一步: 通读所有内容, 理解采访的完整脉络。\n"
        "   - 演讲者真正想表达的核心观点是什么?\n"
        "   - 哪些内容在前面提出、后面补充或总结?\n"
        "   - 演讲者用了什么结构来组织观点?(第一/第二/第三、首先/然后/最后)\n"
        "   - ★哪些句子本身就是承上启下的过渡句?(如'那第三个点''除了这个还有''好接下来讲')\n"
        "   - 哪些是重复/口语废词/跑题的?\n\n"
        "★第二步: 设计一个60-90秒的连贯故事, 按「段落」组织。\n"
        "   每个段落是一个完整的意思单元, 包含2-5个逻辑关联的clip。\n"
        "   段落之间如果ASR中有自然的过渡句, 就把它作为该段落的第一个clip。\n"
        "   - 6-9个段落, 总clips控制在15-25个\n"
        "   - 叙事弧线: Hook → Empathy → Turn → Evidence链 → Insight → Proof → Closing\n"
        "   - ★段落内的clips必须来自ASR原文中的自然逻辑组(如演讲者的第1/2/3点)\n"
        "   - ★段落间过渡: 如果ASR中有承上启下的句子就用作第一个clip, 没有就硬切(不要捏造过渡句)\n"
        "   - ★前后数据必须一致\n\n"
        "★第三步: 为每个段落输出。\n"
        "   - role: narrative_role\n"
        "   - title: 段落标题(≤12字)\n"
        "   - clips: 2-5个clip, 每个clip的text必须逐字来自ASR, source_start/source_end从ASR时间戳取\n"
        "   - ★如果第一个clip本身就起过渡作用, 在note中标注'过渡句'\n\n"
        "★铁律:\n"
        "1. 段落内clips之间要自然流畅 — 它们应该来自ASR中本就相邻或逻辑相关的位置\n"
        "2. ★过渡只能来自ASR原文 — 如果找不到合适的过渡句, 就硬切, 绝不自己编\n"
        "3. 保留演讲者的编号结构 — 如果原文说'第一第二第三', 就按这个顺序\n"
        "4. 数据一致 — 不能前边说1000万, 后边说3亿\n"
        "5. clips的text必须逐字来自ASR(允许删明显的废词), 不能改写\n"
        "6. 同一时间段的clip不要连续超过4个\n\n"
        '输出JSON:\n'
        '{"story":"一句话故事概要",'
        '"sections":[\n'
        '  {"role":"hook_tension","title":"转化率之谜",\n'
        '   "clips":[{"text":"ASR原话","source_start":16.0,"source_end":20.0,"note":"开场hook"}]},\n'
        '  {"role":"empathy","title":"常见的坑",\n'
        '   "clips":[{"text":"其实很多机构都是这样","source_start":40.0,"source_end":43.0,"note":"过渡句"},...]},\n'
        '  ...\n'
        ']}'
    )

    user = (
        f"视频主题方向: {topic}\n\n"
        f"★★完整采访ASR(带时间戳, importance=5最高):\n\n"
        f"{content_text}"
    )

    r = _call_llm(system, user, temp=0.4, max_tokens=4000)
    if not r.get('ok'):
        return {"ok": False, "error": f"故事师失败: {r.get('error', '?')}"}

    result_data = r['result']
    if isinstance(result_data, list):
        result_data = {"story": "", "sections": result_data}

    story = result_data.get('story', '')
    sections = result_data.get('sections', [])

    # Fallback: LLM 返回了旧格式 segments
    if not sections and result_data.get('segments'):
        sections = [{"role": s.get('narrative_role', 'evidence'), "title": "",
                     "bridge": None, "clips": [s]}
                    for s in result_data['segments']]

    # ── 展开 sections → 扁平的 segments ──
    flat_segments = []
    for sec_idx, sec in enumerate(sections):
        role = sec.get('role', 'evidence')
        title = sec.get('title', '')
        clips = sec.get('clips', [])

        for clip in clips:
            text = clip.get('text', clip.get('highlight_text', '')).strip()
            ss = clip.get('source_start', 0)
            se = clip.get('source_end', ss + max(len(text) // 5, 3))
            if len(text) < 3 or ss <= 0:
                continue
            flat_segments.append({
                "seg_id": len(flat_segments),
                "highlight_text": text,
                "source_start": ss,
                "source_end": se,
                "narrative_role": role,
                "edit_type": "trim",
                "note": clip.get('note', title) if clip.get('note') else title,
                "section_idx": sec_idx,
            })

    # 计算时长
    src_total = sum(
        max(s.get('source_end', s.get('source_start', 0) + 5) - s.get('source_start', 0), 0)
        for s in flat_segments
    )
    est_final = src_total * 0.5

    progress("story_done",
        f"✅ 故事: {story[:50]} · {len(sections)}段{len(flat_segments)}clip · 源{src_total:.0f}s · 预估{est_final:.0f}s",
        {"story": story, "sections": len(sections), "clips": len(flat_segments), "source": round(src_total, 1)}
    )

    return {
        "ok": True,
        "pipeline": "story-first-v4",
        "topic": topic,
        "story": story,
        "sections": sections,
        "segments": flat_segments,
        "total": len(flat_segments),
        "ai_generated_count": 0,
        "rich_count": len(flat_segments),
        "final_count": len(flat_segments),
        "review_issues": [],
        "review_verdict": "story_first",
        "revision_notes": "",
        "edit_notes": f"故事优先v4: {len(sections)}段, 全部ASR原文",
        "checks": {},
        "bridges": [],
        "time_estimate": {
            "budget": 90,
            "rich_source": round(src_total, 1),
            "source_total": round(src_total, 1),
            "estimated_final": round(est_final, 1),
            "target": "60-90s",
            "status": "ok" if 50 <= est_final <= 110 else ("over" if est_final > 110 else "under"),
        }
    }
