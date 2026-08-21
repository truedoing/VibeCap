---
title: Python基础
type: topic
tags: [language, concept, implemented]
difficulty: 入门
prerequisites: ["L1-语言与运行时"]
status: implemented
created: 2026-08-19
---

# Python 基础

> Python 够用就行——会一门语言就能上手，重点是 VibeCut 里高频用的那 20%

## 是什么

VibeCut 后端（`vibecut-server/`）全部是 Python：FastAPI 入口、数据管线、LLM/VLM 调用、配音、分镜匹配，一行不差。

但这一篇**不是** Python 全手册，而是给「会一门语言、没写过 Python」的学员一条最短上手路径——只讲 VibeCut 代码里真正高频的概念。目标是：看到 AI 生成的 Python 能读懂、能判断对错，而不是自己从头默写。

## Python 够用就行

### 1. 变量与类型

```python
project_name = "都挺好"   # str
port = 8765               # int
vlm_count = 452 - 17      # int
score = 0.78              # float
is_offline = True         # bool
nothing = None            # None（特殊值：表示"没有"，不是 0/空串/False）
```

Python 动态类型：赋值即定义，不用声明。`None` 是最重要的一个——「没有值」的标记，后面异常处理会专门讲它的坑。

**VibeCut 里：** `handlers/search.py` L14-18 用模块级变量存搜索索引，`semantic_emb = None` 就是「还没加载」的标记。

### 2. 容器：dict 是主角

VibeCut 里 90% 的数据都是 dict（Python 的"对象字面量"）：

```python
scene = {
    "time_range": "05:32-07:15",
    "location": "苏家老宅",
    "characters": ["苏大强", "苏明玉"],
    "event": "苏大强闹着买房子",
    "mood": "压抑",
}
print(scene["location"])     # 取：苏家老宅（键不存在 → 抛 KeyError）
print(scene.get("mood"))     # 取：键不存在 → 返回 None，不报错（安全）
scene["intensity"] = 3       # 增 / 改
```

规则：确定键一定存在用 `scene["key"]`，不确定用 `scene.get("key")`。

**VibeCut 里：** `handlers/search.py` L59-66 的 `_make_result()` 把一次搜索命中拼成一个 dict 返回；`lib/names.py` 整个人名归一化就是一张「错字 → 标准名」的 dict。

### 3. list / tuple / set 什么时候用

| 容器 | 特点 | VibeCut 场景 |
|------|------|-------------|
| `list` | 有序、可重复、可改 | 搜索结果、ASR 片段列表 |
| `tuple` | 有序、不可改 | 固定配对、坐标 |
| `set` | 无序、自动去重 | 算不重复的集数 |
| `dict` | 键 → 值映射 | scene_map、任务状态、meta_entry |

**VibeCut 里：** `cli/build_index.py` L26-29 用 `set` 去重算集数（见下一条的推导式例子）。

### 4. 控制流与列表推导式

for + dict 是最高频组合：

```python
for wrong, right in NAME_MAP.items():    # 遍历 dict 的键值对
    text = text.replace(wrong, right)
```

列表推导式：一行造列表（for + if 压缩成一行）：

```python
eps = [int(d.name[2:]) for d in sources_dir.iterdir() if d.name.startswith("ep")]
#      ↑ 加工每个元素   ↑ for 循环       ↑ 过滤条件
```

**VibeCut 里：** `lib/names.py` L41-42 遍历 `NAME_MAP` 做人名替换；`cli/build_index.py` L26-29 用 `set` + 推导式 + 过滤，一行算出全部集数。

### 5. 函数

```python
def encode(text: str, normalize: bool = True) -> np.ndarray:
    """对文本进行 BGE 编码，返回归一化向量"""
    model = get_model()
    return model.encode([text], normalize_embeddings=normalize)[0]
```

- 默认参数 `normalize: bool = True`：调用时可省略
- 类型标注 `text: str` / `-> np.ndarray`：帮读代码和 IDE 提示，运行时不强制
- docstring（函数第一行字符串）：说明"干什么"，读代码先看它

