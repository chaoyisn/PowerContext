import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  askQuestion,
  listDocuments,
  listProjects,
  type AskResponse,
  type Citation,
  type Claim,
  type ClaimLabel,
  type ContentType,
  type DocumentRecord,
  type PreparedContext,
  type ProgressSnapshot,
  type Project,
  type QaMemory,
  type RestoreResponse,
  type RetrievalMode,
} from '../api/client'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MODE_LABELS,
  Panel,
  SourceTag,
  formatScore,
  scoreKindLabel,
} from '../components/common'
import PageViewer, { type PageViewerTarget } from '../components/PageViewer'
import { useErrorToast } from '../components/Toast'
import './WorkbenchPage.css'

const CLAIM_META: Record<ClaimLabel, { label: string; className: string }> = {
  supported: { label: '资料直接支持', className: 'claim-supported' },
  inferred: { label: '模型推断', className: 'claim-inferred' },
  no_evidence: { label: '尚无证据', className: 'claim-no-evidence' },
}

const INVALID_REASON_ZH: Record<string, string> = {
  not_in_retrieval_result: '该引用不在本次检索结果中——疑似模型编造，已被拦截',
  page_not_found_in_seekdb: 'seekdb 中不存在该页码——疑似幻影页，已被拦截',
  unparsed_response: '来自未能解析为规定 JSON 结构的模型输出',
}

const DOWNGRADE_REASON_ZH: Record<string, string> = {
  no_valid_citation_survived_validation:
    '原标注为「资料直接支持」，但所有引用在 seekdb 校验后均未存活，已自动降级为「模型推断」',
  llm_json_parse_failed: '模型输出未按规定的 JSON 结构返回，无法归入「资料直接支持」',
}

