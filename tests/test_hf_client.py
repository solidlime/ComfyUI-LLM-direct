"""Tests for hf_client helpers using fakes — no transformers/torch needed.

A fake torch is injected into sys.modules before importing hf_client so the
lazy `import torch` picks it up; real torch is never required.
"""

import queue
import sys

import pytest


class FakeTorch:
    def __init__(self):
        self.manual_seeds = []

    def manual_seed(self, seed):
        self.manual_seeds.append(seed)


sys.modules["torch"] = FakeTorch()

import hf_client  # noqa: E402
import openai_client  # noqa: E402


class FakeStreamer:
    STOP = object()

    def __init__(self):
        self.queue = queue.Queue()

    def on_finalized_text(self, text):
        self.queue.put(text)

    def end(self):
        self.queue.put(self.STOP)

    def __iter__(self):
        while True:
            item = self.queue.get()
            if item is self.STOP:
                return
            yield item


class FakeModel:
    def __init__(self, error=None):
        self.error = error
        self.kwargs: dict = {}

    def generate(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        for piece in ("思考", "中", "</think>", "回答"):
            kwargs["streamer"].on_finalized_text(piece)


class FakeTensor:
    device = "cpu"


class FakeTokenizer:
    def __init__(self, return_dict=False):
        self.calls = []
        self.return_dict = return_dict

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.return_dict:
            return {"input_ids": "ids", "attention_mask": "mask"}
        return "tokenized-inputs"


# --- build_inputs ---------------------------------------------------------


def test_build_inputs_calls_apply_chat_template():
    tokenizer = FakeTokenizer()
    messages = [{"role": "user", "content": "hi"}]
    result = hf_client.build_inputs(tokenizer, messages)
    assert result == "tokenized-inputs"
    assert tokenizer.calls[0][0] == messages
    assert tokenizer.calls[0][1] == {
        "tokenize": True,
        "return_dict": True,
        "add_generation_prompt": True,
    }


def test_build_inputs_return_dict_when_supported():
    tok = FakeTokenizer(return_dict=True)
    result = hf_client.build_inputs(tok, [{"role": "user", "content": "hi"}])
    assert result == {"input_ids": "ids", "attention_mask": "mask"}
    assert tok.calls[0][1]["return_dict"] is True


def test_build_inputs_falls_back_without_return_dict():
    class NoDictTok(FakeTokenizer):
        def apply_chat_template(self, messages, **kwargs):
            if kwargs.get("return_dict"):
                raise TypeError("unexpected keyword")
            return super().apply_chat_template(messages, **kwargs)

    tok = NoDictTok()
    result = hf_client.build_inputs(tok, [{"role": "user", "content": "hi"}])
    assert result == "tokenized-inputs"
    assert tok.calls[-1][1]["return_tensors"] == "pt"


# --- run_generate ---------------------------------------------------------


def test_run_generate_dict_inputs_expanded():
    model = FakeModel()
    streamer = FakeStreamer()
    hf_client.run_generate(model, {"input_ids": "ids", "attention_mask": "mask"},
                           streamer, 100, 0.6, 0.9, 0)
    assert model.kwargs["input_ids"] == "ids"
    assert model.kwargs["attention_mask"] == "mask"


def test_run_generate_accumulates_text_and_calls_on_text():
    model = FakeModel()
    streamer = FakeStreamer()
    seen = []
    text = hf_client.run_generate(model, FakeTensor(), streamer, 100, 0.6, 0.9, 0,
                                  on_text=seen.append)
    assert text == "思考中</think>回答"
    assert seen == ["思考", "思考中", "思考中</think>", "思考中</think>回答"]


def _reset_fake_torch():
    torch_ = sys.modules["torch"]
    torch_.manual_seeds.clear()
    return torch_


def test_run_generate_seed_calls_manual_seed():
    model = FakeModel()
    streamer = FakeStreamer()
    torch_ = _reset_fake_torch()
    hf_client.run_generate(model, FakeTensor(), streamer, 100, 0.6, 0.9, 42)
    assert torch_.manual_seeds == [42]
    assert "generator" not in model.kwargs


def test_run_generate_seed_zero_skips_manual_seed():
    model = FakeModel()
    streamer = FakeStreamer()
    torch_ = _reset_fake_torch()
    hf_client.run_generate(model, FakeTensor(), streamer, 100, 0.6, 0.9, 0)
    assert torch_.manual_seeds == []
    assert "generator" not in model.kwargs


def test_run_generate_zero_temperature_is_greedy():
    model = FakeModel()
    streamer = FakeStreamer()
    hf_client.run_generate(model, FakeTensor(), streamer, 100, 0.0, 0.9, 0)
    assert model.kwargs["do_sample"] is False
    assert "temperature" not in model.kwargs


def test_run_generate_positive_temperature_samples():
    model = FakeModel()
    streamer = FakeStreamer()
    hf_client.run_generate(model, FakeTensor(), streamer, 100, 0.6, 0.9, 0)
    assert model.kwargs["do_sample"] is True
    assert model.kwargs["temperature"] == 0.6


def test_run_generate_thread_error_becomes_valueerror():
    streamer = FakeStreamer()
    with pytest.raises(ValueError, match="hf-llm-direct: generation failed: RuntimeError"):
        hf_client.run_generate(FakeModel(error=RuntimeError("oom")), "ids", streamer,
                               100, 0.6, 0.9, 0)


# --- split_before_think_end -----------------------------------------------


def _old_split_before_think_end(text):
    shown = text
    for end in ("</think>", "<|channel|>final<|message|>", "<channel|>"):
        if end in shown:
            shown = shown.split(end, 1)[0]
            break
    return shown


_CORPUS = [
    "思考</think>回答",
    "文<think>思考</think>回答",
    "前<|channel|>analysis 思考</channel|><|channel|>final<|message|>回答",
    "思考<channel|>回答",
    "思考</think>回答<|channel|>final<|message|>後",
    "マーカーなしテキスト",
    "",
]


@pytest.mark.parametrize("text", _CORPUS)
def test_split_before_think_end_matches_old_inline(text):
    assert openai_client.split_before_think_end(text) == _old_split_before_think_end(text)


@pytest.mark.parametrize(("text", "expected"), [
    ("思考</think>回答", "思考"),
    ("文<think>思考</think>回答", "文<think>思考"),
    ("前<|channel|>analysis 思考</channel|><|channel|>final<|message|>回答", "前<|channel|>analysis 思考</channel|>"),
    ("思考<channel|>回答", "思考"),
    ("思考</think>回答<|channel|>final<|message|>後", "思考"),
    ("マーカーなしテキスト", "マーカーなしテキスト"),
    ("", ""),
])
def test_split_before_think_end_corpus(text, expected):
    assert openai_client.split_before_think_end(text) == expected


# --- build_messages -------------------------------------------------------


def test_build_messages_with_system():
    messages = openai_client.build_messages("システム", "リクエスト", "9:16", 10, True)
    assert messages == [
        {"role": "system", "content": "システム"},
        {"role": "user", "content": "resolution: 9:16\nduration: 10s\noriginal_prompt: リクエスト"},
    ]


def test_build_messages_without_system():
    messages = openai_client.build_messages("", "リクエスト", "16:9", 5, True)
    assert messages == [
        {"role": "user", "content": "resolution: 16:9\nduration: 5s\noriginal_prompt: リクエスト"},
    ]


def test_build_messages_no_inject_shape():
    messages = openai_client.build_messages("システム", "リクエスト", "9:16", 10, False)
    assert messages == [
        {"role": "system", "content": "システム"},
        {"role": "user", "content": "リクエスト"},
    ]
