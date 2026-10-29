import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, FormEvent } from 'react'
import {
  compareModes,
  getDocument,
  listDocuments,
  searchDocuments,
  uploadDocument,
  type CompareResponse,
  type ContentType,
  type DocumentDetail,
  type DocumentRecord,
  type RetrievalHit,
  type RetrievalMode,
  type RetrievalResult,
} from '../api/client'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MODE_LABELS,
  Panel,
  SourceTag,
  formatScore,
  formatTimestamp,
  scoreKindLabel,
} from '../components/common'
import { HitRows, type PageTarget } from '../components/EvidenceViews'
import Icon from '../components/Icon'
import PageViewer, { type PageViewerTarget } from '../components/PageViewer'
import { EvidenceSlot, PanelSection, useShellHeader } from '../components/Shell'
import { useErrorToast, useToast } from '../components/Toast'
import '../styles/knowledge.css'

const ACCEPT_EXTENSIONS = ['.pdf', '.md', '.markdown', '.txt']

export default function KnowledgePage() {
  const toast = useToast()
  const toastError = useErrorToast()
  useShellHeader('知识库', '真实物理页、chunk 与三种检索模式都在 seekdb 里')

  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [docsError, setDocsError] = useState<unknown | null>(null)
  const [docsLoading, setDocsLoading] = useState(true)
  const [viewerTarget, setViewerTarget] = useState<PageViewerTarget | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<DocumentDetail | null>(null)
  const [result, setResult] = useState<RetrievalResult | null>(null)

  const loadDocuments = useCallback(async () => {
    setDocsLoading(true)
    try {
      const data = await listDocuments()
      setDocuments(data.documents)
      setDocsError(null)
    } catch (err) {
      setDocsError(err)
    } finally {
      setDocsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  const openPage = (docId: string, pageNo: number, filename?: string) =>
    setViewerTarget({ docId, pageNo, filename })
  const openTarget = (target: PageTarget) =>
    setViewerTarget({ docId: target.docId, pageNo: target.pageNo, filename: target.filename })

  return (
    <div className="page-inner scroll-thin">
      <div className="kb-intro">
        <h1>
          文献都在这条证据通道里 <SourceTag source="seekdb" />
        </h1>
        <p>
          文献按真实物理页存在 seekdb 里，向量 / 全文 / 混合三种检索都回到这些页——只有它们能产生引用。
        </p>
      </div>

      <UploadPanel
        onUploaded={() => void loadDocuments()}
        onError={toastError}
        onSuccess={(doc) =>
          toast({
            kind: 'success',
            title: doc.deduplicated ? '重复上传已去重' : '上传并入库成功',
            message: `${doc.filename} · ${doc.page_count} 页 · ${doc.chunk_count} chunks`,
          })
        }
      />

      <DocumentListPanel
        documents={documents}
        loading={docsLoading}
        error={docsError}
        onRetry={() => void loadDocuments()}
        onOpenPage={openPage}
        expandedId={expandedId}
        onExpand={(docId, detail) => {
          setExpandedId(docId)
          setExpandedDetail(detail)
        }}
      />

      <SearchPanel
        documents={documents}
        onOpenPage={openPage}
        onError={toastError}
        result={result}
        setResult={setResult}
      />

      <EvidenceSlot>
        <PanelSection title="本轮检索命中" count={result ? result.hits.length : 0}>
          {result ? (
            <>
              <HitRows hits={result.hits} onOpenPage={openTarget} />
              <p className="side-empty">
                通过门控 {result.relevant_count} 条 · 被门控剔除 {result.dropped_by_gate} 条 ·{' '}
                {result.elapsed_ms} ms
              </p>
            </>
          ) : (
            <p className="side-empty">还没有检索。在左侧「证据检索」输入问题，命中会实时出现在这里。</p>
          )}
        </PanelSection>

        {expandedDetail ? (
          <PanelSection title="展开的文献" count={`${expandedDetail.pages.length} 页`}>
            <p className="ev-doc-name">{expandedDetail.filename}</p>
            <ul className="ev-page-list">
              {expandedDetail.pages.map((page) => (
                <li key={page.page_id}>
                  <button type="button" onClick={() => openPage(expandedDetail.doc_id, page.page_no, expandedDetail.filename)}>
                    第 {page.page_no} 页
                  </button>
                  <span>{page.is_empty ? '空白页' : `${page.char_count} 字符`}</span>
                </li>
              ))}
            </ul>
            <p className="side-empty mono">doc_id {expandedDetail.doc_id}</p>
          </PanelSection>
        ) : null}

        {result ? (
          <PanelSection title="检索后端（真实配置）">
            <dl className="ev-fact-list">
              <div>
                <dt>collection</dt>
                <dd>
                  <code>{result.backend.collection}</code>
                </dd>
              </div>
              <div>
                <dt>全文分析器</dt>
                <dd>
                  <code>{result.backend.fts_analyzer}</code>
                </dd>
              </div>
              <div>
                <dt>embedding</dt>
                <dd>
                  <code>{result.backend.embedding_provider}</code>（{result.backend.embedding_dimension} 维）
                </dd>
              </div>
              <div>
                <dt>向量距离</dt>
                <dd>
                  <code>{result.backend.vector_distance}</code>
                </dd>
              </div>
              <div>
                <dt>门控</dt>
                <dd>
                  {result.gate.applied ? '已启用' : '未启用'} · min_coverage {result.gate.min_coverage} ·
                  vector_confidence {result.gate.vector_confidence}
                </dd>
              </div>
            </dl>
          </PanelSection>
        ) : null}
      </EvidenceSlot>

      {viewerTarget ? (
        <PageViewer target={viewerTarget} onClose={() => setViewerTarget(null)} />
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------- 上传

function UploadPanel({
  onUploaded,
  onError,
  onSuccess,
}: {
  onUploaded: () => void
  onError: (err: unknown, title?: string) => void
  onSuccess: (doc: DocumentDetail) => void
}) {
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<DocumentDetail | null>(null)
  const [uploadError, setUploadError] = useState<unknown | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const doUpload = async (file: File) => {
    const lower = file.name.toLowerCase()
    if (!ACCEPT_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      setUploadError(
        new Error(`不支持的文件类型：${file.name}。仅接受 ${ACCEPT_EXTENSIONS.join(' / ')}`)
      )
      return
    }
    setUploading(true)
    setUploadError(null)
    setResult(null)
    try {
      const doc = await uploadDocument(file)
      setResult(doc)
      onSuccess(doc)
      onUploaded()
    } catch (err) {
      setUploadError(err)
      onError(err, '上传失败')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) void doUpload(file)
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragOver(false)
    const file = event.dataTransfer.files?.[0]
    if (file) void doUpload(file)
  }

  return (
    <Panel
      title="上传文献"
      subtitle={`接受 ${ACCEPT_EXTENSIONS.join('、')}；doc_id 取自文件内容，重复上传自动去重`}
    >
      <div
        className={dragOver ? 'kb-drop kb-drop-active' : 'kb-drop'}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        role="presentation"
      >
        <span className="kb-drop-icon" aria-hidden="true">
          <Icon name="upload" size={18} />
        </span>
        <div className="kb-drop-body">
          <div className="kb-drop-text">
            {uploading ? '正在解析、分页并写入 seekdb…' : '把文件拖到这里'}
          </div>
          <div className="field-hint">
            {uploading ? 'PDF 会按真实物理页切分，空白页同样保留页级身份。' : '或选择本地文件；解析、切块、向量化都在后端完成。'}
          </div>
        </div>
        {!uploading ? (
          <button type="button" className="btn btn-primary" onClick={() => inputRef.current?.click()}>
            选择文件
          </button>
        ) : null}
        <input
          ref={inputRef}
          id="upload-file"
          type="file"
          accept={ACCEPT_EXTENSIONS.join(',')}
          className="visually-hidden"
          onChange={onFileChange}
        />
      </div>

      {uploadError ? (
        <div style={{ marginTop: 'var(--s-3)' }}>
          <ErrorState error={uploadError} />
        </div>
      ) : null}

      {result ? <UploadResultCard doc={result} /> : null}
    </Panel>
  )
}

function UploadResultCard({ doc }: { doc: DocumentDetail }) {
  return (
    <div className="upload-result">
      <div className="upload-result-head">
        <strong>{doc.filename}</strong>
        {doc.deduplicated ? (
          <span className="badge badge-amber">重复上传已去重</span>
        ) : (
          <span className="badge badge-green">新入库</span>
        )}
      </div>
      <div className="meta-grid">
        <span className="meta-item">
          <span className="meta-key">doc_id</span>
          <span className="meta-value mono">{doc.doc_id}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">page_count</span>
          <span className="meta-value">{doc.page_count}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">chunk_count</span>
          <span className="meta-value">{doc.chunk_count}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">content_type</span>
          <span className="meta-value">{doc.content_type}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">空白页 empty_pages</span>
          <span className="meta-value">
            {doc.empty_pages.length > 0 ? doc.empty_pages.join('、') : '无'}
          </span>
        </span>
        <span className="meta-item">
          <span className="meta-key">embedding_provider</span>
          <span className="meta-value mono">{doc.embedding_provider || '—'}</span>
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 文档列表

function DocumentListPanel({
  documents,
  loading,
  error,
  onRetry,
  onOpenPage,
  expandedId,
  onExpand,
}: {
  documents: DocumentRecord[]
  loading: boolean
  error: unknown | null
  onRetry: () => void
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
  expandedId: string | null
  onExpand: (docId: string | null, detail: DocumentDetail | null) => void
}) {
  const [filter, setFilter] = useState('')
  const [detail, setDetail] = useState<DocumentDetail | null>(null)
  const [detailError, setDetailError] = useState<unknown | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return documents
    return documents.filter(
      (doc) =>
        doc.filename.toLowerCase().includes(needle) ||
        doc.doc_id.toLowerCase().includes(needle) ||
        doc.content_type.toLowerCase().includes(needle)
    )
  }, [documents, filter])

  const toggle = async (doc: DocumentRecord) => {
    if (expandedId === doc.doc_id) {
      setDetail(null)
      onExpand(null, null)
      return
    }
    onExpand(doc.doc_id, null)
    setDetail(null)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const data = await getDocument(doc.doc_id)
      setDetail(data)
      onExpand(doc.doc_id, data)
    } catch (err) {
      setDetailError(err)
      onExpand(doc.doc_id, null)
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <Panel
      title="文档列表"
      subtitle={`共 ${documents.length} 篇；展开任意一篇可以看到每一个物理页（含空白页）`}
      tags={<SourceTag source="seekdb" />}
      actions={
        <>
          <input
            id="kb-filter"
            className="input kb-filter"
            value={filter}
            maxLength={120}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="按文件名 / doc_id 过滤"
            aria-label="按文件名过滤文档列表"
          />
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            <Icon name="refresh" size={13} /> 刷新
          </button>
        </>
      }
    >
      {loading ? <LoadingState text="正在读取 seekdb 中的文档表…" /> : null}
      {!loading && error ? <ErrorState error={error} onRetry={onRetry} /> : null}
      {!loading && !error && documents.length === 0 ? (
        <EmptyState text="知识库为空。先上传一篇 PDF / Markdown / TXT 文献。" />
      ) : null}
      {!loading && !error && documents.length > 0 && visible.length === 0 ? (
        <EmptyState text={`没有文件名匹配「${filter}」的文献。`} />
      ) : null}

      {!loading && !error && visible.length > 0 ? (
        <ul className="doc-grid">
          {visible.map((doc) => (
            <DocumentCard
              key={doc.doc_id}
              doc={doc}
              expanded={expandedId === doc.doc_id}
              detail={expandedId === doc.doc_id ? detail : null}
              detailLoading={expandedId === doc.doc_id && detailLoading}
              detailError={expandedId === doc.doc_id ? detailError : null}
              onToggle={() => void toggle(doc)}
              onOpenPage={onOpenPage}
            />
          ))}
        </ul>
      ) : null}
    </Panel>
  )
}

function DocumentCard({
  doc,
  expanded,
  detail,
  detailLoading,
  detailError,
  onToggle,
  onOpenPage,
}: {
  doc: DocumentRecord
  expanded: boolean
  detail: DocumentDetail | null
  detailLoading: boolean
  detailError: unknown | null
  onToggle: () => void
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
}) {
  return (
    <li className={expanded ? 'doc-card doc-card-expanded' : 'doc-card'}>
      <div className="doc-card-head">
        <span className="doc-card-icon" aria-hidden="true">
          <Icon name={doc.content_type === 'pdf' ? 'page' : 'docs'} size={16} />
        </span>
        <div className="doc-card-name">
          <strong title={doc.filename}>{doc.filename}</strong>
          <span className="doc-card-title">{doc.title || '（无标题）'}</span>
        </div>
        <div className="doc-card-badges">
          <span className="badge">{doc.content_type}</span>
          {doc.status !== 'ready' ? <span className="badge badge-red">状态：{doc.status}</span> : null}
          {doc.deduplicated ? <span className="badge badge-amber">去重命中</span> : null}
        </div>
      </div>

      <div className="doc-stats">
        <span className="doc-stat">
          <strong>{doc.page_count}</strong> 页
        </span>
        <span className="doc-stat">
          <strong>{doc.chunk_count}</strong> chunks
        </span>
        <span className="doc-stat">
          <strong>{(doc.size_bytes / 1024).toFixed(1)}</strong> KB
        </span>
        <span className="doc-stat">
          空白页 <strong>{doc.empty_pages.length > 0 ? doc.empty_pages.join('、') : '无'}</strong>
        </span>
        <span className="doc-stat doc-stat-time">{formatTimestamp(doc.updated_at)}</span>
      </div>

      <div className="doc-card-foot">
        <span className="doc-card-id mono" title={doc.doc_id}>
          {doc.doc_id.slice(0, 16)}…
        </span>
        <button
          type="button"
          className="btn btn-sm"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`${expanded ? '收起' : '展开'} ${doc.filename} 的页导航`}
        >
          {expanded ? '收起' : '页导航'}
          <Icon name={expanded ? 'chevronLeft' : 'chevronRight'} size={13} />
        </button>
      </div>

      {doc.error_message ? (
        <div className="banner banner-red" role="alert">
          {doc.error_message}
        </div>
      ) : null}

      {expanded ? (
        <div className="doc-card-body">
          {detailLoading ? <LoadingState text="正在读取页级身份列表…" /> : null}
          {detailError ? <ErrorState error={detailError} /> : null}
          {detail ? <PageNavigator detail={detail} onOpenPage={onOpenPage} /> : null}
        </div>
      ) : null}
    </li>
  )
}

function PageNavigator({
  detail,
  onOpenPage,
}: {
  detail: DocumentDetail
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
}) {
  if (detail.pages.length === 0) {
    return <EmptyState text="没有页记录（解析时可能未产生任何物理页）。" />
  }
  return (
    <div className="page-navigator">
      <div className="page-navigator-hint">
        共 {detail.pages.length} 个物理页，空白页保留页级身份；点击任意页查看 seekdb 中存储的原文。
      </div>
      <ul className="page-chip-list">
        {detail.pages.map((page) => (
          <li key={page.page_id}>
            <button
              type="button"
              className={page.is_empty ? 'page-chip page-chip-empty' : 'page-chip'}
              onClick={() => onOpenPage(detail.doc_id, page.page_no, detail.filename)}
              title={`page_id: ${page.page_id}\nchar_count: ${page.char_count}${page.is_empty ? '\n空白页（保留页级身份）' : ''}`}
            >
              <span className="page-chip-no">第 {page.page_no} 页</span>
              <span className="page-chip-meta mono">{page.char_count} 字符</span>
              {page.is_empty ? (
                <span className="page-chip-empty-badge">空白页（保留页级身份）</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- 检索

interface SearchFormState {
  query: string
  mode: RetrievalMode
  topK: string
  applyGate: boolean
  docId: string
  contentType: string
  pageFrom: string
  pageTo: string
}

const INITIAL_FORM: SearchFormState = {
  query: '',
  mode: 'hybrid',
  topK: '8',
  applyGate: false,
  docId: '',
  contentType: '',
  pageFrom: '',
  pageTo: '',
}

function SearchPanel({
  documents,
  onOpenPage,
  onError,
  result,
  setResult,
}: {
  documents: DocumentRecord[]
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
  onError: (err: unknown, title?: string) => void
  result: RetrievalResult | null
  setResult: (result: RetrievalResult | null) => void
}) {
  const [form, setForm] = useState<SearchFormState>(INITIAL_FORM)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<unknown | null>(null)
  const [hasSearched, setHasSearched] = useState(false)

  const [comparing, setComparing] = useState(false)
  const [compare, setCompare] = useState<CompareResponse | null>(null)
  const [compareError, setCompareError] = useState<unknown | null>(null)

  const set = <K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }))

  const buildParams = () => ({
    query: form.query.trim(),
    mode: form.mode,
    top_k: Number.parseInt(form.topK, 10) || 8,
    apply_gate: form.applyGate,
    doc_id: form.docId || null,
    content_type: (form.contentType || null) as ContentType | null,
    page_from: form.pageFrom ? Number.parseInt(form.pageFrom, 10) : null,
    page_to: form.pageTo ? Number.parseInt(form.pageTo, 10) : null,
  })

  const runSearch = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.query.trim()) return
    setSearching(true)
    setSearchError(null)
    setHasSearched(true)
    try {
      setResult(await searchDocuments(buildParams()))
    } catch (err) {
      setResult(null)
      setSearchError(err)
      onError(err, '检索失败')
    } finally {
      setSearching(false)
    }
  }

  const runCompare = async () => {
    if (!form.query.trim()) return
    setComparing(true)
    setCompareError(null)
    try {
      setCompare(
        await compareModes({
          query: form.query.trim(),
          top_k: Number.parseInt(form.topK, 10) || 8,
        })
      )
    } catch (err) {
      setCompare(null)
      setCompareError(err)
      onError(err, '三种检索方式对比失败')
    } finally {
      setComparing(false)
    }
  }

  const backendWarning = result?.backend.warning ?? null

  return (
    <>
      <Panel
        title="证据检索"
        subtitle="三种模式的分数语义不同，每条命中都随 score_kind 显式标注"
        tags={<SourceTag source="seekdb" />}
      >
        <form onSubmit={runSearch}>
          <div className="field">
            <label htmlFor="search-query">检索内容</label>
            <textarea
              id="search-query"
              className="textarea kb-query"
              value={form.query}
              maxLength={2000}
              rows={2}
              onChange={(e) => set('query', e.target.value)}
              placeholder="输入要检索的问题或关键词，例如：RRF 融合分数怎么算"
            />
          </div>

          <div className="kb-controls">
            <div className="field">
              <label htmlFor="search-mode">检索模式</label>
              <select
                id="search-mode"
                className="select"
                value={form.mode}
                onChange={(e) => set('mode', e.target.value as RetrievalMode)}
              >
                <option value="vector">向量（cosine_similarity）</option>
                <option value="fulltext">全文（fts_relevance）</option>
                <option value="hybrid">混合（RRF 融合）</option>
              </select>
            </div>
            <div className="field field-narrow">
              <label htmlFor="search-topk">top_k</label>
              <input
                id="search-topk"
                className="input"
                type="number"
                min={1}
                max={50}
                value={form.topK}
                onChange={(e) => set('topK', e.target.value)}
              />
            </div>
            <div className="field field-checkbox">
              <label className="checkbox-field" htmlFor="search-gate">
                <input
                  id="search-gate"
                  type="checkbox"
                  checked={form.applyGate}
                  onChange={(e) => set('applyGate', e.target.checked)}
                />
                启用证据门控（apply_gate）
              </label>
              <span className="field-hint">开启后只保留通过相关性与覆盖率门控的证据</span>
            </div>
          </div>

          <details className="collapsible">
            <summary>可选过滤条件（doc_id / content_type / 页码范围）</summary>
            <div className="kb-controls" style={{ marginTop: 'var(--s-2)' }}>
              <div className="field">
                <label htmlFor="filter-doc">doc_id</label>
                <select
                  id="filter-doc"
                  className="select"
                  value={form.docId}
                  onChange={(e) => set('docId', e.target.value)}
                >
                  <option value="">全部文档</option>
                  {documents.map((doc) => (
                    <option key={doc.doc_id} value={doc.doc_id}>
                      {doc.filename}（{doc.doc_id.slice(0, 8)}…）
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="filter-type">content_type</label>
                <select
                  id="filter-type"
                  className="select"
                  value={form.contentType}
                  onChange={(e) => set('contentType', e.target.value)}
                >
                  <option value="">全部类型</option>
                  <option value="pdf">pdf</option>
                  <option value="markdown">markdown</option>
                  <option value="text">text</option>
                </select>
              </div>
              <div className="field field-narrow">
                <label htmlFor="filter-from">page_from</label>
                <input
                  id="filter-from"
                  className="input"
                  type="number"
                  min={1}
                  value={form.pageFrom}
                  onChange={(e) => set('pageFrom', e.target.value)}
                  placeholder="不限"
                />
              </div>
              <div className="field field-narrow">
                <label htmlFor="filter-to">page_to</label>
                <input
                  id="filter-to"
                  className="input"
                  type="number"
                  min={1}
                  value={form.pageTo}
                  onChange={(e) => set('pageTo', e.target.value)}
                  placeholder="不限"
                />
              </div>
            </div>
          </details>

          <div className="kb-actions">
            <button type="submit" className="btn btn-primary" disabled={searching || !form.query.trim()}>
              {searching ? '检索中…' : '检索'}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => void runCompare()}
              disabled={comparing || !form.query.trim()}
            >
              {comparing ? '对比中…' : '对比三种检索方式'}
            </button>
            <span className="field-hint kb-actions-hint">
              同一条查询可以只切换模式再检索一次，也可以直接并排对比三种模式与它们的重叠。
            </span>
          </div>
        </form>

        {searchError ? (
          <div style={{ marginTop: 'var(--s-3)' }}>
            <ErrorState error={searchError} />
          </div>
        ) : null}

        {searching ? (
          <div style={{ marginTop: 'var(--s-3)' }}>
            <LoadingState text="正在检索 seekdb…" />
          </div>
        ) : null}

        {result && !searching ? (
          <div className="search-result">
            {backendWarning ? (
              <div className="banner banner-amber" role="alert">
                <strong>embedding 不一致：</strong>
                {backendWarning}
              </div>
            ) : null}
            <ResultMeta result={result} />
            {result.hits.length === 0 ? (
              <EmptyState
                text={
                  result.gate.applied && result.dropped_by_gate > 0
                    ? `没有命中。原始命中 ${result.dropped_by_gate} 条全部被证据门控剔除（说明材料与问题相关性不足）。`
                    : '没有命中任何 chunk。'
                }
              />
            ) : (
              <ul className="hit-stack">
                {result.hits.map((hit) => (
                  <HitCard key={hit.chunk_id} hit={hit} onOpenPage={onOpenPage} />
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {!searching && !searchError && !result && hasSearched ? (
          <EmptyState text="没有检索结果。" />
        ) : null}
      </Panel>

      {compareError ? (
        <Panel title="三种检索方式对比">
          <ErrorState error={compareError} />
        </Panel>
      ) : null}
      {compare ? <ComparePanel compare={compare} onOpenPage={onOpenPage} /> : null}
    </>
  )
}

function ResultMeta({ result }: { result: RetrievalResult }) {
  return (
    <div className="result-meta">
      <div className="kb-pills">
        <span className="kb-pill">
          模式 <strong>{MODE_LABELS[result.mode] ?? result.mode}</strong>
        </span>
        <span className="kb-pill">
          命中 <strong>{result.hits.length}</strong>
        </span>
        <span className="kb-pill kb-pill-green">
          通过门控 <strong>{result.relevant_count}</strong>
        </span>
        {result.dropped_by_gate > 0 ? (
          <span className="kb-pill kb-pill-amber">
            门控剔除 <strong>{result.dropped_by_gate}</strong>
          </span>
        ) : null}
        <span className="kb-pill">
          耗时 <strong>{result.elapsed_ms}</strong> ms
        </span>
        {result.gate.applied ? (
          <span className="kb-pill">
            门控 <strong>已启用</strong> · min_coverage {result.gate.min_coverage}
          </span>
        ) : (
          <span className="kb-pill">门控未启用</span>
        )}
      </div>
      <div className="kb-backend mono">
        collection <code>{result.backend.collection}</code> · fts_analyzer{' '}
        <code>{result.backend.fts_analyzer}</code> · embedding <code>{result.backend.embedding_provider}</code>（
        {result.backend.embedding_dimension} 维）· 距离 <code>{result.backend.vector_distance}</code>
      </div>
    </div>
  )
}

function HitCard({
  hit,
  onOpenPage,
}: {
  hit: RetrievalHit
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
}) {
  return (
    <li className="hit-card">
      <div className="hit-card-head">
        <span className="hit-filename" title={hit.filename || hit.doc_id}>
          {hit.filename || hit.title || hit.doc_id}
        </span>
        <span className="badge badge-accent">
          <Icon name="page" size={12} />第 {hit.page_no} 页
        </span>
        {hit.gate_passed ? (
          <span className="badge badge-green">通过门控</span>
        ) : (
          <span className="badge">未过门控</span>
        )}
        <button
          type="button"
          className="btn btn-sm hit-view-btn"
          onClick={() => onOpenPage(hit.doc_id, hit.page_no, hit.filename)}
        >
          查看原文
        </button>
      </div>
      <div className="hit-scores">
        <span className="hit-score-main">
          score <strong>{formatScore(hit.score)}</strong>
          <em className="hit-score-kind">{scoreKindLabel(hit.score_kind)}</em>
        </span>
        <span>
          coverage <strong>{formatScore(hit.coverage)}</strong>
        </span>
        <span>
          normalized_score <strong>{formatScore(hit.normalized_score)}</strong>
        </span>
        <span>
          relevance <strong>{formatScore(hit.relevance)}</strong>
        </span>
      </div>
      <p className="hit-text">{hit.text}</p>
      <div className="hit-ids mono">
        <span>
          chunk_id <code>{hit.chunk_id}</code>
        </span>
        <span>
          page_id <code>{hit.page_id}</code>
        </span>
      </div>
    </li>
  )
}

// ---------------------------------------------------------------- 三模式对比

function ComparePanel({
  compare,
  onOpenPage,
}: {
  compare: CompareResponse
  onOpenPage: (docId: string, pageNo: number, filename?: string) => void
}) {
  const modes: RetrievalMode[] = ['vector', 'fulltext', 'hybrid']
  const warning = compare.backend.warning ?? null
  return (
    <Panel
      title="对比三种检索方式"
      subtitle={`同一条查询：${compare.query}`}
      tags={<SourceTag source="seekdb" />}
    >
      {warning ? (
        <div className="banner banner-amber" role="alert">
          <strong>embedding 不一致：</strong>
          {warning}
        </div>
      ) : null}
      <div className="compare-columns">
        {modes.map((mode) => {
          const result = compare.results[mode]
          if (!result) return null
          return (
            <div className="compare-column" key={mode}>
              <div className="compare-column-head">
                <h3>{MODE_LABELS[mode]}（{mode}）</h3>
                <span className="badge">
                  {result.hits.length} 条 · {result.elapsed_ms} ms
                </span>
              </div>
              {result.hits.length === 0 ? (
                <EmptyState text="该模式没有命中" />
              ) : (
                <ol className="compare-hit-list">
                  {result.hits.map((hit, index) => (
                    <li key={hit.chunk_id} className="compare-hit">
                      <div className="compare-hit-top">
                        <span className="compare-hit-rank">{index + 1}</span>
                        <button
                          type="button"
                          className="compare-hit-link"
                          onClick={() => onOpenPage(hit.doc_id, hit.page_no, hit.filename)}
                        >
                          {hit.filename || hit.doc_id} · 第 {hit.page_no} 页
                        </button>
                      </div>
                      <div className="compare-hit-score">
                        {formatScore(hit.score)}
                        <em>{scoreKindLabel(hit.score_kind)}</em>
                      </div>
                      <div className="compare-hit-id mono">{hit.chunk_id}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )
        })}
      </div>
      <div className="overlap-panel">
        <h3>重叠分析（按 chunk_id）</h3>
        <div className="overlap-columns">
          <div className="overlap-block">
            <div className="overlap-title">
              vector ∩ fulltext（{compare.overlap.vector_and_fulltext.length} 条）
            </div>
            <OverlapIds ids={compare.overlap.vector_and_fulltext} emptyText="两种方式没有共同命中" />
          </div>
          <div className="overlap-block">
            <div className="overlap-title">
              仅 hybrid 命中（RRF 融合独有，{compare.overlap.hybrid_only.length} 条）
            </div>
            <OverlapIds ids={compare.overlap.hybrid_only} emptyText="hybrid 没有独有命中" />
          </div>
        </div>
      </div>
    </Panel>
  )
}

function OverlapIds({ ids, emptyText }: { ids: string[]; emptyText: string }) {
  if (ids.length === 0) return <p className="overlap-empty">{emptyText}</p>
  return (
    <ul className="overlap-id-list mono">
      {ids.map((id) => (
        <li key={id}>{id}</li>
      ))}
    </ul>
  )
}
