# TODO: マルチモーダル対応（画像・動画入力）実装計画

> **実装者へ**: superpowers:subagent-driven-development（推奨）または executing-plans でタスクごとに実行すること。ステップはチェックボックス記法。

**Goal:** 3ノード（gguf/api/hf）に画像・動画入力を optional 追加し、VLM 推論を可能にする。

**Architecture:** 新規 `media.py`（ComfyUI 非依存の純粋関数）でメディア→base64 data URI 化し、`openai_client.build_messages` を拡張して OpenAI 形式 content 配列を生成。3バックエンドが同じ形式を消費する。

**Tech Stack:** numpy / Pillow / PyAV(av) — すべて ComfyUI 同梱依存。新規 pip 依存なし。

## Global Constraints
- 既存ワークフロー非破壊: メディア未接続なら挙動は現状と1バイトも変わらないこと
- 新規外部依存の追加禁止（numpy/PIL/av のみ使用）
- llama-cpp-python <0.3.10 で mmproj 指定時は明確なエラー
- 音声入力は対象外（将来課題、SPEC 参照）
- 各タスク終了時に pytest 全緑 + コミット。テスト実行: `python -m pytest tests/ -v`（tests/pytest.ini の rootdir 設定により tests/ 配下で実行）

---

### Task 1: media.py（共通メディアモジュール）

**Files:**
- Create: `media.py`
- Test: `tests/test_media.py`

**Interfaces:**
- Produces:
  - `image_tensor_to_data_uris(images) -> list[str]` — [B,H,W,C] float 0-1 配列 → PNG data URI リスト
  - `extract_video_frames_to_data_uris(source, frame_count) -> list[str]` — av で開ける source（path or BytesIO）→ 均等サンプリング n 枚の data URI リスト
  - `build_multimodal_content(text, image_uris=None) -> str | list` — uris 無し= str そのまま、有り= content 配列
  - `collect_data_uris(image=None, video=None, video_frames=4) -> list[str]` — ノード側の1行呼び出し用。video は `get_stream_source()` を持つオブジェクト（duck typing）

- [x] **Step 1: 失敗するテストを書く**

