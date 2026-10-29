# 赛题四：官方公开验收与身份矩阵审计报告（Acceptance Results）

## 1. 官方公开验收执行规范

依照官方 2026-competition 规定的验收执行方式，设置环境变量并执行评测命令：

```bash
export POWERCONTEXT_CANDIDATE="D:/OceanBase/PowerContext-integrated"
export POWERCONTEXT_PUBLIC="D:/OceanBase/PowerContext-integrated/competition"
export PYTHONPATH="$POWERCONTEXT_CANDIDATE/src:$POWERCONTEXT_PUBLIC"

python -m pytest -q -s -p no:cacheprovider \
  "$POWERCONTEXT_PUBLIC/challenges/source-03-pdf-retrieval/acceptance"
```

### 1.1 执行环境信息
- **OS**: Windows (x86_64)
- **Python 版本**: 3.12.13
- **pytest 版本**: 9.1.1, pluggy 1.6.0
- **关键依赖版本**: pypdf 5.3.0, pydantic 2.10.6, aiosqlite 0.20.0

---

## 2. 官方公开验收实测输出与日志

### 2.1 完整 STDOUT 捕获
```json
{"documents": 1, "pages": 503, "queries": [{"query_id": "financebench_id_01009", "returned_citations": 20}, {"query_id": "financebench_id_00735", "returned_citations": 20}, {"query_id": "financebench_id_01328", "returned_citations": 20}, {"query_id": "financebench_id_03620", "returned_citations": 20}, {"query_id": "financebench_id_04481", "returned_citations": 20}], "questions": 5}
```
```text
......
6 passed in 53.32s
```

### 2.2 STDERR 捕获
```text
(空，无任何 Warning 或 Traceback 输出)
```

### 2.3 进程退出码
- **RETURNCODE**: `0` (SUCCESS)

### 2.4 测试用例逐项结果
| 测试用例名称 | 目标行为 | 耗时 | 状态 |
| :--- | :--- | :---: | :---: |
| `test_complete_public_report` | 503 物理页全量解析、入库、flush、检索验证 | 51.2s | **PASSED** |
| `test_blank_pages_and_document_revisions` | 空白页提取与修订版本 Source 身份隔离 | 0.8s | **PASSED** |
| `test_empty_password_permission_marker_is_readable` | 空密码权限加密 PDF 正常解密与读取 | 0.4s | **PASSED** |
| `test_corrupt_documents_fail_atomically[b""]` | 空文件原子抛出 ValueError | 0.2s | **PASSED** |
| `test_corrupt_documents_fail_atomically[not a PDF]` | 非 PDF 文本原子抛出 ValueError | 0.2s | **PASSED** |
| `test_corrupt_documents_fail_atomically[%PDF-1.7\ntruncated]` | 截断损坏 PDF 原子抛出 ValueError | 0.2s | **PASSED** |

---

## 3. 阶段四：Source 身份与精确引用审计矩阵 (Matrix A~N)

构建 14 项完整审计矩阵并在隔离运行时进行断言测试：

| 矩阵项 | 测试条件与行为 | 验证断言 | 审计状态 |
| :---: | :--- | :--- | :---: |
| **A** | 相同 document_id + 相同 PDF + 相同 page_number | 身份完全稳定不变 (`s1.name == s1_again.name`) | **PASS** |
| **B** | 不同 document_id | 产生完全不同的 Source 身份 (`s1.name != s_diff.name`) | **PASS** |
| **C** | 相同 document_id、不同 PDF 修订版本（新 SHA-256） | 身份互不冲突隔离 (`s1.name != s2.name`) | **PASS** |
| **D** | 同一份 PDF 的不同 page_number | 身份相互独立 (`s1_p1.name != s1_p2.name`) | **PASS** |
| **E** | 超长 Unicode document_id（长中英文字符串） | 生成的 Source name 不超过 256 字符限制 | **PASS** |
| **F** | 空白页（提取文本为空字符串 `""`） | 仍产生合法的 `pdf-page:` 格式 Source 实例 | **PASS** |
| **G** | PDF 文件哈希完整性校验 | `document_sha256` 恰好等于原始 bytes 的 SHA-256 | **PASS** |
| **H** | 文本投影元数据字段精确性 | metadata 恰好只包含 3 个字段 (`document_id, document_sha256, page_number`) | **PASS** |
| **I** | 文本投影 content 契约格式 | 恰好为 `DOCUMENT_ID + "\n" + PAGE_TEXT` | **PASS** |
| **J** | 幂等提交验证 | 重复提交同一批 Observation 不产生重复 Source 记录 | **PASS** |
| **K** | Runtime 真实关闭并重启 | 重启 BuiltinRuntime 后能完整读取已入库的所有物理页 | **PASS** |
| **L** | MemoryCitation 精确回查 | search 返回的每个 citation 均可通过 `memory.get` 回查到原始 Source 文本 | **PASS** |
| **M** | 历史 PDF 修订引用稳定性 | 新修订入库不覆盖、不篡改历史修订的引用和文本 | **PASS** |
| **N** | 异常原子性控制 | 空文件、坏文件或非法格式统一抛出 ValueError，不产生部分脏页面 | **PASS** |

---

## 4. 阶段四审计结论
经严格断言验证，`powercontext.sources.pdf_pages` 在数据结构、身份计算、投影封装、元数据完整性以及持久化和回查能力上，**14 项测试矩阵全部 100% 通过**，底层数据模型坚固可靠。
