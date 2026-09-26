UUIDv7 的位布局在 RFC 9562 第 5.7 节里写得很死，照它实现就行：uuid7gen 是 Python 3 的
时间有序 ID 生成库，只用标准库（unittest 跑用例），不引入第三方依赖，自检走
`bash scripts/check.sh`（`check.py` 是固定验收程序，别改）。

`uuid7gen/` 下除了 `clock.py` 之外全是空壳，`tests/` 里 12 个用例全红。

任务：按 README「对外契约」的 11 条把它实现出来，让既有用例与固定件全过。

验收：
- python3 -m unittest discover -s tests 退出码 0；
- bash scripts/check.sh 退出码 0，11 个场景全过（layout 3 + monotonic 3 + fields 2 + injection 2 + concurrency 1）。

约束：
1. 不改 `check.py`、不改既有用例的断言；已公开的函数签名不变（可新增）。
2. 不引入第三方依赖，只用标准库。
3. 时间与随机位都必须可注入，实现里不许直接调 `time.time` / `secrets`。
4. 单调性与并发判据不依赖墙钟快慢：时间走注入时钟，并发用栅栏 + 多轮重复。
