#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uuid7gen 的固定验收程序。**别改这个文件。**

用法：
    python3 check.py                     跑全部 11 个场景
    python3 check.py -list               列出全部场景
    python3 check.py --only monotonic    只跑一组（layout / monotonic / fields / injection / concurrency）
    python3 check.py --only fields,injection

输出：
    逐场景 `PASS <组>/<名>` 或 `FAIL <组>/<名>  期望=… 实际=…`
    结尾 `结果：通过 x/N`；全过 exit 0，否则 exit 1。
    失败不早退，一次把问题全暴露。

判据完全确定：时钟与熵源都是本程序自己注入的确定性实现，不读墙钟、不依赖
随机源；并发场景用 `threading.Barrier` 凑齐 8 个线程再放行。
只依赖标准库。`injection` 组会静态扫描 `uuid7gen/` 下**除 clock.py 外**的
实现模块，确认它们没有直接调用真实时钟与 `secrets`。
"""

import ast
import io
import os
import sys
import threading
import tokenize
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:  # pragma: no cover - 老解释器没有 reconfigure
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TS_MASK = (1 << 48) - 1
RAND_A_MASK = (1 << 12) - 1
RAND_B_MASK = (1 << 62) - 1
VERSION = 0b0111
VARIANT = 0b10

CONCURRENCY_THREADS = 8
CONCURRENCY_PER_THREAD = 500
CONCURRENCY_TIMEOUT = 30


# --------------------------------------------------------------- 基础设施

class CheckFailure(Exception):
    def __init__(self, what, expected="-", actual="-"):
        super().__init__(what)
        self.what = what
        self.expected = expected
        self.actual = actual


def brief(value, limit=220):
    text = value if isinstance(value, str) else repr(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def need(condition, what, expected="成立", actual="不成立"):
    if not condition:
        raise CheckFailure(what, expected, actual)


def eq(label, got, want):
    if got != want:
        raise CheckFailure(label, brief(want), brief(got))


def lib():
    """延迟导入待测库：导入失败按场景失败处理，而不是让整程序崩掉。"""
    try:
        import uuid7gen
    except Exception as exc:  # noqa: BLE001
        raise CheckFailure("导入 uuid7gen 失败", "-", "%s: %s" % (type(exc).__name__, exc))
    return uuid7gen


class FakeClock:
    """确定性时钟：由固定件显式推进，完全不读墙钟。"""

    def __init__(self, start_ms=0):
        self._now_ms = int(start_ms)
        self.sleep_calls = 0

    def now_ms(self):
        return self._now_ms

    def sleep_until_next_ms(self):
        self.sleep_calls += 1
        self._now_ms += 1
        return self._now_ms

    def advance(self, delta_ms):
        self._now_ms += int(delta_ms)
        return self._now_ms


class SeqEntropy:
    """确定性熵源：按给定序列依次返回 `rand_bits(n)`（用完从头循环）。"""

    def __init__(self, values):
        self._values = list(values)
        self._index = 0

    def rand_bits(self, n):
        value = self._values[self._index % len(self._values)]
        self._index += 1
        return value & ((1 << n) - 1)


# ------------------------------------------------------------------- layout

def layout_version_variant_bit_positions():
    generate = lib().generate
    value = generate(FakeClock(1_700_000_000_000), SeqEntropy([0x2AAAAAAAAAAAAAAA]))
    need(isinstance(value, int) and 0 <= value < (1 << 128),
         "generate 必须返回 128 位无符号整数", "0 <= value < 2**128", brief(value))
    eq("version 位（79..76）", (value >> 76) & 0xF, VERSION)
    eq("variant 位（63..62）", (value >> 62) & 0b11, VARIANT)


def layout_timestamp_48bit_encoding():
    generate = lib().generate
    ts = 0x0123456789AB  # 一个 48 位时间戳
    rand_b = 0x1555555555555555 & RAND_B_MASK
    value = generate(FakeClock(ts), SeqEntropy([rand_b]))
    expected = (ts << 80) | (VERSION << 76) | (0 << 64) | (VARIANT << 62) | rand_b
    eq("固定时钟 + 固定熵源下与手工构造的整数逐位相同", value, expected)
    eq("最高 48 位就是时间戳", (value >> 80) & TS_MASK, ts)

    top = generate(FakeClock(TS_MASK), SeqEntropy([0]))
    eq("时间戳上界 2**48-1 可编码", (top >> 80) & TS_MASK, TS_MASK)


def layout_random_bits_placement():
    generate = lib().generate
    clock = FakeClock(42)
    entropy = SeqEntropy([0x0000000000000001, 0x0000000000000002])
    first = generate(clock, entropy)
    second = generate(clock, entropy)
    eq("第一个 ID 的 rand_a", (first >> 64) & RAND_A_MASK, 0)
    eq("第一个 ID 的 rand_b 落位", first & RAND_B_MASK, 1)
    eq("第二个 ID 的 rand_a", (second >> 64) & RAND_A_MASK, 1)
    eq("第二个 ID 的 rand_b 落位", second & RAND_B_MASK, 2)
    need(second > first, "同一毫秒内第二个 ID 必须更大", "second > first", brief((first, second)))


# ---------------------------------------------------------------- monotonic

def monotonic_strict_increase_within_same_ms():
    generate = lib().generate
    clock = FakeClock(5_000_000)
    entropy = SeqEntropy([1])
    values = [generate(clock, entropy) for _ in range(64)]
    for index, (previous, current) in enumerate(zip(values, values[1:])):
        need(current > previous, "同一毫秒内必须严格递增（第 %d 次）" % (index + 1),
             "current > previous", brief((previous, current)))
    for value in values:
        eq("同一毫秒内时间戳不变", (value >> 80) & TS_MASK, 5_000_000)
    eq("同一毫秒内第一个 ID 的 rand_a 从 0 起", (values[0] >> 64) & RAND_A_MASK, 0)
    eq("同一毫秒内第 64 个 ID 的 rand_a", (values[63] >> 64) & RAND_A_MASK, 63)


def monotonic_rand_a_exhaustion_advances_ms():
    generate = lib().generate
    clock = FakeClock(7_000_000)
    entropy = SeqEntropy([1])
    values = [generate(clock, entropy) for _ in range(4096)]
    eq("用尽 4096 个取值前不该调 sleep_until_next_ms", clock.sleep_calls, 0)
    eq("第 4096 个 ID 的 rand_a", (values[4095] >> 64) & RAND_A_MASK, 0xFFF)
    eq("第 4096 个 ID 的时间戳", (values[4095] >> 80) & TS_MASK, 7_000_000)

    nxt = generate(clock, entropy)
    need(clock.sleep_calls >= 1, "rand_a 用尽后必须调用 clock.sleep_until_next_ms()",
         "sleep_calls >= 1", brief(clock.sleep_calls))
    eq("推进后时间戳前进一毫秒", (nxt >> 80) & TS_MASK, 7_000_001)
    eq("推进后 rand_a 归零", (nxt >> 64) & RAND_A_MASK, 0)
    need(nxt > values[4095], "推进后仍严格递增", "nxt > 第 4096 个",
         brief((values[4095], nxt)))


def monotonic_increase_across_ms():
    generate = lib().generate
    clock = FakeClock(1_000_000)
    entropy = SeqEntropy([3])
    first = generate(clock, entropy)
    clock.advance(5)
    second = generate(clock, entropy)
    need(second > first, "跨毫秒必须严格递增", "second > first", brief((first, second)))
    eq("跨毫秒后时间戳跟随时钟", (second >> 80) & TS_MASK, 1_000_005)
    eq("跨毫秒后 rand_a 重新从 0 起", (second >> 64) & RAND_A_MASK, 0)
    third = generate(clock, entropy)
    need(third > second, "新毫秒内继续严格递增", "third > second", brief((second, third)))
    eq("新毫秒内时间戳不变", (third >> 80) & TS_MASK, 1_000_005)


# ------------------------------------------------------------------- fields

def fields_parse_generate_roundtrip():
    api = lib()
    generate, parse = api.generate, api.parse
    clock = FakeClock(1_700_000_000_123)
    rand_bs = [0x0123456789ABCDEF, 0x0FEDCBA987654321, 0x00000000000000AA, 0x2AAAAAAAAAAAAAAA]
    entropy = SeqEntropy(rand_bs)
    for index in range(4):
        value = generate(clock, entropy)
        fields = parse(value)
        need(len(fields) == 5, "parse 必须返回 5 个字段",
             "(timestamp_ms, version, variant, rand_a, rand_b)", brief(fields))
        ts, version, variant, rand_a, rand_b = fields
        eq("parse 出的时间戳", ts, (value >> 80) & TS_MASK)
        eq("parse 出的 version", version, VERSION)
        eq("parse 出的 variant", variant, VARIANT)
        eq("parse 出的 rand_a", rand_a, (value >> 64) & RAND_A_MASK)
        eq("parse 出的 rand_b", rand_b, value & RAND_B_MASK)
        rebuilt = (ts << 80) | (version << 76) | (rand_a << 64) | (variant << 62) | rand_b
        eq("parse 与 generate 严格互逆（重组回原值）", rebuilt, value)


def fields_is_valid_positive_and_negative():
    api = lib()
    generate, is_valid = api.generate, api.is_valid
    value = generate(FakeClock(9_000), SeqEntropy([1]))
    need(is_valid(value) is True, "合法 UUIDv7 必须判 True", "True", brief(is_valid(value)))
    need(is_valid(value & ~(0xF << 76)) is False,
         "version 不为 7 必须判 False", "False", brief(is_valid(value & ~(0xF << 76))))
    need(is_valid(value & ~(0b11 << 62)) is False,
         "variant 不为 0b10 必须判 False", "False", brief(is_valid(value & ~(0b11 << 62))))
    need(is_valid(1 << 128) is False, "位宽不为 128 必须判 False", "False", brief(is_valid(1 << 128)))
    need(is_valid(-1) is False, "负数必须判 False", "False", brief(is_valid(-1)))
    handmade = (12345 << 80) | (VERSION << 76) | (0xABC << 64) | (VARIANT << 62) | 0x123456
    need(is_valid(handmade) is True, "手工构造的合法值必须判 True", "True", brief(is_valid(handmade)))
    need(is_valid(uuid.uuid4().int) is False, "UUIDv4 必须判 False", "False",
         brief(is_valid(uuid.uuid4().int)))


# ---------------------------------------------------------------- injection

def injection_fixed_entropy_predictable():
    generate = lib().generate

    def run():
        clock = FakeClock(1_700_000_000_000)
        entropy = SeqEntropy([0x1111111111111111, 0x2222222222222222,
                              0x3333333333333333, 0x4444444444444444])
        return [generate(clock, entropy) for _ in range(4)]

    first = run()
    second = run()
    eq("固定（时钟, 熵源）序列必须逐位可预测", first, second)

    clock = FakeClock(1_700_000_000_000)
    entropy = SeqEntropy([0x9999999999999999, 0x2222222222222222,
                          0x3333333333333333, 0x4444444444444444])
    changed = [generate(clock, entropy) for _ in range(4)]
    need(changed[0] != first[0], "换掉第一处熵源必须改变对应的输出",
         "changed[0] != first[0]", brief((first[0], changed[0])))
    eq("只换了第一处熵，其余输出不变", changed[1:], first[1:])


def _forbidden_usage_lineno(source):
    """返回疑似直接调用真实时钟 / secrets 的行号（注释与字符串里的不算）。"""
    hits = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return hits
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        nxt2 = tokens[index + 2] if index + 2 < len(tokens) else None
        nxt3 = tokens[index + 3] if index + 3 < len(tokens) else None
        # secrets.<名字>
        if token.string == "secrets" and nxt is not None \
                and nxt.type == tokenize.OP and nxt.string == ".":
            hits.append(token.start[0])
        # time.time / time.time_ns
        elif token.string == "time" and nxt is not None \
                and nxt.type == tokenize.OP and nxt.string == "." \
                and nxt2 is not None and nxt2.type == tokenize.NAME \
                and nxt2.string in ("time", "time_ns"):
            hits.append(token.start[0])
        # from time import time / time_ns
        elif token.string == "from" and nxt is not None and nxt.string == "time" \
                and nxt2 is not None and nxt2.string == "import" \
                and nxt3 is not None and nxt3.string in ("time", "time_ns"):
            hits.append(token.start[0])
        # from secrets import ...
        elif token.string == "from" and nxt is not None and nxt.string == "secrets" \
                and nxt2 is not None and nxt2.string == "import":
            hits.append(token.start[0])
    return hits


def injection_no_real_clock_no_secrets_scan_and_injection():
    api = lib()
    generate = api.generate

    root = os.path.join(HERE, "uuid7gen")
    need(os.path.isdir(root), "uuid7gen/ 目录必须存在", "存在", root)
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in sorted(filenames):
            if not filename.endswith(".py") or filename == "clock.py":
                continue  # clock.py 是已给好的边界适配器，扫描不看它
            path = os.path.join(dirpath, filename)
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            rel = os.path.relpath(path, HERE).replace(os.sep, "/")
            try:
                ast.parse(source)
            except SyntaxError as exc:
                raise CheckFailure("实现模块存在语法错误", "%s 语法正确" % rel,
                                   "%s: %s" % (rel, exc))
            for lineno in _forbidden_usage_lineno(source):
                offenders.append("%s:%d" % (rel, lineno))
    need(not offenders,
         "实现模块（除 clock.py 外）不得直接调用真实时钟与 secrets",
         "无 time.time / time.time_ns / secrets.* 调用", brief(offenders))

    # 行为断言：注入的时钟与熵源必须被真正使用（避免纯静态扫描在起点天生全绿）
    distinct_ts = 0x0ABCDEF12345
    distinct_rand_b = 0x2AAAAAAAAAAAAAA
    value = generate(FakeClock(distinct_ts), SeqEntropy([distinct_rand_b]))
    eq("时间戳必须来自注入的时钟", (value >> 80) & TS_MASK, distinct_ts)
    eq("rand_b 必须来自注入的熵源", value & RAND_B_MASK, distinct_rand_b)
    eq("version 位", (value >> 76) & 0xF, VERSION)


# -------------------------------------------------------------- concurrency

def concurrency_barrier_8_threads_no_duplicates_ordered():
    generate = lib().generate
    clock = FakeClock(1_000_000)
    entropy = SeqEntropy(list(range(1, 512)))
    barrier = threading.Barrier(CONCURRENCY_THREADS)
    lock = threading.Lock()
    per_thread = []
    errors = []

    def worker():
        try:
            barrier.wait(timeout=CONCURRENCY_TIMEOUT)
            produced = [generate(clock, entropy) for _ in range(CONCURRENCY_PER_THREAD)]
            with lock:
                per_thread.append(produced)
        except Exception as exc:  # noqa: BLE001 - 线程里的异常也要带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(CONCURRENCY_THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(CONCURRENCY_TIMEOUT)

    stuck = sum(1 for thread in threads if thread.is_alive())
    need(stuck == 0, "栅栏放行后 8 个线程必须都能在 %d 秒内完成" % CONCURRENCY_TIMEOUT,
         "0 个线程卡住", "%d 个线程卡住" % stuck)
    need(not errors, "工作线程不得抛异常", "无异常", brief(errors))
    eq("完成的线程数", len(per_thread), CONCURRENCY_THREADS)

    everything = [value for produced in per_thread for value in produced]
    eq("生成总数", len(everything), CONCURRENCY_THREADS * CONCURRENCY_PER_THREAD)
    eq("唯一值数（不得重复）", len(set(everything)),
       CONCURRENCY_THREADS * CONCURRENCY_PER_THREAD)
    for produced in per_thread:
        for previous, current in zip(produced, produced[1:]):
            need(current > previous, "同一线程内必须严格递增（不得被并发破坏）",
                 "current > previous", brief((previous, current)))
    for value in everything:
        need(isinstance(value, int) and 0 <= value < (1 << 128),
             "并发生成的值必须是 128 位无符号整数", "0 <= value < 2**128", brief(value))


# ------------------------------------------------------------------- 汇总

GROUPS = [
    ("layout", [
        ("L1_version_variant_bit_positions", "version / variant 位位置（RFC 9562 §5.7）",
         layout_version_variant_bit_positions),
        ("L2_timestamp_48bit_encoding", "48 位时间戳编码（固定时钟下与手工构造整数逐位相同）",
         layout_timestamp_48bit_encoding),
        ("L3_random_bits_placement", "rand_a / rand_b 随机位落位正确",
         layout_random_bits_placement),
    ]),
    ("monotonic", [
        ("M1_strict_increase_within_same_ms", "同一毫秒内严格递增", monotonic_strict_increase_within_same_ms),
        ("M2_rand_a_exhaustion_advances_ms", "rand_a 用尽后必须 sleep 并前进一毫秒",
         monotonic_rand_a_exhaustion_advances_ms),
        ("M3_increase_across_ms", "跨毫秒严格递增且 rand_a 重新起算", monotonic_increase_across_ms),
    ]),
    ("fields", [
        ("F1_parse_generate_roundtrip", "parse 与 generate 严格互逆", fields_parse_generate_roundtrip),
        ("F2_is_valid_positive_and_negative", "is_valid 正反例", fields_is_valid_positive_and_negative),
    ]),
    ("injection", [
        ("I1_fixed_entropy_predictable", "固定熵源下输出逐位可预测", injection_fixed_entropy_predictable),
        ("I2_no_real_clock_no_secrets_scan_and_injection",
         "不得直接调用真实时钟与 secrets（静态扫描 + 注入行为同时成立）",
         injection_no_real_clock_no_secrets_scan_and_injection),
    ]),
    ("concurrency", [
        ("C1_barrier_8_threads_no_duplicates_ordered",
         "栅栏后 8 线程各 500 次：无重复且单调不被破坏",
         concurrency_barrier_8_threads_no_duplicates_ordered),
    ]),
]


def parse_argv(argv):
    do_list = False
    only = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-list", "--list"):
            do_list = True
        elif arg in ("--only", "--group"):
            index += 1
            if index >= len(argv):
                sys.stderr.write("--only 需要一个组名（layout/monotonic/fields/injection/concurrency）\n")
                raise SystemExit(2)
            only = {part.strip() for part in argv[index].split(",") if part.strip()}
        elif arg in ("-h", "--help"):
            sys.stdout.write("用法: python3 check.py [-list] [--only <组名>]\n")
            raise SystemExit(0)
        else:
            sys.stderr.write("未知参数: %s\n" % arg)
            raise SystemExit(2)
        index += 1
    return do_list, only


def main(argv):
    do_list, only = parse_argv(argv)

    if do_list:
        for group, scenarios in GROUPS:
            for name, why, _func in scenarios:
                sys.stdout.write("[%-11s] %-42s %s\n" % (group, name, why))
        return 0

    selected = []
    for group, scenarios in GROUPS:
        if only is not None and group not in only:
            continue
        for name, _why, func in scenarios:
            selected.append((group, name, func))

    if not selected:
        sys.stderr.write("没有匹配的场景\n")
        return 2

    passed = 0
    failed = 0
    for group, name, func in selected:
        key = "%s/%s" % (group, name)
        try:
            func()
        except CheckFailure as exc:
            failed += 1
            sys.stdout.write("FAIL %s  期望=%s 实际=%s（%s）\n"
                             % (key, exc.expected, exc.actual, exc.what))
        except Exception as exc:  # noqa: BLE001 - 异常本身就是失败证据
            failed += 1
            sys.stdout.write("FAIL %s  期望=场景正常完成 实际=%s: %s\n"
                             % (key, type(exc).__name__, exc))
        else:
            passed += 1
            sys.stdout.write("PASS %s\n" % key)
        sys.stdout.flush()

    total = len(selected)
    sys.stdout.write("结果：通过 %d/%d\n" % (passed, total))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
