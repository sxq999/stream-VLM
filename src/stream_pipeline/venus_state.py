"""Experimental unit-boundary state isolation for a prepared native Venus.

One backend and one set of weights are reused. Execution is serialized; this is
a correctness-oriented co-located baseline, not GPU batching or a PD engine.
PyTorch is injected so importing the main harness does not require a GPU stack.
"""
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import random
import threading


@dataclass
class Session:
    state: dict
    rng: dict
    next_seq: int = 0
    failed: bool = False


class NativeSessionBank:
    BASE_FIELDS = (
        "audio_past_key_values", "llm_past_key_values", "audio_chunk_idx",
        "tts_last_turn_tokens", "llm_generated", "llm_generate_completed",
        "new_user_msg", "session_id", "token2wav_cache", "streaming_text_preserve",
        "streaming_position_offset", "_next_round_id", "_pending_round_id",
        "_omni_chunk_history", "_round_history", "_rope_inv_freq_cache",
    )
    WAVE_FIELDS = ("cache", "stream_cache", "hift_cache_dict")
    DUPLEX_SHARED = {"model", "processor", "tokenizer", "decoder"}
    DECODER_SHARED = {"m", "tokenizer"}

    def __init__(self, duplex, torch, numpy, devices=(0, 1)):
        self.duplex, self.torch, self.np = duplex, torch, numpy
        self.base = duplex.model
        self.wave = self.base.tts.audio_tokenizer
        self.devices = tuple(devices)
        self.lock = threading.RLock()
        self.active = None
        self.sessions = {}
        for name in ("get_streaming_snapshot", "restore_streaming_snapshot"):
            if not callable(getattr(duplex.processor, name, None)):
                raise TypeError(f"Native processor lacks {name}")
        self.initial_state = self.capture()
        self.initial_rng = self.rng_get()
        # All model modules are held by identity, never deep-copied with state.
        self.shared_memo = {id(module): module for module in self.base.modules()}
        for name in ("audio_tokenizer", "flow", "hift"):
            part = getattr(self.wave, name, None)
            if part is not None and hasattr(part, "modules"):
                self.shared_memo.update({id(m): m for m in part.modules()})

    @staticmethod
    def namespace(obj, excluded):
        return {k: v for k, v in vars(obj).items() if k not in excluded}

    @staticmethod
    def replace_namespace(obj, values, excluded):
        for key in list(vars(obj)):
            if key not in excluded:
                delattr(obj, key)
        vars(obj).update(values)

    def capture(self):
        return {
            "duplex": self.namespace(self.duplex, self.DUPLEX_SHARED),
            "decoder": self.namespace(self.duplex.decoder, self.DECODER_SHARED),
            "base": {k: getattr(self.base, k) for k in self.BASE_FIELDS if hasattr(self.base, k)},
            "wave": {k: getattr(self.wave, k) for k in self.WAVE_FIELDS if hasattr(self.wave, k)},
            # This API returns an owned snapshot of streaming mel state.
            "processor": copy.deepcopy(self.duplex.processor.get_streaming_snapshot()),
        }

    def restore(self, state):
        self.replace_namespace(self.duplex, state["duplex"], self.DUPLEX_SHARED)
        self.replace_namespace(self.duplex.decoder, state["decoder"], self.DECODER_SHARED)
        for owner, names, values in [(self.base, self.BASE_FIELDS, state["base"]),
                                     (self.wave, self.WAVE_FIELDS, state["wave"])]:
            for name in names:
                if name in values:
                    setattr(owner, name, values[name])
                elif hasattr(owner, name):
                    delattr(owner, name)
        self.duplex.processor.restore_streaming_snapshot(state["processor"])

    def rng_get(self):
        return {"python": random.getstate(), "numpy": self.np.random.get_state(),
                "cpu": self.torch.get_rng_state(),
                "cuda": [self.torch.cuda.get_rng_state(d) for d in self.devices]}

    def rng_set(self, state):
        random.setstate(state["python"])
        self.np.random.set_state(state["numpy"])
        self.torch.set_rng_state(state["cpu"])
        for device, value in zip(self.devices, state["cuda"]):
            self.torch.cuda.set_rng_state(value, device)

    def create(self, session_id):
        with self.lock:
            if self.active is not None or session_id in self.sessions:
                raise ValueError("Session exists or backend is active")
            memo = dict(self.shared_memo)
            for value in self.initial_state["duplex"].values():
                if isinstance(value, threading.Event):
                    event = threading.Event()
                    if value.is_set():
                        event.set()
                    memo[id(value)] = event
            self.sessions[session_id] = Session(copy.deepcopy(self.initial_state, memo), copy.deepcopy(self.initial_rng))

    @contextmanager
    def activate(self, session_id, seq):
        with self.lock:
            if self.active is not None:
                raise RuntimeError("Nested backend activation is not supported")
            session = self.sessions[session_id]
            if session.failed:
                raise RuntimeError("Session failed previously; reset rather than retry partial state")
            if seq != session.next_seq:
                raise ValueError(f"Expected unit {session.next_seq}, got {seq}")
            outer_rng = self.rng_get()
            self.restore(session.state)
            self.rng_set(session.rng)
            self.active = session_id
            try:
                yield self.duplex
                session.next_seq += 1
            except BaseException:
                session.failed = True
                raise
            finally:
                session.state = self.capture()
                session.rng = self.rng_get()
                self.rng_set(outer_rng)
                self.active = None

    def clear(self):
        with self.lock:
            if self.active is not None:
                raise RuntimeError("Backend is active")
            self.restore(self.initial_state)
            self.rng_set(self.initial_rng)
            self.sessions.clear()

    def weight_identity(self):
        owners = [("model", self.base)]
        owners += [("wave."+name, getattr(self.wave, name)) for name in ("audio_tokenizer", "flow", "hift")
                   if hasattr(getattr(self.wave, name, None), "named_parameters")]
        return tuple((prefix+"."+name, parameter.data_ptr(), parameter.numel(), str(parameter.device))
                     for prefix, owner in owners for name, parameter in owner.named_parameters())
