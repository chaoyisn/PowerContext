# PowerContext 赛题十：字符位置与原始证据回查校验报告

## 一、位置语义与契约不变量

赛题十对原文片段坐标设立了最为严格的正确性标准：
1. **语义单位**：原 Memory entry 文本的半开 Python Unicode 字符索引 `[start, end)`。
2. **绝对禁止**：
   - 禁止使用 UTF-8 字节偏移作为字符位置。
   - 禁止返回浮点数或布尔值替代整型坐标。
   - 禁止在归一化（如 `lower()`、`strip()`、Unicode NFKC 规约）后的派生字符串上计算索引，而必须能够映射回原串。
3. **核心不变量**：
   $$\forall f \in \text{fragments}, \quad 0 \le f.\text{start} < f.\text{end} \le \text{len}(\text{raw\_text}) \quad \land \quad \text{raw\_text}[f.\text{start} : f.\text{end}] == f.\text{text}$$

---

## 二、坐标回查与断言验证机制

在测试框架与运行时校验中，我们实施了逐层回查断言：

```python
# 1. 真实 Memory 存储回查
cit = MemoryCitation(
    memory_ref=fragment.address.memory.artifact,
    entry_id=fragment.address.entry_id,
    entry_version_id=fragment.address.entry_version_id,
)
entry = await memory.get(GetMemoryEntryRequest(citation=cit))
raw_text = entry.entry.text

# 2. 坐标与切片严格不变量
assert type(fragment.start) is int and type(fragment.end) is int
assert 0 <= fragment.start < fragment.end <= len(raw_text)
assert raw_text[fragment.start : fragment.end] == fragment.text

# 3. JSON 信封与片段对应一致
assert item["content"] == fragment.text
assert item["start"] == fragment.start
assert item["end"] == fragment.end
```

---

## 三、复杂边界场景的坐标验证

| 场景用例 | 文本特征 | 验证要点 | 结论 |
| :--- | :--- | :--- | :---: |
| **中文字符（T09）** | `海洋观测站记录温度数据。` | 中文字符每个在 Python 中占用 1 个字符宽度，但在 UTF-8 中占 3 个字节。验证切片基于字符偏移，`raw[0:5] == '海洋观测站'`，未混淆字节与字符。 | **PASS** |
| **Emoji 与多字节（T10）** | `🛰️ Satellite telemetry recorded 25 degrees.` | 复杂 Unicode 字符（卫星 Emoji 由变音符号及高位码点组成），切片完全保持原 Emoji 完整性，不发生裂字。 | **PASS** |
| **长文本后部（T02, T03）** | 前缀 70 次重复背景文字，事实位于第 2100 字符之后 | 验证坐标能够正确标定在 `[2100, 2145)`，而非重新在文本前部搜索相同关键词导致位置错乱。 | **PASS** |
| **大小写混合（T12）** | 文本包含大写基因名 `BRCA2`，查询使用小写 `brca2` | 匹配打分使用小写分词，但在截取坐标及正文切片时保留原始大写，`raw[start:end]` 完全等于原始字符。 | **PASS** |
| **特殊字符与转义（T11, T27）** | 包含 Windows 路径 `C:\OceanBase\Data` 与双引号 `"` | 原文反斜杠与引号原样保留在 `fragment.text`，JSON 传输时虽转义为 `\"`，但坐标计算仍忠实于原始切片。 | **PASS** |
| **重叠与相邻合并（T07, T08）** | 两个相关句子相邻，中间仅隔一个空格或句号 | 合并后的新区间 `[start_1, end_2)` 切片 `raw[start_1:end_2]` 包含中间连接符号，坐标依然严密满足半开区间定义。 | **PASS** |
