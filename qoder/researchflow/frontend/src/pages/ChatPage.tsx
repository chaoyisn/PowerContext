import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, RefObject } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  askQuestion,
  listDocuments,
  listProjects,
  saveProgress,
  searchDocuments,
  uploadDocument,
  type AskResponse,
  type Claim,
  type ClaimLabel,
  type ContentType,
  type DocumentRecord,
  type Project,
  type RetrievalMode,
  type RetrievalResult,
} from '../api/client'
import { EmptyState, ErrorState, MODE_LABELS, formatScore, scoreKindLabel } from '../components/common'
import {
  CitationPanel,
  HitRows,
  QaMemorySection,
  type PageTarget,
} from '../components/EvidenceViews'
import Icon from '../components/Icon'
import PageViewer from '../components/PageViewer'
import { EvidenceSlot, PanelSection, useShell, useShellHeader } from '../components/Shell'
import { useErrorToast, useToast } from '../components/Toast'
import {
  createDraft,
  getSession,
  saveExchange,
  type ChatSession,
  type Exchange,
} from '../state/sessions'
import '../styles/chat.css'

const CLAIM_META: Record<ClaimLabel, { label: string; className: string; badge: string }> = {
  supported: { label: '资料直接支持', className: 'claim-supported', badge: 'badge-green' },
  inferred: { label: '模型推断', className: 'claim-inferred', badge: 'badge-amber' },
  no_evidence: { label: '尚无证据', className: 'claim-no-evidence', badge: 'badge-red' },
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

const SUGGESTIONS = [
  '这篇论文的检索方法与传统 BM25 相比有什么优势？',
  '混合检索的 RRF 融合分数是怎么算出来的？',
  '空白页为什么仍然要保留页级身份？',
]

type AnswerMode = 'qa' | 'retrieval'

export default function ChatPage() {
  const shell = useShell()
  const toast = useToast()
  const toastError = useErrorToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const sessionId = params.get('s')

  const [session, setSession] = useState<ChatSession>(() => createDraft(shell.project, 'hybrid'))
  const [projects, setProjects] = useState<Project[]>([])
  const [documents, setDocuments] = useState<DocumentRecord[]>([])

  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<RetrievalMode>('hybrid')
  const [answerMode, setAnswerMode] = useState<AnswerMode>('qa')
  const [topK, setTopK] = useState('8')
  const [applyGate, setApplyGate] = useState(true)
  const [docId, setDocId] = useState('')
  const [contentType, setContentType] = useState('')
  const [pageFrom, setPageFrom] = useState('')
  const [pageTo, setPageTo] = useState('')

  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)

  const [busy, setBusy] = useState(false)
  const [streamError, setStreamError] = useState<unknown | null>(null)
  const [failedQuestion, setFailedQuestion] = useState('')
  const [viewerTarget, setViewerTarget] = useState<PageTarget | null>(null)
  const [highlighted, setHighlighted] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const following = useRef(true)

  const projectId = shell.project
  useShellHeader(
    session.exchanges.length === 0 ? '开始一个新问题' : session.title || '研究对话',
    session.exchanges.length === 0 ? '' : `${session.exchanges.length} 轮 · 证据来自 seekdb`
  )

  useEffect(() => {
    void listProjects().then((data) => setProjects(data.projects)).catch(() => setProjects([]))
    void listDocuments().then((data) => setDocuments(data.documents)).catch(() => setDocuments([]))
  }, [])

  // ?s= 决定回放哪一段本机对话；没有 s 参数时永远从空白开始，绝不复用上一条回答。
  useEffect(() => {
    if (!sessionId) {
      setSession(createDraft(projectId, mode))
      return
    }
    const stored = getSession(sessionId)
    if (stored) {
      setSession(stored)
      setMode(stored.mode)
    } else {
      setSession(createDraft(projectId, mode))
      navigate('/workbench', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // 贴着底部时跟随新内容；正在回看历史时保持位置不动，改由「回到最新消息」接管。
  useEffect(() => {
    const node = scrollRef.current
    if (!node || !following.current) return
    node.scrollTop = node.scrollHeight
  }, [busy, session.exchanges.length])

  const onChatScroll = () => {
    const node = scrollRef.current
    if (!node) return
    const gap = node.scrollHeight - node.scrollTop - node.clientHeight
    const bottom = gap < 80
    following.current = bottom
    if (bottom !== atBottom) setAtBottom(bottom)
  }

  const jumpToLatest = () => {
    const node = scrollRef.current
    if (!node) return
    following.current = true
    setAtBottom(true)
    node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }

  const focusCitation = useCallback(
    (citationId: string) => {
      shell.setEvidence('open')
      const element = document.getElementById(`citation-${citationId}`)
      if (element) element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setHighlighted(citationId)
      window.setTimeout(() => setHighlighted((current) => (current === citationId ? null : current)), 2400)
    },
    [shell]
  )

  const openPage = useCallback((target: PageTarget) => setViewerTarget(target), [])

  const attachUpload = async (file: File) => {
    setUploading(true)
    try {
      const doc = await uploadDocument(file)
      setDocId(doc.doc_id)
      setPendingFile(null)
      toast({
        kind: 'success',
        title: doc.deduplicated ? '重复文档已去重，直接复用库中版本' : '文档已入库',
        message: `${doc.filename} · ${doc.page_count} 页 · ${doc.chunk_count} chunks；本轮提问已限定在该文档`,
      })
      const data = await listDocuments()
      setDocuments(data.documents)
    } catch (err) {
      setPendingFile(null)
      toastError(err, '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const submit = async (event: FormEvent, override?: string) => {
    event.preventDefault()
    const text = (override ?? question).trim()
    if (!text || busy) return
    setStreamError(null)
    setFailedQuestion('')
    setBusy(true)
    setQuestion('')
    const draft: ChatSession = { ...session, projectId, mode }
    try {
      if (answerMode === 'qa') {
        const response = await askQuestion({
          question: text,
          mode,
          top_k: Number.parseInt(topK, 10) || 8,
          project_id: projectId || null,
          doc_id: docId || null,
          content_type: (contentType || null) as ContentType | null,
          page_from: pageFrom ? Number.parseInt(pageFrom, 10) : null,
          page_to: pageTo ? Number.parseInt(pageTo, 10) : null,
        })
        commit(draft, { question: text, askedAt: new Date().toISOString(), kind: 'qa', response })
      } else {
        const response = await searchDocuments({
          query: text,
          mode,
          top_k: Number.parseInt(topK, 10) || 8,
          apply_gate: applyGate,
          doc_id: docId || null,
          content_type: (contentType || null) as ContentType | null,
          page_from: pageFrom ? Number.parseInt(pageFrom, 10) : null,
          page_to: pageTo ? Number.parseInt(pageTo, 10) : null,
        })
        commit(draft, { question: text, askedAt: new Date().toISOString(), kind: 'retrieval', response })
      }
    } catch (err) {
      setStreamError(err)
      setFailedQuestion(text)
      toastError(err, answerMode === 'qa' ? '问答请求失败' : '检索失败')
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const retryLast = () => {
    if (!failedQuestion) return
    void submit({ preventDefault: () => {} } as FormEvent, failedQuestion)
  }

  const commit = (draft: ChatSession, exchange: Exchange) => {
    const next = saveExchange(draft, exchange)
    const merged = next.find((item) => item.id === draft.id) ?? draft
    setSession(merged)
    if (location.pathname === '/') navigate(`/workbench?s=${encodeURIComponent(merged.id)}`, { replace: true })
  }

  const latest = session.exchanges[session.exchanges.length - 1]
  const latestQa: AskResponse | null = latest && latest.kind === 'qa' ? latest.response : null
  const latestRetrieval: RetrievalResult | null =
    latest && latest.kind === 'retrieval' ? latest.response : null

  const nextSteps = useMemo(() => {
    const memory = latestQa?.memory
    if (!memory || !('memory_available' in memory)) return []
    return memory.snapshot?.next_steps ?? []
  }, [latestQa])

  return (
    <div className="chat-view">
      <div className="chat-scroll scroll-thin" ref={scrollRef} onScroll={onChatScroll}>
        <div className="chat-inner">
          {session.exchanges.length === 0 && location.pathname === '/' ? (
            <Hero onPick={(text) => setQuestion(text)} />
          ) : null}

          {session.exchanges.length === 0 && location.pathname !== '/' ? (
            <EmptyState
              text="还没有对话。底部输入一个问题即可开始——回答只会建立在 seekdb 中真实存在页级证据之上。"
            />
          ) : null}

          {session.exchanges.map((exchange, index) => (
            <Turn
              key={`${exchange.askedAt}-${index}`}
              exchange={exchange}
              index={index}
              highlighted={highlighted}
              onFocusCitation={focusCitation}
              onOpenPage={openPage}
              projectId={projectId}
              onToast={toast}
              onToastError={toastError}
              isLast={index === session.exchanges.length - 1}
            />
          ))}

          {busy ? (
            <div className="turn">
              <div className="msg msg-assistant">
                <span className="avatar" aria-hidden="true">
                  <Icon name="sparkle" size={16} />
                </span>
                <div className="msg-body">
                  <div className="thinking" role="status" aria-live="polite">
                    <span className="thinking-dots" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                    {answerMode === 'qa'
                      ? '正在做门控检索并生成有据回答（可能需要数十秒）…'
                      : '正在 seekdb 中检索页级证据…'}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {streamError ? (
            <div className="turn">
              <div className="msg msg-assistant">
                <div className="msg-body">
                  <ErrorState
                    error={streamError}
                    onRetry={failedQuestion ? retryLast : undefined}
                    retryLabel="重试这个问题"
                  />
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <Composer
        showJump={session.exchanges.length > 0 && !atBottom}
        onJump={jumpToLatest}
        question={question}
        setQuestion={setQuestion}
        mode={mode}
        setMode={setMode}
        answerMode={answerMode}
        setAnswerMode={setAnswerMode}
        topK={topK}
        setTopK={setTopK}
        applyGate={applyGate}
        setApplyGate={setApplyGate}
        projectId={projectId}
        setProjectId={shell.setProject}
        projects={projects}
        docId={docId}
        setDocId={setDocId}
        documents={documents}
        contentType={contentType}
        setContentType={setContentType}
        pageFrom={pageFrom}
        setPageFrom={setPageFrom}
        pageTo={pageTo}
        setPageTo={setPageTo}
        pendingFile={pendingFile}
        setPendingFile={setPendingFile}
        uploading={uploading}
        onUploaded={(file) => void attachUpload(file)}
        busy={busy}
        onSubmit={submit}
        inputRef={inputRef}
      />

      <EvidenceSlot>
        {latestQa ? (
          <>
            {latestQa.memory ? <QaMemorySection memory={latestQa.memory} /> : null}
            {nextSteps.length > 0 ? (
              <PanelSection title="下一步（来自研究记忆）" count={nextSteps.length}>
                <ul className="ev-mem-list">
                  {nextSteps.map((item, index) => (
                    <li key={index}>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </PanelSection>
            ) : null}
            <CitationPanel
              citations={latestQa.citations}
              unused={latestQa.unused_evidence}
              highlighted={highlighted}
              onOpenPage={openPage}
              onFocus={focusCitation}
            />
            <PanelSection title="本轮检索命中" count={latestQa.retrieval.hits.length}>
              <HitRows hits={latestQa.retrieval.hits} onOpenPage={openPage} />
            </PanelSection>
          </>
        ) : null}

        {latestRetrieval ? (
          <>
            <PanelSection title="本轮检索命中" count={latestRetrieval.hits.length}>
              <HitRows hits={latestRetrieval.hits} onOpenPage={openPage} />
            </PanelSection>
            {latestRetrieval.citations.length > 0 ? (
              <CitationPanel
                citations={latestRetrieval.citations}
                unused={[]}
                highlighted={highlighted}
                onOpenPage={openPage}
                onFocus={focusCitation}
              />
            ) : null}
          </>
        ) : null}

        {!latestQa && !latestRetrieval ? (
          <p className="side-empty">
            本轮引用的 seekdb 页级证据与 PowerContext 研究记忆会出现在这里，分色标注来源。
          </p>
        ) : null}
      </EvidenceSlot>

      {viewerTarget ? (
        <PageViewer
          target={{ docId: viewerTarget.docId, pageNo: viewerTarget.pageNo, filename: viewerTarget.filename }}
          onClose={() => setViewerTarget(null)}
        />
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------- 首页 hero

function Hero({ onPick }: { onPick: (text: string) => void }) {
  return (
    <section className="hero">
      <h1>
        每个回答，都要能翻到<em>那一页</em>。
      </h1>
      <p className="hero-sub">
        提问后只在 seekdb 的页级证据里找答案，引用逐条核验；研究进度存进 PowerContext，换个会话还能接着做。
      </p>

      <div className="suggestions">
        <span className="suggestions-label">试试这些问题</span>
        {SUGGESTIONS.map((text) => (
          <button type="button" key={text} className="chip" onClick={() => onPick(text)}>
            <Icon name="target" size={12} />
            {text}
          </button>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- 一轮对话

function Turn({
  exchange,
  index,
  highlighted,
  onFocusCitation,
  onOpenPage,
  projectId,
  onToast,
  onToastError,
  isLast,
}: {
  exchange: Exchange
  index: number
  highlighted: string | null
  onFocusCitation: (id: string) => void
  onOpenPage: (target: PageTarget) => void
  projectId: string
  onToast: ReturnType<typeof useToast>
  onToastError: (err: unknown, title?: string) => void
  isLast: boolean
}) {
  return (
    <div className={isLast ? 'turn turn-last' : 'turn'}>
      <div className="msg msg-user">
        <div className="msg-bubble">{exchange.question}</div>
        <span className="msg-meta">
          第 {index + 1} 轮 · {new Date(exchange.askedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
      <div className="msg msg-assistant">
        <span className="avatar" aria-hidden="true">
          <Icon name="sparkle" size={16} />
        </span>
        <div className="msg-body">
          {exchange.kind === 'qa' ? (
            <QaAnswer
              response={exchange.response}
              highlighted={highlighted}
              onFocusCitation={onFocusCitation}
              projectId={projectId}
              question={exchange.question}
              onToast={onToast}
              onToastError={onToastError}
            />
          ) : (
            <RetrievalAnswer response={exchange.response} onOpenPage={onOpenPage} />
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 问答回答

function QaAnswer({
  response,
  highlighted,
  onFocusCitation,
  projectId,
  question,
  onToast,
  onToastError,
}: {
  response: AskResponse
  highlighted: string | null
  onFocusCitation: (id: string) => void
  projectId: string
  question: string
  onToast: ReturnType<typeof useToast>
  onToastError: (err: unknown, title?: string) => void
}) {
  const shell = useShell()
  const grounded = response.mode === 'grounded'
  const [savingMemory, setSavingMemory] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)

  const saveToMemory = async () => {
    if (!projectId) {
      onToast({ kind: 'info', title: '请先在左侧选择一个研究项目', message: '记忆按 project 绑定 PowerContext scope，没有项目无法写入。' })
      return
    }
    setSavingMemory(true)
    try {
      const result = await saveProgress(projectId, {
        completed_work: [
          `围绕「${question.slice(0, 120)}」完成一次证据问答，${response.citations.length} 条引用通过 seekdb 核验`,
        ],
        decisions: [],
        open_questions: [],
        next_steps: [],
        key_evidence: response.citations.slice(0, 10).map((citation) => ({
          doc_id: citation.doc_id,
          filename: citation.filename,
          page_no: citation.page_no,
          chunk_id: citation.chunk_id,
          quote: citation.quote.slice(0, 600),
        })),
        note: `由对话页显式保存（mode=${response.mode}，论断 ${response.label_summary.supported} 直接支持 / ${response.label_summary.inferred} 推断 / ${response.label_summary.no_evidence} 无证据）`,
        confirmed_by: 'user',
      })
      setSavedAt(result.updated_at)
      onToast({
        kind: 'success',
        title: result.written === 0 && result.snapshot_unchanged ? '内容未变化，未产生重复记忆' : '本轮已写入研究记忆',
        message: `写入 ${result.written} 条 · 去重跳过 ${result.skipped_duplicates} 条 · seq ${result.seq}`,
      })
    } catch (err) {
      onToastError(err, '保存到记忆失败')
    } finally {
      setSavingMemory(false)
    }
  }

  return (
    <>
      <div className="msg-tags">
        {grounded ? (
          <span className="badge badge-green">
            <Icon name="check" size={12} /> 证据问答（grounded）
          </span>
        ) : (
          <span className="badge badge-amber">仅检索模式（retrieval_only）</span>
        )}
        <span className="badge">
          {MODE_LABELS[response.retrieval.mode] ?? response.retrieval.mode} · top_k {response.retrieval.hits.length}
        </span>
        {response.invalid_citations.length > 0 ? (
          <span className="badge badge-red">拦截 {response.invalid_citations.length} 条无效引用</span>
        ) : null}
      </div>

      {!grounded ? (
        <div className="banner banner-amber" role="status">
          未配置 LLM 或没有可用证据：下面不是模型生成的回答，而是 seekdb 检索到的原始证据列表。
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

      {response.invalid_citations.length > 0 ? <InvalidCitations items={response.invalid_citations} /> : null}

      {response.citations.length > 0 ? (
        <div className="cite-inline">
          <span className="cite-inline-label">证据来源</span>
          {response.citations.map((citation) => (
            <button
              key={citation.citation_id}
              type="button"
              className={highlighted === citation.citation_id ? 'cite-chip cite-chip-lg citation-highlight' : 'cite-chip cite-chip-lg'}
              onClick={() => {
                onFocusCitation(citation.citation_id)
                shell.setEvidence('open')
              }}
              aria-label={`引用 ${citation.citation_id}`}
              title={`${citation.filename || citation.doc_id} · 第 ${citation.page_no} 页`}
            >
              [{citation.citation_id}] {citation.filename || citation.doc_id} · 第 {citation.page_no} 页
            </button>
          ))}
        </div>
      ) : (
        <div className="cite-inline">
          <span className="cite-inline-label">证据来源</span>
          <span className="field-hint">本轮没有引用：没有证据通过门控。</span>
        </div>
      )}

      <div className="msg-actions">
        <button type="button" className="btn btn-sm" onClick={() => shell.setEvidence('open')}>
          <Icon name="panelRight" size={14} /> 本轮使用的资料
        </button>
        <button type="button" className="btn btn-sm btn-memory" onClick={() => void saveToMemory()} disabled={savingMemory}>
          <Icon name="bookmark" size={14} />
          {savingMemory ? '正在写入 PowerContext…' : savedAt ? '再次保存到记忆' : '保存到记忆'}
        </button>
        {savedAt ? <span className="field-hint">已显式保存 · {savedAt}</span> : null}
      </div>

      <FooterMeta response={response} />
    </>
  )
}

/** 把回答文本中的 [c1] 标记渲染成可点击的引用 chip。 */
function AnswerWithCitations({ answer, onFocusCitation }: { answer: string; onFocusCitation: (id: string) => void }) {
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
        <h3>
          <Icon name="shield" size={15} /> 论断核验
        </h3>
        <div className="claims-summary">
          {labels.map((label) => (
            <span key={label} className={`badge ${CLAIM_META[label].badge}`}>
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

function InvalidCitations({ items }: { items: AskResponse['invalid_citations'] }) {
  return (
    <div className="invalid-panel" role="alert">
      <div className="invalid-title">
        <Icon name="alert" size={14} /> 拦截到 {items.length} 条无效引用（未能通过 seekdb 核验，已从回答与论断中剔除）
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

function FooterMeta({ response }: { response: AskResponse }) {
  const backend = response.retrieval.backend
  const llm = response.llm
  return (
    <div className="qa-footer-meta">
      <span>
        seekdb <code>{backend.endpoint}</code> · collection <code>{backend.collection}</code> · fts_analyzer{' '}
        <code>{backend.fts_analyzer}</code> · embedding <code>{backend.embedding_provider}</code>
      </span>
      <span>
        总耗时 {response.elapsed_ms} ms · 检索 {response.retrieval.elapsed_ms} ms
      </span>
      <span>
        LLM：
        {llm.enabled
          ? `${llm.model_returned ?? llm.model} · prompt_tokens ${llm.prompt_tokens ?? '—'} · completion_tokens ${
              llm.completion_tokens ?? '—'
            }`
          : `未启用（${llm.reason ?? '原因未知'}）`}
      </span>
      {backend.warning ? <span className="qa-footer-warning">warning: {backend.warning}</span> : null}
    </div>
  )
}

// ---------------------------------------------------------------- 仅检索回答

function RetrievalAnswer({
  response,
  onOpenPage,
}: {
  response: RetrievalResult
  onOpenPage: (target: PageTarget) => void
}) {
  return (
    <>
      <div className="msg-tags">
        <span className="badge badge-accent">
          <Icon name="search" size={12} /> 仅检索模式（不调用 LLM）
        </span>
        <span className="badge">{MODE_LABELS[response.mode] ?? response.mode}</span>
        <span className="badge">{response.gate.applied ? '已启用证据门控' : '未启用门控'}</span>
      </div>
      <p className="field-hint">
        这一条不是模型回答，而是 seekdb 直接返回的 {response.hits.length} 个 chunk；
        {response.gate.applied
          ? ` 门控按 coverage ≥ ${response.gate.min_coverage} 过滤，本轮丢弃 ${response.dropped_by_gate} 条，${response.relevant_count} 条判定相关。`
          : ` 未做门控过滤，命中 ${response.hits.length} 条。`}
      </p>

      {response.error ? (
        <div className="banner banner-red" role="alert">
          检索返回错误：{response.error}
        </div>
      ) : null}

      {response.hits.length === 0 ? (
        <EmptyState text="没有任何命中。可以尝试换成混合检索，或者放宽 top_k 与页码过滤。" />
      ) : (
        <ul className="hit-list">
          {response.hits.map((hit, index) => (
            <li className="hit-row" key={hit.chunk_id}>
              <span className="hit-rank">{index + 1}</span>
              <div className="hit-main">
                <div className="hit-text">{hit.text}</div>
                <div className="hit-meta">
                  <button
                    type="button"
                    className="hit-file"
                    onClick={() => onOpenPage({ docId: hit.doc_id, pageNo: hit.page_no, filename: hit.filename })}
                  >
                    <Icon name="page" size={12} /> {hit.filename || hit.doc_id} · 第 {hit.page_no} 页
                  </button>
                  <span className="hit-score-main">
                    {formatScore(hit.score)} {scoreKindLabel(hit.score_kind)}
                  </span>
                  <span>relevance {formatScore(hit.relevance)}</span>
                  <span>coverage {formatScore(hit.coverage)}</span>
                  <span className={hit.gate_passed ? 'badge badge-green' : 'badge badge-amber'}>
                    {hit.gate_passed ? '通过门控' : '未过门控'}
                  </span>
                  <span className="mono">{hit.chunk_id}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="qa-footer-meta">
        <span>
          POST /api/retrieval/search · seekdb <code>{response.backend.endpoint}</code> · collection{' '}
          <code>{response.backend.collection}</code>
        </span>
        <span>耗时 {response.elapsed_ms} ms</span>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- 输入区

interface ComposerProps {
  question: string
  setQuestion: (value: string) => void
  mode: RetrievalMode
  setMode: (value: RetrievalMode) => void
  answerMode: AnswerMode
  setAnswerMode: (value: AnswerMode) => void
  topK: string
  setTopK: (value: string) => void
  applyGate: boolean
  setApplyGate: (value: boolean) => void
  projectId: string
  setProjectId: (value: string) => void
  projects: Project[]
  docId: string
  setDocId: (value: string) => void
  documents: DocumentRecord[]
  contentType: string
  setContentType: (value: string) => void
  pageFrom: string
  setPageFrom: (value: string) => void
  pageTo: string
  setPageTo: (value: string) => void
  pendingFile: File | null
  setPendingFile: (value: File | null) => void
  uploading: boolean
  onUploaded: (file: File) => void
  busy: boolean
  onSubmit: (event: FormEvent) => void
  inputRef: RefObject<HTMLTextAreaElement>
  showJump: boolean
  onJump: () => void
}

function Composer(props: ComposerProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [options, setOptions] = useState(false)
  // 折叠起来之后，非默认设置必须仍然看得见，否则「仅检索」会静默生效。
  const optionSummary = [
    props.answerMode === 'retrieval' ? '仅检索' : '',
    props.projectId ? '已关联项目' : '',
    props.topK !== '8' ? `top_k ${props.topK}` : '',
    props.docId ? '限定文档' : '',
  ]
    .filter(Boolean)
    .join(' · ')

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    // 中文输入法用回车确认候选词，那一次回车不能当成发送。
    const native = event.nativeEvent as KeyboardEvent['nativeEvent'] & { isComposing?: boolean }
    if (native.isComposing || native.keyCode === 229) return
    event.preventDefault()
    props.onSubmit(event as unknown as FormEvent)
  }

  // 单行起步，随内容长高，到 CSS 的 240px 上限后内部滚动。
  useEffect(() => {
    const node = props.inputRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight}px`
  }, [props.question, props.inputRef])

  return (
    <div className="composer-dock">
      {props.showJump ? (
        <button type="button" className="jump-latest" onClick={props.onJump}>
          <Icon name="chevronDown" size={14} />
          回到最新消息
        </button>
      ) : null}
      <div className="composer-wrap">
      <form className={props.busy ? 'composer is-busy' : 'composer'} onSubmit={props.onSubmit}>
        {props.pendingFile ? (
          <div className="pending-file">
            <Icon name="upload" size={13} />
            <span>
              {props.uploading ? `正在解析并入库：${props.pendingFile.name}` : `待上传：${props.pendingFile.name}`}
            </span>
            <button type="button" className="btn btn-sm" onClick={() => props.setPendingFile(null)} disabled={props.uploading}>
              移除
            </button>
          </div>
        ) : null}

        <div className="composer-top">
          <label className="visually-hidden" htmlFor="qa-question">
            问题
          </label>
          <textarea
            id="qa-question"
            ref={props.inputRef}
            className="textarea composer-input"
            value={props.question}
            rows={2}
            maxLength={4000}
            onChange={(event) => props.setQuestion(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="问一个需要文献证据的问题，例如：这篇论文的检索方法与传统 BM25 相比有什么优势？"
          />
          <button
            type="submit"
            className="btn btn-primary composer-send"
            disabled={props.busy || !props.question.trim() || props.uploading}
            aria-busy={props.busy}
          >
            <Icon name="send" size={16} />
            <span>{props.busy ? '生成中' : '提问'}</span>
          </button>
        </div>

        <div className="composer-bar">
          <button type="button" className="chip" onClick={() => fileRef.current?.click()} disabled={props.uploading}>
            <Icon name="upload" size={13} />
            {props.uploading ? '正在入库…' : '上传文档'}
          </button>
          <input
            ref={fileRef}
            id="chat-upload-file"
            type="file"
            accept=".pdf,.md,.markdown,.txt"
            className="visually-hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) props.onUploaded(file)
              event.target.value = ''
            }}
          />

          <select
            id="qa-mode"
            className="select composer-select"
            value={props.mode}
            onChange={(event) => props.setMode(event.target.value as RetrievalMode)}
            aria-label="检索模式"
          >
            <option value="vector">向量（cosine_similarity）</option>
            <option value="fulltext">关键词全文（fts_relevance）</option>
            <option value="hybrid">混合（RRF 融合）</option>
          </select>

          <button
            type="button"
            className={options ? 'chip chip-active' : 'chip'}
            onClick={() => setOptions((current) => !current)}
            aria-expanded={options}
          >
            <Icon name="layers" size={13} />
            选项
            {optionSummary ? <span className="chip-note">{optionSummary}</span> : null}
          </button>
        </div>

        {options ? (
          <div className="composer-advanced">
            <div className="field">
              <span>回答方式</span>
              <div className="composer-switch" role="group" aria-label="回答方式">
                <button
                  type="button"
                  className={props.answerMode === 'qa' ? 'seg-item seg-item-active' : 'seg-item'}
                  onClick={() => props.setAnswerMode('qa')}
                  aria-pressed={props.answerMode === 'qa'}
                >
                  <Icon name="sparkle" size={13} /> 问答
                </button>
                <button
                  type="button"
                  className={props.answerMode === 'retrieval' ? 'seg-item seg-item-active' : 'seg-item'}
                  onClick={() => props.setAnswerMode('retrieval')}
                  aria-pressed={props.answerMode === 'retrieval'}
                >
                  <Icon name="search" size={13} /> 仅检索
                </button>
              </div>
            </div>

            <label className="field" htmlFor="qa-project">
              <span>关联研究项目（附带任务记忆）</span>
              <select
                id="qa-project"
                className="select"
                value={props.projectId}
                onChange={(event) => props.setProjectId(event.target.value)}
              >
                <option value="">不关联项目</option>
                {props.projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.title}（{project.project_id}）
                  </option>
                ))}
              </select>
            </label>

            <label className="field field-narrow" htmlFor="qa-topk">
              <span>top_k</span>
              <input
                id="qa-topk"
                className="input"
                type="number"
                min={1}
                max={50}
                value={props.topK}
                onChange={(event) => props.setTopK(event.target.value)}
              />
            </label>

            {props.answerMode === 'retrieval' ? (
              <div className="field field-narrow">
                <span>证据门控</span>
                <label className="checkbox-field gate-toggle" htmlFor="qa-gate">
                  <input
                    id="qa-gate"
                    type="checkbox"
                    checked={props.applyGate}
                    onChange={(event) => props.setApplyGate(event.target.checked)}
                  />
                  启用证据门控
                </label>
              </div>
            ) : null}

            <label className="field" htmlFor="qa-doc">
              <span>限定文档</span>
              <select id="qa-doc" className="select" value={props.docId} onChange={(event) => props.setDocId(event.target.value)}>
                <option value="">全部文档</option>
                {props.documents.map((doc) => (
                  <option key={doc.doc_id} value={doc.doc_id}>
                    {doc.filename}（{doc.doc_id.slice(0, 8)}…）
                  </option>
                ))}
              </select>
            </label>
            <label className="field" htmlFor="qa-type">
              <span>content_type</span>
              <select id="qa-type" className="select" value={props.contentType} onChange={(event) => props.setContentType(event.target.value)}>
                <option value="">全部类型</option>
                <option value="pdf">pdf</option>
                <option value="markdown">markdown</option>
                <option value="text">text</option>
              </select>
            </label>
            <label className="field field-narrow" htmlFor="qa-from">
              <span>page_from</span>
              <input
                id="qa-from"
                className="input"
                type="number"
                min={1}
                value={props.pageFrom}
                onChange={(event) => props.setPageFrom(event.target.value)}
                placeholder="不限"
              />
            </label>
            <label className="field field-narrow" htmlFor="qa-to">
              <span>page_to</span>
              <input
                id="qa-to"
                className="input"
                type="number"
                min={1}
                value={props.pageTo}
                onChange={(event) => props.setPageTo(event.target.value)}
                placeholder="不限"
              />
            </label>
          </div>
        ) : null}

        <p className="composer-hint">
          <kbd className="kbd">Enter</kbd> 发送 · <kbd className="kbd">Shift</kbd>+<kbd className="kbd">Enter</kbd> 换行
          {' —— '}
          {props.answerMode === 'qa'
            ? '回答只使用 seekdb 中通过证据门控且回查核验成功的页级证据。'
            : '仅检索模式：跳过 LLM，直接返回 seekdb 的页级命中。'}
          {props.docId ? ' 已限定在单个文档内检索。' : ''}
        </p>
      </form>
      </div>
    </div>
  )
}
