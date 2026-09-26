"""uuid7gen —— 时间有序 ID（UUIDv7，RFC 9562 §5.7）生成库（Python 3，仅标准库）。

对外只暴露这几个名字：

    generate(clock=None, entropy=None, *, mono=True) -> int
    parse(value)        -> (timestamp_ms, version, variant, rand_a, rand_b)
    is_valid(value)     -> bool
    sort_key(value)     -> int
    Uuid7Error / TimestampRangeError
    clock.FakeClock / clock.SystemClock / clock.SystemEntropy

完整的语义约定见 README 的「对外契约」一节。
"""

from . import clock, layout
from .errors import TimestampRangeError, Uuid7Error
from .gen import generate, is_valid, parse, sort_key

__all__ = [
    "generate",
    "parse",
    "is_valid",
    "sort_key",
    "Uuid7Error",
    "TimestampRangeError",
    "clock",
    "layout",
]
__version__ = "0.1.0"