**VibeCut 里：** `lib/embeddings.py` L18-21 的 `encode()`——带类型标注、docstring、默认参数，是最标准的函数写法。

### 6. 类与单例

```python
_enc_model = None

def get_model(model_name: str = "BAAI/bge-base-zh-v1.5"):
    """延迟加载 BGE 模型（单例）"""
    global _enc_model
    if _enc_model is None:
        from sentence_transformers import SentenceTransformer
        _enc_model = SentenceTransformer(model_name)
    return _enc_model
```

- `global`：函数内修改模块级变量必须声明
- **单例模式**：模型只加载一次（加载很贵），之后复用同一份
- VibeCut 里类用得少，更多是「模块级全局 + 函数」风格——读代码时认得 `class` 即可

**VibeCut 里：** `lib/embeddings.py` L6-15——BGE 模型在 6.8GB VRAM 限制下必须单例，重复加载会爆内存。

### 7. 模块与 import

一个文件一个模块，`import` 导入；包（package）= 含 `__init__.py` 的目录：

```python
from routers import search, task_crud, segments, media  # 导入包里的多个模块
from routers.asr import router as asr_router            # as 起别名
```

**VibeCut 里：** `vibecut-server/main.py` L30-46——瘦入口，把 13 个 router 全部 import 后注册进 FastAPI。整个后端就是 `main.py → routers/ → handlers/ → lib/` 的依赖链，看懂这一条就掌握了后端结构。

### 8. 异常处理

```python
try:
    return json.load(open(path))
except Exception:
    return None   # 文件坏了就返回 None，让上层决定怎么兜底
```

- 用 try/except 包住「可能出错」的操作：文件不存在、JSON 解析失败、网络超时
- 最常用 `except Exception` 兜底，需要精确区分时再写具体类型
- **NoneType 坑**：函数返回 None 后，直接对返回值 `.get()`/`[...]` 会抛 `AttributeError: 'NoneType' object has no attribute ...`。VibeCut 修过真 bug——VLM 返回空 content 导致 None 崩溃，修复是"空时 fallback"。

**VibeCut 里：** `lib/segments_store.py` L24-27 `load_segments()` 用 try/except 保证文件损坏也不崩；`handlers/search.py` L22-29 用 `try: from opencc import OpenCC` 捕获 ImportError——没装 opencc 就用原样文本，优雅降级。

### 9. f-string 与格式化

```python
print(f"[drama] 编码 {len(texts)} 条 (VLM:{vlm_count} ASR:{len(texts)-vlm_count})...")
```

f-string：`f"..."` 里用 `{}` 直接插变量/表达式，是最常用的格式化方式。

**VibeCut 里：** `cli/build_index.py` L194 `f"✅ 索引: {pkl_path} ({len(texts)}条, {embeddings.shape[1]}维)"`。

## 在 VibeCut 中的应用

| 概念 | VibeCut 例子 |
|------|-------------|
| dict | scene_map / meta_entry / 搜索结果（`handlers/search.py` L59） |
| 函数 + 类型标注 | `lib/embeddings.py` L18 `encode()` |
| 单例 | `lib/embeddings.py` L9 `get_model()`（6.8GB VRAM 限制） |
| 模块 / import | `main.py` L30 注册 13 个 router |
| 异常兜底 | `lib/segments_store.py` L24 `load_segments()` |
| f-string | `cli/build_index.py` L194 |

## 前置知识

- [[L1-语言与运行时]] — Python 是 L1 层的第一块基石

## 延伸

- [[Python-数据处理]] — dict / 推导式在数据管线里的实战
- [[Python-标准库与并发]] — 函数 / 模块在文件、命令、线程里的实战
- [[JavaScript与React生态]] — 对照理解「语言 + 生态」的结构

## 动手实验

1. 读 `vibecut-server/lib/embeddings.py`（21 行），说出单例是怎么实现的、为什么必须单例。
2. 用 dict 描述《都挺好》苏大强家的一个场景（人物/地点/事件/情绪），再用 `.get()` 安全读取。
3. 把 `cli/build_index.py` L26-29 的推导式拆成普通 for 循环，体会推导式的简写。
