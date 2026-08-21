---
title: Python-数据处理
type: topic
tags: [language, technique, implemented]
difficulty: 入门
prerequisites: ["Python基础"]
status: implemented
created: 2026-08-19
---

# Python 数据处理

> JSON、正则、文本清洗、numpy——VibeCut 数据管线的日常

## 是什么

VibeCut 数据管线里最常碰的四件事：**JSON 读写**（结构化数据落地）、**文本清洗**（ASR 转写不干净）、**正则**（按模式提取/替换）、**numpy**（向量数学）。这一篇把四件套都过一遍，锚点全在真实代码。

```
ASR/VLM 原始数据 ──→ 文本清洗 + 正则 ──→ 编码成向量(numpy) ──→ 落盘(json/npy)
```

## JSON：VibeCut 的数据交换格式

```python
import json

data = json.load(open(path))              # 文件 → Python dict/list
json.dump(data, open(path, "w"), ensure_ascii=False, indent=2)   # dict → 文件
```

- `ensure_ascii=False`：中文直接写进文件（否则 "都挺好" 会存成 `\u90fd\u633a\u597d` 这样的转义，人没法读）
- `indent=2`：带缩进，人读和 diff 都方便
- 含中文的文件建议显式 `open(path, encoding="utf-8")`，别依赖系统默认

### segments.json 全链路

VibeCut 的核心数据流就是一条 JSON 链：

```
脚本生成 → save_segments() 落盘 segments.json → handlers 读取 → 前端 fetch 消费
```

**VibeCut 里：** `lib/segments_store.py` L30-36 `save_segments()`——`ensure_ascii=False, indent=2` 就是上面第二行的写法；L19-27 `load_segments()` 读回并用 try/except 兜底。`cli/build_index.py` L183-192 `save_index()` 更典型：一份数据同时存 pickle + `.npy` + json 三种格式。

## 文本清洗

ASR（语音转文字）输出不干净：带时间戳、说话人标记、同音错别字。清洗 = 截断噪声 + 归一化。

```python
text = s.get("description", "")
cal_marker = "\n[人物校准:"
if cal_marker in text:
    text = text[:text.index(cal_marker)]   # 截断到校准标记之前
```

**人名归一化**——把 ASR 的同音字误识别映射回标准名：

```python
def normalize_names(text: str) -> str:
    for wrong, right in NAME_MAP.items():
        text = text.replace(wrong, right)
    return text
```

**VibeCut 里：** `lib/names.py` L39-43——46 集全量修复 326 处人名（朱莉→朱丽、宋明成→苏明成）。这张映射表是「人名归一化铁律」的唯一真相源，scene_map 和 synopsis 生成 prompt 都引用它。

## 正则 re

按模式找/替换，比 `str.replace` 强得多：

```python
import re

m = re.search(r'\[?\s*(\d+)\s*/\s*(\d+)\s*\]?', line)   # 匹配 "12/20" 或 "[12/20]"
if m:
    current, total = int(m.group(1)), int(m.group(2))    # 取两个捕获组
```

- `r"..."` 原始字符串：`\d` 不会被转义
- `(\d+)` 捕获组：`m.group(1)` 取第 1 个
- `re.sub(pattern, repl, text)` 做替换（清洗场景最常用）

**VibeCut 里：** `lib/subprocess_runner.py` L115-118——从子进程输出的 `12/20` 里正则提取进度，算出百分比实时更新到前端。

## numpy 与向量

BGE 把每段文本编码成 768 维向量，搜索就是向量数学：

```python
import numpy as np

q_emb = encode(query)                    # 查询向量 (768,)
scores = np.dot(emb, q_emb)              # 所有向量 × 查询向量 = 相似度数组
top = np.argsort(scores)[-200:][::-1]    # 相似度最高的 200 个下标（倒序）
```

- 向量已归一化（`normalize_embeddings=True`），`np.dot` 结果就是余弦相似度
- `np.argsort` 返回排序后的下标，`[::-1]` 倒序 = 从高到低

**VibeCut 里：** `handlers/search.py` L125-127——语义搜索核心三行。向量落盘用 `cli/build_index.py` L191 `np.save(str(npy_path), embeddings.astype(np.float32))`——87MB 的 `semantic_embeddings.npy` 就是这么来的。

## 在 VibeCut 中的应用

| 工具 | 干什么 | 文件 |
|------|--------|------|
| json | segments.json / meta 落盘 | `lib/segments_store.py`、`cli/build_index.py` L183 |
| 字符串清洗 | ASR 去噪、截断校准标记 | `cli/build_index.py` L81-83 |
| 人名归一化 | 同音字映射 | `lib/names.py` |
| re | 解析进度、提取数字 | `lib/subprocess_runner.py` L115 |
| numpy | 向量编码 / 相似度计算 | `lib/embeddings.py`、`handlers/search.py` L125 |

## 前置知识

- [[Python基础]] — dict / 推导式 / 异常是这篇的前置

## 延伸

- [[文本嵌入与语义向量]] — 为什么文本能变成数字
- [[向量检索与索引]] — 向量怎么搜索（它把本笔记当 numpy 基础的前置）
- [[BGE索引实战]] — VibeCut 索引构建全貌

## 动手实验

1. 写一个函数：输入一行含 `[12/20]` 进度的文本，用正则提取两个数字并打印。
2. 读 `lib/names.py`，给 `NAME_MAP` 加两个误识别映射，观察替换顺序为什么按长度降序（先长后短）。
3. 用 numpy 手算两个向量的余弦相似度，和 `np.dot`（归一化后）对比结果。
