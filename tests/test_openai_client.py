"""Tests for openai_client helpers: equivalence to the old inline gguf logic,
payload/header contracts, and error aggregation."""

import json
import re

import httpx
import pytest

import openai_client
from openai_client import (
    build_user_content,
    chat_completion,
    chat_completion_stream,
    strip_think,
    strip_turn_markers,
)


# Reference copy of the old inline logic from GGUFLLMDirect.generate() —
# strip_think must produce byte-identical output.
def _old_strip_think(text):
    if "</think>" in text:
        text = text.split("</think>", 1)[-1]
    elif "<|channel|>final<|message|>" in text:
        text = text.split("<|channel|>final<|message|>", 1)[-1]
    elif "<channel|>" in text:
        text = text.split("<channel|>", 1)[-1]
    return text


# Old inline marker stripping: same regex, same flags, same trailing strip.
_OLD_MARKER_RE = r"<\|?end_of_turn\|?>|<\|?end_turn\|?>|\|end_of_turn\||_?end_of_turn|_?end_turn"


def _old_strip_markers(text):
    return re.sub(_OLD_MARKER_RE, "", text, flags=re.IGNORECASE).strip()


# (input, expected) pairs derived from the old elif order:
# </think> first, then <|channel|>final<|message|>, then <channel|>.
STRIP_THINK_CORPUS = [
    # LFM2.5: bare reasoning terminated by </think>.
    ("思考</think>回答", "回答"),
    # Qwen-style <think>...</think> wrapper: everything before </think> dies,
    # so the leading text goes with it.
    ("文<think>思考</think>回答", "回答"),
    # GPT-OSS channel format: only the final<|message|> channel survives.
    ("前<|channel|>analysis 思考</channel|><|channel|>final<|message|>回答", "回答"),
    # Gemma 4 closes its thought block with <channel|> (reversed form).
    ("思考<channel|>回答", "回答"),
    # </think> present means the elif branches never run.
    ("思考</think>回答<|channel|>final<|message|>後", "回答<|channel|>final<|message|>後"),
    # No marker: passthrough.
    ("ただのテキスト", "ただのテキスト"),
]


@pytest.mark.parametrize("text,expected", STRIP_THINK_CORPUS)
def test_strip_think_corpus(text, expected):
    assert strip_think(text) == expected


@pytest.mark.parametrize("text", [t for t, _ in STRIP_THINK_CORPUS] + ["", "<think>思考</think>"])
def test_strip_think_matches_old_inline(text):
    assert strip_think(text) == _old_strip_think(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a<|end_of_turn|>b", "ab"),
        ("a<end_of_turn>b", "ab"),
            ("a|end_of_turn|b", "ab"),
            # \|end_turn\| (piped) is NOT in the pattern — only \|end_of_turn\|
            # is — so |end_turn| keeps its pipes, exactly like the old code.
            ("a|end_turn|b", "a||b"),
            ("a<|END_OF_TURN|>b", "ab"),
            (" a<|end_of_turn|>b ", "ab"),
            # Removal never introduces spaces; only literal marker text dies.
            ("a<|end_of_turn|>b c", "ab c"),
    ],
)
def test_strip_turn_markers(text, expected):
    assert strip_turn_markers(text) == expected


def test_strip_turn_markers_matches_old_inline():
    for text in ["a<|end_of_turn|>b", "x<end_turn>y", "q|end_of_turn|r", "s_end_turn t", "u<|End_Turn|>v", "マーカーなし"]:
        assert strip_turn_markers(text) == _old_strip_markers(text)


def test_build_user_content_inject_shape():
    assert build_user_content("9:16", 10, "hello", True) == "resolution: 9:16\nduration: 10s\noriginal_prompt: hello"


def test_build_user_content_empty_input():
    assert build_user_content("9:16", 10, "", True) == "resolution: 9:16\nduration: 10s"


def test_build_user_content_whitespace_input():
    assert build_user_content("9:16", 10, "   ", True) == "resolution: 9:16\nduration: 10s"


def test_build_user_content_no_inject():
    assert build_user_content("9:16", 10, "hello", False) == "hello"
    assert build_user_content("9:16", 10, "", False) == ""


def _ok_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_handler(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})


def test_chat_completion_ok():
    client = _ok_client(_ok_handler)
    assert chat_completion(client, "http://x:8080/v1", "m", [{"role": "user", "content": "q"}]) == "answer"


