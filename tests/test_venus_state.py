import random
import threading
from types import SimpleNamespace
import unittest
from stream_pipeline.venus_state import NativeSessionBank


class RandomAPI:
    @staticmethod
    def get_state(): return random.getstate()
    @staticmethod
    def set_state(x): random.setstate(x)


class FakeProcessor:
    def __init__(self): self.data = {"samples": []}
    def get_streaming_snapshot(self): return self.data  # intentionally aliases
    def restore_streaming_snapshot(self, x): self.data = {"samples": list(x["samples"])}


def fixture():
    wave = SimpleNamespace(cache=[], stream_cache={}, hift_cache_dict={})
    base = SimpleNamespace(audio_past_key_values=[], processor=None, tts=SimpleNamespace(audio_tokenizer=wave),
                           modules=lambda: [])
    decoder = SimpleNamespace(m=base, tokenizer=object(), cache=[], offset=0)
    duplex = SimpleNamespace(model=base, decoder=decoder, processor=FakeProcessor(), tokenizer=object(),
                             total_ids=[], break_event=threading.Event(), session_stop_event=threading.Event())
    torch = SimpleNamespace(get_rng_state=random.getstate, set_rng_state=random.setstate,
                            cuda=SimpleNamespace(get_rng_state=lambda d: random.getstate(),
                                                 set_rng_state=lambda s, d: random.setstate(s)))
    return NativeSessionBank(duplex, torch, SimpleNamespace(random=RandomAPI()), devices=(0,))


class StateIsolationTests(unittest.TestCase):
    def test_mutable_state_and_rng_resume_independently(self):
        b = fixture()
        b.create("A"); b.create("B")
        with b.activate("A", 0) as d:
            d.total_ids.append("a")
            d.decoder.cache.append("kv-a")
            d.model.audio_past_key_values.append("audio-a")
            d.model.tts.audio_tokenizer.stream_cache["x"] = "wave-a"
            d.processor.data["samples"].append(1)
            first = random.random()
        with b.activate("B", 0) as d:
            self.assertEqual(d.total_ids, [])
            self.assertEqual(d.decoder.cache, [])
            self.assertEqual(d.model.audio_past_key_values, [])
            self.assertEqual(d.model.tts.audio_tokenizer.stream_cache, {})
            self.assertEqual(d.processor.data["samples"], [])
            self.assertEqual(random.random(), first)
            d.total_ids.append("b")
        with b.activate("A", 1) as d:
            self.assertEqual(d.total_ids, ["a"])
            self.assertEqual(d.decoder.cache, ["kv-a"])
            self.assertEqual(d.model.audio_past_key_values, ["audio-a"])
            self.assertEqual(d.processor.data["samples"], [1])
        self.assertIsNot(b.sessions["A"].state["duplex"]["break_event"],
                         b.sessions["B"].state["duplex"]["break_event"])

    def test_failed_partial_unit_cannot_be_silently_retried(self):
        b = fixture(); b.create("A")
        with self.assertRaisesRegex(ValueError, "fail"):
            with b.activate("A", 0) as d:
                d.total_ids.append("partial")
                raise ValueError("fail")
        with self.assertRaisesRegex(RuntimeError, "failed previously"):
            with b.activate("A", 0): pass

    def test_order_and_late_created_fields_do_not_leak(self):
        b = fixture(); b.create("A"); b.create("B")
        with self.assertRaises(ValueError):
            with b.activate("A", 1): pass
        with b.activate("A", 0) as d: d.late_field = "A"
        with b.activate("B", 0) as d: self.assertFalse(hasattr(d, "late_field"))
        with b.activate("A", 1) as d: self.assertEqual(d.late_field, "A")


if __name__ == "__main__": unittest.main()
