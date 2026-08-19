# VibeCut 数据处理架构演进 v4 — 场景质检漏斗

> 当前生效。本文档记录「人物在场判定」处理架构的三次演进 + 场景质检漏斗算法。
> 前代文档: [DATA_PIPELINE_V3.md](./DATA_PIPELINE_V3.md)（三层推理）, [DATA_PIPELINE.md](./DATA_PIPELINE.md)（v2 废弃）。

## 一、架构演进：人物在场判定怎么变的

### 阶段 V1 — VLM 全量辨认（废弃）

```
源视频 → 抽帧 → VLM 直接认人(~29%错误) → characters
```

- 让 VLM 直接识别画面里是谁，靠人脸/画面推断
- **缺陷**: 无参考照时完全靠猜（实测把苏明成认成"白敬亭/吴昕"）；有参考照也 ~29% 错误
- **结论**: VLM 没有可靠的视觉身份能力，认人这条路废弃

### 阶段 V2 — 场记Agent（DeepSeek 读字幕，当前主线）

```
SRT字幕 → DeepSeek 场记 → scene_map(characters/loc/event) → 喂给 VLM 描述画面
```

- 人物权威从 VLM 移到 DeepSeek（读字幕推断），VLM 只做画面描述
- **缺陷（在场盲区）**: 文本只能证明「被提到」，证明不了「在场」
  - S6 例: 窗口字幕「明玉 我已经和明成离婚了」（朱丽在电话里告诉明玉）→ DeepSeek 以为明玉在场
  - 「你放心大哥」→ 大哥=苏明哲没解析 → 漏掉真正在场的苏明哲
- **更深**: VLM 描述按错误的 scene_map prompt 生成 → 回声污染（描述里也出现苏明玉）
- **结论**: 文本推断能做身份线索，做不了在场事实

### 阶段 V3 — 场景质检漏斗（PySceneDetect + 亮度 + 字幕，当前）

```
PySceneDetect(视觉切分) + 亮度regime检测 → 找混合窗口(SUSPECT)
        ↓ DeepSeek 字幕断裂分析 → 确认/否决 (MIXED/SINGLE)
        ↓ 拆分 + 各半重生成 chars/loc/event + 重跑 VLM
        ↓ 人工只兜底 UNCERTAIN 残差
```

- **核心洞察**: 场景切分是「视觉属性」（画面切没切），不是文本属性。根子在切分，次生所有人物错误
- **人工量**: 1511 场景 → 12 个 UNCERTAIN（0.8%）
- 人物在场性靠画面（视觉断点）+ 身份靠文本（字幕断裂）**交叉验证**

## 二、场景质检漏斗算法

### 漏斗结构

```
L1 本地(无API)   亮度regime检测 → 76% 场景确定性清除(亮度稳定=单场景)
L2 DeepSeek(按需) 字幕断裂分析 → 确认 SUSPECT 是混合(MIXED) 还是光线变化(SINGLE)
L3 自动修正        MIXED → 按断点拆两半, 各半重生成 chars/loc/event + 重跑 VLM
L4 人工(最少)      仅 UNCERTAIN 残差 (0.8%)
```

### L1 亮度 regime 检测（`cli/score_scene_mix.py`）

对每个 scene_map 场景 [a,b]:
```
抽每 3s 一帧的灰度均值 → 亮度序列 v
比较前 1/3 与后 1/3 平均亮度差:
  diff > 20  → SUSPECT(可能混合窗口)
  diff ≤ 20  → CLEAR(单场景, 亮度稳定)
```
- 阈值 20 在 EP32 校准（S6 混合 diff=24, 单场景 2-18）
- 原理: 混合窗口（如 S6 朱丽家→饭店）有持续亮度转变；单场景（同一房间对话）亮度稳定

### L2 字幕断裂分析（`cli/analyze_subtitle_break.py`）

对 SUSPECT 场景, DeepSeek 读窗口字幕:
```
判断字幕是【连贯剧情段】还是【两个不同剧情段拼一起】:
  话题/地点/人物组明显切换 → MIXED(断裂)
  持续同一话题 → SINGLE(光线变化)
  字幕过短/无内容 → UNCERTAIN
```
- 与 L1 视觉断点**交叉验证**: 视觉断 + 字幕断 = 真混合; 视觉断 + 字幕连贯 = 光线变化
- EP32 实测: 369 SUSPECT → 79 MIXED / 278 SINGLE / 12 UNCERTAIN

### L3 拆分 + 重生成（`cli/generate_split_plan.py` + `cli/apply_splits.py`）

MIXED 场景按断点拆成两半:
```
拆出两半的断点(DeepSeek 给 break_time, 或取亮度最大转变点)
各半字幕单独喂 DeepSeek → 生成这半的 chars/loc/event/mood(窗口干净, 文本推断大幅提升)
scene_map 场景替换为两个半段; VLM 缓存重排索引, 新半段重跑 MiMo 描述
```
- 只对 MIXED 场景操作, 其余 76%+278 个 CLEAR/SINGLE 场景不动
- 亲属称谓解析铁律（大哥→苏明哲 等）已加入场记 prompt, 修确定性漏检

### L4 人工兜底

UNCERTAIN 残差（字幕过短/静默场景）→ 数据台/审查页展示断点两侧关键帧 + 字幕 → 人定案

## 三、关键发现（血泪教训）

| 发现 | 证据 |
|---|---|
| VLM 无视觉身份能力 | 无参考照认成"白敬亭/吴昕" |
| 文本证明不了「在场」 | S6 明玉被电话告知却标为在场 |
| VLM 描述是 scene_map 的回声 | 17 集后半无真实帧, VLM 纯靠 prompt 文字编造 |
| 场景切分是根因 | S6 混合窗口次生人物/事件/描述全部错误 |
| 机位切换≠场景切换 | ffmpeg scene 分数全红, 需 min_scene_len 合并 |
| 亮度 regime 是有效信号 | S6 亮度差 24 可标, 单场景 2-18 不标 |
| DeepSeek 字幕断裂可靠 | UNCERTAIN 从 MiMo 50%+ 降到 3% |
| 手动改数据会放大错误 | 「苏明玉请客」是我基于错误 chars 编的 |

## 四、脚本清单

| 脚本 | 职责 | 依赖 |
|---|---|---|
| `cli/score_scene_mix.py` | L1 亮度 regime 检测 | 本地 ffmpeg+PIL |
| `cli/analyze_subtitle_break.py` | L2 字幕断裂分析 | DeepSeek |
| `cli/classify_scene_mix.py` | (备选) MiMo 场景分辨 | MiMo（慢, UNCERTAIN 高） |
| `cli/generate_split_plan.py` | 拆分方案生成 | DeepSeek |
| `cli/apply_splits.py` | 拆分应用(scene_map+VLM重排) | 本地 |
| `cli/rerun_split_vlm.py` | 新半段 VLM 描述 | MiMo |
| `cli/extract_scene_frames.py` | 定向抽帧(每场景3帧) | ffmpeg |
| `cli/calibrate_scene_map.py` | 人物校准(早期方案, 保留参考) | DeepSeek |

## 五、当前数据状态

- 总场景: 1589（原 1511 + 拆分）
- 79 个混合窗口已拆成干净场景
- 12 个 UNCERTAIN 人工判定为单场景（保留）
- 亲属称谓铁律已入 prompt（防未来）
