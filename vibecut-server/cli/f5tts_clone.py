#!/usr/bin/env python3
"""F5-TTS 零样本声音克隆测试
用 narr_000.wav 做参考音频，克隆音色后生成新解说词

模型: /Users/apple/.cache/modelscope/... (本地，从 ModelScope 下载)
"""
import sys, os, time, subprocess
import warnings
warnings.filterwarnings("ignore")

# 强制 CPU（Intel Mac 没有 Apple Silicon MPS，也没有 CUDA）
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# 先 import torch，禁用 MPS
import torch
# 如果 MPS 可用但我们在 Intel Mac 上，强制禁用
if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    # Intel Mac MPS 后端不支持 ComplexFloat
    torch.backends.mps.is_available = lambda: False

# 修复 torchaudio + multiprocessing spawn 导致的 PYTHONHASHSEED 问题
import multiprocessing as mp
try:
    mp.set_start_method("fork")
except RuntimeError:
    pass

# 本地模型路径（从 ModelScope 下载）
MODEL_DIR = "/Users/apple/.cache/modelscope/models/SWivid--F5-TTS_Emilia-ZH-EN/snapshots/master"
CKPT_FILE = os.path.join(MODEL_DIR, "model_1250000.safetensors")
VOCAB_FILE = os.path.join(MODEL_DIR, "vocab.txt")

# 输入输出
REF_AUDIO_48K = "/Users/zgl/VibeCut/都挺好/tasks/Task7024/work_dir/tts_segments/narr_000.wav"
REF_AUDIO_16K = "/tmp/narr_000_16k.wav"  # F5-TTS 需要 16kHz
OUT_PATH     = "/Users/zgl/VibeCut/都挺好/tasks/Task7024/work_dir/cloned_f5tts.wav"

# 参考音频对应原文
REF_TEXT = (
    "蒙总为了公司顺利上市，决定清理公司那些光拿钱不干活的亲戚，"
    "结果遭到了蒙太的激烈反对。蒙太直接以离婚相要挟，逼迫老蒙交出"
    "一半股权，那公司上市的计划就泡汤了。"
)
# 测试文本：含多音字，方便与原音频对比
TEST_TEXT = (
    "蒙总为了公司顺利上市，决定清理公司那些光拿钱不干活的亲戚，"
    "结果遭到了蒙太的激烈反对。蒙太直接以离婚相要挟，逼迫老蒙交出"
    "一半股权。"
)

print("=" * 60)
print("🎤 F5-TTS 零样本声音克隆测试")
print(f"   模型: {CKPT_FILE}")
print(f"   参考音频: {REF_AUDIO_48K}")
print(f"   测试文本: {TEST_TEXT[:50]}...")
print("=" * 60)

# Step 1: 将参考音频转为 16kHz 单声道
print("\n🔧 转换参考音频为 16kHz...")
subprocess.run([
    "/opt/anaconda3/bin/ffmpeg", "-y", "-i", REF_AUDIO_48K,
    "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
    REF_AUDIO_16K
], capture_output=True)
print(f"   已保存: {REF_AUDIO_16K}")

# Step 2: 加载模型
print("\n⏳ 加载模型...")
start = time.time()

from f5_tts.api import F5TTS

tts = F5TTS(
    model="F5TTS_v1_Base",
    ckpt_file=CKPT_FILE,
    vocab_file=VOCAB_FILE,
    device="cpu",
)
print(f"✅ 模型加载完成 ({time.time() - start:.0f}s)")

# Step 3: 声音克隆 + 合成
print("\n🎧 开始声音克隆 + 合成 (CPU 推理，耐心等待)...")
start = time.time()

tts.infer(
    ref_file=REF_AUDIO_16K,
    ref_text=REF_TEXT,
    gen_text=TEST_TEXT,
    file_wave=OUT_PATH,
    cross_fade_duration=0.0,
    speed=1.0,
    nfe_step=16,         # 降步数加速测试（32更好但慢一倍）
    remove_silence=False,
)

elapsed = time.time() - start
size_kb = os.path.getsize(OUT_PATH) / 1024
print(f"✅ 合成完成 ({elapsed:.0f}s, {size_kb:.0f}KB)")
print(f"📁 输出: {OUT_PATH}")
