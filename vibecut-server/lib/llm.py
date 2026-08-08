"""统一 LLM API 调用 — 消除 10 种重复实现"""

import json
import os
import time
import urllib.request as _ur
from typing import Optional


def _call(
    system_prompt: str,
    user_content: str,
    *,
    model: str = "moonshot-v1-8k",
    api_key_env: str = "MOONSHOT_API_KEY",
    api_url_env: str = "MOONSHOT_API_URL",
    default_url: str = "https://api.moonshot.cn/v1",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: int = 60,
    retries: int = 3,
    retry_delay: float = 3.0,
    label: str = "llm",
) -> dict:
    """统一 LLM 调用：Moonshot / MiMo 通用

    Returns:
        {"ok": True, "content": str} or {"ok": False, "error": str}
    """
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        return {"ok": False, "error": f"未配置 {api_key_env}"}

    api_url = os.environ.get(api_url_env, default_url)
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    for attempt in range(retries):
        try:
            req = _ur.Request(
                f"{api_url}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with _ur.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            # 清理 markdown 代码块
            if text.startswith("```"):
                text = text.split("\n", 1)[1].split("```")[0].strip()
            return {"ok": True, "content": text}
        except Exception as e:
            print(f"  [{label}] attempt {attempt + 1}/{retries} failed: {e}")
            if attempt == retries - 1:
                return {"ok": False, "error": str(e)[:200]}
            time.sleep(retry_delay)

    return {"ok": False, "error": "unknown"}


def call_json(
    system_prompt: str,
    user_content: str,
    *,
    model: str = "moonshot-v1-8k",
    api_key_env: str = "MOONSHOT_API_KEY",
    api_url_env: str = "MOONSHOT_API_URL",
    default_url: str = "https://api.moonshot.cn/v1",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: int = 60,
    retries: int = 3,
    label: str = "llm",
) -> dict:
    """调用 LLM 并解析 JSON 返回

    Returns:
        {"ok": True, "data": <parsed_json>} or {"ok": False, "error": str}
    """
    result = _call(
        system_prompt=system_prompt,
        user_content=user_content,
        model=model,
        api_key_env=api_key_env,
        api_url_env=api_url_env,
        default_url=default_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        retries=retries,
        label=label,
    )
    if not result["ok"]:
        return result

    text = result["content"]
    try:
        return {"ok": True, "data": json.loads(text)}
    except json.JSONDecodeError:
        # 尝试修复截断的 JSON
        lines = text.split("\n")
        for trim in range(1, min(20, len(lines))):
            fixed = "\n".join(lines[:-trim])
            if fixed.rstrip().endswith("}") or fixed.rstrip().endswith("]"):
                try:
                    data = json.loads(
                        fixed
                        + ("}" if fixed.count("{") > fixed.count("}") else "")
                        + ("]" if fixed.count("[") > fixed.count("]") else "")
                    )
                    return {"ok": True, "data": data}
                except json.JSONDecodeError:
                    continue
        return {"ok": False, "error": f"JSON 解析失败: {text[:200]}", "raw": text[:500]}


# ── 便捷封装 ──

def call_moonshot(system: str, user: str, **kwargs) -> dict:
    """调用 Moonshot (DeepSeek) API"""
    return _call(system, user, model="moonshot-v1-8k",
                 api_key_env="MOONSHOT_API_KEY",
                 default_url="https://api.moonshot.cn/v1", **kwargs)


def call_moonshot_json(system: str, user: str, **kwargs) -> dict:
    """调用 Moonshot API + 解析 JSON"""
    return call_json(system, user, model="moonshot-v1-8k",
                     api_key_env="MOONSHOT_API_KEY",
                     default_url="https://api.moonshot.cn/v1", **kwargs)


def call_mimo(system: str, user: str, **kwargs) -> dict:
    """调用 MiMo API"""
    return _call(system, user, model="mimo-v2.5",
                 api_key_env="MIMO_API_KEY",
                 api_url_env="MIMO_API_URL",
                 default_url="https://api.xiaomimimo.com/v1", **kwargs)