export default function WorkbenchPage() {
  const toastError = useErrorToast()

  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<RetrievalMode>('hybrid')
  const [topK, setTopK] = useState('8')
  const [projectId, setProjectId] = useState('')
  const [docId, setDocId] = useState('')
  const [contentType, setContentType] = useState('')
  const [pageFrom, setPageFrom] = useState('')
  const [pageTo, setPageTo] = useState('')

  const [projects, setProjects] = useState<Project[]>([])
  const [documents, setDocuments] = useState<DocumentRecord[]>([])

  const [asking, setAsking] = useState(false)
  const [response, setResponse] = useState<AskResponse | null>(null)
  const [askError, setAskError] = useState<unknown | null>(null)

  const [viewerTarget, setViewerTarget] = useState<PageViewerTarget | null>(null)
  const [highlightedCitation, setHighlightedCitation] = useState<string | null>(null)

  useEffect(() => {
    listProjects()
      .then((data) => setProjects(data.projects))
      .catch(() => setProjects([]))
    listDocuments()
      .then((data) => setDocuments(data.documents))
      .catch(() => setDocuments([]))
  }, [])

  const ask = async (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim()) return
    setAsking(true)
    setAskError(null)
    try {
      const result = await askQuestion({
        question: question.trim(),
        mode,
        top_k: Number.parseInt(topK, 10) || 8,
        project_id: projectId || null,
        doc_id: docId || null,
        content_type: (contentType || null) as ContentType | null,
        page_from: pageFrom ? Number.parseInt(pageFrom, 10) : null,
        page_to: pageTo ? Number.parseInt(pageTo, 10) : null,
      })
      setResponse(result)
    } catch (err) {
      setResponse(null)
      setAskError(err)
      toastError(err, '问答请求失败')
    } finally {
      setAsking(false)
    }
  }

  const focusCitation = useCallback((citationId: string) => {
    const element = document.getElementById(`citation-${citationId}`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    setHighlightedCitation(citationId)
    window.setTimeout(() => {
      setHighlightedCitation((current) => (current === citationId ? null : current))
    }, 2000)
  }, [])

  const openPage = (docIdValue: string, pageNo: number, filename?: string) =>
    setViewerTarget({ docId: docIdValue, pageNo, filename })

  return (
    <div>
      <div className="page-title-row">
        <h1>AI 工作台</h1>
        <SourceTag source="seekdb" />
      </div>
      <p className="page-desc">
        证据问答：回答只能建立在 seekdb 检索且通过门控的页级证据之上。模型给出的每条引用都会回到
        seekdb 逐条核验——不在检索结果里的引用被拦截，页码不存在的引用被拦截，失去引用的
        「资料直接支持」论断自动降级为「模型推断」。可选关联项目以附带 PowerContext 任务记忆。
      </p>

      <Panel title="提问">
        <form onSubmit={ask}>
          <div className="field">
            <label htmlFor="qa-question">问题</label>
            <textarea
              id="qa-question"
              className="textarea qa-question"
              value={question}
              rows={3}
              maxLength={4000}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：这篇论文的检索方法与传统 BM25 相比有什么优势？"
            />
          </div>

          <div className="form-row" style={{ marginTop: 'var(--sp-2)' }}>
            <div className="field">
              <label htmlFor="qa-mode">检索模式</label>
              <select
                id="qa-mode"
                className="select"
                value={mode}
                onChange={(e) => setMode(e.target.value as RetrievalMode)}
              >
                <option value="vector">向量（cosine_similarity）</option>
                <option value="fulltext">全文（fts_relevance）</option>
                <option value="hybrid">混合（RRF 融合）</option>
              </select>
            </div>
            <div className="field field-narrow">
              <label htmlFor="qa-topk">top_k</label>
              <input
                id="qa-topk"
                className="input"
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="qa-project">关联项目（附带任务记忆）</label>
              <select
                id="qa-project"
                className="select"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
              >
                <option value="">不关联项目</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.title}（{project.project_id}）
                  </option>
                ))}
              </select>
            </div>
          </div>

          <details className="collapsible">
            <summary>可选证据过滤（doc_id / content_type / 页码范围）</summary>
            <div className="form-row" style={{ marginTop: 'var(--sp-1)' }}>
              <div className="field">
                <label htmlFor="qa-doc">doc_id</label>
                <select id="qa-doc" className="select" value={docId} onChange={(e) => setDocId(e.target.value)}>
                  <option value="">全部文档</option>
                  {documents.map((doc) => (
                    <option key={doc.doc_id} value={doc.doc_id}>
                      {doc.filename}（{doc.doc_id.slice(0, 8)}…）
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="qa-type">content_type</label>
                <select
                  id="qa-type"
                  className="select"
                  value={contentType}
                  onChange={(e) => setContentType(e.target.value)}
                >
                  <option value="">全部类型</option>
                  <option value="pdf">pdf</option>
                  <option value="markdown">markdown</option>
                  <option value="text">text</option>
                </select>
              </div>
              <div className="field field-narrow">
                <label htmlFor="qa-from">page_from</label>
                <input
                  id="qa-from"
                  className="input"
                  type="number"
                  min={1}
                  value={pageFrom}
                  onChange={(e) => setPageFrom(e.target.value)}
                  placeholder="不限"
                />
              </div>
              <div className="field field-narrow">
                <label htmlFor="qa-to">page_to</label>
                <input
                  id="qa-to"
                  className="input"
                  type="number"
                  min={1}
                  value={pageTo}
                  onChange={(e) => setPageTo(e.target.value)}
                  placeholder="不限"
                />
              </div>
            </div>
          </details>

          <div style={{ marginTop: 'var(--sp-2)' }}>
            <button type="submit" className="btn btn-primary" disabled={asking || !question.trim()}>
              {asking ? '正在检索并生成回答…' : '提问'}
            </button>
          </div>
        </form>
      </Panel>

      {askError ? (
        <Panel title="回答">
          <ErrorState error={askError} />
        </Panel>
      ) : null}

      {asking ? (
        <Panel title="回答">
          <LoadingState text="正在执行门控检索，并在配置 LLM 时生成有据回答（可能需要数十秒）…" />
        </Panel>
      ) : null}

      {response && !asking ? (
        <AnswerView
          response={response}
          highlightedCitation={highlightedCitation}
          onFocusCitation={focusCitation}
          onOpenPage={openPage}
        />
      ) : null}

      {viewerTarget ? (
        <PageViewer target={viewerTarget} onClose={() => setViewerTarget(null)} />
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------- 回答视图

function AnswerView({
  response,
  highlightedCitation,
  onFocusCitation,
  onOpenPage,
}: {
  response: AskResponse
  highlightedCitation: string | null
  onFocusCitation: (id: string) => void
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
}) {
  const grounded = response.mode === 'grounded'
  return (
    <>
      <Panel
        title="回答"
        tags={
          grounded ? (
            <span className="badge badge-green">证据问答（grounded）</span>
          ) : (
            <span className="badge badge-amber">仅检索模式（retrieval_only）</span>
          )
        }
      >
        {!grounded ? (
          <div className="banner banner-amber" role="status">
            未配置 LLM 或没有可用证据：以下内容不是模型生成的回答，而是 seekdb
            检索到的原始证据列表（回答文本以【仅检索模式】开头）。
          </div>
        ) : null}
        {response.missing ? (
          <div className="banner banner-info" role="status">
            {response.missing}
          </div>
        ) : null}
        <div className={grounded ? 'answer-text' : 'answer-text answer-pre'}>
          <AnswerWithCitations answer={response.answer} onFocusCitation={onFocusCitation} />
        </div>
        {response.claims.length > 0 ? (
          <ClaimsSection claims={response.claims} labelSummary={response.label_summary} onFocusCitation={onFocusCitation} />
        ) : null}
        {response.invalid_citations.length > 0 ? (
          <InvalidCitationsPanel items={response.invalid_citations} />
        ) : null}
      </Panel>

      {response.memory ? <MemoryPanel memory={response.memory} /> : null}

      <CitationsPanel
        citations={response.citations}
        unused={response.unused_evidence}
        highlightedCitation={highlightedCitation}
        onOpenPage={onOpenPage}
        onFocusCitation={onFocusCitation}
      />

      <FooterMeta response={response} />
    </>
  )
}

/** 把回答文本中的 [c1] 标记渲染成可点击的引用 chip。 */
function AnswerWithCitations({
  answer,
  onFocusCitation,
}: {
  answer: string
  onFocusCitation: (id: string) => void
}) {
  if (!answer) return <EmptyState text="（没有回答文本）" />
  const parts = answer.split(/(\[c\d{1,3}\])/g)
  return (
    <p className="answer-paragraph">
      {parts.map((part, index) => {
        const match = /^\[(c\d{1,3})\]$/.exec(part)
        if (match) {
          const id = match[1]
          return (
            <button
              key={`${id}-${index}`}
              type="button"
              className="cite-chip"
              onClick={() => onFocusCitation(id)}
              aria-label={`跳转到引用 ${id}`}
              title={`查看引用 ${id} 及其原文页`}
            >
              [{id}]
            </button>
          )
        }
        return <span key={index}>{part}</span>
      })}
    </p>
  )
}

// ---------------------------------------------------------------- 论断分组

function ClaimsSection({
  claims,
  labelSummary,
  onFocusCitation,
}: {
  claims: Claim[]
  labelSummary: Record<ClaimLabel, number>
  onFocusCitation: (id: string) => void
}) {
  const labels: ClaimLabel[] = ['supported', 'inferred', 'no_evidence']
  return (
    <div className="claims-section">
      <div className="claims-header">
        <h3>论断核验</h3>
        <div className="claims-summary">
          {labels.map((label) => (
            <span key={label} className={`badge ${summaryBadgeClass(label)}`}>
              {CLAIM_META[label].label}：{labelSummary[label] ?? 0}
            </span>
          ))}
        </div>
      </div>
      <div className="claims-groups">
        {labels.map((label) => {
          const group = claims.filter((claim) => claim.label === label)
          if (group.length === 0) return null
          return (
            <div key={label} className={`claim-group ${CLAIM_META[label].className}`}>
              <div className="claim-group-title">{CLAIM_META[label].label}</div>
              <ul className="claim-list">
                {group.map((claim, index) => (
                  <li key={index} className="claim-item">
                    <div className="claim-statement">{claim.statement}</div>
                    <div className="claim-meta">
                      {claim.citation_ids.map((id) => (
                        <button
                          key={id}
                          type="button"
                          className="cite-chip"
                          onClick={() => onFocusCitation(id)}
                          aria-label={`跳转到引用 ${id}`}
                        >
                          [{id}]
                        </button>
                      ))}
                      {claim.downgraded ? (
                        <span className="badge badge-amber" title={claim.downgrade_reason}>
                          已降级
                          {claim.downgrade_reason
                            ? `：${DOWNGRADE_REASON_ZH[claim.downgrade_reason] ?? claim.downgrade_reason}（${claim.downgrade_reason}）`
                            : ''}
                        </span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function summaryBadgeClass(label: ClaimLabel): string {
  if (label === 'supported') return 'badge-green'
  if (label === 'inferred') return 'badge-amber'
  return 'badge-red'
}

// ---------------------------------------------------------------- 无效引用

function InvalidCitationsPanel({
  items,
}: {
  items: AskResponse['invalid_citations']
}) {
  return (
    <div className="invalid-panel" role="alert">
      <div className="invalid-title">
        拦截到 {items.length} 条无效引用（未能通过 seekdb 核验，已从回答与论断中剔除）
      </div>
      <ul className="invalid-list">
        {items.map((item, index) => (
          <li key={`${item.citation_id}-${index}`}>
            <code className="invalid-id">{item.citation_id}</code>
            <span>{INVALID_REASON_ZH[item.reason] ?? item.reason}</span>
            <code className="invalid-raw">{item.reason}</code>
            {item.doc_id ? (
              <span className="invalid-extra">
                doc_id <code>{item.doc_id}</code> · page_no {item.page_no ?? '—'}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- 引用面板

function CitationsPanel({
  citations,
  unused,
  highlightedCitation,
  onOpenPage,
  onFocusCitation,
}: {
  citations: Citation[]
  unused: Citation[]
  highlightedCitation: string | null
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
  onFocusCitation: (id: string) => void
}) {
  return (
    <Panel
      title={`引用与证据（${citations.length}）`}
      subtitle="每条引用都对应 seekdb 中真实存在的物理页与 chunk"
      tags={<SourceTag source="seekdb" />}
    >
      {citations.length === 0 ? (
        <EmptyState text="本次问答没有产生任何引用（没有通过门控的证据）。" />
      ) : (
        <ul className="citation-list">
          {citations.map((citation) => (
            <li
              key={citation.citation_id}
              id={`citation-${citation.citation_id}`}
              className={
                highlightedCitation === citation.citation_id
                  ? 'citation-card citation-highlight'
                  : 'citation-card'
              }
            >
              <div className="citation-head">
                <button
                  type="button"
                  className="cite-chip cite-chip-lg"
                  onClick={() => onFocusCitation(citation.citation_id)}
                  aria-label={`引用 ${citation.citation_id}`}
                >
                  [{citation.citation_id}]
                </button>
                <span className="citation-filename">{citation.filename || citation.doc_id}</span>
                <span className="badge badge-accent">第 {citation.page_no} 页</span>
                <button
                  type="button"
                  className="btn btn-sm citation-view"
                  onClick={() => onOpenPage(citation.doc_id, citation.page_no, citation.filename)}
                >
                  查看原文
                </button>
              </div>
              <div className="citation-scores">
                <span>
                  relevance <strong>{formatScore(citation.relevance)}</strong>
                </span>
                <span>
                  coverage <strong>{formatScore(citation.coverage)}</strong>
                </span>
                <span>
                  score <strong>{formatScore(citation.score)}</strong>
                  <em className="hit-score-kind">{scoreKindLabel(citation.score_kind)}</em>
                </span>
              </div>
              <div className="citation-ids">
                <span>
                  chunk_id <code>{citation.chunk_id}</code>
                </span>
                <span>
                  doc_id <code>{citation.doc_id}</code>
                </span>
                <span>
                  page_id <code>{citation.page_id}</code>
                </span>
              </div>
              <blockquote className="citation-quote">{citation.quote}</blockquote>
            </li>
          ))}
        </ul>
      )}

      <details className="collapsible unused-details">
        <summary>检索到但未被引用（{unused.length}）</summary>
        {unused.length === 0 ? (
          <p className="unused-empty">所有通过门控的证据都被回答引用了。</p>
        ) : (
          <ul className="unused-list">
            {unused.map((citation) => (
              <li key={citation.citation_id} className="unused-item">
                <span className="badge">{citation.citation_id}</span>
                <span className="unused-text">{citation.quote}</span>
                <span className="unused-meta">
                  {citation.filename} · 第 {citation.page_no} 页 · relevance{' '}
                  {formatScore(citation.relevance)}
                </span>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => onOpenPage(citation.doc_id, citation.page_no, citation.filename)}
                >
                  查看原文
                </button>
              </li>
            ))}
          </ul>
        )}
      </details>
    </Panel>
  )
}

// ---------------------------------------------------------------- 记忆面板

function MemoryPanel({ memory }: { memory: QaMemory }) {
  // PowerContext 故障时的退化结构：{available:false, error, source:'memory'}
  if (!('memory_available' in memory)) {
    return (
      <Panel title="任务记忆" tags={<SourceTag source="powercontext" />} className="panel-memory">
        <div className="banner banner-amber" role="status">
          PowerContext 不可用，检索与问答不受影响（它们只依赖 seekdb）。
          <div className="mono memory-error-detail">原因：{memory.error}</div>
        </div>
      </Panel>
    )
  }

  const restored = memory as RestoreResponse
  return (
    <Panel
      title="任务记忆（随问题一并召回）"
      tags={<SourceTag source="powercontext" />}
      subtitle="以下是历史研究进度，不是文献原文证据"
      className="panel-memory"
    >
      {!restored.memory_available ? (
        <div className="banner banner-amber" role="status">
          PowerContext 不可用，检索与问答不受影响。
          {restored.error ? <div className="mono memory-error-detail">原因：{restored.error}</div> : null}
        </div>
      ) : (
        <div className="memory-body">
          {restored.resume_brief ? (
            <>
              <h3 className="memory-subtitle">续研简报 resume_brief</h3>
              <pre className="memory-brief">{restored.resume_brief}</pre>
            </>
          ) : null}
          {restored.snapshot ? <SnapshotSummary snapshot={restored.snapshot} /> : null}
          {restored.prepared_context ? <PreparedContextView context={restored.prepared_context} /> : null}
        </div>
      )}
    </Panel>
  )
}

function SnapshotSummary({ snapshot }: { snapshot: ProgressSnapshot }) {
  const rows: { label: string; items: string[] }[] = [
    { label: '已完成工作', items: snapshot.completed_work ?? [] },
    { label: '已确认决策', items: snapshot.decisions ?? [] },
    { label: '未解决问题', items: snapshot.open_questions ?? [] },
    { label: '下一步', items: snapshot.next_steps ?? [] },
  ]
  return (
    <div className="memory-snapshot">
      <h3 className="memory-subtitle">
        进度快照（seq {snapshot.seq ?? '—'} · {snapshot.updated_at ?? '—'} · confirmed_by{' '}
        {snapshot.confirmed_by ?? '—'}）
      </h3>
      <div className="memory-snapshot-grid">
        {rows.map((row) => (
          <div key={row.label} className="memory-snapshot-block">
            <div className="memory-snapshot-label">{row.label}</div>
            {row.items.length === 0 ? (
              <span className="memory-empty-inline">（无记录）</span>
            ) : (
              <ul>
                {row.items.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {snapshot.key_evidence && snapshot.key_evidence.length > 0 ? (
          <div className="memory-snapshot-block">
            <div className="memory-snapshot-label">关键证据（指向 seekdb）</div>
            <ul>
              {snapshot.key_evidence.map((item, index) => (
                <li key={index}>
                  {item.filename || item.doc_id} 第 {item.page_no} 页 ·{' '}
                  <code>{item.chunk_id}</code>
                  {item.quote ? ` — ${item.quote}` : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function PreparedContextView({ context }: { context: PreparedContext }) {
  return (
    <details className="collapsible memory-prepared">
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
        <div>
          <span className="meta-key">recall_query：</span>
          <code>{context.recall_query}</code>
        </div>
      </div>
      {context.search_hits.length > 0 ? (
        <ul className="memory-hit-list">
          {context.search_hits.map((hit, index) => (
            <li key={index}>
              <span className="badge">{hit.kind}</span>
              <span className="memory-hit-text">{hit.text}</span>
              <span className="memory-hit-score mono">score {formatScore(hit.score)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="memory-empty-inline">search_memory 没有命中（完整记忆通过 list_memory_entries 全量读取，不依赖搜索）。</p>
      )}
      <p className="memory-note">{context.note}</p>
    </details>
  )
}

// ---------------------------------------------------------------- 底部元信息

function FooterMeta({ response }: { response: AskResponse }) {
  const backend = response.retrieval.backend
  const llm = response.llm
  return (
    <div className="qa-footer-meta">
      <span>
        seekdb <code>{backend.endpoint}</code> · collection <code>{backend.collection}</code> ·
        fts_analyzer <code>{backend.fts_analyzer}</code> · embedding <code>{backend.embedding_provider}</code>
      </span>
      <span>
        模式 {MODE_LABELS[response.retrieval.mode] ?? response.retrieval.mode} · 总耗时{' '}
        {response.elapsed_ms} ms · 检索 {response.retrieval.elapsed_ms} ms
      </span>
      <span>
        LLM：
        {llm.enabled
          ? `${llm.model_returned ?? llm.model} · prompt_tokens ${llm.prompt_tokens ?? '—'} · completion_tokens ${llm.completion_tokens ?? '—'}`
          : `未启用（${llm.reason ?? '原因未知'}）`}
      </span>
      {backend.warning ? <span className="qa-footer-warning">warning: {backend.warning}</span> : null}
    </div>
  )
}
