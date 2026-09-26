"""既有用例。

这 12 个用例断言的是 README「对外契约」里的语义，**断言本身是契约的一部分，
不要修改**。起点状态下 `uuid7gen/gen.py` 与 `uuid7gen/layout.py` 全是空壳：
`generate()` 等公开函数直接抛 `NotImplementedError`，所以 12 个用例当前
全部是 error —— 这是预期起点。

跑法：

    python3 -m unittest discover -s tests
"""

import os
import sys
import threading
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid7gen import generate, is_valid, parse, sort_key  # noqa: E402
from uuid7gen.clock import FakeClock  # noqa: E402

TS_MASK = (1 << 48) - 1
RAND_A_MASK = (1 << 12) - 1
RAND_B_MASK = (1 << 62) - 1


class SeqEntropy:
    """确定性熵源：按给定序列依次返回 `rand_bits(n)` 的结果（用完从头循环）。"""

    def __init__(self, values):
        self._values = list(values)
        self._index = 0
        self.calls = []

    def rand_bits(self, n):
        self.calls.append(n)
        value = self._values[self._index % len(self._values)]
        self._index += 1
        return value & ((1 << n) - 1)


class TestUuid7gen(unittest.TestCase):
    # 契约 2：version / variant 位位置
    def test_01_layout_version_and_variant(self):
        clock = FakeClock(1_700_000_000_000)
        entropy = SeqEntropy([0x2AAAAAAAAAAAAAAA & RAND_B_MASK])
        value = generate(clock, entropy)
        self.assertTrue(0 <= value < (1 << 128))
        self.assertEqual(0b0111, (value >> 76) & 0xF)
        self.assertEqual(0b10, (value >> 62) & 0b11)

    # 契约 2、3：48 位时间戳占据最高 48 位
    def test_02_layout_timestamp_bits(self):
        clock = FakeClock(1_700_000_000_123)
        entropy = SeqEntropy([0x1555555555555555 & RAND_B_MASK])
        value = generate(clock, entropy)
        self.assertEqual(1_700_000_000_123, (value >> 80) & TS_MASK)

    # 契约 2、5、6：rand_a 计数器与 rand_b 随机位各就其位
    def test_03_layout_rand_a_and_rand_b_placement(self):
        clock = FakeClock(1_000_000)
        entropy = SeqEntropy([0x0000000000000001, 0x0000000000000002])
        first = generate(clock, entropy)
        second = generate(clock, entropy)
        self.assertEqual(0, (first >> 64) & RAND_A_MASK)
        self.assertEqual(0x0000000000000001, first & RAND_B_MASK)
        self.assertEqual(1, (second >> 64) & RAND_A_MASK)
        self.assertEqual(0x0000000000000002, second & RAND_B_MASK)
        self.assertGreater(second, first)

    # 契约 4、5：同一毫秒内严格递增
    def test_04_monotonic_within_same_ms(self):
        clock = FakeClock(5_000_000)
        entropy = SeqEntropy(list(range(1, 64)))
        values = [generate(clock, entropy) for _ in range(60)]
        for previous, current in zip(values, values[1:]):
            self.assertGreater(current, previous)
        for value in values:
            self.assertEqual(5_000_000, (value >> 80) & TS_MASK)

    # 契约 5：rand_a 用尽 4096 个取值后必须推进到下一毫秒
    def test_05_rand_a_exhaustion_advances_ms(self):
        clock = FakeClock(7_000_000)
        entropy = SeqEntropy([1])
        values = [generate(clock, entropy) for _ in range(4097)]
        self.assertEqual(0xFFF, (values[4095] >> 64) & RAND_A_MASK)
        self.assertEqual(7_000_000, (values[4095] >> 80) & TS_MASK)
        self.assertGreaterEqual(clock.sleep_calls, 1)
        self.assertEqual(7_000_001, (values[-1] >> 80) & TS_MASK)
        self.assertEqual(0, (values[-1] >> 64) & RAND_A_MASK)
        self.assertGreater(values[-1], values[4095])

    # 契约 4、5：跨毫秒仍然严格递增，且新毫秒内 rand_a 从 0 重新开始
    def test_06_monotonic_across_ms(self):
        clock = FakeClock(1_000_000)
        entropy = SeqEntropy([3])
        first = generate(clock, entropy)
        clock.advance(5)
        second = generate(clock, entropy)
        self.assertGreater(second, first)
        self.assertEqual(1_000_005, (second >> 80) & TS_MASK)
        self.assertEqual(0, (second >> 64) & RAND_A_MASK)
        third = generate(clock, entropy)
        self.assertGreater(third, second)
        self.assertEqual(1_000_005, (third >> 80) & TS_MASK)

    # 契约 7：parse 与 generate 严格互逆
    def test_07_parse_is_inverse_of_generate(self):
        clock = FakeClock(1_700_000_000_123)
        rand_b_values = [0x0123456789ABCDEF, 0x0FEDCBA987654321, 0x00000000000000AA]
        entropy = SeqEntropy(rand_b_values)
        values = [generate(clock, entropy) for _ in range(3)]
        for index, value in enumerate(values):
            ts, version, variant, rand_a, rand_b = parse(value)
            self.assertEqual(1_700_000_000_123, ts)
            self.assertEqual(0b0111, version)
            self.assertEqual(0b10, variant)
            self.assertEqual(index, rand_a)
            self.assertEqual(rand_b_values[index] & RAND_B_MASK, rand_b)

    # 契约 8：is_valid 正反例
    def test_08_is_valid_accepts_and_rejects(self):
        value = generate(FakeClock(42), SeqEntropy([7]))
        self.assertTrue(is_valid(value))
        self.assertFalse(is_valid(value & ~(0xF << 76)))
        self.assertFalse(is_valid(value & ~(0b11 << 62)))
        self.assertFalse(is_valid(1 << 128))
        self.assertFalse(is_valid(-1))
        self.assertFalse(is_valid(uuid.uuid4().int))
        handmade = (12345 << 80) | (0b0111 << 76) | (0xABC << 64) | (0b10 << 62) | 0x123456
        self.assertTrue(is_valid(handmade))

    # 契约 9：sort_key 与「时间戳 -> rand_a -> rand_b」排序一致
    def test_09_sort_key_orders_by_fields(self):
        def make(ts, rand_a, rand_b):
            return (ts << 80) | (0b0111 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b

        a = make(100, 0, 5)
        b = make(100, 0, 9)
        c = make(100, 1, 0)
        d = make(101, 0, 0)
        self.assertEqual([a, b, c, d], sorted([d, c, b, a], key=sort_key))
        self.assertLess(sort_key(a), sort_key(b))
        self.assertLess(sort_key(c), sort_key(d))

    # 契约 6、10：注入固定时钟与熵源时输出逐位可预测
    def test_10_injected_clock_and_entropy_are_reproducible(self):
        def run():
            clock = FakeClock(1_700_000_000_000)
            entropy = SeqEntropy([0x1111111111111111, 0x2222222222222222,
                                  0x3333333333333333, 0x4444444444444444])
            return [generate(clock, entropy) for _ in range(4)]

        self.assertEqual(run(), run())

    # 契约 3：时间戳越界必须拒绝
    def test_11_timestamp_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            generate(FakeClock(-1), SeqEntropy([1]))
        with self.assertRaises(ValueError):
            generate(FakeClock(1 << 48), SeqEntropy([1]))
        with self.assertRaises(ValueError):
            generate(FakeClock((1 << 48) + 12345), SeqEntropy([1]))

    # 契约 11：多线程并发生成不得重复、不得破坏单调性
    def test_12_concurrent_generate_unique_and_monotonic(self):
        clock = FakeClock(1_000_000)
        entropy = SeqEntropy(list(range(1, 512)))
        barrier = threading.Barrier(8)
        per_thread = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=30)
                produced = [generate(clock, entropy) for _ in range(500)]
                per_thread.append(produced)
            except Exception as exc:  # noqa: BLE001 - 线程里的异常也要带回主线程
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

        if errors:
            raise errors[0]
        self.assertEqual(8, len(per_thread))
        everything = [value for produced in per_thread for value in produced]
        self.assertEqual(4000, len(everything))
        self.assertEqual(4000, len(set(everything)))
        for produced in per_thread:
            for previous, current in zip(produced, produced[1:]):
                self.assertGreater(current, previous)


if __name__ == "__main__":
    unittest.main()
