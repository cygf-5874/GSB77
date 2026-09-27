"""UUIDv7 的生成、解析与排序（RFC 9562 §5.7）。

本文件当前是**空壳**：`generate` / `parse` / `is_valid` / `sort_key` 的函数体
只抛 `NotImplementedError`，公开签名已经是最终形态，不要改动签名。

语义细节全部在 README 的「对外契约」一节（第 1、3～11 条）。
时间与随机位都从注入的 `clock` / `entropy` 里取（见 `uuid7gen.clock`）：
缺省用 `SystemClock` / `SystemEntropy`，但实现里不得直接调用真实时钟与 `secrets`。
"""

from .clock import SystemClock, SystemEntropy  # noqa: F401  （缺省适配器）
from .errors import TimestampRangeError
from .layout import (
    RAND_A_BITS,
    RAND_A_MAX,
    RAND_B_BITS,
    RAND_B_MAX,
    TS_MAX,
    VARIANT,
    VERSION,
    pack,
    unpack,
)

import threading
import weakref

_DEFAULT_CLOCK = SystemClock()
_DEFAULT_ENTROPY = SystemEntropy()

# 一把全局锁：让「读时钟 -> 推进计数器 -> 取随机位」整体原子，
# 并发生成时既不会重复，也不会破坏任何单线程看到的单调性。
_LOCK = threading.Lock()


class _MonoState:
    """单个 clock 实例上的单调序列状态（契约第 5 条）。"""

    __slots__ = ("timestamp_ms", "rand_a")

    def __init__(self):
        self.timestamp_ms = -1
        self.rand_a = -1


# 单调状态按 clock 实例隔离；弱引用键避免时钟被回收后状态泄漏。
_STATES = weakref.WeakKeyDictionary()


def _state_for(clock):
    state = _STATES.get(clock)
    if state is None:
        state = _MonoState()
        _STATES[clock] = state
    return state


def _check_timestamp(timestamp_ms):
    if not 0 <= timestamp_ms <= TS_MAX:
        raise TimestampRangeError(
            "毫秒时间戳必须在 [0, 2**48) 内，得到 %r" % (timestamp_ms,)
        )


def generate(clock=None, entropy=None, *, mono=True):
    """生成一个 UUIDv7，返回 128 位无符号整数。"""
    if clock is None:
        clock = _DEFAULT_CLOCK
    if entropy is None:
        entropy = _DEFAULT_ENTROPY

    if not mono:
        timestamp_ms = clock.now_ms()
        _check_timestamp(timestamp_ms)
        rand_a = entropy.rand_bits(RAND_A_BITS) & RAND_A_MAX
        rand_b = entropy.rand_bits(RAND_B_BITS) & RAND_B_MAX
        return pack(timestamp_ms, rand_a, rand_b)

    with _LOCK:
        state = _state_for(clock)
        now = clock.now_ms()
        _check_timestamp(now)
        if now > state.timestamp_ms:
            # 时钟前进（或首次调用）：新毫秒，计数器归零。
            state.timestamp_ms = now
            state.rand_a = 0
        else:
            # 同一毫秒或时钟回拨：沿用上一时间戳，计数器递增。
            state.rand_a += 1
            if state.rand_a > RAND_A_MAX:
                # 12 位计数器用尽：推进到下一毫秒再归零，绝不回绕。
                advanced = clock.sleep_until_next_ms()
                _check_timestamp(advanced)
                state.timestamp_ms = max(advanced, state.timestamp_ms + 1)
                state.rand_a = 0
        rand_b = entropy.rand_bits(RAND_B_BITS) & RAND_B_MAX
        return pack(state.timestamp_ms, state.rand_a, rand_b)


def parse(value):
    """把 128 位值拆成 `(timestamp_ms, version, variant, rand_a, rand_b)`。"""
    if isinstance(value, int):
        integer = value
    else:
        wrapped = getattr(value, "int", None)
        if isinstance(wrapped, int):
            integer = wrapped
        else:
            raise TypeError(
                "value 必须是 int 或带 int 属性的 128 位包装，得到 %s"
                % type(value).__name__
            )
    return unpack(integer)


def is_valid(value):
    """`value` 是否是合法 UUIDv7（version==7、variant==0b10、128 位宽）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if not 0 <= value < (1 << 128):
        return False
    _ts, version, variant, _rand_a, _rand_b = unpack(value)
    return version == VERSION and variant == VARIANT


def sort_key(value):
    """返回一个可按无符号整数排序的键。"""
    timestamp_ms, _version, _variant, rand_a, rand_b = parse(value)
    return (
        (timestamp_ms << (RAND_A_BITS + RAND_B_BITS))
        | (rand_a << RAND_B_BITS)
        | rand_b
    )
