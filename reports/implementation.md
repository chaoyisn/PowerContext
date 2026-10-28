# PowerContext 赛题十：功能实现详解与代码剖析

## 一、修改文件清单与职责说明

1. `src/powercontext/builtin/runtime/models.py`:
   - 在 `PrepareContextRequest` 模型中新增字段 `evidence_selection: bool = Field(default=False, strict=True)`。
2. `src/powercontext/builtin/runtime/prepared_context.py`:
   - 新增 `EvidenceFragment` 数据类。
   - 在 `PreparedContextBuild` 中新增 `fragments: tuple[EvidenceFragment, ...] = ()` 字段。
   - 在 `PreparedContextBuilder` 中增加 `_build_evidence_selection_result` 及其多语言分词、句子切分、BM25 打分、相邻合并和信封序列化实现。
   - 在 `build_scopes_result` 和 `probe_budget` 中接入分流逻辑。
3. `src/powercontext/http/_generated/models.py`:
   - 在 HTTP 契约模型 `PrepareContextRequest` 中声明 `evidence_selection: Annotated[StrictBool, ...] = False`，保证 HTTP API 映射畅通。
4. `tests/unit/test_query_aware_evidence_selection.py`:
   - 全量覆盖 T01-T30 场景及性质测试的新增测试套件。

---

## 二、关键算法实现细节

### 2.1 多语言词项提取与停用词过滤

```python
_STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    ...
})

def _tokenize_evidence_text(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    cjk = re.findall(r"[\u4e00-\u9fff]", text.lower())
    tokens = words + cjk
    if len(cjk) > 1:
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i] + cjk[i + 1])
    return tokens
```

- 将文本转小写后分别提取英文/数字 token 与 CJK 字符。
- 对于 CJK 文本自动补充 Bigram，从而在无空格中文语境中准确匹配短语。

### 2.2 绝对字符位置切分与回查一致性

```python
def _extract_sentence_spans(raw_text: str) -> list[tuple[int, int]]:  # noqa: C901
    spans: list[tuple[int, int]] = []
    pattern = re.compile(r'(?<=[.!?\u3002\uff01\uff1f])\s+|\n+|(?<=[\u3002\uff01\uff1f\uff1b])')
    pos = 0
    for match in pattern.finditer(raw_text):
        start = pos
        end = match.start()
        while start < end and raw_text[start].isspace():
            start += 1
        while end > start and raw_text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
        pos = match.end()
    if pos < len(raw_text):
        start = pos
        end = len(raw_text)
        while start < end and raw_text[start].isspace():
            start += 1
        while end > start and raw_text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
    if not spans:
        start = 0
        end = len(raw_text)
        while start < end and raw_text[start].isspace():
            start += 1
        while end > start and raw_text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
    return spans
```

- **字符不变量维护**：通过在原串 `raw_text` 上扫描匹配，区间 `[start, end)` 直接对应 Python Unicode 字符索引。
- 保证 `raw_text[start:end]` 恒等于片段文本，无需在归一化后反向猜测原串位置。

### 2.3 BM25 + 查询覆盖率 + 模式优先打分

```python
coverage = len(set(matched)) / len(q_content_set)
bm25 = 0.0
for t in matched:
    idf = math.log(1.0 + (N - df[t] + 0.5) / (df[t] + 0.5)) + 1.0
    tf = tokens.count(t)
    bm25 += idf * (tf * 2.5) / (tf + 1.5)

phrase_boost = 0.0
lower_slice = text_slice.lower()
if lower_query and lower_query in lower_slice:
    phrase_boost += 8.0
elif len(query_words) >= 2:
    for i in range(len(query_words) - 1):
        bigram = f"{query_words[i]} {query_words[i + 1]}"
        if bigram in lower_slice:
            phrase_boost += 2.0

num_boost = sum(3.0 for t in matched if t.isdigit())
doc_prior = 1.0 / (1.0 + hit_idx)

score = (1.0 + 3.0 * coverage) * bm25 + phrase_boost + num_boost + doc_prior
```

- 采用覆盖率乘子 `(1.0 + 3.0 * coverage)` 强烈偏好包含多个不同查询关键词的句子。
- 完整短语匹配奖励 `+8.0`，二元组奖励 `+2.0`。
- 数字实体命中奖励 `+3.0`，提高关键事实参数（温度、端口、阈值）的召回率。

### 2.4 相邻证据合并与 UTF-8 真实预算模拟

```python
for cand in all_candidate_spans:
    merged_index = -1
    cand_key = (cand.group.scope_id, cand.hit.entry_id, cand.hit.entry_version_id)
    for i, sel in enumerate(selected):
        sel_key = (sel.group.scope_id, sel.hit.entry_id, sel.hit.entry_version_id)
        if sel_key != cand_key:
            continue
        overlap = not (cand.end < sel.start or cand.start > sel.end)
        adjacent = False
        if not overlap:
            gap_s = min(sel.end, cand.end)
            gap_e = max(sel.start, cand.start)
            gap_text = cand.hit.text[gap_s:gap_e]
            if gap_s == gap_e or gap_text.strip() == "" or gap_text in {".", ",", ";", " - "}:
                adjacent = True
        if overlap or adjacent:
            merged_index = i
            break

    if merged_index >= 0:
        exist = selected[merged_index]
        new_start = min(exist.start, cand.start)
        new_end = max(exist.end, cand.end)
        merged_cand = _CandidateEvidenceSpan(
            group=exist.group,
            hit=exist.hit,
            hit_idx=exist.hit_idx,
            start=new_start,
            end=new_end,
            text=exist.hit.text[new_start:new_end],
            score=exist.score + cand.score,
        )
        trial = list(selected)
        trial[merged_index] = merged_cand
        if _evidence_envelope_bytes(_make_items(trial)) <= request.max_bytes:
            selected = trial
        else:
            dropped_items += 1
    else:
        trial = [*selected, cand]
        if _evidence_envelope_bytes(_make_items(trial)) <= request.max_bytes:
            selected = trial
        else:
            if not selected:
                # 首个证据超预算时在字符边界二分收缩
                low = cand.start + 10
                high = cand.end - 1
                best_cand = None
                while low <= high:
                    mid = (low + high) // 2
                    sub_text = cand.hit.text[cand.start:mid]
                    trial_c = _CandidateEvidenceSpan(
                        group=cand.group,
                        hit=cand.hit,
                        hit_idx=cand.hit_idx,
                        start=cand.start,
                        end=mid,
                        text=sub_text,
                        score=cand.score,
                    )
                    if _evidence_envelope_bytes(_make_items([trial_c])) <= request.max_bytes:
                        best_cand = trial_c
                        low = mid + 1
                    else:
                        high = mid - 1
                if best_cand is not None:
                    selected = [best_cand]
                else:
                    dropped_items += 1
            else:
                dropped_items += 1
```

- 每次接纳新片段或合并时，直接调用 `_evidence_envelope_bytes(_make_items(trial))` 计算最终 UTF-8 编码字节数。
- 杜绝静态估算偏差与生成后硬截断。
