from pathlib import Path
import sys

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import numpy as np
import pytest
from walkie.audio_engine import JitterBuffer


def test_jitter_buffer_push_pop():
    jb = JitterBuffer(min_depth=2, max_depth=5)
    frame = np.zeros(960, dtype=np.int16)
    jb.push(frame)
    result = jb.pop()
    assert result is None


def test_jitter_buffer_min_depth():
    jb = JitterBuffer(min_depth=2, max_depth=5)
    frame = np.zeros(960, dtype=np.int16)
    jb.push(frame)
    assert jb.pop() is None
    jb.push(frame)
    result = jb.pop()
    assert result is not None


def test_jitter_buffer_fifo():
    jb = JitterBuffer(min_depth=1, max_depth=5)
    f1 = np.ones(960, dtype=np.int16) * 1
    f2 = np.ones(960, dtype=np.int16) * 2
    jb.push(f1)
    jb.push(f2)
    r1 = jb.pop()
    r2 = jb.pop()
    assert r1[0] == 1
    assert r2[0] == 2


def test_jitter_buffer_overflow():
    jb = JitterBuffer(min_depth=1, max_depth=3)
    frames = [np.ones(960, dtype=np.int16) * i for i in range(5)]
    for f in frames:
        jb.push(f)
    result = jb.pop()
    assert result is not None


def test_jitter_buffer_clear():
    jb = JitterBuffer(min_depth=1, max_depth=5)
    jb.push(np.zeros(960, dtype=np.int16))
    jb.clear()
    result = jb.pop()
    assert result is None


def test_jitter_buffer_drain_refill():
    jb = JitterBuffer(min_depth=1, max_depth=5)
    frame = np.ones(960, dtype=np.int16)
    jb.push(frame)
    r1 = jb.pop()
    assert r1 is not None
    r2 = jb.pop()
    assert r2 is None
