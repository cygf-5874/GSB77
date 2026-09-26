"""可注入的时钟与熵源 —— uuid7gen 的 I/O 边界。

`generate()` 只通过这些接口拿时间与随机位，因此测试可以把时间与随机源完全
钉死：判据不依赖墙钟、不依赖真随机。

本文件是**已给好的基础设施**（无缺陷），正常不需要修改。固定验收程序会注入
它自己的时钟与熵源，改这里不会让判定变绿。

接口约定：

    Clock.now_ms()                -> int  当前的 Unix 毫秒时间戳
    Clock.sleep_until_next_ms()   -> int  推进到下一个毫秒，返回新的 now_ms()
    Entropy.rand_bits(n)          -> int  返回 n 个随机位（0 <= r < 2**n）
"""

import secrets
import time


class Clock:
    """时钟接口。实现只需提供下面两个方法。"""

    def now_ms(self):
        """当前 Unix 毫秒时间戳（int）。"""
        raise NotImplementedError("clock.now_ms")

    def sleep_until_next_ms(self):
        """推进到下一个毫秒，返回推进后的 `now_ms()`。"""
        raise NotImplementedError("clock.sleep_until_next_ms")


class FakeClock(Clock):
    """确定性时钟：由调用方显式推进，完全不读墙钟。"""

    def __init__(self, start_ms=0):
        self._now_ms = int(start_ms)
        self.sleep_calls = 0        # sleep_until_next_ms() 被调用了多少次
        self.sleep_history = []     # 每次推进后的时间戳

    def now_ms(self):
        return self._now_ms

    def sleep_until_next_ms(self):
        self.sleep_calls += 1
        self._now_ms += 1
        self.sleep_history.append(self._now_ms)
        return self._now_ms

    def advance(self, delta_ms):
        """把时钟手动往前拨 `delta_ms` 毫秒（测试用），返回新的时间戳。"""
        self._now_ms += int(delta_ms)
        return self._now_ms


class SystemClock(Clock):
    """真实时钟（`generate()` 的缺省时钟）。"""

    def now_ms(self):
        return time.time_ns() // 1_000_000

    def sleep_until_next_ms(self):
        target = self.now_ms() + 1
        while self.now_ms() < target:
            time.sleep(0.0002)
        return self.now_ms()


class Entropy:
    """熵源接口：`rand_bits(n)` 返回 n 个随机位（0 <= r < 2**n）。"""

    def rand_bits(self, n):
        raise NotImplementedError("entropy.rand_bits")


class SystemEntropy(Entropy):
    """真实熵源（`generate()` 的缺省熵源，基于 `secrets`）。"""

    def rand_bits(self, n):
        return secrets.randbits(n)
