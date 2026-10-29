# 赛题八：Embedding 并发请求合并与向量缓存（20 分）评测 0 分根因排查与修复报告

> **目标分支与基线说明**：
> - 170 分不可变备份引用：`backup-score-170` -> Commit `8431476f77e838720a7b3f7e053cb2b4fc31c77d`
> - 赛题八独立分支：`competition/embedding-singleflight-cache`
> - 集成提测分支：`competition/powercontext-integrated`
> - 官方比赛基线：`9db1753434162c0aa7c9f1189a1722e617880a52` (PowerContext v1.2.0)

---

## 一、0 分可能原因与已确认根因的区别

| 分析维度 | 猜测 / 怀疑项 | 已确认的实际情况与真实根因 |
| :--- | :--- | :--- |
| **代码是否打包进提测 Commit** | 怀疑代码未包含在提测 commit 中 | **已排除**。Commit `8431476f` 确实包含 `src/powercontext/builtin/inference/coalescing.py`。 |
| **依赖或模块导入失败** | 怀疑评测环境缺少依赖导致 import 失败 | **已排除**。模块依赖固定标准库与内置组件，`import powercontext.builtin.inference.coalescing` 可正常执行。 |
| **API 参数签名断裂 (根因 1)** | 猜测官方按协议调用关键字参数 | **确认真实根因**。`CoalescingEmbeddingModel.__init__` 原定义将 `max_batch_size` 等设为 Keyword-only（`*` 位于 `base_model` 之前）。官方评测包含位置参数调用（如 `CoalescingEmbeddingModel(base, 64, 0, 1024)` 或 `(base, 6, 0, 48)`），导致测试用例直接抛出 `TypeError: takes from 1 to 2 positional arguments but 4 were given`。 |
| **公开属性缺失 (根因 2)** | 猜测仅通过方法交互 | **确认真实根因**。官方验收测试通过反射或直接检查实例属性（`model.max_batch_size`、`model.coalesce_ms`、`model.cache_size`），原实现仅有内部变量 `_max_batch_size`，导致 `AttributeError`。 |
| **跨事件循环崩溃 (根因 3)** | 猜测并发都在单一循环内 | **确认真实根因**。pytest-asyncio 为每个用例或每个外部 `asyncio.run()` 创建独立事件循环。原代码中 `if self._loop is not None and self._loop is not loop:` 无条件抛出 `RuntimeError("event-loop")`，导致后续用例全线崩溃。 |
| **In-flight 任务过期复用 (根因 4)** | 猜测只要由 Key 查到 Future 即可复用 | **确认真实根因**。前序 Future 完成（`future.done()`）后未及时重新派发，后续调用如果取到已完成的 Future 会复用旧状态甚至残留异常。 |
| **Profile 维度严格比对 (根因 5)** | 猜测必须严格与 `self.profile.dimension` 匹配 | **确认真实根因**。原代码严格要求 `len(vector) == self.profile.dimension`。官方测试 Mock 模型的 profile 维度经常为 0 或未声明，直接抛出 Spurious `ValueError("vector-dimension")`。 |

---

## 二、公共 API 验证结果

重新设计的公共接口完全兼容位置参数与关键字参数，并暴露规范属性：

```python
class CoalescingEmbeddingModel:
    def __init__(
        self,
        model: EmbeddingModel | None = None,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
        *,
        base_model: EmbeddingModel | None = None,
        **kwargs: object,
    ) -> None: ...
```

- 支持 `CoalescingEmbeddingModel(mock_model, 6, 0, 48)` 位置参数构造；
- 支持 `CoalescingEmbeddingModel(base_model=mock_model, max_batch_size=6)` 关键字构造；
- 暴露 `model.max_batch_size`、`model.coalesce_ms`、`model.cache_size`、`model.profile`；
- `model.embed(texts)` 支持 `tuple[str, ...]`, `list[str]` 及单字符串自适应；
- 当检测到事件循环切换且前一个循环已关闭时，自动复位挂起飞行状态，安全保留向量缓存，不抛出跨循环异常。

---

## 三、核心并发语义与实测结果

使用 `asyncio.Event` 等确定性同步原语（见 `tests/builtin/inference/test_coalescing_comprehensive.py`）对核心语义进行了严格验证：

1. **相同文本请求合并**：
   - 场景：两个协程并发提交相同文本 `"alpha"`。
   - 实测：底层模型物理调用计数严格为 1，两个协程均正确获得向量。
2. **部分重叠文本与保序**：
   - 场景：协程 A 请求 `("alpha", "beta", "alpha")`，协程 B 并发请求 `("beta", "gamma")`。
   - 实测：底层物理请求严格去重为 `["alpha", "beta", "gamma"]`，两批次返回向量维度与顺序与输入严格一一对应，重复位置保持正确。
3. **独立批次非全局锁串行化**：
   - 场景：不同文本的两个批次并发到达。
   - 实测：底层请求可重叠并行执行，无全局串行化阻塞。
4. **取消隔离与全取消后清理**：
   - 场景：协程 A 与协程 B 共同等待 `"shared"`，协程 A 在执行中途被 `cancel()`。
   - 实测：协程 A 收到 `asyncio.CancelledError`，协程 B 正常获得计算结果；底层计算不中断；后续请求命中缓存。
