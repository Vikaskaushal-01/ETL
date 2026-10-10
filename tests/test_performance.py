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
