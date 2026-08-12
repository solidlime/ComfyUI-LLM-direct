"""
Minimal GGUF prompt node: direct Llama() + create_chat_completion, no presets,
no cleaning pipeline. Proven to complete long H3 prompt generations where the
VRGDG node truncated. Stop sequences are start-of-turn markers only, so the
model keeps generating past an early <end_of_turn>; the marker is stripped
afterwards.

Models are resolved through the standard folder_paths mechanism relative to
the ComfyUI models directory (models/LLM/GGUF), so the node works wherever
the install lives.
"""

import gc
import os
import sys
from pathlib import Path

import folder_paths
import httpx

from llama_cpp import Llama

# ComfyUI loads this folder via spec_from_file_location without adding it to
# sys.path, so expose our own dir for the sibling helper module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openai_client

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_START_STOPS = ("<start_of_turn>", "<|start_of_turn|>", "|start_of_turn|", "_start_turn", "_start_of_turn")

# Same fixed choices as pytraveler/MiniMax-H3-Prompt-Rewriter-ComfyUI.
_RESOLUTIONS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")


def _register_gguf_folder():
    gguf_dir = Path(folder_paths.models_dir) / "LLM" / "GGUF"
    if gguf_dir.is_dir():
        # Own folder name: comfyui-easy-use already registers "llm" with
        # supported_pt_extensions, which filters out .gguf files.
        folder_paths.add_model_folder_path("llm_gguf", str(gguf_dir))


_register_gguf_folder()


def _send_progress(text):
    try:
        from server import PromptServer  # ComfyUI 環境でのみ存在
        from comfy_execution.utils import get_executing_context
    except ImportError:
        return  # pytest 環境
    ctx = get_executing_context()
    node_id = ctx.node_id if ctx is not None else getattr(PromptServer.instance, "last_node_id", None)
    # ponytail: last_node_id fallback can race with parallel prompts, but ctx
    # covers normal execution so the fallback is only a best-effort escape.
    if node_id is not None and PromptServer.instance is not None:
        try:
            PromptServer.instance.send_progress_text(text, node_id)
        except Exception:
            # Progress display is best-effort: a broken socket must not kill
            # the whole generation.
            pass


def _gguf_choices():
    return [p for p in folder_paths.get_filename_list("llm_gguf") if p.lower().endswith(".gguf")]


class DirectGGUFPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_path": (_gguf_choices(),),
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "user_input": ("STRING", {"multiline": True}),
                "resolution": (_RESOLUTIONS, {"default": "9:16"}),
                "duration": ("INT", {"default": 10, "min": 1, "max": 15}),
                "enable_thinking": ("BOOLEAN", {"default": False}),
                "strip_think": ("BOOLEAN", {"default": True}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 2.0, "step": 0.01}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "top_k": ("INT", {"default": 64, "min": 0, "max": 512}),
                "min_p": ("FLOAT", {"default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01}),
                "repeat_penalty": ("FLOAT", {"default": 1.1, "min": 0.0, "max": 2.0, "step": 0.01}),
                "max_tokens": ("INT", {"default": 4096, "min": 256, "max": 65536}),
                "n_ctx": ("INT", {"default": 4096, "min": 512, "max": 131072}),
                "n_gpu_layers": ("INT", {"default": 99, "min": 0, "max": 999}),
                "n_threads": ("INT", {"default": 4, "min": 1, "max": 32}),
                "n_batch": ("INT", {"default": 256, "min": 16, "max": 2048}),
                "flash_attn": ("BOOLEAN", {"default": True}),
                # mmap keeps reading the file from disk during generation
                # (visible as disk-usage spikes while ComfyUI is running).
                # Loading the file into RAM up front removes that I/O.
                "use_mmap": ("BOOLEAN", {"default": False}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2**32 - 1}),
                "unload_after_run": ("BOOLEAN", {"default": False}),
                # Off for plain LLM use: the resolution/duration header is
                # only meaningful for H3-style prompt rewriting tasks.
                "inject_shape": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "generate"
    CATEGORY = "LLM"

    _cache = {}

    @classmethod
    def _get_llm(cls, model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap):
        key = (model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap)
        llm = cls._cache.get(key)
        if llm is None:
            # Drop any previously loaded model first: keeping more than one
            # resident steals VRAM from ComfyUI's own models. Collect so the
            # old model's VRAM is freed before the new one is allocated.
            cls._cache.clear()
            gc.collect()
            llm = Llama(
                model_path=folder_paths.get_full_path("llm_gguf", model_path),
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                n_threads=n_threads,
                n_batch=n_batch,
                flash_attn=flash_attn,
                mmap=use_mmap,
                verbose=False,
            )
            cls._cache[key] = llm
        return llm

    def generate(self, model_path, system_prompt, user_input, resolution="9:16", duration=10,
                 enable_thinking=False, strip_think=True, temperature=0.6, top_p=0.9, top_k=64,
                 min_p=0.05, repeat_penalty=1.1, max_tokens=4096, n_ctx=4096, n_gpu_layers=99,
                 n_threads=4, n_batch=256, flash_attn=True, use_mmap=False, seed=0,
                 unload_after_run=False, inject_shape=True):
        llm = self._get_llm(model_path, n_ctx, n_gpu_layers, n_threads, flash_attn, n_batch, use_mmap)
        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": openai_client.build_user_content(resolution, duration, user_input, inject_shape)})
        # Call the template handler directly so enable_thinking reaches the
        # model's Jinja template (create_chat_completion drops extra kwargs).
        handler = llm._chat_handlers.get("chat_template.default")
        resp = handler(
            llama=llm,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            repeat_penalty=repeat_penalty,
            max_tokens=max_tokens,
            stop=list(_START_STOPS),
            seed=seed if seed > 0 else None,
            enable_thinking=bool(enable_thinking),
            stream=True,
        )
        text = ""
        for chunk in resp:
            # Delta has no "content" on the role-only first chunk and the
            # finish_reason last one, so .get() is required.
            piece = chunk["choices"][0].get("delta", {}).get("content")
            if not piece:
                continue
            text += piece
            # Show the same cleaned text that will be returned: thinking is
            # mixed into content for local models, so strip before display.
            _send_progress(openai_client.strip_turn_markers(openai_client.strip_think(text)))
        if strip_think:
            text = openai_client.strip_think(text)
        text = openai_client.strip_turn_markers(text)
        if unload_after_run:
            self._cache.clear()
            gc.collect()
        return (text,)


class DirectOpenAIPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": "http://127.0.0.1:8080/v1"}),
                "model": ("STRING", {"default": ""}),
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "user_input": ("STRING", {"multiline": True}),
                "api_key": ("STRING", {"default": "", "password": True}),
                "resolution": (_RESOLUTIONS, {"default": "9:16"}),
                "duration": ("INT", {"default": 10, "min": 1, "max": 15}),
                "inject_shape": ("BOOLEAN", {"default": True}),
                "enable_thinking": ("BOOLEAN", {"default": True}),
                "reasoning_effort": (("auto", "low", "medium", "high", "max"), {"default": "auto"}),
                "strip_think": ("BOOLEAN", {"default": True}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 2.0, "step": 0.01}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "max_tokens": ("INT", {"default": 4096, "min": 1, "max": 65536}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2**32 - 1}),
                "timeout": ("FLOAT", {"default": 300.0, "min": 5.0, "max": 3600.0}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "generate"
    CATEGORY = "LLM"

    def generate(self, base_url, model, system_prompt, user_input, api_key="", resolution="9:16",
                 duration=10, inject_shape=True, enable_thinking=True, reasoning_effort="auto",
                 strip_think=True, temperature=0.6, top_p=0.9, max_tokens=4096, seed=0,
                 timeout=300.0):
        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": openai_client.build_user_content(resolution, duration, user_input, inject_shape)})
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            text = openai_client.chat_completion_stream(
                client, base_url, model, messages, api_key,
                temperature, top_p, max_tokens, seed,
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
                on_chunk=lambda t: _send_progress(
                    openai_client.strip_turn_markers(openai_client.strip_think(t))))
        if strip_think:
            text = openai_client.strip_think(text)
        text = openai_client.strip_turn_markers(text)
        return (text,)


NODE_CLASS_MAPPINGS["DirectGGUFPrompt"] = DirectGGUFPrompt
NODE_DISPLAY_NAME_MAPPINGS["DirectGGUFPrompt"] = "gguf-direct"

NODE_CLASS_MAPPINGS["DirectOpenAIPrompt"] = DirectOpenAIPrompt
NODE_DISPLAY_NAME_MAPPINGS["DirectOpenAIPrompt"] = "openai-direct"
