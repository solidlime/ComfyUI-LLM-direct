"""Pure-logic helpers for Hugging Face transformers models.

No ComfyUI imports: this module stays unit-testable in isolation with fake
torch / model / tokenizer / streamer objects injected by the tests.
"""

import threading

try:
    import torch
except ImportError:
    torch = None


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


def run_generate(model, inputs, streamer, max_new_tokens, temperature, top_p,
                 seed, on_text=None):
    """Run model.generate on a worker thread, feeding the streamer.

    inputs is a tensor or a dict-like BatchFeature from build_inputs; dict
    inputs are expanded into generate kwargs (input_ids + pixel_values etc.).
    Exceptions raised on the worker thread are collected and re-raised as a
    ValueError on the caller thread after the stream is drained, so a
    mid-generation OOM does not die silently in a background thread.
    """
    errors = []

    def _generate():
        try:
            kwargs = dict(
                streamer=streamer,
                max_new_tokens=max_new_tokens,
                top_p=top_p,
                # temperature=0.0 means greedy: transformers rejects
                # non-positive temperature in TemperatureLogitsWarper.
                do_sample=temperature > 0,
            )
            if isinstance(inputs, dict):
                kwargs.update(inputs)
            else:
                kwargs["input_ids"] = inputs
            if temperature > 0:
                kwargs["temperature"] = temperature
            if seed > 0:
                # seed=0 means "not specified": keep the run non-deterministic.
                torch.manual_seed(seed)
            model.generate(**kwargs)
        except Exception as exc:
            errors.append(exc)
        finally:
            streamer.end()

    thread = threading.Thread(target=_generate)
    thread.start()
    text = []
    for piece in streamer:
        text.append(piece)
        if on_text is not None:
            on_text("".join(text))
    thread.join()
    if errors:
        raise ValueError(f"hf-llm-direct: generation failed: {type(errors[0]).__name__}") from errors[0]
    return "".join(text)
