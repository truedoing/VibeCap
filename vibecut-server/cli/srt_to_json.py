"""SRT → subtitle_result.json 转换脚本

把 46 集标准 SRT 字幕转成与 asr_result.json 同构的 [{start, end, text}]，
落盘到 sources/epN/subtitle_result.json（不覆盖 asr_result.json）。

SRT 数据质量优于 whisper ASR（人名/名场面台词准确，时间戳精确到毫秒），
后续关键消费点应优先读 subtitle_result.json。

用法:
  cd vibecut-server
  /opt/anaconda3/bin/python3 cli/srt_to_json.py
"""
import json
import re
import sys
from pathlib import Path

BASE = Path("/Users/zgl/VIBECAP/都挺好")
SUBTITLE_DIR = BASE / "subtitle"
SOURCES_DIR = BASE / "sources"

# SRT 时间码: 00:01:09,166 --> 00:01:10,538
_TIME_PAT = re.compile(r"(\d+):(\d+):(\d+),(\d+)")

# 片头广告/水印行，跳过
_SKIP_PREFIXES = ("感谢订阅", "CN DRAMA", "中剧独播")


def parse_srt(path: Path) -> list:
    """解析单个 SRT 文件 → [{start, end, text}]（秒，浮点）"""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.split("\n")

    result = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        # 时间码行
        m = _TIME_PAT.search(line)
        if m and "-->" in line:
            h1, m1, s1, ms1 = map(int, m.groups()[:4])
            # 结束时间码在 --> 后
            rest = line.split("-->", 1)[1]
            m2 = _TIME_PAT.search(rest)
            start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
            if m2:
                h2, m2_, s2, ms2 = map(int, m2.groups()[:4])
                end = h2 * 3600 + m2_ * 60 + s2 + ms2 / 1000
            else:
                end = start + 2.0
            # 下一行是字幕文本
            if i + 1 < n:
                text = lines[i + 1].strip()
                if text and not text.startswith(_SKIP_PREFIXES):
                    result.append({"start": round(start, 2), "end": round(end, 2), "text": text})
            i += 2
        else:
            i += 1
    return result


def main():
    srt_files = sorted(SUBTITLE_DIR.glob("*.srt"))
    if not srt_files:
        print("未找到 SRT 文件，目录:", SUBTITLE_DIR)
        sys.exit(1)

    print(f"找到 {len(srt_files)} 个 SRT 文件")
    converted = 0
    for srt in srt_files:
        # 从文件名提取集号: S01E41 → 41
        m = re.search(r"S01E(\d+)", srt.name)
        if not m:
            print(f"  ⚠️ 无法解析集号: {srt.name}")
            continue
        ep = int(m.group(1))
        segs = parse_srt(srt)
        if not segs:
            print(f"  ⚠️ EP{ep}: 解析为空")
            continue

        out_dir = SOURCES_DIR / f"ep{ep}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "subtitle_result.json"
        json.dump(segs, open(out_file, "w"), ensure_ascii=False, indent=2)
        converted += 1
        print(f"  ✅ EP{ep}: {len(segs)} 条 → {out_file.relative_to(BASE)}")

    print(f"\n完成: {converted}/{len(srt_files)} 集已转换")


if __name__ == "__main__":
    main()
