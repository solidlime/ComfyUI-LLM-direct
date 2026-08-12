"""Pure-logic helpers for OpenAI-compatible chat APIs.

No ComfyUI imports: this module stays unit-testable in isolation. Shared by
the openai-direct node and, for the stripping helpers, gguf-direct.
"""

import os
import re

import httpx


def strip_think(text):
    # LFM2.5 emits bare reasoning terminated by </think>; Qwen-style
    # models wrap it in <think>...</think>; GPT-OSS uses
    # <|channel|>analysis...<|channel|>final<|message|>; Gemma 4
    # closes its thought block with <channel|> (reversed form). All
    # collapse to: keep only the final answer part.
    if "</think>" in text:
        text = text.split("</think>", 1)[-1]
    elif "<|channel|>final<|message|>" in text:
        text = text.split("<|channel|>final<|message|>", 1)[-1]
    elif "<channel|>" in text:
        text = text.split("<channel|>", 1)[-1]
    return text


def strip_turn_markers(text):
    # Strip end/start-of-turn markers the model emitted; keep everything else.
    return re.sub(r"<\|?end_of_turn\|?>|<\|?end_turn\|?>|\|end_of_turn\||_?end_of_turn|_?end_turn", "", text, flags=re.IGNORECASE).strip()


def build_user_content(resolution, duration, user_input, inject_shape):
    # Same injection format as pytraveler's writer nodes: shape constraints
    # live at the top of the user turn, the request follows as original_prompt.
    if inject_shape:
        content = f"resolution: {resolution}\nduration: {int(duration)}s"
        if user_input.strip():
            content += f"\noriginal_prompt: {user_input}"
    else:
        content = user_input
    return content


def chat_completion(client, base_url, model, messages, api_key="", temperature=0.6,
                    top_p=0.9, max_tokens=4096, seed=0, enable_thinking=True,
                    reasoning_effort="auto"):
    url = f"{base_url.rstrip('/')}/chat/completions"
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if seed > 0:
        payload["seed"] = seed
    if not enable_thinking:
        payload["thinking"] = {"type": "disabled"}
    elif reasoning_effort != "auto":
        payload["reasoning_effort"] = reasoning_effort
    try:
        resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        # Keep the message generic: never leak URL, headers or request body.
        raise ValueError(f"openai-direct: request failed: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise ValueError(f"openai-direct: API error {resp.status_code}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("openai-direct: unexpected response") from None
    if content is None:
        # o-series models can spend all tokens on reasoning and return no
        # visible text; raise max_tokens or disable thinking in that case.
        raise ValueError(
            "openai-direct: no content in response (model may have consumed "
            "all tokens on reasoning; raise max_tokens or disable thinking)"
        )
    return content
