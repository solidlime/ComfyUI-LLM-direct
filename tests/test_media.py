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


class FakeStreams:
    def __init__(self, total):
        self.video = [FakeStream(total)]


class FakeContainer:
    def __init__(self, total):
        self.streams = FakeStreams(total)
        self.decoded = 0

    def decode(self, video=0):
        for i in range(self._total()):
            self.decoded += 1
            yield FakeFrame(i)

    def _total(self):
        return self.streams.video[0].frames if self.streams.video[0].frames else 10_000

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