```python
"""Tests for media helpers: tensor->URI conversion, video frame sampling,
and multimodal content building. Uses numpy directly (no torch needed)."""

import base64
import io

import numpy as np
import pytest
from PIL import Image

import media


def _decode_uri(uri):
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri[len("data:image/png;base64,"):])
    return Image.open(io.BytesIO(raw))


# --- image_tensor_to_data_uris ---------------------------------------------


def test_image_batch_two_frames():
    batch = np.zeros((2, 4, 4, 3), dtype=np.float32)
    batch[1] = 1.0
    uris = media.image_tensor_to_data_uris(batch)
    assert len(uris) == 2
    assert _decode_uri(uris[0]).size == (4, 4)
    # frame 1 is all-white
    assert _decode_uri(uris[1]).getpixel((0, 0)) == (255, 255, 255)


def test_image_values_clipped():
    batch = np.full((1, 2, 2, 3), 5.0, dtype=np.float32)  # out of range
    uri = media.image_tensor_to_data_uris(batch)[0]
    assert _decode_uri(uri).getpixel((0, 0)) == (255, 255, 255)


def test_image_rejects_non_4d():
    with pytest.raises(ValueError, match="B,H,W,C"):
        media.image_tensor_to_data_uris(np.zeros((4, 4, 3), dtype=np.float32))


# --- extract_video_frames_to_data_uris -------------------------------------


class FakeFrame:
    def __init__(self, i):
        self.i = i

    def to_image(self):
        return Image.new("RGB", (2, 2), color=(self.i % 256, 0, 0))


class FakeStream:
    def __init__(self, total):
        self.frames = total


class FakeContainer:
    def __init__(self, total):
        self.streams = {"video": [FakeStream(total)]}
        self.decoded = 0

    def decode(self, video=0):
        for i in range(self._total()):
            self.decoded += 1
            yield FakeFrame(i)

    def _total(self):
        return self.streams["video"][0].frames if self.streams["video"][0].frames else 10_000

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def fake_av(monkeypatch):
    holder = {}

    def install(container):
        holder["container"] = container
        monkeypatch.setattr(media.av, "open", lambda source, mode="r": container)

    return install, holder


def test_video_known_total_samples_n(fake_av):
    install, holder = fake_av
    install(FakeContainer(100))
    uris = media.extract_video_frames_to_data_uris("fake.mp4", 4)
    assert len(uris) == 4
    # early stop: last wanted index is 75 -> exactly 76 decodes, not all 100
    assert holder["container"].decoded == 76


def test_video_unknown_total_collects_then_samples(fake_av):
    install, _ = fake_av
    install(FakeContainer(0))  # frames unknown -> metadata 0
    uris = media.extract_video_frames_to_data_uris("fake.mp4", 5)
    assert len(uris) == 5


def test_video_n_larger_than_total_returns_all(fake_av):
    install, _ = fake_av
    install(FakeContainer(3))
    uris = media.extract_video_frames_to_data_uris("fake.mp4", 8)
    assert len(uris) == 3


def test_video_decode_error_raises(fake_av, monkeypatch):
    install, _ = fake_av
    container = FakeContainer(10)

    def boom(video=0):
        raise RuntimeError("corrupt")

    monkeypatch.setattr(container, "decode", boom)
    install(container)
    with pytest.raises(ValueError, match="動画デコードに失敗"):
        media.extract_video_frames_to_data_uris("fake.mp4", 4)


# --- build_multimodal_content ----------------------------------------------


def test_content_no_uris_is_plain_string():
    assert media.build_multimodal_content("hello", None) == "hello"
    assert media.build_multimodal_content("hello", []) == "hello"


def test_content_with_uris_is_array():
    out = media.build_multimodal_content("見て", ["data:image/png;base64,AAA"])
    assert out == [
        {"type": "text", "text": "見て"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]


def test_content_empty_text_images_only():
    out = media.build_multimodal_content("", ["u1", "u2"])
    assert out == [
        {"type": "image_url", "image_url": {"url": "u1"}},
        {"type": "image_url", "image_url": {"url": "u2"}},
    ]


# --- collect_data_uris ------------------------------------------------------


class FakeVideo:
    def __init__(self, source):
        self.source = source

    def get_stream_source(self):
        return self.source


def test_collect_nothing():
    assert media.collect_data_uris() == []


def test_collect_image_and_video(fake_av):
    install, _ = fake_av
    install(FakeContainer(6))
    batch = np.zeros((1, 2, 2, 3), dtype=np.float32)
    uris = media.collect_data_uris(image=batch, video=FakeVideo("v.mp4"), video_frames=2)
    assert len(uris) == 3  # 1 image + 2 frames
```

- [x] **Step 2: テストが失敗することを確認**

Run: `cd tests; python -m pytest test_media.py -v`
Expected: FAIL（media モジュールが存在しない）

- [x] **Step 3: media.py を実装**

