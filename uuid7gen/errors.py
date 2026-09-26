"""uuid7gen 的公开异常类型。

**这个文件里的类名是契约的一部分，不要改**：调用方按 `Uuid7Error` 这一个基类
就能捕获本库抛出的所有错误。

`TimestampRangeError` 同时继承 `ValueError`，所以「时间戳越界」既满足
契约里的 `ValueError` 约定，又能被本库专属的异常类型区分出来。
"""


class Uuid7Error(Exception):
    """uuid7gen 抛出的所有错误的基类。"""


class TimestampRangeError(Uuid7Error, ValueError):
    """毫秒时间戳不在 `[0, 2**48)` 内（契约第 3 条）。"""