def test_chat_completion_api_error():
    client = _ok_client(lambda req: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(ValueError, match="api-llm-direct: API error 400"):
        chat_completion(client, "http://x:8080/v1", "m", [])


def test_chat_completion_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("connect timed out")

    client = _ok_client(handler)
    with pytest.raises(ValueError, match="api-llm-direct: request failed"):
        chat_completion(client, "http://x:8080/v1", "m", [])


def test_chat_completion_content_none():
    client = _ok_client(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}))
    with pytest.raises(ValueError, match="no content"):
        chat_completion(client, "http://x:8080/v1", "m", [])


def test_chat_completion_bad_shape():
    client = _ok_client(lambda req: httpx.Response(200, json={"choices": []}))
    with pytest.raises(ValueError, match="unexpected response"):
        chat_completion(client, "http://x:8080/v1", "m", [])


def _capture():
    seen = {}

    def handler(request):
        seen["body"] = request.read().decode()
        seen["headers"] = request.headers
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    return handler, seen


def test_chat_completion_seed_sent():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], seed=42)
    assert json.loads(seen["body"])["seed"] == 42


def test_chat_completion_seed_zero_omitted():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], seed=0)
    assert "seed" not in json.loads(seen["body"])


def test_chat_completion_api_key_header(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], api_key="k")
    assert seen["headers"]["Authorization"] == "Bearer k"


def test_chat_completion_no_auth_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [])
    assert "Authorization" not in seen["headers"]


def test_chat_completion_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "envk")
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [])
    assert seen["headers"]["Authorization"] == "Bearer envk"


def test_chat_completion_trailing_slash_url():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1/", "m", [])
    assert seen["url"] == "http://x:8080/v1/chat/completions"


def test_chat_completion_thinking_disabled():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], enable_thinking=False)
    assert json.loads(seen["body"])["thinking"] == {"type": "disabled"}


def test_chat_completion_reasoning_effort():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], reasoning_effort="high")
    assert json.loads(seen["body"])["reasoning_effort"] == "high"


def test_chat_completion_thinking_disabled_wins_over_effort():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [], enable_thinking=False, reasoning_effort="high")
    body = json.loads(seen["body"])
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_chat_completion_defaults_add_no_fields():
    handler, seen = _capture()
    client = _ok_client(handler)
    chat_completion(client, "http://x:8080/v1", "m", [])
    body = json.loads(seen["body"])
    assert "thinking" not in body
    assert "reasoning_effort" not in body


def _sse_response(*events):
    body = "\n\n".join(f"data: {json.dumps(e)}" for e in events) + "\n\n"
    return httpx.Response(200, content=body.encode())


def _stream_capture():
    seen = {}

    def handler(request):
        seen["body"] = request.read().decode()
        return _sse_response({"choices": [{"delta": {"content": "x"}, "index": 0}]})

    return handler, seen