```python
"""Pure-logic media helpers: convert ComfyUI IMAGE batches and video sources
into base64 data URIs for multimodal LLM input.

No ComfyUI imports: stays unit-testable in isolation. Depends only on
numpy / Pillow / PyAV, which are all bundled with ComfyUI.
"""

import base64
import io

import av
import numpy as np
from PIL import Image


def _pil_to_data_uri(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def image_tensor_to_data_uris(images):
    """Convert a [B,H,W,C] float 0-1 image batch into PNG data URIs."""
    arr = np.asarray(images, dtype=np.float32)
    if arr.ndim != 4:
        raise ValueError(f"media: IMAGE バッチは [B,H,W,C] である必要があります (got ndim={arr.ndim})")
    uris = []
    for frame in arr:
        img = Image.fromarray(np.clip(frame * 255.0, 0, 255).astype(np.uint8), mode="RGB")
        uris.append(_pil_to_data_uri(img))
    return uris


def _sample_indices(total, n):
    """Evenly spaced indices covering [0, total); None when total is unknown."""
    if total <= 0:
        return None
    n = min(n, total)
    return sorted({min(int(i * total / n), total - 1) for i in range(n)})


def _sample_list(frames, n):
    wanted = _sample_indices(len(frames), n)
    return [frames[i] for i in wanted]


def extract_video_frames_to_data_uris(source, frame_count):
    """Open a video source (path or file-like) with PyAV and sample
    frame_count evenly spaced frames as data URIs.

    ponytail: single sequential decode pass keeping only selected indices;
    seek-based sampling is the upgrade path if long-video latency matters.
    """
    uris = []
    try:
        with av.open(source, mode="r") as container:
            total = container.streams.video[0].frames or 0
            wanted = _sample_indices(total, frame_count)
            wanted_set = set(wanted) if wanted is not None else None
            collected = []
            for idx, frame in enumerate(container.decode(video=0)):
                if wanted_set is None:
                    collected.append(frame.to_image())
                elif idx in wanted_set:
                    collected.append(frame.to_image())
                    if len(collected) == len(wanted_set):
                        break
    except Exception as exc:
        raise ValueError(f"media: 動画デコードに失敗しました ({type(exc).__name__})") from exc
    if wanted is None:
        collected = _sample_list(collected, frame_count)
    return [_pil_to_data_uri(img) for img in collected]


def build_multimodal_content(text, image_uris=None):
    """Plain string without media (legacy behavior), OpenAI content array with."""
    if not image_uris:
        return text
    content = []
    if text.strip():
        content.append({"type": "text", "text": text})
    for uri in image_uris:
        content.append({"type": "image_url", "image_url": {"url": uri}})
    return content


def collect_data_uris(image=None, video=None, video_frames=4):
    """One-call helper for nodes: images first, then sampled video frames."""
    uris = []
    if image is not None:
        uris.extend(image_tensor_to_data_uris(image))
    if video is not None:
        uris.extend(extract_video_frames_to_data_uris(video.get_stream_source(), video_frames))
    return uris
```

注意: `extract_video_frames_to_data_uris` 内で `wanted` が未定義になる経路（例外時に except へ飛ぶ）はないが、`total<=0` のとき `wanted=None` なので最後の `if wanted is None` 分岐とセットで動く。変数スコープは with ブロック外で参照するため、try 直前で `wanted = None` に初期化しておくこと（実装時に確認）。

- [x] **Step 4: テストが通ることを確認**

Run: `cd tests; python -m pytest test_media.py -v`
Expected: PASS 全件

- [x] **Step 5: コミット**

```bash
git add media.py tests/test_media.py
git commit -m "feat: media.py 共通メディアモジュール（画像/動画→data URI、content配列組み立て）"
```

---

### Task 2: openai_client.build_messages 拡張

**Files:**
- Modify: `openai_client.py:46-51`（build_messages のみ）
- Test: `tests/test_openai_client.py`（末尾に追加）

**Interfaces:**
- Consumes: `media.build_multimodal_content(text, image_uris)`（Task 1）
- Produces: `build_messages(system_prompt, user_input, resolution, duration, inject_shape, image_uris=None)` — 第6引数追加、デフォルト None で後方互換

- [x] **Step 1: 失敗するテストを書く**（tests/test_openai_client.py 末尾に追記）

```python
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
```

- [x] **Step 2: 失敗確認**

Run: `cd tests; python -m pytest test_openai_client.py -k image_uris -v`
Expected: FAIL（TypeError: unexpected keyword argument）

- [x] **Step 3: 実装**（openai_client.py の build_messages を置換）

```python
def build_messages(system_prompt, user_input, resolution, duration, inject_shape, image_uris=None):
    import media
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    text = build_user_content(resolution, duration, user_input, inject_shape)
    messages.append({"role": "user", "content": media.build_multimodal_content(text, image_uris)})
    return messages
```

注: `import media` はファイル先頭ではなく関数内でも可（循環なし・遅延読み込み）。先頭に置いても壊れないが、既存の httpx 以外の import を増やさない方針なら関数内でよい。**決定: ファイル先頭に `import media` を追加**（openai_client は純粋モジュールで media も純粋、循環なし）。

- [x] **Step 4: 全テスト確認**

Run: `cd tests; python -m pytest -v`
Expected: PASS（既存 build_messages テスト含め全緑＝後方互換の証明）

- [x] **Step 5: コミット**

```bash
git add openai_client.py tests/test_openai_client.py
git commit -m "feat: build_messages マルチモーダル対応（image_uries → content 配列）"
```

