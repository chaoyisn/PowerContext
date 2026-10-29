import { useCallback, useEffect, useMemo, useState } from 'react'
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
  type ProgressSnapshot,
  type RestoreResponse,
  type RetrievalHit,
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
import { MemoryPanelBody, MemoryUnavailable } from '../components/EvidenceViews'
import Icon from '../components/Icon'
import { EvidenceSlot, PanelSection, useShell, useShellHeader } from '../components/Shell'
import { useErrorToast, useToast } from '../components/Toast'
import '../styles/memory.css'

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
  const shell = useShell()
  useShellHeader('研究进度', '历史记忆来自 PowerContext，与 seekdb 的文献证据分开存放')

  const [projects, setProjects] = useState<Project[]>([])
  const [projectsError, setProjectsError] = useState<unknown | null>(null)
  const [selectedProject, setSelectedProject] = useState(shell.project)

  const [status, setStatus] = useState<MemoryStatusResponse | null>(null)
  const [statusError, setStatusError] = useState<unknown | null>(null)

  const [recallQuery, setRecallQuery] = useState('')
  const [restoring, setRestoring] = useState(false)
  const [restored, setRestored] = useState<RestoreResponse | null>(null)
  const [restoreError, setRestoreError] = useState<unknown | null>(null)

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

  const runRestore = useCallback(
    async (projectId: string, query: string) => {
      setRestoring(true)
      setRestoreError(null)
      try {
        setRestored(await restoreProgress(projectId, query))
      } catch (err) {
        setRestored(null)
        setRestoreError(err)
        toastError(err, '恢复任务记忆失败')
      } finally {
        setRestoring(false)
      }
    },
    [toastError]
  )

  useEffect(() => {
    void loadProjects()
    void loadStatus()
  }, [loadProjects, loadStatus])

  // 本机记住的项目可能已被删除，别拿一个不存在的 scope 去请求。
  useEffect(() => {
    if (projects.length === 0) return
    if (selectedProject && !projects.some((project) => project.project_id === selectedProject)) {
      setSelectedProject('')
    }
  }, [projects, selectedProject])

  // 换一个会话、只选同一个项目就能接着上次继续——所以选中项目即刻自动恢复一次。
  useEffect(() => {
    if (!selectedProject) {
      setRestored(null)
      return
    }
    void runRestore(selectedProject, '')
  }, [selectedProject, runRestore])

  const pickProject = (projectId: string) => {
    setSelectedProject(projectId)
    shell.setProject(projectId)
  }

  const selected = projects.find((project) => project.project_id === selectedProject) ?? null

  return (
    <div className="page-inner page-inner-narrow scroll-thin">
      <div className="mem-intro">
        <h1>
          研究进度 <SourceTag source="powercontext" />
        </h1>
        <p>
          研究进度存在 PowerContext。保存永远由你显式触发，系统不会把模型输出自动写进记忆。
        </p>
      </div>

      <Panel
        title="记忆通道"
        subtitle="一个研究项目对应 PowerContext 里的一个 Scope"
        tags={<SourceTag source="powercontext" />}
        actions={
          <button type="button" className="btn btn-sm" onClick={() => void loadStatus()}>
            <Icon name="refresh" size={13} /> 刷新
          </button>
        }
      >
        <MemoryStatusBody status={status} error={statusError} />

        {projectsError ? (
          <div style={{ marginTop: 'var(--s-3)' }}>
            <ErrorState error={projectsError} onRetry={() => void loadProjects()} />
          </div>
        ) : projects.length === 0 ? (
          <div className="empty-state" style={{ marginTop: 'var(--s-3)' }}>
            还没有项目。请在左侧「研究项目」里新建一个，再回到这里保存进度。
          </div>
        ) : (
          <div className="mem-project-row">
            <div className="field">
              <label htmlFor="memory-project">研究项目</label>
              <select
                id="memory-project"
                className="select"
                value={selectedProject}
                onChange={(e) => pickProject(e.target.value)}
              >
                <option value="">请选择项目</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.title}（{project.project_id}）
                  </option>
                ))}
              </select>
            </div>
            {selected ? (
              <div className="mem-project-meta">
                <span className="field-hint">
                  scope_id：<code>{selected.scope_id || '未绑定（首次保存时绑定）'}</code>
                </span>
                {selected.objective ? (
                  <span className="field-hint">目标：{selected.objective}</span>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </Panel>

      {selectedProject ? (
        <>
          <Panel
            title="续研简报"
            subtitle="换一个会话之后，从这份简报接着往下做"
            tags={<SourceTag source="powercontext" />}
            actions={
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => void runRestore(selectedProject, recallQuery)}
                disabled={restoring}
              >
                <Icon name="refresh" size={13} /> 重新恢复
              </button>
            }
            className="panel-memory"
          >
            <RestoreControls
              query={recallQuery}
              setQuery={setRecallQuery}
              loading={restoring}
              onSubmit={() => void runRestore(selectedProject, recallQuery)}
            />
            {restoring ? <LoadingState text="正在从 PowerContext 读取记忆…" /> : null}
            {!restoring && restoreError ? (
              <ErrorState error={restoreError} onRetry={() => void runRestore(selectedProject, recallQuery)} />
            ) : null}
            {!restoring && restored ? <RestoreView data={restored} /> : null}
          </Panel>

          <SavePanel
            projectId={selectedProject}
            onError={toastError}
            onSuccess={(message) => {
              toast({ kind: 'success', title: message })
              void runRestore(selectedProject, recallQuery)
            }}
          />

          <HistoryPanel
            projectId={selectedProject}
            onError={toastError}
            refreshKey={restored?.entry_count ?? 0}
          />
        </>
      ) : (
        <Panel title="保存与恢复">
          <EmptyState text="选择一个研究项目后，这里会出现续研简报、显式保存与记忆历史。" />
        </Panel>
      )}

      <EvidenceSlot>
        <PanelSection title="记忆通道" count={restored ? `${restored.entry_count} 条` : 0}>
          {!selectedProject ? (
            <p className="side-empty">还没有选择项目。项目确定后，这里会常驻该项目的记忆摘要。</p>
          ) : restored && restored.memory_available ? (
            <MemoryPanelBody restored={restored} />
          ) : (
            <MemoryUnavailable reason={restored?.error ?? status?.error} />
          )}
        </PanelSection>
      </EvidenceSlot>
    </div>
  )
}

// ---------------------------------------------------------------- 通道状态

function MemoryStatusBody({
  status,
  error,
}: {
  status: MemoryStatusResponse | null
  error: unknown | null
}) {
  if (error && !status) {
    return (
      <>
        <ErrorState error={error} />
        <div className="banner banner-amber" style={{ marginTop: 'var(--s-2)' }} role="status">
          PowerContext 不可用时，文献检索与问答不受影响——它们只依赖 seekdb。
        </div>
      </>
    )
  }
  if (!status) return <LoadingState text="正在检测 PowerContext…" />
  return (
    <>
      <div className={status.available ? 'mem-status mem-status-ok' : 'mem-status mem-down'} role="status">
        <StatusDot level={status.available ? 'green' : 'red'} />
        <span className="mem-status-name">
          {status.backend}（{status.role}）
          {status.available ? ' 在线' : ' 不可用'}
        </span>
        <code className="mem-status-url">{status.url}</code>
        {status.package_version ? (
          <span className="mem-status-chip">v{status.package_version}</span>
        ) : null}
        {typeof status.latency_ms === 'number' ? (
          <span className="mem-status-chip">{status.latency_ms} ms</span>
        ) : null}
        {status.available && status.database_ready === false ? (
          <span className="badge badge-amber">database 未就绪</span>
        ) : null}
      </div>
      {status.error ? <div className="mem-status-reason mono">原因：{status.error}</div> : null}
      <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
        {status.note}
      </p>
    </>
  )
}

// ---------------------------------------------------------------- 恢复

function RestoreControls({
  query,
  setQuery,
  loading,
  onSubmit,
}: {
  query: string
  setQuery: (value: string) => void
  loading: boolean
  onSubmit: () => void
}) {
  return (
    <form
      className="mem-restore-form"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
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
  )
}

function RestoreView({ data }: { data: RestoreResponse }) {
  if (!data.memory_available) {
    return (
      <div>
        <div className="banner banner-amber" role="status">
          PowerContext 不可用，检索与问答不受影响（它们只依赖 seekdb）。
          {data.error ? <div className="mono">原因：{data.error}</div> : null}
        </div>
        {data.resume_brief ? <pre className="memory-brief">{data.resume_brief}</pre> : null}
      </div>
    )
  }

  return (
    <div className="restore-view">
      <div className="mem-facts">
        <span className="mem-fact">
          记忆条数 <strong>{data.entry_count}</strong>
        </span>
        <span className="mem-fact">
          scope_id <code>{data.scope_id ?? '—'}</code>
        </span>
        <span className="mem-fact">
          package_version <code>{data.memory_backend.package_version ?? '—'}</code>
        </span>
        {data.title ? <span className="mem-fact">{data.title}</span> : null}
      </div>

      {data.resume_brief ? (
        <>
          <div className="mem-block-title">续研简报 resume_brief（PowerContext 生成）</div>
          <pre className="memory-brief">{data.resume_brief}</pre>
        </>
      ) : (
        <EmptyState text="没有可生成的简报（尚无任何记忆）。" />
      )}

      <MemoryCards grouped={data.grouped} />
      {data.snapshot ? <SnapshotDetails snapshot={data.snapshot} /> : null}
      {data.prepared_context ? <PreparedContextBlock context={data.prepared_context} /> : null}
    </div>
  )
}

function MemoryCards({ grouped }: { grouped: Record<string, MemoryEntry[]> }) {
  const blocks = MEMORY_KIND_ORDER.filter((kind) => (grouped[kind] ?? []).length > 0)
  if (blocks.length === 0) {
    return <EmptyState text="还没有任何记忆条目。" />
  }
  return (
    <div className="mem-cards">
      {blocks.map((kind) => {
        const entries = grouped[kind] ?? []
        return (
          <div
            key={kind}
            className={kind === 'decision' ? 'mem-card mem-card-decision' : 'mem-card'}
          >
            <div className="mem-card-title">
              {memoryKindLabel(kind)}
              <span>{entries.length}</span>
            </div>
            <ul className="mem-card-list">
              {entries.map((entry, index) => (
                <li key={`${entry.artifact_id}-${index}`} title={`seq ${entry.seq} · ${entry.updated_at}`}>
                  {entry.kind === 'progress_snapshot' ? (
                    <span className="mono mem-card-snapshot">{entry.text.slice(0, 200)}…</span>
                  ) : (
                    entry.text
                  )}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function SnapshotDetails({ snapshot }: { snapshot: ProgressSnapshot }) {
  const evidence = snapshot.key_evidence ?? []
  return (
    <details className="collapsible" style={{ marginTop: 'var(--s-3)' }}>
      <summary>进度快照 progress_snapshot（seq {snapshot.seq ?? '—'}）</summary>
      <div className="meta-grid" style={{ marginTop: 'var(--s-2)' }}>
        <span className="meta-item">
          <span className="meta-key">objective</span>
          <span className="meta-value">{snapshot.objective || '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">confirmed_by</span>
          <span className="meta-value">{snapshot.confirmed_by ?? '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">updated_at</span>
          <span className="meta-value">{snapshot.updated_at ?? '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">fingerprint</span>
          <span className="meta-value mono">{snapshot.fingerprint ?? '—'}</span>
        </span>
      </div>
      {evidence.length > 0 ? (
        <ul className="mem-evidence-list">
          {evidence.map((item, index) => (
            <li key={`${item.chunk_id}-${index}`}>
              <span className="mem-evidence-name">
                {item.filename || item.doc_id} · 第 {item.page_no} 页
              </span>
              <span className="mono">{item.chunk_id}</span>
              {item.quote ? <p className="mem-evidence-quote">{item.quote}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </details>
  )
}

function PreparedContextBlock({ context }: { context: PreparedContext }) {
  return (
    <details className="collapsible" style={{ marginTop: 'var(--s-3)' }}>
      <summary>召回细节 prepared_context（PowerContext 上下文准备）</summary>
      <div className="meta-grid" style={{ marginTop: 'var(--s-2)' }}>
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
      <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
        recall_query：<code>{context.recall_query}</code>
      </p>
      {context.search_hits.length > 0 ? (
        <ul className="mem-recall-hits">
          {context.search_hits.map((hit, index) => (
            <li key={`${hit.artifact_id}-${index}`}>
              <span className="badge badge-memory">{memoryKindLabel(hit.kind)}</span>
              <span className="mem-recall-text">{hit.text}</span>
              <span className="mono mem-recall-score">score {formatScore(hit.score)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-hint">
          search_memory 没有命中；完整记忆通过 list_memory_entries 全量读取，不依赖关键词搜索。
        </p>
      )}
      <p className="field-hint">{context.note}</p>
    </details>
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
  onSuccess: (message: string) => void
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
      onSuccess(
        saved.written === 0 && saved.snapshot_unchanged
          ? '内容未变化，未产生重复记忆'
          : `研究进度已显式保存（写入 ${saved.written} 条，去重跳过 ${saved.skipped_duplicates} 条）`
      )
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
      subtitle="保存永远由你手动触发；模型输出不会被自动写入记忆"
      tags={<SourceTag source="powercontext" />}
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
          <div className="field field-narrow">
            <label htmlFor="save-confirmed">confirmed_by</label>
            <input
              id="save-confirmed"
              className="input"
              value={confirmedBy}
              maxLength={64}
              onChange={(e) => setConfirmedBy(e.target.value)}
            />
          </div>
        </div>
        <span className="field-hint">
          confirmed_by 默认 user——每条记忆都记录「由谁确认保存」，方便日后区分人工确认与模型输出。
        </span>

        <div className="field" style={{ marginTop: 'var(--s-3)' }}>
          <label htmlFor="save-objective">研究目标 objective</label>
          <textarea
            id="save-objective"
            className="textarea"
            value={objective}
            maxLength={2000}
            rows={2}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="这个项目要回答的核心问题"
          />
        </div>

        <div className="mem-editor-grid">
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
        </div>

        <EvidenceEditor evidence={keyEvidence} onChange={setKeyEvidence} onError={onError} />

        <div className="mem-editor-grid">
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
        </div>

        <div className="field" style={{ marginTop: 'var(--s-3)' }}>
          <label htmlFor="save-note">备注 note（可选）</label>
          <textarea
            id="save-note"
            className="textarea"
            value={note}
            maxLength={1000}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            placeholder="本次保存的补充说明"
          />
        </div>

        {formError ? (
          <div className="banner banner-red" style={{ marginTop: 'var(--s-3)' }} role="alert">
            {formError}
          </div>
        ) : null}

        <div className="mem-save-actions">
          <button type="submit" className="btn btn-memory" disabled={saving}>
            {saving ? '正在写入 PowerContext…' : '显式保存研究进度'}
          </button>
          <span className="field-hint">
            这是一个刻意的用户动作：系统永不自动保存，重复内容会被去重（skipped_duplicates）。
          </span>
        </div>
      </form>

      {saveError ? (
        <div style={{ marginTop: 'var(--s-3)' }}>
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
        <Icon name={unchanged ? 'clock' : 'check'} size={14} />
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
          <span className="field-hint">（本次没有新增离散记忆条目）</span>
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

// ---------------------------------------------------------------- 列表编辑器

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
                className="btn btn-sm btn-icon"
                onClick={() => remove(index)}
                aria-label={`删除${label}第 ${index + 1} 条`}
              >
                <Icon name="trash" size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn btn-sm" onClick={add} disabled={items.length >= 50}>
        <Icon name="plus" size={13} /> 添加一行
      </button>
    </fieldset>
  )
}

// ---------------------------------------------------------------- 关键证据

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
          还没有证据条目。可以用下方「从检索结果选择」自动填充 doc_id / filename / page_no / chunk_id /
          quote，也可以手动添加。
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
                <div className="field field-narrow">
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
          <Icon name="plus" size={13} /> 手动添加一行
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

// ---------------------------------------------------------------- 历史

function HistoryPanel({
  projectId,
  onError,
  refreshKey,
}: {
  projectId: string
  onError: (err: unknown, title?: string) => void
  refreshKey: number
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
  }, [load, refreshKey])

  const entries = useMemo(
    () => (data ? [...data.entries].sort((a, b) => a.seq - b.seq) : []),
    [data]
  )

  return (
    <Panel
      title="记忆历史"
      subtitle={
        data
          ? `共 ${data.entry_count} 条记忆 · ${data.snapshot_count} 个进度快照（按 seq 排序）`
          : '按 seq 排序的全部原子记忆'
      }
      tags={<SourceTag source="powercontext" />}
      className="panel-memory"
      actions={
        <button type="button" className="btn btn-sm" onClick={() => void load()} disabled={loading}>
          <Icon name="refresh" size={13} /> 刷新
        </button>
      }
    >
      {loading ? <LoadingState text="正在读取 PowerContext 历史…" /> : null}
      {!loading && error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
      {!loading && data && entries.length === 0 ? (
        <EmptyState text="还没有任何记忆条目。先在上方显式保存一次研究进度。" />
      ) : null}
      {!loading && data && entries.length > 0 ? (
        <ol className="mem-history">
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
    <li className={isSnapshot ? 'mem-hitem mem-hitem-snapshot' : 'mem-hitem'}>
      <div className="mem-hitem-head">
        <span className={isSnapshot ? 'badge badge-memory' : 'badge'}>
          {memoryKindLabel(entry.kind)}
        </span>
        <span className="mem-hitem-seq mono">seq {entry.seq}</span>
        <span className="mem-hitem-time">{formatTimestamp(entry.updated_at)}</span>
        <span className="mem-hitem-id mono" title={`${entry.artifact_id} · rev ${entry.revision} · ${entry.state}`}>
          {entry.artifact_id.slice(0, 12)}… · rev {entry.revision} · {entry.state}
        </span>
      </div>
      <div className={isSnapshot ? 'mem-hitem-text mem-hitem-snapshot-text mono' : 'mem-hitem-text'}>
        {entry.text}
      </div>
    </li>
  )
}
