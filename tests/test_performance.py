"""
The speed-ups must not change any result: dates parse exactly as pandas parses them, cached file
reads match fresh reads, and a remote model is asked each question once, with its answers ending up
in the same places as before.
"""
import json
import os
import random
import tempfile
import threading
import time
import types
import unittest
import warnings

import numpy as np
import pandas as pd

from agents.intake_agent.intake_agent import SYSTEM_INSTRUCTION
from agents.transformation_agent.transformation_agent import parse_dates
from backend.core import llm
from backend.utils import file_utils
from tests.test_platform_regressions import PlatformTestCase


def _pandas_dates(series):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors="coerce", format="mixed")


def _outcome(fn, series):
    try:
        return fn(series)
    except Exception as e:
        return (type(e).__name__, str(e))


class TestParseDates(unittest.TestCase):
    POOLS = {
        "formats": ["05/01/2024", "Jan 5, 2024", "31/12/2024", "12/31/2024", "2024", "Q1 2024", "2024-02-30", "Tuesday", "5 Jan 24", "", "  "],
        "nulls": ["2024-01-05", "Jan 6, 2023", "bad", None, np.nan, ""],
        "one_timezone": ["2024-01-05T10:00:00Z", "2024-02-05T11:00:00Z", "bad", ""],
        "same_offset": ["2024-01-05 10:00:00+05:30", "2024-03-05 10:00:00+05:30", "nope"],
        "mixed_timezones": ["2024-01-05", "2024-01-05 10:00:00+05:30", "2024-01-05T10:00:00Z"],
        "epochs_as_text": ["1700000000", "1600000000", "abc"],
    }

    def test_matches_pandas(self):
        rng = random.Random(7)
        for name, pool in self.POOLS.items():
            for size in (50, 3000):
                series = pd.Series([rng.choice(pool) for _ in range(size)], name="d", index=range(9, 9 + size))
                for variant in (series, series.astype("string")):
                    expected, got = _outcome(_pandas_dates, variant), _outcome(parse_dates, variant)
                    if isinstance(expected, tuple) or isinstance(got, tuple):
                        self.assertEqual(expected, got, name)
                        continue
                    self.assertEqual(expected.dtype, got.dtype, name)
                    self.assertTrue(expected.index.equals(got.index), name)
                    self.assertEqual(expected.name, got.name)
                    self.assertTrue(expected.equals(got), name)


class TestReadCache(unittest.TestCase):
    def test_copies_and_edits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.csv")
            with open(path, "w") as f:
                f.write("id,name\n1,abc\n2,def\n")
            first = file_utils.read_dataset(path)
            first.loc[0, "name"] = "changed"
            # A caller changing its copy does not change what the next caller reads
            self.assertEqual(file_utils.read_dataset(path).loc[0, "name"], "abc")
            # An edit of the same size is seen even when the modification time does not change
            stat = os.stat(path)
            with open(path, "w") as f:
                f.write("id,name\n1,xyz\n2,def\n")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(file_utils.read_dataset(path).loc[0, "name"], "xyz")
            self.assertTrue(file_utils.read_dataset(path, nrows=1).equals(pd.read_csv(path, nrows=1)))


class FakeGemini:
    """A remote model that takes a moment to answer, with the offline engine's (deterministic) answers."""

    def __init__(self, delay=0.2):
        self.delay = delay
        self.prompts = []
        self.lock = threading.Lock()

    def invoke(self, messages):
        system = next((c for r, c in messages if r == "system"), None)
        prompt = next(c for r, c in messages if r == "user")
        with self.lock:
            self.prompts.append(prompt)
        time.sleep(self.delay)
        return types.SimpleNamespace(content=llm.run_mock_engine(prompt, system, "JSON" in prompt))


class RemoteModel:
    """Points query_llm at a FakeGemini for the duration of a test."""

    def __init__(self, cache=False, delay=0.2):
        self.model = FakeGemini(delay)
        self.cache = cache

    def __enter__(self):
        self.saved = (llm.LLM_PROVIDER, llm.gemini_models, llm._ollama_circuit_open_until, llm.LLM_CACHE)
        llm.LLM_PROVIDER = "gemini"
        llm.gemini_models = [("fake-gemini", self.model)]
        llm._ollama_circuit_open_until = time.time() + 3600
        llm.LLM_CACHE = self.cache
        llm._answer_cache.clear()
        return self.model

    def __exit__(self, *exc):
        llm.LLM_PROVIDER, llm.gemini_models, llm._ollama_circuit_open_until, llm.LLM_CACHE = self.saved
        llm._answer_cache.clear()
        llm._inflight.clear()


class TestModelQueries(unittest.TestCase):
    def test_prefetched_answer_is_used_once(self):
        with RemoteModel() as model:
            llm.prefetch_llm("Profile this. Return ONLY valid JSON.", "sys", json_mode=True)
            answer = llm.query_llm("Profile this. Return ONLY valid JSON.", "sys", json_mode=True)
            self.assertTrue(llm.is_real_llm_available())
            self.assertEqual(len(model.prompts), 1)
            # Without the cache, asking again is a new question
            llm.query_llm("Profile this. Return ONLY valid JSON.", "sys", json_mode=True)
            self.assertEqual(len(model.prompts), 2)
            self.assertEqual(answer, llm.run_mock_engine("Profile this. Return ONLY valid JSON.", "sys", True))

    def test_cached_answer(self):
        with RemoteModel(cache=True) as model:
            first = llm.query_llm("Summarize. Return ONLY valid JSON.", "sys", json_mode=True)
            second = llm.query_llm("Summarize. Return ONLY valid JSON.", "sys", json_mode=True)
            self.assertEqual(first, second)
            self.assertEqual(len(model.prompts), 1)
            self.assertTrue(llm.is_real_llm_available())

    def test_identical_queries_at_once_share_one_answer(self):
        with RemoteModel(delay=0.5) as model:
            answers = []
            threads = [threading.Thread(target=lambda: answers.append(llm.query_llm("Same question", "sys"))) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(set(answers)), 1)
            self.assertEqual(len(model.prompts), 1)


SALES = b"sale_id,order_id,product_id,quantity,unit_price,total_price,sale_date\nS1,O1,P1,2,5.0,10.0,2024-01-05\nS2,O2,P2,,3.0,9.0,2024-01-06\nS3,O3,P3,1,,4.0,bad date\n"


class TestPipelineWithRemoteModel(PlatformTestCase):
    def test_each_question_is_asked_once_and_answers_land_as_before(self):
        with RemoteModel() as model:
            status = self.run_pipeline(self.alice, "perf_sales.csv", SALES)
        self.assertIn(status["status"], ("Success", "Passed with Warnings"))
        # Intake recommendations, storage format and executive summary; no transformation narration
        self.assertEqual(len(model.prompts), 3, [p.strip()[:60] for p in model.prompts])
        intake_prompt = next(p for p in model.prompts if "recommended_transformations" in p)
        expected = json.loads(llm.run_mock_engine(intake_prompt, SYSTEM_INSTRUCTION, True))["recommended_transformations"]
        self.assertEqual(status["stages"]["intake"]["metadata"]["recommended_transformations"], expected)
        report = json.load(open(status["stages"]["report"]["output"]["json_path"], encoding="utf-8"))
        self.assertIn(json.dumps(expected), json.dumps(report))
