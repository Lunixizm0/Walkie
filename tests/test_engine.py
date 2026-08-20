from pathlib import Path
import sys

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import threading
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


def test_jitter_buffer_min_depth_zero():
    jb = JitterBuffer(min_depth=0, max_depth=5)
    frame = np.zeros(960, dtype=np.int16)
    jb.push(frame)
    result = jb.pop()
    assert result is not None


def test_jitter_buffer_max_depth_one():
    jb = JitterBuffer(min_depth=1, max_depth=1)
    f1 = np.ones(960, dtype=np.int16) * 1
    f2 = np.ones(960, dtype=np.int16) * 2
    jb.push(f1)
    jb.push(f2)
    r1 = jb.pop()
    assert r1[0] == 2


def test_jitter_buffer_pop_order_preserved():
    jb = JitterBuffer(min_depth=1, max_depth=10)
    for i in range(10):
        jb.push(np.ones(960, dtype=np.int16) * i)
    for i in range(10):
        r = jb.pop()
        assert r is not None
        assert r[0] == i


def test_jitter_buffer_clear_and_refill():
    jb = JitterBuffer(min_depth=2, max_depth=5)
    jb.push(np.ones(960, dtype=np.int16) * 1)
    jb.push(np.ones(960, dtype=np.int16) * 2)
    jb.clear()
    assert jb.pop() is None
    jb.push(np.ones(960, dtype=np.int16) * 3)
    assert jb.pop() is None
    jb.push(np.ones(960, dtype=np.int16) * 4)
    r = jb.pop()
    assert r is not None
    assert r[0] == 3


def test_jitter_buffer_many_pushes_then_pops():
    jb = JitterBuffer(min_depth=1, max_depth=100)
    for i in range(100):
        jb.push(np.ones(960, dtype=np.int16) * (i % 256))
    results = []
    for _ in range(50):
        r = jb.pop()
        if r is not None:
            results.append(int(r[0]))
    assert len(results) > 0
    assert results == sorted(results)


def test_jitter_buffer_concurrent_push_pop():
    jb = JitterBuffer(min_depth=5, max_depth=50)
    errors = []

    def producer():
        try:
            for i in range(200):
                jb.push(np.ones(960, dtype=np.int16) * (i % 256))
        except Exception as e:
            errors.append(e)

    def consumer():
        try:
            popped = 0
            while popped < 100:
                r = jb.pop()
                if r is not None:
                    popped += 1
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=producer)
    t2 = threading.Thread(target=consumer)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert len(errors) == 0


def test_jitter_buffer_concurrent_multiple_producers():
    jb = JitterBuffer(min_depth=1, max_depth=300)
    errors = []

    def producer(n):
        try:
            for i in range(50):
                jb.push(np.ones(960, dtype=np.int16) * n)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=producer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert len(errors) == 0
    count = 0
    while jb.pop() is not None:
        count += 1
    assert count == 200


def test_jitter_buffer_frame_shape():
    jb = JitterBuffer(min_depth=1, max_depth=5)
    frame = np.zeros(960, dtype=np.int16)
    jb.push(frame)
    result = jb.pop()
    assert result.shape == (960,)


def test_jitter_buffer_2d_frame():
    jb = JitterBuffer(min_depth=1, max_depth=5)
    frame = np.zeros((960, 1), dtype=np.int16)
    jb.push(frame)
    result = jb.pop()
    assert result is not None