---

### Task 3: api-llm-direct ノード配線

**Files:**
- Modify: `__init__.py:227-270`（APILLMDirect の INPUT_TYPES と generate）
- Test: 実機スモークは Task 6 に集約（ノードクラスは ComfyUI 依存のためユニットテスト対象外という既存方針）

**Interfaces:**
- Consumes: `media.collect_data_uris`, `openai_client.build_messages(..., image_uris=)`
- Produces: なし（末端）

- [x] **Step 1: INPUT_TYPES に optional 追加**（`__init__.py` 冒頭に `import media` を追加した上で）

```python
            "optional": {
                "image": ("IMAGE",),
                "video": ("VIDEO",),
                "video_frames": ("INT", {"default": 4, "min": 1, "max": 32}),
            },
```

- [x] **Step 2: generate シグネチャと本文を変更**

```python
    def generate(self, base_url, model, system_prompt, user_input, api_key="", resolution="9:16",
                 duration=10, inject_shape=True, enable_thinking=True, reasoning_effort="auto",
                 strip_think=True, temperature=0.6, top_p=0.9, max_tokens=4096, seed=0,
                 timeout=300.0, image=None, video=None, video_frames=4):
        uris = media.collect_data_uris(image=image, video=video, video_frames=video_frames)
        messages = openai_client.build_messages(system_prompt, user_input, resolution, duration, inject_shape, image_uris=uris)
```

以降の行は無変更。payload は content 配列をそのまま通す。

- [x] **Step 3: 全テスト実行（回帰確認）**

Run: `cd tests; python -m pytest -v`
Expected: PASS

- [x] **Step 4: コミット**

```bash
git add __init__.py
git commit -m "feat: api-llm-direct 画像/動画入力対応"
```

---

### Task 4: gguf-llm-direct ノード配線（mmproj）

**Files:**
- Modify: `__init__.py:117-223`（GGUFLLMDirect）

**Interfaces:**
- Consumes: `media.collect_data_uris`, `openai_client.build_messages(..., image_uris=)`
- Produces: `_get_llm(model_path, ..., mmproj_path)` — キャッシュキーに mmproj_path を含める

- [x] **Step 1: INPUT_TYPES に optional 追加**（Task 3 と同一ブロック構造）

```python
            "optional": {
                "image": ("IMAGE",),
                "video": ("VIDEO",),
                "video_frames": ("INT", {"default": 4, "min": 1, "max": 32}),
                "mmproj_path": ("STRING", {"default": ""}),
            },
```

- [x] **Step 2: mtmd ハンドラ解決ヘルパーを追加**（クラス外・`_gguf_choices` 付近）

```python
def _resolve_mmproj_handler(mmproj_path):
    """Return an MTMD chat handler for the given mmproj GGUF, or None."""
    if not mmproj_path.strip():
        return None
    import llama_cpp
    from llama_cpp.llama_chat_format import MTMDChatHandler
    full = folder_paths.get_full_path("llm_gguf", mmproj_path.strip()) or mmproj_path.strip()
    return MTMDChatHandler(clip_model_path=full, verbose=False)
```

バージョンガード: `MTMDChatHandler` の import 失敗（<0.3.10）を except ImportError で捕まえ、`ValueError("gguf-llm-direct: マルチモーダルには llama-cpp-python >= 0.3.10 が必要です")` を投げること。

- [x] **Step 3: _get_llm を拡張**

キャッシュキーに `mmproj_path` を追加し、handler が解決できたら `Llama(chat_handler=...)` を渡す:

```python
    @classmethod
    def _get_llm(cls, model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap, mmproj_path=""):
        key = (model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap, mmproj_path)
        llm = cls._cache.get(key)
        if llm is None:
            cls._cache.clear()
            gc.collect()
            kwargs = dict(
                model_path=folder_paths.get_full_path("llm_gguf", model_path),
                n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, n_threads=n_threads,
                n_batch=n_batch, flash_attn=flash_attn, mmap=use_mmap, verbose=False,
            )
            handler = _resolve_mmproj_handler(mmproj_path)
            if handler is not None:
                kwargs["chat_handler"] = handler
            llm = Llama(**kwargs)
            cls._cache[key] = llm
        return llm
```

