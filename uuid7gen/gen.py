"""UUIDv7 的生成、解析与排序（RFC 9562 §5.7）。

语义细节全部在 README 的「对外契约」一节（第 1、3～11 条）。
时间与随机位都从注入的 `clock` / `entropy` 里取（见 `uuid7gen.clock`）：
缺省用 `SystemClock` / `SystemEntropy`，但实现里不得直接调用真实时钟与 `secrets`。

单调性设计（契约第 4、5、11 条）：

- 单调状态（上一毫秒 + `rand_a` 计数器）按 `clock` 实例隔离，存于
  `_mono_states`（`WeakKeyDictionary`，键是 clock 对象本身）；
  `clock=None` 时共用同一个进程级默认时钟，因此缺省路径仍是一条连续序列。
- 所有状态读写、时钟推进与熵源取值都在同一把锁内完成，因此并发下
  全局序列严格递增，任一线程拿到的子序列也严格递增且无重复。
- 时钟回拨（`now_ms` 小于上一毫秒）时沿用上一毫秒继续递增计数器，
  保证返回值严格大于上一次。
"""

import threading
import weakref

from . import layout
from .clock import SystemClock, SystemEntropy  # noqa: F401  （缺省适配器）

_DEFAULT_CLOCK = SystemClock()
_DEFAULT_ENTROPY = SystemEntropy()

_lock = threading.Lock()
_mono_states = weakref.WeakKeyDictionary()


def _mono_state(clock):
    """取 `clock` 实例专属的单调状态 `[last_ms, rand_a]`，没有则新建。"""
    state = _mono_states.get(clock)
    if state is None:
        state = [-1, 0]
        _mono_states[clock] = state
    return state


def _next_mono_fields(clock):
    """在锁内推进单调状态，返回 `(timestamp_ms, rand_a)`。"""
    now_ms = layout.check_timestamp(clock.now_ms())
    state = _mono_state(clock)
    last_ms, rand_a = state
    if now_ms > last_ms:
        state[0] = now_ms
        state[1] = 0
        return now_ms, 0
    # 同一毫秒或时钟回拨：沿用上一毫秒，计数器递增。
    rand_a += 1
    if rand_a > layout.RAND_A_MAX:
        # 12 位计数器用尽：推进到下一毫秒，计数器归零继续。
        slept_ms = layout.check_timestamp(clock.sleep_until_next_ms())
        now_ms = slept_ms if slept_ms > last_ms else last_ms + 1
        layout.check_timestamp(now_ms)
        state[0] = now_ms
        state[1] = 0
        return now_ms, 0
    state[1] = rand_a
    return last_ms, rand_a


def generate(clock=None, entropy=None, *, mono=True):
    """生成一个 UUIDv7，返回 128 位无符号整数。"""
    if clock is None:
        clock = _DEFAULT_CLOCK
    if entropy is None:
        entropy = _DEFAULT_ENTROPY
    if not mono:
        timestamp_ms = layout.check_timestamp(clock.now_ms())
        rand_a = entropy.rand_bits(layout.RAND_A_BITS)
        rand_b = entropy.rand_bits(layout.RAND_B_BITS)
        return layout.pack(timestamp_ms, rand_a, rand_b)
    with _lock:
        timestamp_ms, rand_a = _next_mono_fields(clock)
        rand_b = entropy.rand_bits(layout.RAND_B_BITS)
        return layout.pack(timestamp_ms, rand_a, rand_b)


def parse(value):
    """把 128 位值拆成 `(timestamp_ms, version, variant, rand_a, rand_b)`。"""
    if isinstance(value, int) and not isinstance(value, bool):
        raw = value
    elif hasattr(value, "int"):
        raw = value.int  # uuid.UUID 等带 int 属性的 128 位包装
    else:
        raise TypeError(
            "value 必须是 int 或带 int 属性的 128 位包装，收到 %r"
            % type(value).__name__)
    if not isinstance(raw, int):
        raise TypeError("value.int 必须是 int，收到 %r" % type(raw).__name__)
    return layout.unpack(raw)


def is_valid(value):
    """`value` 是否是合法 UUIDv7（version==7、variant==0b10、128 位宽）。"""
    try:
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        _ts, version, variant, _rand_a, _rand_b = layout.unpack(value)
        return version == layout.VERSION and variant == layout.VARIANT
    except Exception:  # noqa: BLE001 - 契约第 8 条：任何输入都不抛异常
        return False


def sort_key(value):
    """返回一个可按无符号整数排序的键（时间戳 -> rand_a -> rand_b）。"""
    timestamp_ms, _version, _variant, rand_a, rand_b = parse(value)
    return ((timestamp_ms << (layout.RAND_A_BITS + layout.RAND_B_BITS))
            | (rand_a << layout.RAND_B_BITS)
            | rand_b)
