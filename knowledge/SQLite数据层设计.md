---
title: SQLite数据层设计
type: topic
tags: [infrastructure, implemented]
difficulty: 入门
prerequisites: ["SQL 基础", "Python sqlite3 模块"]
status: implemented
created: 2026-08-04
---

# SQLite 数据层设计

> 一个文件就是一个数据库。用 WAL 模式撑起并发读写，用 `threading.local()` 保线程安全。

## 是什么

SQLite 是一个**嵌入式关系型数据库**。不同于 MySQL / PostgreSQL 需要独立安装、独立进程运行，SQLite 直接把数据存在一个 `.db` 文件里，Python 通过标准库 `sqlite3` 直接读写这个文件。

VibeCut 的 `vibecut.db` 文件包含所有项目数据：剧集元数据、索引条目、任务和分段。

## 为什么是 SQLite 而不是 MySQL / PostgreSQL

| 维度 | SQLite | MySQL / PostgreSQL |
|------|--------|-------------------|
| 安装 | Python 自带，零配置 | 需要独立安装服务端 |
| 运维 | 一个文件，备份就是 `cp vibecut.db backup.db` | 需要管理用户、权限、端口 |
| 并发 | 读并发好（WAL），写串行 | 真正的读写并发 |
| 性能 | 百万条以内无压力 | 百万条起步才显优势 |
| 部署 | `python3 server.py` 就搞定 | 需要 docker-compose + 环境变量 |

VibeCut 是个单人使用的桌面级项目，数据量最多几十万条，SQLite 完全够用。选择它的核心理由是：**少一个依赖就少一个问题**。

## 关键概念

### 1. WAL 模式（Write-Ahead Logging）

```sql
PRAGMA journal_mode=WAL;
```

传统 SQLite 的写操作会锁住整个数据库文件 —— 写的时候不能读。WAL 模式改变了这个规则：写操作先写入一个独立的 WAL 文件（`vibecut.db-wal`），读操作继续读主文件。**读写互不阻塞。**

VibeCut 的典型场景：用户在编剧台的搜索操作（读）和 AI 生成脚本后的分段入库（写）可以同时进行，不会互相卡住。

WAL 模式下，数据库实际上由三个文件组成：
```
vibecut.db         ← 主数据库
vibecut.db-wal     ← 预写日志（写操作暂存区）
vibecut.db-shm     ← 共享内存索引（加速 WAL 访问）
```

这三个文件共同工作，对使用者完全透明。

### 2. `threading.local()` — 线程安全的连接管理

```python
import threading

class VibeCutDB:
    def __init__(self, db_path):
        self._db_path = db_path
        self._local = threading.local()  # 每个线程独立的存储空间

    def _get_conn(self):
        # 每个线程第一次调用时创建自己的连接
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row      # 让查询结果可以用列名访问
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")  # 锁等待最多5秒
            self._local.conn = conn
        return self._local.conn
```

为什么不用全局连接池？因为 `ThreadingServer` 下每个 HTTP 请求跑在不同线程里。`threading.local()` 确保每个线程有自己独立的数据库连接，线程之间不会互相干扰 —— 这是 Python 标准库提供的最简洁的线程安全方案。

SQLite 在 WAL 模式下支持一个写者 + 多个读者并发，但**每个线程必须用自己的连接**。如果多个线程共享一个连接，SQLite 会报错或行为异常。

### 3. Schema 设计

VibeCut 的数据模型围绕"项目 → 剧集 → 任务 → 分段"这条主线：