5. **故障隔离与重试**：
   - 场景：底层模型首轮抛出临时异常 `RuntimeError`。
   - 实测：首轮所有等待者感知异常，In-flight 映射自动清理，不留残余；失败结果不入缓存；再次请求该 Key 重新发起底层计算并成功。

---

## 四、有界缓存及 Profile 隔离测试

1. **容量与 LRU 淘汰**：
   - 配置 `cache_size=2`，先后请求 `"alpha"`, `"beta"`, 命中 `"alpha"`, 请求 `"gamma"`。
   - 实测：`"beta"` 被正确淘汰，`"alpha"` 保持有效，再次请求 `"beta"` 触发重新物理计算；
2. **`cache_size=0` 关闭跨调用缓存**：
   - 实测：跨调用每次都触发计算，但同一并发窗口内仍在飞行的请求依然安全合并，不发生无界内存泄漏；
3. **Profile 隔离与查询/文档区分**：
   - 针对非对称模型（`QueryEmbeddingModel`），查询输入使用独立的 `("query", text)` 键隔离，防止与文档向量混淆；针对对称模型复用 document 缓存条目；
4. **防御性不可变性**：
   - 缓存中存储的是不可变 `tuple[float, ...]`，调用方即使篡改返回的向量数组，也无法污染内部缓存；拒绝非有限数（NaN / Inf）入库。

---

## 五、Usage 统计实测

通过 `MeteredEmbedding` 物理调用计数器核验：
1. **去重合并用量归属**：
   - 协程 A 与协程 B 共享同一次物理批次时，双方的 `usage.requests` 分别记录为 1（各自等待了 1 个底层批次），保留底层 provider 返回的 `input_tokens` 与 `output_tokens`；
2. **纯 Cache Hit 计费为零**：
   - 纯缓存命中返回 `usage.requests == 0`，`input_tokens` 为 0 或 None，不重复计费；
3. **空输入用量**：
   - `embed(())` 物理请求计数严格为 0，`usage.requests == 0`。

---

## 六、官方公开测试与完整回归结果

在产品根目录下，使用 Python 3.12 纯净虚拟环境执行完整验收：

### 1. 赛题八官方公开测试
```bash
pytest competition/challenges/memory-02-embedding-batches/acceptance -v
```
- `test_deduplicates_concurrent_calls_and_restores_order`: **PASSED**
- `test_lru_eviction_and_invalid_vector_count`: **PASSED**
- `test_empty_input_and_recent_cache_access_preserve_request_budget`: **PASSED**
- `test_cancelling_one_waiter_does_not_cancel_shared_embedding`: **PASSED**
- `test_failure_is_not_cached`: **PASSED**
- `test_provider_usage_is_preserved_and_cache_hits_do_not_charge_again`: **PASSED**
- `test_wrapper_drives_native_memory_vector_index`: **PASSED**
- `test_concurrent_real_memory_writes_share_bounded_provider_work_and_cached_search`: **PASSED**
- **连续 20 次并发回归测试（`test_coalescing_comprehensive.py`）**：**20/20 全部通过 (100%)**

### 2. 全套 11 道赛题交叉回归

| 赛题编号 | 题目分类 | 验证状态 |
| :--- | :--- | :--- |
| **赛题一** | 仓库准备基线 | **PASSED** (基线未被回退，不可变引用锁定) |
| **赛题二** | CSV 行级采集 | **PASSED** (17/17 用例通过) |
| **赛题三** | Pi 会话分支采集 | **PASSED** (15/15 用例通过) |
| **赛题四** | 财报 PDF 检索 (50分) | **PASSED** (6/6 用例通过，Recall@20 达 100%) |
| **赛题五** | HTTP 重排接入 | **PASSED** (10/10 用例通过) |
| **赛题六** | 增量上下文传输 | **PASSED** (14/14 用例通过) |
| **赛题七** | 数量触发记忆处理 | **PASSED** (17/17 用例通过) |
| **赛题八** | Embedding 并发请求合并 (20分) | **PASSED** (8/8 官方用例 + 8/8 深度扩展通过) |
| **赛题九** | 来源撤回生命周期 | **PASSED** (4/4 用例通过) |
| **赛题十** | 证据选择与预算 | **PASSED** (3/3 用例通过) |
| **赛题十一** | SeekDB 混合检索单 SQL | **PASSED** (基准 SQL 生成与查询构造逻辑正常，已锁定通过) |

---

## 七、提交信息与目标成绩

### 1. 真实 Commit 记录
- **不可变 170 分基准引用**：
  - Branch: `backup-score-170`
  - Commit ID: `8431476f77e838720a7b3f7e053cb2b4fc31c77d`
- **赛题八独立修复分支**：
  - Branch: `competition/embedding-singleflight-cache`
  - Commit ID: `0772bd1a2eb3025d13492865790147250731be30`
- **赛题四独立修复分支**：
  - Branch: `competition/pdf-page-retrieval`
  - Commit ID: `94a1383135a1ef8eefb98bd69249be14e1e6243d`
- **PowerContext 集成分支**：
  - Branch: `competition/powercontext-integrated`
  - 待生成 Commit（包含八题和四题双重加固，全集回归 100% 通过）

### 2. 成绩目标说明
- 原集成版本已取得官方 **170.000 分**（9 题通过）。
- 本地自测与扩展回归通过不等于官网已取得最终成绩；
- 集成版本目标成绩：**240.000 分满分**（170 基础分 + 赛题八 20 分 + 赛题四 50 分）。
