import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  getMemoryHistory,
  getMemoryStatus,
  listProjects,
  restoreProgress,
  saveProgress,
  searchDocuments,
  type EvidencePointer,
  type MemoryEntry,
  type MemoryHistoryResponse,
  type MemoryStatusResponse,
  type PreparedContext,
  type Project,
  type RetrievalHit,
  type RestoreResponse,
  type SaveProgressResponse,
} from '../api/client'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MEMORY_KIND_ORDER,
  Panel,
  SourceTag,
  StatusDot,
  formatScore,
  formatTimestamp,
  memoryKindLabel,
} from '../components/common'
import { useErrorToast, useToast } from '../components/Toast'
import './MemoryPage.css'

const EMPTY_EVIDENCE: EvidencePointer = {
  doc_id: '',
  filename: '',
  page_no: 0,
  chunk_id: '',
  quote: '',
}

export default function MemoryPage() {
  const toast = useToast()
  const toastError = useErrorToast()

  const [projects, setProjects] = useState<Project[]>([])
  const [projectsError, setProjectsError] = useState<unknown | null>(null)
  const [selectedProject, setSelectedProject] = useState('')

  const [status, setStatus] = useState<MemoryStatusResponse | null>(null)
  const [statusError, setStatusError] = useState<unknown | null>(null)

  const loadProjects = useCallback(async () => {
    try {
      const data = await listProjects()
      setProjects(data.projects)
      setProjectsError(null)
    } catch (err) {
      setProjectsError(err)
    }
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getMemoryStatus())
      setStatusError(null)
    } catch (err) {
      setStatus(null)
      setStatusError(err)
    }
  }, [])

  useEffect(() => {
    void loadProjects()
    void loadStatus()
  }, [loadProjects, loadStatus])

  return (
    <div>
      <div className="page-title-row">
        <h1>任务记忆</h1>
        <SourceTag source="powercontext" />
      </div>
      <p className="page-desc">
        长期研究任务记忆（目标、已完成工作、已确认决策、关键证据指针、未解决问题、下一步）存于
        PowerContext，与 seekdb 的文献证据完全分离。保存永远由用户显式触发，系统不会自动写入；
        恢复的续研简报让换一个会话之后也能接着上次的进度继续工作。
      </p>

      <MemoryStatusBanner status={status} error={statusError} onRetry={() => void loadStatus()} />

      <Panel title="选择项目">
        {projectsError ? (
          <ErrorState error={projectsError} onRetry={() => void loadProjects()} />
        ) : projects.length === 0 ? (
          <EmptyState text="还没有项目。请先到「项目总览」页创建项目。" />
        ) : (
          <div className="form-row">
            <div className="field">
              <label htmlFor="memory-project">项目</label>
              <select
                id="memory-project"
                className="select"
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
              >
                <option value="">请选择项目</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.title}（{project.project_id}）
                  </option>
                ))}
              </select>
            </div>
            {selectedProject ? (
              <span className="field-hint memory-scope-hint">
                scope_id：
                <code>
                  {projects.find((p) => p.project_id === selectedProject)?.scope_id ?? '未绑定（首次保存时绑定）'}
                </code>
              </span>
            ) : null}
          </div>
        )}
      </Panel>

      {selectedProject ? (
        <>
          <SavePanel projectId={selectedProject} onError={toastError} onSuccess={toast} />
          <RestorePanel projectId={selectedProject} onError={toastError} />
          <HistoryPanel projectId={selectedProject} onError={toastError} />
        </>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------- 状态横幅

function MemoryStatusBanner({
  status,
  error,
  onRetry,
}: {
  status: MemoryStatusResponse | null
  error: unknown | null
  onRetry: () => void
}) {
  return (
    <Panel
      title="PowerContext 状态"
      tags={<SourceTag source="powercontext" />}
      actions={
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          刷新
        </button>
      }
    >
      {error && !status ? (
        <div>
          <ErrorState error={error} onRetry={onRetry} />
          <div className="banner banner-amber" style={{ marginTop: 'var(--sp-1)' }} role="status">
            PowerContext 不可用，检索与问答不受影响（它们只依赖 seekdb）。
          </div>
        </div>
      ) : null}
      {status ? (
        <div className="memory-status-body">
          <div className={status.available ? 'banner banner-info' : 'banner banner-amber'} role="status">
            <StatusDot level={status.available ? 'green' : 'red'} />
            <span>
              {status.backend}（{status.role}）
              {status.available ? ' 可用' : ' 不可用'} · <code>{status.url}</code>
              {status.package_version ? <> · package_version {status.package_version}</> : null}
              {status.error ? <div className="mono">原因：{status.error}</div> : null}
            </span>
          </div>
          <p className="memory-status-note">{status.note}</p>
        </div>
      ) : null}
    </Panel>
  )
}

// ---------------------------------------------------------------- 保存

function SavePanel({
  projectId,
  onError,
  onSuccess,
}: {
  projectId: string
  onError: (err: unknown, title?: string) => void
  onSuccess: (toast: { kind: 'success'; title: string; message?: string }) => void
}) {
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [completedWork, setCompletedWork] = useState<string[]>([])
  const [decisions, setDecisions] = useState<string[]>([])
  const [keyEvidence, setKeyEvidence] = useState<EvidencePointer[]>([])
  const [openQuestions, setOpenQuestions] = useState<string[]>([])
  const [nextSteps, setNextSteps] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [confirmedBy, setConfirmedBy] = useState('user')

  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<SaveProgressResponse | null>(null)
  const [saveError, setSaveError] = useState<unknown | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const hasContent =
      objective.trim() ||
      completedWork.some((item) => item.trim()) ||
      decisions.some((item) => item.trim()) ||
      keyEvidence.length > 0 ||
      openQuestions.some((item) => item.trim()) ||
      nextSteps.some((item) => item.trim())
    if (!hasContent) {
      setFormError(
        '没有可保存的内容：objective / completed_work / decisions / key_evidence / open_questions / next_steps 至少填写一项。'
      )
      return
    }
    setFormError(null)
    setSaving(true)
    setSaveError(null)
    setResult(null)
    try {
      const saved = await saveProgress(projectId, {
        title: title.trim(),
        objective: objective.trim(),
        completed_work: completedWork.map((item) => item.trim()).filter(Boolean),
        decisions: decisions.map((item) => item.trim()).filter(Boolean),
        key_evidence: keyEvidence.map((item) => ({ ...item, quote: item.quote.slice(0, 600) })),
        open_questions: openQuestions.map((item) => item.trim()).filter(Boolean),
        next_steps: nextSteps.map((item) => item.trim()).filter(Boolean),
        note: note.trim(),
        confirmed_by: confirmedBy.trim() || 'user',
      })
      setResult(saved)
      onSuccess({
        kind: 'success',
        title:
          saved.written === 0 && saved.snapshot_unchanged
            ? '内容未变化，未产生重复记忆'
            : `研究进度已显式保存（写入 ${saved.written} 条，去重跳过 ${saved.skipped_duplicates} 条）`,
      })
    } catch (err) {
      setSaveError(err)
      onError(err, '保存研究进度失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      title="显式保存研究进度"
      tags={<SourceTag source="powercontext" />}
      subtitle="保存永远由你手动触发；模型输出不会被自动写入记忆"
      className="panel-memory"
    >
      <form onSubmit={submit}>
        <div className="form-row">
          <div className="field">
            <label htmlFor="save-title">项目标题 title（可选，覆盖注册表标题）</label>
            <input
              id="save-title"
              className="input"
              value={title}
              maxLength={256}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="留空则沿用项目注册时的标题"
            />
          </div>
          <div className="field">
            <label htmlFor="save-confirmed">confirmed_by</label>
            <input
              id="save-confirmed"
              className="input"
              value={confirmedBy}
              maxLength={64}
              onChange={(e) => setConfirmedBy(e.target.value)}
            />
            <span className="field-hint">默认 user——每条记忆都会记录「由谁确认保存」。</span>
          </div>
        </div>

        <div className="field" style={{ marginTop: 'var(--sp-2)' }}>
          <label htmlFor="save-objective">研究目标 objective</label>
          <textarea
            id="save-objective"
            className="textarea"
            value={objective}
            maxLength={2000}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="这个项目要回答的核心问题"
          />
        </div>

        <StringListEditor
          id="save-completed"
          label="已完成工作 completed_work"
          items={completedWork}
          onChange={setCompletedWork}
          placeholder="例如：完成了 3 篇对比论文的入库与页级切分"
        />
        <StringListEditor
          id="save-decisions"
          label="已确认决策 decisions"
          items={decisions}
          onChange={setDecisions}
          placeholder="例如：D1 — 采用 hybrid（RRF）作为默认检索模式"
        />

        <EvidenceEditor evidence={keyEvidence} onChange={setKeyEvidence} onError={onError} />

        <StringListEditor
          id="save-open"
          label="未解决问题 open_questions"
          items={openQuestions}
          onChange={setOpenQuestions}
          placeholder="例如：空白页对 BM25 统计的影响还没有量化"
        />
        <StringListEditor
          id="save-next"
          label="下一步 next_steps"
          items={nextSteps}
          onChange={setNextSteps}
          placeholder="例如：补一组 top_k=20 的召回对比实验"
        />

        <div className="field" style={{ marginTop: 'var(--sp-2)' }}>
          <label htmlFor="save-note">备注 note（可选）</label>
          <textarea
            id="save-note"
            className="textarea"
            value={note}
            maxLength={1000}
            onChange={(e) => setNote(e.target.value)}
            placeholder="本次保存的补充说明"
          />
        </div>

        {formError ? (
          <div className="banner banner-red" style={{ marginTop: 'var(--sp-2)' }} role="alert">
            {formError}
          </div>
        ) : null}

        <div className="save-actions">
          <button type="submit" className="btn btn-memory" disabled={saving}>
            {saving ? '正在写入 PowerContext…' : '显式保存研究进度'}
          </button>
          <span className="field-hint">
            这是一个刻意的用户动作：系统永不自动保存，重复内容会被去重（skipped_duplicates）。
          </span>
        </div>
      </form>

      {saveError ? (
        <div style={{ marginTop: 'var(--sp-2)' }}>
          <ErrorState error={saveError} />
        </div>
      ) : null}

      {result ? <SaveResultView result={result} /> : null}
    </Panel>
  )
}

function SaveResultView({ result }: { result: SaveProgressResponse }) {
  const unchanged = result.written === 0 && result.snapshot_unchanged
  return (
    <div className={unchanged ? 'save-result save-result-unchanged' : 'save-result'} role="status">
      <div className="save-result-title">
        {unchanged ? '内容未变化，未产生重复记忆' : '保存成功'}
      </div>
      <div className="meta-grid">
        <span className="meta-item">
          <span className="meta-key">seq</span>
          <span className="meta-value">{result.seq}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">written</span>
          <span className="meta-value">{result.written}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">skipped_duplicates</span>
          <span className="meta-value">{result.skipped_duplicates}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">snapshot_unchanged</span>
          <span className="meta-value">{result.snapshot_unchanged ? '是' : '否'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">snapshot_artifact_id</span>
          <span className="meta-value mono">{result.snapshot_artifact_id ?? '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">snapshot_revision</span>
          <span className="meta-value">{result.snapshot_revision ?? '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">scope_id</span>
          <span className="meta-value mono">{result.scope_id}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">updated_at</span>
          <span className="meta-value">{result.updated_at}</span>
        </span>
      </div>
      <div className="save-result-kinds">
        <span className="meta-key">written_kinds：</span>
        {result.written_kinds.length === 0 ? (
          <span className="memory-empty-inline">（本次没有新增离散记忆条目）</span>
        ) : (
          result.written_kinds.map((kind, index) => (
            <span key={`${kind}-${index}`} className="badge badge-memory">
              {memoryKindLabel(kind)}（{kind}）
            </span>
          ))
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 字符串列表编辑器

function StringListEditor({
  id,
  label,
  items,
  onChange,
  placeholder,
}: {
  id: string
  label: string
  items: string[]
  onChange: (items: string[]) => void
  placeholder?: string
}) {
  const update = (index: number, value: string) =>
    onChange(items.map((item, i) => (i === index ? value : item)))
  const remove = (index: number) => onChange(items.filter((_, i) => i !== index))
  const add = () => onChange([...items, ''])

  return (
    <fieldset className="list-editor">
      <legend>{label}</legend>
      {items.length === 0 ? (
        <p className="list-editor-empty">还没有条目，点击下方「添加一行」。</p>
      ) : (
        <ul className="list-editor-rows">
          {items.map((item, index) => (
            <li key={index} className="list-editor-row">
              <label className="visually-hidden" htmlFor={`${id}-${index}`}>
                {label} 第 {index + 1} 条
              </label>
              <input
                id={`${id}-${index}`}
                className="input"
                value={item}
                placeholder={placeholder}
                onChange={(e) => update(index, e.target.value)}
              />
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => remove(index)}
                aria-label={`删除${label}第 ${index + 1} 条`}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn btn-sm" onClick={add} disabled={items.length >= 50}>
        添加一行
      </button>
    </fieldset>
  )
}

// ---------------------------------------------------------------- 关键证据编辑器 + 引用选择器

function EvidenceEditor({
  evidence,
  onChange,
  onError,
}: {
  evidence: EvidencePointer[]
  onChange: (items: EvidencePointer[]) => void
  onError: (err: unknown, title?: string) => void
}) {
  const [pickerQuery, setPickerQuery] = useState('')
  const [pickerSearching, setPickerSearching] = useState(false)
  const [pickerHits, setPickerHits] = useState<RetrievalHit[]>([])
  const [pickerError, setPickerError] = useState<unknown | null>(null)
  const [pickerSearched, setPickerSearched] = useState(false)

  const update = (index: number, patch: Partial<EvidencePointer>) =>
    onChange(evidence.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  const remove = (index: number) => onChange(evidence.filter((_, i) => i !== index))
  const addEmpty = () => onChange([...evidence, { ...EMPTY_EVIDENCE }])

  const addFromHit = (hit: RetrievalHit) => {
    if (evidence.length >= 30) {
      onError(new Error('key_evidence 最多 30 条（后端限制）'), '无法添加')
      return
    }
    onChange([
      ...evidence,
      {
        doc_id: hit.doc_id,
        filename: hit.filename,
        page_no: hit.page_no,
        chunk_id: hit.chunk_id,
        quote: hit.text.slice(0, 600),
      },
    ])
  }

  const runPicker = async (event: FormEvent) => {
    event.preventDefault()
    if (!pickerQuery.trim()) return
    setPickerSearching(true)
    setPickerError(null)
    setPickerSearched(true)
    try {
      const result = await searchDocuments({ query: pickerQuery.trim(), mode: 'hybrid', top_k: 10 })
      setPickerHits(result.hits)
    } catch (err) {
      setPickerHits([])
      setPickerError(err)
      onError(err, '证据检索失败')
    } finally {
      setPickerSearching(false)
    }
  }

  return (
    <fieldset className="list-editor evidence-editor">
      <legend>
        关键证据 key_evidence（指向 seekdb 的页级指针，最多 30 条）
        <SourceTag source="seekdb" />
      </legend>

      {evidence.length === 0 ? (
        <p className="list-editor-empty">
          还没有证据条目。可以用下方「从检索结果选择」自动填充 doc_id / filename / page_no / chunk_id / quote，也可以手动添加。
        </p>
      ) : (
        <ul className="evidence-rows">
          {evidence.map((item, index) => (
            <li key={index} className="evidence-row">
              <div className="evidence-row-grid">
                <div className="field">
                  <label htmlFor={`ev-doc-${index}`}>doc_id</label>
                  <input
                    id={`ev-doc-${index}`}
                    className="input mono-input"
                    value={item.doc_id}
                    onChange={(e) => update(index, { doc_id: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`ev-file-${index}`}>filename</label>
                  <input
                    id={`ev-file-${index}`}
                    className="input"
                    value={item.filename}
                    onChange={(e) => update(index, { filename: e.target.value })}
                  />
                </div>
                <div className="field field-page">
                  <label htmlFor={`ev-page-${index}`}>page_no</label>
                  <input
                    id={`ev-page-${index}`}
                    className="input"
                    type="number"
                    min={0}
                    value={item.page_no}
                    onChange={(e) => update(index, { page_no: Number.parseInt(e.target.value, 10) || 0 })}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`ev-chunk-${index}`}>chunk_id</label>
                  <input
                    id={`ev-chunk-${index}`}
                    className="input mono-input"
                    value={item.chunk_id}
                    onChange={(e) => update(index, { chunk_id: e.target.value })}
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor={`ev-quote-${index}`}>quote（≤600 字）</label>
                <textarea
                  id={`ev-quote-${index}`}
                  className="textarea"
                  rows={2}
                  maxLength={600}
                  value={item.quote}
                  onChange={(e) => update(index, { quote: e.target.value })}
                />
              </div>
              <div className="evidence-row-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => remove(index)}
                  aria-label={`删除第 ${index + 1} 条关键证据`}
                >
                  删除此条证据
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="evidence-actions">
        <button type="button" className="btn btn-sm" onClick={addEmpty} disabled={evidence.length >= 30}>
          手动添加一行
        </button>
      </div>

      <div className="citation-picker">
        <div className="citation-picker-title">从检索结果选择（POST /api/retrieval/search，hybrid）</div>
        <form onSubmit={runPicker} className="citation-picker-form">
          <label className="visually-hidden" htmlFor="evidence-picker-query">
            证据检索关键词
          </label>
          <input
            id="evidence-picker-query"
            className="input"
            value={pickerQuery}
            maxLength={2000}
            onChange={(e) => setPickerQuery(e.target.value)}
            placeholder="检索文献内容，命中后可一键加入关键证据"
          />
          <button type="submit" className="btn" disabled={pickerSearching || !pickerQuery.trim()}>
            {pickerSearching ? '检索中…' : '检索'}
          </button>
        </form>
        {pickerError ? <ErrorState error={pickerError} /> : null}
        {pickerSearched && !pickerSearching && !pickerError && pickerHits.length === 0 ? (
          <EmptyState text="没有检索命中，换个关键词试试。" />
        ) : null}
        {pickerHits.length > 0 ? (
          <ul className="picker-hit-list">
            {pickerHits.map((hit) => (
              <li key={hit.chunk_id} className="picker-hit">
                <div className="picker-hit-head">
                  <span className="picker-hit-name">
                    {hit.filename || hit.doc_id} · 第 {hit.page_no} 页
                  </span>
                  <span className="badge">
                    relevance {formatScore(hit.relevance)} · {hit.score_kind}
                  </span>
                  <button type="button" className="btn btn-sm" onClick={() => addFromHit(hit)}>
                    加入关键证据
                  </button>
                </div>
                <div className="picker-hit-id mono">{hit.chunk_id}</div>
                <p className="picker-hit-text">{hit.text}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </fieldset>
  )
}

// ---------------------------------------------------------------- 恢复

function RestorePanel({
  projectId,
  onError,
}: {
  projectId: string
  onError: (err: unknown, title?: string) => void
}) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<RestoreResponse | null>(null)
  const [error, setError] = useState<unknown | null>(null)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(
    async (recallQuery: string) => {
      setLoading(true)
      setError(null)
      setLoaded(true)
      try {
        setData(await restoreProgress(projectId, recallQuery))
      } catch (err) {
        setData(null)
        setError(err)
        onError(err, '恢复任务记忆失败')
      } finally {
        setLoading(false)
      }
    },
    [projectId, onError]
  )

  useEffect(() => {
    void load('')
    // 切换项目时自动重新恢复一次（不带 recall query）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  return (
    <Panel
      title="恢复研究进度"
      tags={<SourceTag source="powercontext" />}
      subtitle="换会话后从这里继续工作；可选填 recall query 让 PowerContext 做相关性召回"
      className="panel-memory"
      actions={
        <button type="button" className="btn btn-sm" onClick={() => void load(query)} disabled={loading}>
          重新恢复
        </button>
      }
    >
      <form
        className="restore-form"
        onSubmit={(event) => {
          event.preventDefault()
          void load(query)
        }}
      >
        <div className="field">
          <label htmlFor="restore-query">recall query（可选）</label>
          <input
            id="restore-query"
            className="input"
            value={query}
            maxLength={2000}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：上次关于检索门控的决策（纯中文可能不命中 FTS，后端会用 ASCII 锚点扩展）"
          />
        </div>
        <button type="submit" className="btn" disabled={loading}>
          {loading ? '恢复中…' : '恢复记忆'}
        </button>
      </form>

      {loading ? <LoadingState text="正在从 PowerContext 读取记忆…" /> : null}
      {!loading && error ? <ErrorState error={error} onRetry={() => void load(query)} /> : null}
      {!loading && data ? <RestoreView data={data} /> : null}
      {!loading && !error && !data && loaded ? <EmptyState text="没有恢复结果。" /> : null}
    </Panel>
  )
}

function RestoreView({ data }: { data: RestoreResponse }) {
  if (!data.memory_available) {
    return (
      <div>
        <div className="banner banner-amber" role="status">
          PowerContext 不可用，检索与问答不受影响（它们只依赖 seekdb）。
          {data.error ? <div className="mono memory-error-detail">原因：{data.error}</div> : null}
        </div>
        {data.resume_brief ? <pre className="memory-brief">{data.resume_brief}</pre> : null}
      </div>
    )
  }

  return (
    <div className="restore-view">
      <div className="meta-grid restore-meta">
        <span className="meta-item">
          <span className="meta-key">scope_id</span>
          <span className="meta-value mono">{data.scope_id ?? '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">记忆条数</span>
          <span className="meta-value">{data.entry_count}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">package_version</span>
          <span className="meta-value mono">{data.memory_backend.package_version ?? '—'}</span>
        </span>
      </div>

      <h3 className="memory-subtitle">续研简报 resume_brief（换会话后从这里继续）</h3>
      {data.resume_brief ? (
        <pre className="memory-brief">{data.resume_brief}</pre>
      ) : (
        <EmptyState text="没有可生成的简报（尚无任何记忆）。" />
      )}

      <h3 className="memory-subtitle" style={{ marginTop: 'var(--sp-2)' }}>
        按类型分组的记忆条目
      </h3>
      <div className="restore-grouped">
        {MEMORY_KIND_ORDER.map((kind) => {
          const entries = data.grouped[kind] ?? []
          if (entries.length === 0) return null
          return (
            <div key={kind} className="restore-kind-block">
              <div className="restore-kind-title">
                {memoryKindLabel(kind)}（{kind} · {entries.length} 条）
              </div>
              <ul className="restore-entry-list">
                {entries.map((entry, index) => (
                  <li key={`${entry.artifact_id}-${index}`}>
                    {kind === 'progress_snapshot' ? (
                      <span className="mono restore-snapshot-text">{entry.text.slice(0, 240)}…</span>
                    ) : (
                      <span>{entry.text}</span>
                    )}
                    <span className="restore-entry-meta mono">
                      seq {entry.seq} · {entry.updated_at || '—'} · {entry.artifact_id} · rev{' '}
                      {entry.revision} · {entry.state}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      {data.prepared_context ? <PreparedContextBlock context={data.prepared_context} /> : null}
    </div>
  )
}

function PreparedContextBlock({ context }: { context: PreparedContext }) {
  return (
    <details className="collapsible memory-prepared" style={{ marginTop: 'var(--sp-2)' }}>
      <summary>prepared_context（PowerContext 上下文准备细节）</summary>
      <div className="meta-grid" style={{ marginTop: 'var(--sp-1)' }}>
        <span className="meta-item">
          <span className="meta-key">status</span>
          <span className="meta-value mono">{context.status || '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">content_bytes</span>
          <span className="meta-value">{context.content_bytes}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">search_mode</span>
          <span className="meta-value mono">{context.search_mode || '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">recall_query_expanded</span>
          <span className="meta-value">{context.recall_query_expanded ? '是（已用 ASCII 锚点扩展）' : '否'}</span>
        </span>
      </div>
      <div className="memory-recall">
        <span className="meta-key">recall_query：</span>
        <code>{context.recall_query}</code>
      </div>
      {context.search_hits.length > 0 ? (
        <ul className="memory-hit-list">
          {context.search_hits.map((hit, index) => (
            <li key={index}>
              <span className="badge badge-memory">{hit.kind}</span>
              <span className="memory-hit-text">{hit.text}</span>
              <span className="memory-hit-score mono">score {formatScore(hit.score)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="memory-empty-inline">search_memory 没有命中。</p>
      )}
      <p className="memory-note">{context.note}</p>
    </details>
  )
}

// ---------------------------------------------------------------- 历史

function HistoryPanel({
  projectId,
  onError,
}: {
  projectId: string
  onError: (err: unknown, title?: string) => void
}) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<MemoryHistoryResponse | null>(null)
  const [error, setError] = useState<unknown | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await getMemoryHistory(projectId))
    } catch (err) {
      setData(null)
      setError(err)
      onError(err, '读取记忆历史失败')
    } finally {
      setLoading(false)
    }
  }, [projectId, onError])

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const entries = data ? [...data.entries].sort((a, b) => a.seq - b.seq) : []

  return (
    <Panel
      title="记忆历史"
      tags={<SourceTag source="powercontext" />}
      subtitle={
        data
          ? `共 ${data.entry_count} 条记忆 · ${data.snapshot_count} 个进度快照（按 seq 排序）`
          : '按 seq 排序的全部原子记忆'
      }
      className="panel-memory"
      actions={
        <button type="button" className="btn btn-sm" onClick={() => void load()} disabled={loading}>
          刷新
        </button>
      }
    >
      {loading ? <LoadingState text="正在读取 PowerContext 历史…" /> : null}
      {!loading && error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
      {!loading && data && entries.length === 0 ? (
        <EmptyState text="还没有任何记忆条目。先在上方显式保存一次研究进度。" />
      ) : null}
      {!loading && data && entries.length > 0 ? (
        <ol className="history-timeline">
          {entries.map((entry, index) => (
            <HistoryItem key={`${entry.artifact_id}-${index}`} entry={entry} />
          ))}
        </ol>
      ) : null}
    </Panel>
  )
}

function HistoryItem({ entry }: { entry: MemoryEntry }) {
  const isSnapshot = entry.kind === 'progress_snapshot'
  return (
    <li className={isSnapshot ? 'history-item history-item-snapshot' : 'history-item'}>
      <div className="history-marker" aria-hidden="true" />
      <div className="history-body">
        <div className="history-head">
          <span className={isSnapshot ? 'badge badge-memory' : 'badge'}>
            {memoryKindLabel(entry.kind)}（{entry.kind}）
          </span>
          <span className="history-meta mono">
            seq {entry.seq} · {formatTimestamp(entry.updated_at) || '—'} · {entry.artifact_id} · rev{' '}
            {entry.revision} · {entry.state}
          </span>
        </div>
        {isSnapshot ? (
          <pre className="history-snapshot-text">{entry.text}</pre>
        ) : (
          <div className="history-text">{entry.text}</div>
        )}
      </div>
    </li>
  )
}