```sql
-- 顶层：注册项目
CREATE TABLE dramas (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,    -- "都挺好" / "杨老师教育"
    slug TEXT
);

-- 第二层：每集的数据质量元数据
CREATE TABLE episodes (
    drama_id INTEGER REFERENCES dramas(id),
    ep_number INTEGER,
    asr_raw_count INTEGER,       -- ASR 原始文本条数
    vlm_scene_count INTEGER,     -- VLM 分析的场景数
    subtitle_count INTEGER,      -- 字幕条数
    indexed BOOLEAN DEFAULT 0,   -- 是否已加入语义索引
    ...
);

-- 第三层：索引条目（BGE 编码后的每条数据）
CREATE TABLE index_entries (
    drama_id INTEGER,
    ep_number INTEGER,
    entry_type TEXT CHECK(entry_type IN ('vlm','asr','sub')),
    start REAL, end REAL,        -- 时间区间
    text TEXT,                    -- 内容文本
    weight REAL DEFAULT 1.0      -- 权重
);

-- 第四层：任务（一个具体的剪辑任务）
CREATE TABLE tasks (
    drama_id INTEGER,
    name TEXT,                    -- "Task7024" / "0801学习新东方"
    status TEXT DEFAULT 'editing',
    segments_count INTEGER       -- 分段数量
);

-- 第五层：任务分段（每个 segment 的数据）
CREATE TABLE task_segments (
    task_id INTEGER REFERENCES tasks(id),
    seg_id INTEGER,
    source_start REAL,            -- 素材起始秒
    source_end REAL,              -- 素材结束秒
    highlight_text TEXT,          -- 高亮文本
    narration_text TEXT,          -- 旁白文本
    ...
);

-- 数据质量报告
CREATE TABLE quality_reports (
    drama_id INTEGER,
    ep_number INTEGER,
    asr_score REAL, vlm_score REAL,
    overall_score REAL            -- 综合质量分
);
```

设计特点：
- **UNIQUE 约束防止重复**：`(drama_id, ep_number)` 不会插入两次
- **级联删除**：删除 drama 时自动清除相关的 episodes / tasks
- **CHECK 约束**：`entry_type` 只能是 `vlm` / `asr` / `sub` 三种
- **索引优化**：在 `(drama_id, ep_number)` 和 `(task_id, seg_id)` 上建了联合索引

## 在 VibeCut 中的应用

**文件位置**：`vibecut-server/db.py`

- 第17-125行：完整 Schema 定义（`SCHEMA_SQL` 字符串）
- 第128-133行：增量迁移（`MIGRATIONS` — 为旧表添加新列）
- 第136-159行：`VibeCutDB.__init__` 和 `_get_conn()`（初始化 + 线程本地连接）

**在 server.py 中的使用**：
- 第11-13行：全局 `db = VibeCutDB("vibecut.db")` 单例
- `/segments.json` 端点：先查 DB → 文件兜底
- `/picks` 端点：读写 picks 数据
- `/data/quality` 端点：质量报告查询

**关键 API**：
- `db.ensure_drama(name)` — 获取或创建项目
- `db.get_task(drama_id, task_name)` — 查询任务
- `db.get_task_segments(task_id)` — 查询分段
- `db.save_picks(drama_id, task_name, picks)` — 保存 picks
- `db.compute_quality_report(drama_id, ep_number, path)` — 质量评分

## 动手实验

1. **用 sqlite3 命令行探索 vibecut.db**

```bash
sqlite3 vibecut.db
.tables              # 看有哪些表
.schema tasks        # 看 tasks 表结构
SELECT * FROM dramas;
SELECT name, status FROM tasks;
```

2. **写一个简单的 Python 脚本感受 threading.local**

```python
import sqlite3, threading

local = threading.local()

def worker(name):
    if not hasattr(local, "conn"):
        local.conn = sqlite3.connect(":memory:")
        print(f"[{name}] 创建新连接: {id(local.conn)}")
    else:
        print(f"[{name}] 复用连接: {id(local.conn)}")

threads = [threading.Thread(target=worker, args=(f"T{i}",)) for i in range(5)]
for t in threads: t.start()
for t in threads: t.join()
# 输出: 5 个线程各创建了 1 个连接，归各自独立持有
```

3. **观察 WAL 文件的生成**

```bash
rm -f test.db test.db-wal test.db-shm
python3 -c "
import sqlite3
conn = sqlite3.connect('test.db')
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('CREATE TABLE t(x)')
conn.execute('INSERT INTO t VALUES(1)')
conn.commit()
"
ls -la test.db*  # 你会看到 test.db-wal 和 test.db-shm
```

## 前置知识

- [[L1-语言与运行时]] — Python sqlite3 模块和 threading 模块
- 基础 SQL — SELECT / INSERT / CREATE TABLE

## 延伸

- [[HTTP服务与SSE流式]] — 服务端如何通过 API 暴露数据库数据
- [[BGE索引实战]] — 索引条目如何入库到 index_entries 表
- [[向量检索与索引]] — 为什么索引数据同时存文件和数据库