- [x] **Step 4: generate を変更**

```python
    def generate(self, model_path, system_prompt, user_input, resolution="9:16", duration=10,
                 enable_thinking=False, strip_think=True, temperature=0.6, top_p=0.9, top_k=64,
                 min_p=0.05, repeat_penalty=1.1, max_tokens=4096, n_ctx=4096, n_gpu_layers=99,
                 n_threads=4, n_batch=256, flash_attn=True, use_mmap=False, seed=0,
                 unload_after_run=False, inject_shape=True,
                 image=None, video=None, video_frames=4, mmproj_path=""):
        has_media = image is not None or video is not None
        if has_media and not mmproj_path.strip():
            raise ValueError("gguf-llm-direct: 画像/動画入力には mmproj_path の指定が必要です")
        llm = self._get_llm(model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap, mmproj_path)
        uris = media.collect_data_uris(image=image, video=video, video_frames=video_frames)
        messages = openai_client.build_messages(system_prompt, user_input, resolution, duration, inject_shape, image_uris=uris)
        if mmproj_path.strip():
            # カスタムハンドラ経由: create_chat_completion は extra kwargs を落とすため直接呼ぶ
            resp = llm.chat_handler(
                llama=llm, messages=messages,
                temperature=temperature, top_p=top_p, top_k=top_k, min_p=min_p,
                repeat_penalty=repeat_penalty, max_tokens=max_tokens,
                stop=list(_START_STOPS), seed=seed if seed > 0 else None,
                enable_thinking=bool(enable_thinking), stream=True,
            )
        else:
            handler = llm._chat_handlers.get("chat_template.default")
            resp = handler(...)  # 既存呼び出しをそのまま維持
```

以降（チャンク結合〜返却）は無変更。

⚠️ 既知リスク（実機確認事項）: MTMDChatHandler が `enable_thinking` をテンプレートへ透過しない場合、VLM モデルでは thinking 切替が効かない可能性。機能劣害は「thinking 常時有効」程度で許容し、Task 6 の実機スモークで確認する。

- [x] **Step 5: 全テスト実行**

Run: `cd tests; python -m pytest -v`
Expected: PASS

- [x] **Step 6: コミット**

```bash
git add __init__.py
git commit -m "feat: gguf-llm-direct 画像/動画入力対応（mmproj + mtmd ハンドラ）"
```

---

### Task 5: hf-llm-direct ノード配線（VLM 対応）

**Files:**
- Modify: `hf_client.py`（build_inputs / run_generate）
- Modify: `__init__.py:93-114, 273-341`（_hf_choices / HFLLMDirect）
- Test: `tests/test_hf_client.py`（FakeTokenizer 拡張・新テスト追加）

**Interfaces:**
- Consumes: `media.collect_data_uris`, `openai_client.build_messages(..., image_uris=)`
- Produces: `hf_client.build_inputs(processor, messages)` — 戻り値は tensor または dict（BatchFeature）; `run_generate(model, inputs, ...)` — inputs が dict なら `generate(**inputs)` 形式に展開

- [x] **Step 1: テストを更新・追加**

FakeTokenizer を戻り値切替可能にし、新テストを追加:

```python
class FakeTokenizer:
    def __init__(self, return_dict=False):
        self.calls = []
        self.return_dict = return_dict

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.return_dict:
            return {"input_ids": "ids", "attention_mask": "mask"}
        return "tokenized-inputs"


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


def test_run_generate_dict_inputs_expanded():
    model = FakeModel()
    streamer = FakeStreamer()
    hf_client.run_generate(model, {"input_ids": "ids", "attention_mask": "mask"},
                           streamer, 100, 0.6, 0.9, 0)
    assert model.kwargs["input_ids"] == "ids"
    assert model.kwargs["attention_mask"] == "mask"
```

既存 `test_build_inputs_calls_apply_chat_template` は新シグネチャに合わせ更新（kwargs アサーションを return_dict パスのものに変更）。

- [x] **Step 2: 失敗確認**

Run: `cd tests; python -m pytest test_hf_client.py -v`
Expected: FAIL

- [x] **Step 3: hf_client.py を実装**

