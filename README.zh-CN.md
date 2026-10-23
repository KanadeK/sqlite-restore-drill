# sqlite-restore-drill 中文说明

对一份**已经关闭、单文件且不依赖 WAL/journal 的 SQLite 备份**做恢复演练。
原文件只按字节读取，绝不交给 SQLite 打开；数据库操作全部在自动清理的临时副本中进行。
Python 3.11+，没有第三方运行时依赖，也不需要外部 sqlite3 命令或网络。

## 安装与试用

```sh
git clone https://github.com/KanadeK/sqlite-restore-drill.git
cd sqlite-restore-drill
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
python examples/make_demo.py demo.db
sqlite-restore-drill demo.db --contract examples/contract.json --json
```

示例生成器创建两条明确标记的合成记录并关闭连接。输出 `ok: true` 表示本次演练通过。
把契约副本中的 `min_rows` 改为 3，便可观察真实的数据契约失败。
也可从 GitHub Release 下载 wheel 后用 `pip install --no-deps 文件路径` 安装；没有发布到 PyPI。

每次演练检查完整 `integrity_check`、独立的外键检查、指定表/列、行数上下界、
`user_version`，再执行创建测试表、写入、读取和回滚，最后确认原文件哈希与属性未变。
契约是严格的版本 1 JSON，拒绝重复键、未知键及错误类型，不接受任意 SQL。

退出码：0 为通过，1 为演练失败，2 为参数或契约错误。`--json` 输出版本化报告；
参数/契约错误仍是 stderr 文本。报告不含数据行或 SQLite 原始错误，但可能含表名、计数及版本。
`--max-bytes` 默认 1 GiB，`--timeout` 默认 60 秒，是协作式预算，不能中断阻塞的文件系统调用。
`--temp-dir` 可指定已有的临时父目录。

## 使用边界

拒绝非空 `-wal`、`-journal`、`-shm` 以及非普通文件或符号链接侧文件；空的普通侧文件保留。
必须用正确的备份流程得到一致产物，不能直接复制活动库后指望工具找回遗漏事务。
通过检查不代表备份新鲜、业务数据完整或应用可以正常升级，也不代表恶意数据库被安全隔离。
不支持 SQL dump、加密库、远程存储和复杂虚拟表恢复。

需要多数据库、provider、签名证据或 S3 工作流时，请比较英文 README 中列出的成熟替代品。
本工具的价值是独立、轻量、边界明确的本地演练流程。

卸载：`python -m pip uninstall sqlite-restore-drill`。不再需要时删除虚拟环境与示例 `demo.db`。
正常运行自动删除副本；强制终止可能留下临时目录，确认进程停止后再清理。
完整格式、限制和开发检查见 [英文 README](README.md) 与 [贡献说明](CONTRIBUTING.md)。
