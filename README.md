# uuid7gen

一个 **UUIDv7**（RFC 9562 §5.7，时间有序 ID）生成与解析库（Python 3，
**零第三方依赖**：只用标准库，跑用例用随 Python 提供的 `unittest`）。

UUIDv7 的结构是「48 位毫秒时间戳 + 版本 + 单调计数器 + 随机位」，
所以它既是**全局唯一**的，又**按时间有序**。目标不是包一层 `uuid`，
而是：**位布局照 RFC 写死 + 同一毫秒内严格单调 + 时间与随机位完全可注入**。

## 怎么跑

```bash
python3 -m unittest discover -s tests   # 既有用例（tests/）
python3 check.py                        # 固定验收程序
python3 check.py -list                  # 列出全部场景
python3 check.py --only layout          # 只跑一组
bash scripts/check.sh                   # 固定件入口的薄封装
```

前提：**Python 3.10+**（本仓库在 CPython 3.13 上验收）。

> ⚠️ **勿改**：`check.py` 是固定验收程序；`tests/test_uuid7gen.py` 里既有用例的
> 断言；`uuid7gen/errors.py` 里的异常类名。这些都是一次性的契约面。
>
> 公开的**函数签名**（模块名、函数名、参数与关键字参数）已经是最终形态，
> 可以新增内部函数与辅助类型，但不要改下面 `API` 一节列出的这些。
>
> `uuid7gen/clock.py` 是**已给好**的注入边界（时钟 / 熵源接口 + 真实适配器），
> 正常不需要改：固定件会**自己**注入时钟与熵源，改它不会让判定变绿。

起点状态：`uuid7gen/gen.py` 与 `uuid7gen/layout.py` 里的公开函数都是空壳，
调用就抛 `NotImplementedError`；`tests/` 里 12 个用例当前**全部是 error**
（能导入，没有语法错）；`python3 check.py` 打印 `结果：通过 0/11`
并以退出码 1 结束。

## 对外契约

下面 11 条是 uuid7gen 的对外契约，**它们是契约而不是「当前行为」的转述**。
语义细节以本节为准；实现方式不限，但必须让这 11 条同时成立。

### 1. `generate(clock=None, entropy=None, *, mono=True) -> int`

返回一个 128 位无符号整数（`0 <= value < 2**128`；用 `uuid.UUID(int=value)`
包装亦可）。时间戳取自注入的 `clock`，随机位取自注入的 `entropy`。

- `clock` 需提供 `now_ms() -> int` 与 `sleep_until_next_ms() -> int`
  （见 `uuid7gen/clock.py` 的 `Clock` / `FakeClock` / `SystemClock`）。
- `entropy` 需提供 `rand_bits(n) -> int`，返回 `0 <= r < 2**n`
  （见 `uuid7gen/clock.py` 的 `Entropy` / `SystemEntropy`）。
- `clock` / `entropy` 缺省时用**真实**时间与 `secrets` —— 但实现里不得直接调，
  见第 10 条。
- `mono=True`（缺省）时 `rand_a` 用作单调计数器（第 4、5 条）；
  `mono=False` 时关闭单调计数器，`rand_a` 改由 `entropy.rand_bits(12)` 提供，
  此时**不保证**唯一与单调，只保证位布局正确。

### 2. 位布局（RFC 9562 §5.7）

128 位从高到低切分如下：

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           unix_ts_ms                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          unix_ts_ms           |  ver  |       rand_a          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|var|                        rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| 位区间 | 宽度 | 字段 | 取值 |
| --- | --- | --- | --- |
| 127..80 | 48 | `unix_ts_ms` | 毫秒时间戳，48 位大端语义（占最高 48 位） |
| 79..76 | 4 | `ver` | 恒为 `0b0111` |
| 75..64 | 12 | `rand_a` | 单调计数器（见第 5 条） |
| 63..62 | 2 | `var` | 恒为 `0b10` |
| 61..0 | 62 | `rand_b` | 每次调用的随机位 |

即：

```
value = (unix_ts_ms << 80) | (ver << 76) | (rand_a << 64) | (var << 62) | rand_b
ver   = 0b0111
var   = 0b10
```

### 3. 时间戳范围

`unix_ts_ms` 取 `clock.now_ms()`。`now_ms < 0` 或 `now_ms >= 2**48`
一律拒绝，抛 `ValueError`（`uuid7gen.TimestampRangeError` 是它同时的子类）。
合法取值原样编码到高 48 位。

### 4. 严格单调

任意两次相邻调用（同一实例、同一进程内顺序调用），**后一次返回的无符号整数
必须严格大于前一次** —— 同一毫秒内成立，跨毫秒也成立。
时钟回拨（`now_ms` 变小）时同样不得返回不大于上一次的值。

### 5. `rand_a` 计数器与「用尽推进」

`mono=True` 时 `rand_a` 是一个 12 位计数器：

- 同一毫秒内的**第一个** ID：`rand_a == 0`；此后每次调用 `rand_a` 递增 1。
- 用尽 4096 个取值（即 `rand_a` 从 0 走到 4095）后，**必须**调用
  `clock.sleep_until_next_ms()` 推进到下一毫秒，再把 `rand_a` 归 0 继续；
  **不许回绕、不许重复**。
- 若时钟已经前进到更大的毫秒，`rand_a` 从 0 重新开始。
- 单调状态**按 `clock` 实例隔离**：同一个 `clock` 对象上连续调用共享同一个
  `rand_a` 计数器；换一个 `clock` 对象即视为一条新序列，计数器从 0 重新开始
  （这样「固定时钟 + 固定熵源」的序列才可逐位复现）。`clock=None` 时用同一个
  进程级默认时钟，因此缺省路径仍是一条连续序列。

