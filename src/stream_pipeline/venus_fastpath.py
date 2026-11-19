# SPDX-License-Identifier: Apache-2.0
# Native feed flow adapted from Realtime-Venus-Omni/utils.py, StreamDecoder.
# Copyright 2026 The Realtime-Venus Team and The OpenBMB Team.
# Changes: guarded reversible hook; bypass discarded causal-LM logits only.
"""Guarded experimental removal of unused native vocabulary projections.

This is baseline hygiene, not a new serving/PD algorithm. The full hidden-to-
vocabulary projection shape is retained when logits are needed. No batching,
new kernels, precision changes, or model-file edits are performed.
"""
from contextlib import contextmanager
import hashlib
import inspect
from pathlib import Path


def source_sha256(method):
    return hashlib.sha256(inspect.getsource(method).encode()).hexdigest()


@contextmanager
def hidden_only_feed(decoder, torch, *, decoder_file_sha256, llm_forward_sha256):
    """Patch only this decoder inside an isolated single-backend process.

    Checks bind the adaptation to audited source. The class hook avoids storing
    bound methods in session snapshots; other decoder instances use the original
    implementation. Do not run independent model work in another thread here.
    """
    cls = type(decoder)
    original = cls.feed
    actual_file = hashlib.sha256(Path(inspect.getfile(cls)).read_bytes()).hexdigest()
    if actual_file != decoder_file_sha256:
        raise ValueError("Decoder source differs from audited implementation")
    if source_sha256(type(decoder.m).forward) != llm_forward_sha256:
        raise ValueError("Language-model forward differs from audited implementation")
    if type(decoder.m).__name__ != "Qwen3ForCausalLM" or not callable(getattr(decoder.m, "model", None)):
        raise TypeError("This fast path only supports the audited Qwen3 wrapper")
    if getattr(original, "_venus_hidden_only", False):
        raise RuntimeError("Nested fast-path activation is unsupported")

    def feed(instance, embeds, return_logits=False):
        if instance is not decoder:
            return original(instance, embeds, return_logits=return_logits)
        length = embeds.size(0)
        past = instance.get_cache_length()
        positions = torch.arange(past, past + length, device=embeds.device).unsqueeze(0)
        # Same transformer call as the audited causal-LM wrapper. Its discarded
        # vocabulary logits are skipped; hidden states and KV remain native.
        out = instance.m.model(inputs_embeds=embeds.unsqueeze(0), position_ids=positions,
                               past_key_values=instance.cache, return_dict=True,
                               output_hidden_states=True)
        instance.cache = out.past_key_values
        if return_logits:
            hidden = out.hidden_states[-1]
            # Keep all positions in this GEMM to preserve the original shape.
            return instance.m.lm_head(hidden)[:, -1], hidden

    feed._venus_hidden_only = True
    cls.feed = feed
    try:
        yield
    finally:
        cls.feed = original