```python
def build_inputs(processor, messages):
    """Tokenize a chat message list through the processor's chat template.

    Returns a tensor (older transformers / text-only fallback) or a dict-like
    BatchFeature (multimodal: input_ids + pixel_values etc.).
    """
    try:
        return processor.apply_chat_template(
            messages, tokenize=True, return_dict=True, add_generation_prompt=True
        )
    except (TypeError, ValueError):
        # transformers too old for return_dict support
        return processor.apply_chat_template(
            messages, tokenize=True, return_tensors="pt", add_generation_prompt=True
        )
```

run_generate は `input_ids=input_ids` 行を以下に変更:

```python
            if isinstance(inputs, dict):
                kwargs.update(inputs)
            else:
                kwargs["input_ids"] = inputs
```

（引数名 `input_ids` → `inputs` に変更、docstring 更新）

- [x] **Step 4: _hf_choices を VLM 対応に拡張**（`__init__.py:112` の条件を変更）

```python
            if any(("ForCausalLM" in a) or ("ForConditionalGeneration" in a) for a in architectures):
                choices.append(entry.name)
```

コメントも更新（Llava 除外の説明を VLM 含む旨に書き換え）。

- [x] **Step 5: HFLLMDirect のモデルロードを VLM 対応に**

`__init__.py` の transformers import に追加:

```python
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
    from transformers import AutoModelForImageTextToText
except ImportError:
    ...
    AutoModelForImageTextToText = None
```

_get_model 内、アーキテクチャ判定してロードクラスを切替:

```python
        config_path = Path(path) / "config.json"
        arch = ""
        if config_path.is_file():
            try:
                arch = "".join(json.load(config_path.open(encoding="utf-8")).get("architectures", []))
            except (OSError, ValueError):
                pass
        loader = AutoModelForImageTextToText if (
            "ForConditionalGeneration" in arch and AutoModelForImageTextToText is not None
        ) else AutoModelForCausalLM
        model = loader.from_pretrained(path, device_map="auto", torch_dtype=dtype)
```

- [x] **Step 6: HFLLMDirect.generate を配線**

INPUT_TYPES に Task 3 と同一の optional ブロック（mmproj なし）を追加し:

```python
        uris = media.collect_data_uris(image=image, video=video, video_frames=video_frames)
        messages = openai_client.build_messages(system_prompt, user_input, resolution, duration, inject_shape, image_uris=uris)
        inputs = hf_client.build_inputs(tokenizer, messages)
```

run_generate 呼び出しの第2引数を `inputs` に変更。以降無変更。

- [x] **Step 7: 全テスト実行**

Run: `cd tests; python -m pytest -v`
Expected: PASS

- [x] **Step 8: コミット**

```bash
git add hf_client.py __init__.py tests/test_hf_client.py
git commit -m "feat: hf-llm-direct VLM 対応（ForConditionalGeneration + return_dict 入力）"
```

---

### Task 6: ドキュメント同期 + 最終検証

**Files:**
- Modify: `README.md`（マルチモーダル入力の説明追加）

- [x] **Step 1: README 更新** — 3ノードの optional 入力（image/video/video_frames、gguf は mmproj_path）、対応モデル例（Qwen2.5-VL 等）、動画はフレーム抽出方式である旨を追記
- [x] **Step 2: 全テスト実行** — `cd tests; python -m pytest -v` → 全緑
- [x] **Step 3: 実機スモーク（ComfyUI 起動環境で）**
  > 注記: メディアパイプライン（tensor→data URI、動画フレーム抽出、content 配列組み立て）はユニットテストで検証済み。VLM モデル実推論（api/gguf/hf の実機生成）はユーザー環境での確認事項として残す。
  1. api ノード + ローカル VLM サーバー（例: vLLM/Qwen2.5-VL）で LoadImage → 画像1枚の説明生成を確認
  2. gguf ノード + Qwen2.5-VL GGUF + mmproj で同様に確認（enable_thinking の透過可否も観察）
  3. メディア未接続の既存ワークフローが従来通り動くことを確認
- [x] **Step 4: コミット + プッシュ**

```bash
git add README.md .spec/
git commit -m "docs: マルチモーダル対応の README 同期"
```

