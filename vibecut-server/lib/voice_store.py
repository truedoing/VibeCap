"""全局音色库 — 预设音色 + 克隆音色（跨项目共享）

克隆音色持久化到 GLOBAL_VOICES_DIR/voices.json，参考音频存 GLOBAL_VOICES_DIR/ref_*.wav。
"""
import json
from pathlib import Path

from config import GLOBAL_VOICES_DIR
from tts_engine import PRESET_VOICES


def _registry_path() -> Path:
    return GLOBAL_VOICES_DIR / "voices.json"


def list_voices() -> list[dict]:
    """返回所有可用音色（预设 + 克隆），按名称排序。

    克隆音色条目：{"name", "label", "kind": "clone", "ref_audio", "ref_text"}
    预设音色条目：{"name", "label", "kind": "preset"}
    """
    presets = [{"name": name, "label": v.get("label", name), "kind": "preset"}
               for name, v in PRESET_VOICES.items()]
    clones = []
    registry = _registry_path()
    if registry.exists():
        try:
            data = json.load(open(registry))
            for entry in data.get("voices", []):
                name = entry.get("name", "")
                if not name:
                    continue
                clones.append({
                    "name": name,
                    "label": entry.get("label", name),
                    "kind": "clone",
                    "ref_audio": entry.get("ref_audio", ""),
                    "ref_text": entry.get("ref_text", ""),
                })
        except Exception:
            pass
    return presets + clones


def create_clone_voice(name: str, ref_audio: str, ref_text: str = "") -> dict:
    """新建克隆音色（全局共享）。ref_audio 为参考音频的本地绝对路径。

    Returns:
        {"ok": True, "voice": {...}}
        {"ok": False, "error": str}
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "音色名不能为空"}
    if not ref_audio or not Path(ref_audio).exists():
        return {"ok": False, "error": f"参考音频不存在: {ref_audio}"}

    GLOBAL_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    registry = _registry_path()
    data = {"voices": []}
    if registry.exists():
        try:
            data = json.load(open(registry))
        except Exception:
            data = {"voices": []}

    # 同名覆盖
    data["voices"] = [v for v in data.get("voices", []) if v.get("name") != name]
    entry = {
        "name": name,
        "label": name,
        "ref_audio": str(Path(ref_audio).resolve()),
        "ref_text": (ref_text or "").strip(),
    }
    data["voices"].append(entry)
    json.dump(data, open(registry, "w"), ensure_ascii=False, indent=2)
    return {"ok": True, "voice": {"name": name, "label": name, "kind": "clone",
                                  "ref_audio": entry["ref_audio"], "ref_text": entry["ref_text"]}}


def resolve_voice_ref(voice: str) -> tuple[str | None, str | None]:
    """根据音色名解析 (ref_audio_path, ref_text)。

    预设音色返回 (None, None)；克隆音色返回 (ref_audio, ref_text)。
    未知音色返回 (None, None)（按预设音色名直接传给 MiMo）。
    """
    registry = _registry_path()
    if not registry.exists():
        return None, None
    try:
        data = json.load(open(registry))
        for entry in data.get("voices", []):
            if entry.get("name") == voice:
                return entry.get("ref_audio"), entry.get("ref_text", "")
    except Exception:
        pass
    return None, None
