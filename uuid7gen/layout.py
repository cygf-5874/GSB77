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
    return (
        (timestamp_ms << 80)
        | (VERSION << 76)
        | (rand_a << 64)
        | (VARIANT << 62)
        | rand_b
    )


def unpack(value):
    """把 128 位无符号整数拆成 `(timestamp_ms, version, variant, rand_a, rand_b)`。"""
    if not isinstance(value, int):
        raise TypeError("value 必须是 int，得到 %s" % type(value).__name__)
    if not 0 <= value < (1 << 128):
        raise ValueError("value 必须在 [0, 2**128) 内，得到 %r" % (value,))
    timestamp_ms = (value >> 80) & TS_MAX
    version = (value >> 76) & 0xF
    rand_a = (value >> 64) & RAND_A_MAX
    variant = (value >> 62) & 0b11
    rand_b = value & RAND_B_MAX
    return (timestamp_ms, version, variant, rand_a, rand_b)