def test_chat_completion_stream_accumulates():
    events = [
        {"choices": [{"delta": {"role": "assistant"}, "index": 0}]},
        {"choices": [{"delta": {"content": "Hello"}, "index": 0}]},
        {"choices": [{"delta": {"content": " world"}, "index": 0}]},
        {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks = []
    result = chat_completion_stream(client, "http://x:8080/v1", "m", [], on_chunk=chunks.append)
    assert result == "Hello world"
    assert chunks == ["Hello", "Hello world"]


def test_chat_completion_stream_skips_reasoning():
    events = [
        {"choices": [{"delta": {"reasoning_content": "hidden"}, "index": 0}]},
        {"choices": [{"delta": {"content": "answer"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks = []
    result = chat_completion_stream(client, "http://x:8080/v1", "m", [], on_chunk=chunks.append)
    assert result == "answer"
    assert chunks == ["answer"]


def test_chat_completion_stream_role_only_no_chunk():
    events = [
        {"choices": [{"delta": {"role": "assistant"}, "index": 0}]},
        {"choices": [{"delta": {"content": "x"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks = []
    chat_completion_stream(client, "http://x:8080/v1", "m", [], on_chunk=chunks.append)
    assert chunks == ["x"]


def test_chat_completion_stream_api_error():
    client = _ok_client(lambda req: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(ValueError, match="api-llm-direct: API error 400"):
        chat_completion_stream(client, "http://x:8080/v1", "m", [])


def test_chat_completion_stream_split_events():
    events = [
        {"choices": [{"delta": {"content": "Hello"}, "index": 0}]},
        {"choices": [{"delta": {"content": " world"}, "index": 0}]},
        {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]},
    ]
    payload = ("\n\n".join(f"data: {json.dumps(e)}" for e in events) + "\n\n").encode()
    half = len(payload) // 2
    client = _ok_client(
        lambda req: httpx.Response(200, content=iter([payload[:half], payload[half:]]))
    )
    chunks = []
    result = chat_completion_stream(client, "http://x:8080/v1", "m", [], on_chunk=chunks.append)
    assert result == "Hello world"
    assert chunks == ["Hello", "Hello world"]


def test_chat_completion_stream_thinking_disabled():
    handler, seen = _stream_capture()
    client = _ok_client(handler)
    chat_completion_stream(client, "http://x:8080/v1", "m", [], enable_thinking=False)
    assert json.loads(seen["body"])["thinking"] == {"type": "disabled"}


def test_chat_completion_stream_seed_sent():
    handler, seen = _stream_capture()
    client = _ok_client(handler)
    chat_completion_stream(client, "http://x:8080/v1", "m", [], seed=42)
    assert json.loads(seen["body"])["seed"] == 42


def test_chat_completion_stream_reasoning_only():
    events = [
        {"choices": [{"delta": {"reasoning_content": "a"}, "index": 0}]},
        {"choices": [{"delta": {"reasoning_content": "b"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks, thoughts = [], []
    result = chat_completion_stream(
        client, "http://x:8080/v1", "m", [], on_chunk=chunks.append, on_reasoning=thoughts.append
    )
    assert result == ""
    assert chunks == []
    assert thoughts == ["a", "ab"]


def test_chat_completion_stream_reasoning_then_content():
    events = [
        {"choices": [{"delta": {"reasoning_content": "think"}, "index": 0}]},
        {"choices": [{"delta": {"content": "answer"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks, thoughts = [], []
    result = chat_completion_stream(
        client, "http://x:8080/v1", "m", [], on_chunk=chunks.append, on_reasoning=thoughts.append
    )
    assert result == "answer"
    assert chunks == ["answer"]
    assert thoughts == ["think"]


def test_chat_completion_stream_no_reasoning():
    events = [
        {"choices": [{"delta": {"content": "plain"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    thoughts = []
    result = chat_completion_stream(
        client, "http://x:8080/v1", "m", [], on_reasoning=thoughts.append
    )
    assert result == "plain"
    assert thoughts == []


def test_chat_completion_stream_reasoning_and_content_mixed():
    events = [
        {"choices": [{"delta": {"reasoning_content": "think", "content": "ans"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    chunks, thoughts = [], []
    result = chat_completion_stream(
        client, "http://x:8080/v1", "m", [], on_chunk=chunks.append, on_reasoning=thoughts.append
    )
    assert result == "ans"
    assert chunks == ["ans"]
    assert thoughts == ["think"]


def test_chat_completion_stream_empty_reasoning_skipped():
    events = [
        {"choices": [{"delta": {"reasoning_content": ""}, "index": 0}]},
        {"choices": [{"delta": {"content": "x"}, "index": 0}]},
    ]
    client = _ok_client(lambda req: _sse_response(*events))
    thoughts = []
    result = chat_completion_stream(
        client, "http://x:8080/v1", "m", [], on_reasoning=thoughts.append
    )
    assert result == "x"
    assert thoughts == []


def test_chat_completion_stream_request_failed():
    def handler(request):
        raise httpx.ConnectTimeout("connect timed out")

    client = _ok_client(handler)
    with pytest.raises(ValueError, match="api-llm-direct: request failed: ConnectTimeout"):
        chat_completion_stream(client, "http://x:8080/v1", "m", [])


def test_chat_completion_stream_unexpected_response():
    body = "data: {not json}\n\n".encode()
    client = _ok_client(lambda req: httpx.Response(200, content=body))
    with pytest.raises(ValueError, match="api-llm-direct: unexpected response"):
        chat_completion_stream(client, "http://x:8080/v1", "m", [])

# --- build_messages multimodal ----------------------------------------------


def test_build_messages_with_image_uris():
    messages = openai_client.build_messages(
        "システム", "リクエスト", "9:16", 10, True,
        image_uris=["data:image/png;base64,AAA"],
    )
    assert messages == [
        {"role": "system", "content": "システム"},
        {"role": "user", "content": [
            {"type": "text", "text": "resolution: 9:16\nduration: 10s\noriginal_prompt: リクエスト"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]},
    ]


def test_build_messages_empty_uris_keeps_string():
    # 後方互換: 空リストなら従来どおり str
    messages = openai_client.build_messages("", "hi", "9:16", 10, False, image_uris=[])
    assert messages == [{"role": "user", "content": "hi"}]