> 注記: push はユーザー指示により未実施。コミットメッセージは計画の「README 更新」から「README 同期」に変更。

---

## Drive-by Findings（実装中に発見したら報告）
- （なし）

---
---

# 第2弾: フォローアップ（thinking プレビューノード + パラメータ並び替え）

> SPEC 追記分（F1〜F3）の実装計画。実装は #011（fix-1 セッション再利用）。

### Task 7: パラメータ並び替え + thinking プレビューノード追加

**Files:**
- Modify: `__init__.py`（3ノード INPUT_TYPES 並び替え、generate シグネ整合、LLMThinkingPreview 追加）

**Interfaces:**
- Produces: `NODE_CLASS_MAPPINGS["LLMThinkingPreview"]`、INPUT `text`(STRING, forceInput)、RETURN `("STRING",)` 名 `text`

- [ ] **Step 1: 3ノードの required を SPEC F3 順に並び替え** — 基本→プロンプト形状→思考・出力→サンプリング→llama起動(gguf)→運用。optional 変更なし
- [ ] **Step 2: generate() シグネを同順に整合**（kwargs 名渡しのため機能影響なし）
- [ ] **Step 3: LLMThinkingPreview ノード追加**

```python
class LLMThinkingPreview:
    """Realtime thinking display node. The WS stream is rendered by the JS
    extension (web/llm-direct.js); the Python side is a pure passthrough.
    The input link identifies which LLM node's stream to show."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "passthrough"
    CATEGORY = "LLM"

    def passthrough(self, text):
        return (text,)
```

- [ ] **Step 4: 登録** — `NODE_CLASS_MAPPINGS["LLMThinkingPreview"] = LLMThinkingPreview`、表示名 `"llm-thinking-preview"`
- [ ] **Step 5: 検証** — `python -m py_compile __init__.py` + `cd tests; python -m pytest -v` 全緑
- [ ] **Step 6: コミット** — `git commit -m "feat: llm-thinking-preview ノード追加 + パラメータ並び替え"`

### Task 8: JS 拡張 — inline 廃止 + プレビューノード WS 購読

**Files:**
- Modify: `web/llm-direct.js`

**Interfaces:**
- Consumes: WS イベント `llm_direct_reasoning` `{node, text}`（変更なし）、ノード名 `LLMThinkingPreview`（Task 7）

- [ ] **Step 1: beforeRegisterNodeDef の inline DOM ウィジェット追加を削除**（3ノード分）
- [ ] **Step 2: onReasoning をプレビューノード対応に書き換え** — イベント発火時にグラフ走査し、入力リンク origin_id が e.detail.node と一致する LLMThinkingPreview ノードのみ更新:

```javascript
function onReasoning(e) {
  const graph = window.app?.graph;
  if (!graph) return;
  for (const node of graph._nodes) {
    if (node.type !== "LLMThinkingPreview") continue;
    const link = node.getInputLink(0);
    if (!link || String(link.origin_id) !== String(e.detail.node)) continue;
    const widget = node.widgets?.find((w) => w.name === "reasoning");
    if (!widget?.element) continue;
    const el = widget.element;
    const stickToBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent = e.detail.text;  // innerHTML は XSS 境界なので禁止
    if (stickToBottom) el.scrollTop = el.scrollHeight;
  }
}
```

- [ ] **Step 3: プレビューノード側のウィジェット生成** — beforeRegisterNodeDef を LLMThinkingPreview 用に再利用（既存の addDOMWidget ロジック流用・serialize:false 維持）
- [ ] **Step 4: コミット** — `git commit -m "feat: thinking 表示をプレビューノードへ移行（inline 廃止）"`

### Task 9: README 同期 + 最終検証

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 更新** — llm-thinking-preview ノードの説明追加（接続方法・リアルタイム表示・inline 表示廃止を明記）
- [ ] **Step 2: 全テスト + py_compile**
- [ ] **Step 3: REVIEW (#081)** → GATE → コミット + push
- [ ] **Step 4: 実機確認（ユーザー環境）** — ComfyUI 再起動後: ①プレビューノード接続でリアルタイム表示 ②inline 表示が消えたこと ③パラメータ順 ④旧ワークフローが壊れないこと
