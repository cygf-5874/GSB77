"""UUIDv7 的生成、解析与排序（RFC 9562 §5.7）。

本文件当前是**空壳**：`generate` / `parse` / `is_valid` / `sort_key` 的函数体
只抛 `NotImplementedError`，公开签名已经是最终形态，不要改动签名。

语义细节全部在 README 的「对外契约」一节（第 1、3～11 条）。
时间与随机位都从注入的 `clock` / `entropy` 里取（见 `uuid7gen.clock`）：
缺省用 `SystemClock` / `SystemEntropy`，但实现里不得直接调用真实时钟与 `secrets`。
"""

from .clock import SystemClock, SystemEntropy  # noqa: F401  （缺省适配器）


def generate(clock=None, entropy=None, *, mono=True):
    """生成一个 UUIDv7，返回 128 位无符号整数。"""
    raise NotImplementedError("not implemented")


def parse(value):
    """把 128 位值拆成 `(timestamp_ms, version, variant, rand_a, rand_b)`。"""
    raise NotImplementedError("not implemented")


def is_valid(value):
    """`value` 是否是合法 UUIDv7（version==7、variant==0b10、128 位宽）。"""
    raise NotImplementedError("not implemented")


def sort_key(value):
    """返回一个可按无符号整数排序的键。"""
    raise NotImplementedError("not implemented")