### 6. `rand_b` 与可预测性

每次调用都从 `entropy.rand_bits(62)` 取**新的** `rand_b`。
注入固定熵源（按调用顺序给固定值）时，输出必须**逐位可预测**：同一
（时钟, 熵源）序列重复跑，得到完全相同的一串整数。

### 7. `parse(value) -> (timestamp_ms, version, variant, rand_a, rand_b)`

字段级拆解：按第 2 条的位区间把 128 位值拆成 5 个字段，
与 `generate` 严格互逆（`parse(generate(...))` 还原出全部字段）。
接受 `0 <= value < 2**128` 的 `int`，或带 `int` 属性的 128 位包装
（如 `uuid.UUID`）；越界抛 `ValueError`，类型不符抛 `TypeError`。

### 8. `is_valid(value) -> bool`

`value` 是合法 UUIDv7 当且仅当：**version == 7**、**variant == `0b10`**、
**位宽为 128**（`0 <= value < 2**128`）。任何输入都返回 `bool`，不抛异常：
非整数、负数、`>= 2**128`、version 或 variant 不对，一律返回 `False`。

### 9. `sort_key(value) -> int`

返回一个可按**无符号整数**排序的键：用它排序一组值，结果与
「先按 `timestamp_ms`、再按 `rand_a`、最后按 `rand_b`」排序一致。

### 10. 缺省用真实时间与 `secrets`，但测试路径必须可完全注入

不传 `clock` / `entropy` 时用真实时间与 `secrets`（实现见 `uuid7gen/clock.py`
的 `SystemClock` / `SystemEntropy`）。但 `uuid7gen/` 下的**实现模块**
（`gen.py`、`layout.py`）里**不得出现** `time.time` / `time.time_ns` /
`secrets.*` 的直接调用，也不得用 `from time import time` / `from time import
time_ns` / `from secrets import ...` 这类等价写法绕开 —— 时间与随机只能从
注入的 `clock` / `entropy` 拿。（`clock.py` 是已给好的边界适配器，扫描不看它。）

### 11. 线程安全

多个线程同时对同一个 `generate` 调用点发起生成时：**不得产生重复值**，
也不得破坏单调性（每个线程自己按序拿到的值必须严格递增）。

## 实现约束

- **只用标准库**，不连数据库、不访问网络、不起中间件。
- 判据确定性：不依赖墙钟、机器速度、随机源。固定件全部用**注入时钟**与
  **注入熵源**，并发场景用**栅栏**（凑齐 8 个线程才放行）。

## API

```
uuid7gen
  generate(clock=None, entropy=None, *, mono=True) -> int
  parse(value)                                     -> (ts, ver, var, rand_a, rand_b)
  is_valid(value)                                  -> bool
  sort_key(value)                                  -> int
  Uuid7Error < Exception
  TimestampRangeError < Uuid7Error, ValueError

uuid7gen.clock
  Clock            # now_ms() / sleep_until_next_ms() 接口
  FakeClock        # 确定性时钟（测试用）
  SystemClock      # 真实时钟（缺省）
  Entropy          # rand_bits(n) 接口
  SystemEntropy    # 真实熵源（缺省，基于 secrets）

uuid7gen.layout
  VERSION / VARIANT / TS_BITS / RAND_A_BITS / RAND_B_BITS
  pack(timestamp_ms, rand_a, rand_b)               -> int
  unpack(value)                                    -> (ts, ver, var, rand_a, rand_b)
```

## 验收

`check.py` 是固定验收程序，**不要修改**。它按 5 组共 11 个场景检查上面的契约：

| 组 | 场景 | 对应契约 |
| --- | --- | --- |
| `layout` | `L1_version_variant_bit_positions` | 2 |
| `layout` | `L2_timestamp_48bit_encoding` | 2、3 |
| `layout` | `L3_random_bits_placement` | 2、6 |
| `monotonic` | `M1_strict_increase_within_same_ms` | 4、5 |
| `monotonic` | `M2_rand_a_exhaustion_advances_ms` | 5 |
| `monotonic` | `M3_increase_across_ms` | 4、5 |
| `fields` | `F1_parse_generate_roundtrip` | 7 |
| `fields` | `F2_is_valid_positive_and_negative` | 8 |
| `injection` | `I1_fixed_entropy_predictable` | 6、10 |
| `injection` | `I2_no_real_clock_no_secrets_scan_and_injection` | 10（静态扫描 + 注入行为，二者须同时成立） |
| `concurrency` | `C1_barrier_8_threads_no_duplicates_ordered` | 11 |

跑法：`python3 check.py` 退出码 0 表示 11/11 全过；`python3 -m unittest
discover -s tests` 必须全绿。固定件逐场景判定、**失败不早退**：一次把问题全暴露。

## 目录

```
.
├── README.md                 本文件
├── .gitignore
├── .gitattributes
├── PROMPT.md                 任务提示（逐字）
├── check.py                  固定验收程序（勿改）
├── scripts/check.sh          固定件入口的薄封装
├── uuid7gen/
│   ├── __init__.py           对外导出
│   ├── clock.py              时钟 / 熵源接口与真实适配器（已给全，勿改）
│   ├── gen.py                generate / parse / is_valid / sort_key（当前为空壳）
│   ├── layout.py             位布局 pack / unpack（当前为空壳）
│   └── errors.py             异常类型（勿改名）
└── tests/test_uuid7gen.py    既有用例（12 个，勿改断言）
```
