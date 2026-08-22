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
    collected = []
    wanted = None
    try:
        with av.open(source, mode="r") as container:
            total = container.streams.video[0].frames or 0
            wanted = _sample_indices(total, frame_count)
            wanted_set = set(wanted) if wanted is not None else None
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
        source = video.get_stream_source() if hasattr(video, "get_stream_source") else video
        uris.extend(extract_video_frames_to_data_uris(source, video_frames))
    return uris
