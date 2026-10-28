# Context Delta 修复审计

## 契约与原因

上次提测 HEAD：`291ff38f1685937ab3e77e9f57ee460e5a551d56`，实现提交 `929ae719da1080be4bbddb56dbc0896327390ad2`。基线为 `dab240063bfcfa7917898dc44da4baadb3747bd0`。语雀页本次仍不可访问；使用仓库正式发布的 `competition/challenges/context-02-incremental-pack/instruction.md` 和公开 acceptance 作为契约。平台未提供失败日志，以下为本地复现的问题，不能断言是官方失败原因。

1. `prepare_incremental` 把 request 声明为仅限位置参数，而题目展示的签名允许 `request=`。实际关键字调用抛 TypeError；现允许关键字调用。
2. Runtime 原先按 512 字节填满分块。输入为 400 字节稳定前缀、中间一个字符变化及 1000 字节后缀时，变化位于首块，复用块为 0；现 Runtime 使用 64 字节上限，可复用 384 字节。协议仅允许完整块前缀，因此前面改变时仍可能无复用。此修改不影响 `from_content` 的 512 字节默认参数或 wire 字段。

修改：`src/powercontext/builtin/runtime/application.py`；回归测试：`tests/builtin/runtime/test_context_pack_repair.py`。协议实现和官方测试未修改。普通 prepare 仍由增量方法调用。

## 测试矩阵

公开 acceptance 14 项、既有测试 8 项、新增测试 15 项共 **37 passed**，连续三次（4.02、3.52、3.91 秒）。Ruff 和 Linux 目标 Python 3.12 的变更文件 type check 通过。

| 用例 | 实际结果 |
| --- | --- |
| T01 首包 | 通过，公开验收和矩阵 |
| T02 不变 | 通过 |
| T03 尾部追加 | 通过 |
| T04 中间插入 | 通过 |
| T05 中间删除 | 通过 |
| T06 修改 | 通过 |
| T07 重排 | 通过 |
| T08 正文相同引用 revision 不同 | 引用文本变化的重建通过；结构化 citation 对象未覆盖 |
| T09 同正文不同引用身份 | 引用文本变化的重建通过；结构化 citation 对象未覆盖 |
| T10 Unicode/转义 | 通过 |
| T11 空/单包 | 通过 |
| T12 字节边界 | 通过（64/65 字节及既有 UTF-8 上限测试） |
| T13 多轮 | 五轮重建通过 |
| T14 缺失/错误 base | 错误 base 拒绝通过；缺失 base 在接口层未单独测试 |
| T15 损坏 delta | 通过 |
| T16 独立进程 | 通过：JSON 文件交给独立 Python 进程，连续五轮仅用 wire 数据重建 |
| T17 JSON 往返 | 通过 |
| T18 实际字节 | 通过下述合成对照；官方测量未运行 |
| T19 原 prepare | 公开 Runtime 集成通过；完整 HTTP 回归未运行 |
| T20 公共接口 | `request=` 通过测试替身验证；真实 HTTP Client 端到端未运行 |

Pack 固定 wire 字段只包括 schema、items、digest、byte_count，不能承载独立结构化 citation 列表；本实现忠实重建 prepare 正文，未证明独立结构化引用对象的往返。不能把文本引用测试等同于结构化引用测试。

## 成本与回归

40 轮合成数据使用四个版本、每个连续 10 轮；每个正文有 400 字节稳定前缀、单字符版本差异和 1000 字节后缀。原始正文总计 56,040 bytes。512 字节块 wire 为 17,657 bytes（节省 68.49%），64 字节块为 16,491 bytes（节省 70.57%）；一次版本变化的 delta 从 2,136 降至 1,699 bytes。包含首包和所有协议字段。此序列不是官方要求的 8 个真实 meeting turn，不可据此认定正式 45% 门槛通过。

本轮未重跑完整项目 pytest；上次 Windows 未安装项目的隔离环境结果为 3421 passed、137 failed、240 skipped，详见 `test_results.md`。本轮公开 acceptance 全部通过，包括原生 Runtime 测试。未运行真实 Server + HTTP Client、官方 Linux 容器及隐藏成本序列；上次环境 WSL 返回拒绝访问，Docker daemon 未连接。

本报告写入修复提交前，最终分支 HEAD 完整 SHA 见任务交付回执及 `git rev-parse HEAD`。
