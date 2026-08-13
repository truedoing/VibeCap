#!/usr/bin/env python3
"""F5-TTS 常驻 Worker — stdin/stdout JSON 行协议

协议 (每行一个 JSON):
  ← {"action":"load_model"}  → {"ok":true}
  ← {"action":"infer","ref_audio":"...","ref_text":"...","gen_text":"...","out_path":"..."}
                               → {"ok":true,"duration":4.2,"size":12345}
                               → {"ok":false,"error":"..."}
  ← {"action":"ping"}         → {"pong":true}

用法:
  python3 f5_worker.py    # 启动后从 stdin 读 JSON, 结果写入 stdout

Python 环境: /opt/anaconda3/envs/cosyvoice/bin/python3
"""

import sys, os, json, time, subprocess, signal

MODEL_DIR = "/Users/apple/.cache/modelscope/models/SWivid--F5-TTS_Emilia-ZH-EN/snapshots/master"
CKPT = os.path.join(MODEL_DIR, "model_1250000.safetensors")
VOCAB = os.path.join(MODEL_DIR, "vocab.txt")
N_FE_STEP = 32
SPEED = 1.05
TIMEOUT_PER_STEP = 600  # 每次推理最长 10 分钟

_tts = None


def load_model():
    global _tts
    if _tts is not None:
        return True
    from f5_tts.api import F5TTS
    _tts = F5TTS(
        model='F5TTS_v1_Base',
        ckpt_file=CKPT,
        vocab_file=VOCAB,
        device='cpu',
    )
    return True


def do_infer(ref_audio, ref_text, gen_text, out_path, speed=1.0):
    global _tts
    if _tts is None:
        load_model()

    # 转 16kHz
    ref_16k = "/tmp/_f5_worker_ref_16k.wav"
    subprocess.run(['/opt/anaconda3/bin/ffmpeg', '-y', '-i', ref_audio,
        '-ar', '16000', '-ac', '1', '-sample_fmt', 's16', ref_16k],
        capture_output=True, timeout=30)

    if not os.path.exists(ref_16k):
        return {"ok": False, "error": "ffmpeg 转 16kHz 失败"}

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

    start = time.time()
    _tts.infer(
        ref_file=ref_16k,
        ref_text=ref_text,
        gen_text=gen_text,
        file_wave=out_path,
        cross_fade_duration=0.0,
        speed=speed,
        nfe_step=N_FE_STEP,
        remove_silence=False,
    )
    elapsed = time.time() - start

    dur = float(subprocess.run(['/opt/anaconda3/bin/ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', out_path],
        capture_output=True, text=True, timeout=10).stdout.strip())
    size = os.path.getsize(out_path)

    return {"ok": True, "duration": dur, "elapsed": elapsed, "size": size}


def main():
    # 关键: 重定向 stdout 为 stderr, 让 C 库的 print 不污染 JSON 协议
    # 真正的 JSON 结果写入 sys.stdout.buffer 底层 fd
    real_stdout = os.fdopen(os.dup(1), 'w', buffering=1)  # fd 1 的副本
    sys.stdout = sys.stderr  # C 扩展的 print → stderr (日志)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        action = msg.get("action", "")

        if action == "ping":
            real_stdout.write(json.dumps({"pong": True}) + "\n")
            real_stdout.flush()
        elif action == "load_model":
            try:
                load_model()
                real_stdout.write(json.dumps({"ok": True}) + "\n")
                real_stdout.flush()
            except Exception as e:
                real_stdout.write(json.dumps({"ok": False, "error": str(e)[:200]}) + "\n")
                real_stdout.flush()
        elif action == "infer":
            try:
                result = do_infer(
                    ref_audio=msg["ref_audio"],
                    ref_text=msg.get("ref_text", msg.get("gen_text", "")),
                    gen_text=msg["gen_text"],
                    out_path=msg["out_path"],
                    speed=msg.get("speed", SPEED),
                )
                real_stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
                real_stdout.flush()
            except Exception as e:
                real_stdout.write(json.dumps({"ok": False, "error": str(e)[:300]}) + "\n")
                real_stdout.flush()
        elif action == "quit":
            break

    sys.exit(0)


if __name__ == "__main__":
    main()
