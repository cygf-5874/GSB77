"""UUIDv7 的位布局（RFC 9562 §5.7）。

本文件当前是**空壳**：`pack()` 与 `unpack()` 的函数体只抛 `NotImplementedError`，
公开签名与常量已经是最终形态，不要改动签名与返回约定。

128 位从高到低切分（大端语义，最高 48 位是毫秒时间戳）：

    位区间   宽度  字段
    127..80  48    unix_ts_ms   毫秒时间戳
    79..76    4    ver          恒为 0b0111
    75..64   12    rand_a       单调计数器
    63..62    2    var          恒为 0b10
    61..0    62    rand_b       每次调用的随机位

语义细节全部在 README 的「对外契约」一节（第 2、3、7 条）。
"""

VERSION = 0b0111
VARIANT = 0b10

TS_BITS = 48
RAND_A_BITS = 12
RAND_B_BITS = 62

TS_MAX = (1 << TS_BITS) - 1
RAND_A_MAX = (1 << RAND_A_BITS) - 1
RAND_B_MAX = (1 << RAND_B_BITS) - 1


def pack(timestamp_ms, rand_a, rand_b):
    """把三个字段按 RFC 9562 §5.7 拼成一个 128 位无符号整数。"""
    raise NotImplementedError("not implemented")


def unpack(value):
    """把 128 位无符号整数拆成 `(timestamp_ms, version, variant, rand_a, rand_b)`。"""
    raise NotImplementedError("not implemented")
