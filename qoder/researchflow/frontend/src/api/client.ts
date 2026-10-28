/**
 * ResearchFlow API 客户端。
 *
 * 所有接口类型与 frontend/api-contract.json（OpenAPI 3）以及后端真实响应结构一一对应。
 * 非 2xx 响应统一解析为 {error: {code, message, detail, path, request_id}} 信封并抛出
 * ApiError；网络不可达时也抛出 ApiError（code=network_error），绝不静默吞错。
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8787'

// ---------------------------------------------------------------- 基础类型

export type RetrievalMode = 'vector' | 'fulltext' | 'hybrid'
export type ContentType = 'pdf' | 'markdown' | 'text'
export type AnswerMode = 'grounded' | 'retrieval_only'
export type ClaimLabel = 'supported' | 'inferred' | 'no_evidence'

/** 后端错误信封（app/api/main.py 的 _error_payload）。 */
export interface ApiErrorEnvelope {
  code: string
  message: string
  detail: Record<string, unknown>
  path: string
  request_id: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: Record<string, unknown>
  readonly path: string
  readonly requestId: string

  constructor(status: number, envelope: Partial<ApiErrorEnvelope>) {
    super(envelope.message || `请求失败（HTTP ${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.code = envelope.code || 'unknown_error'
    this.detail = envelope.detail || {}
    this.path = envelope.path || ''
    this.requestId = envelope.request_id || ''
  }

  static fromPayload(status: number, payload: unknown, path: string): ApiError {
    if (payload && typeof payload === 'object') {
      const record = payload as Record<string, unknown>
      const error = record.error
      if (error && typeof error === 'object') {
        const err = error as Record<string, unknown>
        return new ApiError(status, {
          code: String(err.code ?? 'unknown_error'),
          message: String(err.message ?? ''),
          detail: (err.detail && typeof err.detail === 'object' ? err.detail : {}) as Record<string, unknown>,
          path: String(err.path ?? path),
          request_id: String(err.request_id ?? ''),
        })
      }
      if (Array.isArray(record.detail)) {
        // FastAPI 422 校验错误：{detail: [{loc, msg, type}, ...]}
        const messages = (record.detail as { loc?: unknown[]; msg?: string }[])
          .map((item) => `${(item.loc ?? []).join('.')}: ${item.msg ?? ''}`)
          .join('；')
        return new ApiError(status, {
          code: 'validation_error',
          message: messages || '请求参数校验失败',
          path,
        })
      }
      if (typeof record.message === 'string' && record.message) {
        return new ApiError(status, { message: record.message, path })
      }
    }
    return new ApiError(status, { message: `请求失败（HTTP ${status}）`, path })
  }
}

/** 把任意异常转换成可展示的 {title, message, requestId}。 */
export function describeError(err: unknown): { title: string; message: string; requestId?: string } {
  if (err instanceof ApiError) {
    return {
      title: err.code === 'network_error' ? '后端连接失败' : `请求失败（${err.code}）`,
      message: err.message,
      requestId: err.requestId || undefined,
    }
  }
  if (err instanceof Error) return { title: '发生错误', message: err.message }
  return { title: '发生错误', message: String(err) }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause)
    throw new ApiError(0, {
      code: 'network_error',
      message: `无法连接 ResearchFlow 后端（${url}）：${reason}。请确认后端已在该地址启动，或配置 VITE_API_BASE_URL。`,
      path,
    })
  }
  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    throw ApiError.fromPayload(response.status, payload, path)
  }
  return (await response.json()) as T
}

function compact(value: object): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (item !== null && item !== undefined) out[key] = item
  }
  return out
}

function jsonInit(body: unknown, method = 'POST'): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

// ---------------------------------------------------------------- /api/health、/api/meta

export interface SeekdbCounts {
  documents: number | null
  pages: number | null
  projects: number | null
  chunks: number | null
}

export interface SeekdbHealth {
  available: boolean
  mode?: string
  endpoint?: string
  database?: string
  server_version?: string
  fts_analyzer?: string
  counts?: SeekdbCounts
  stored_embedding?: { provider: string | null; dimension: string | null; updated_at: string | null }
  latency_ms?: number
  error?: string
}

export interface PowerContextHealth {
  available: boolean
  url?: string
  liveness?: string
  readiness?: string
  package_version?: string | null
  api_contract_version?: string | null
  server_id?: string | null
  database_ready?: boolean | null
  latency_ms?: number
  error?: string
}

export interface LlmInfo {
  enabled: boolean
  base_url: string
  model: string
  provider: string
  reason: string | null
}

export interface EmbeddingInfo {
  provider: string
  dimension: number
  note: string
  configured: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  components: {
    seekdb: SeekdbHealth
    powercontext: PowerContextHealth
    llm: LlmInfo
    embedding: EmbeddingInfo
  }
  capabilities: {
    upload: boolean
    retrieval: boolean
    qa: boolean
    qa_generates_answers: boolean
    memory: boolean
  }
}

export interface MetaResponse {
  app: string
  version: string
  seekdb: Record<string, unknown>
  powercontext: Record<string, unknown>
  llm: Record<string, unknown>
  embedding: Record<string, unknown>
  retrieval: Record<string, unknown>
  upload: Record<string, unknown>
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/api/health')
}

export function getMeta(): Promise<MetaResponse> {
  return apiFetch<MetaResponse>('/api/meta')
}

// ---------------------------------------------------------------- 文档（seekdb）

export interface DocumentRecord {
  doc_id: string
  filename: string
  content_type: string
  size_bytes: number
  page_count: number
  chunk_count: number
  title: string
  status: string
  deduplicated: boolean
  empty_pages: number[]
  error_message: string | null
  created_at: string | null
  updated_at: string | null
  embedding_provider: string
}

export interface PageSummary {
  page_id: string
  doc_id: string
  page_no: number
  char_count: number
  is_empty: boolean
}

export interface DocumentDetail extends DocumentRecord {
  pages: PageSummary[]
}

export interface DocumentListResponse {
  count: number
  documents: DocumentRecord[]
  embedding_provider: string
}

export interface PageDetail extends PageSummary {
  content: string
  filename: string
  content_type: string
}

export interface DeleteDocumentResponse {
  doc_id: string
  deleted: boolean
  pages_removed: number
}

export function uploadDocument(file: File, force = false): Promise<DocumentDetail> {
  const form = new FormData()
  form.append('file', file)
  const suffix = force ? '?force=true' : ''
  return apiFetch<DocumentDetail>(`/api/documents/upload${suffix}`, { method: 'POST', body: form })
}

export function listDocuments(): Promise<DocumentListResponse> {
  return apiFetch<DocumentListResponse>('/api/documents')
}

export function getDocument(docId: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(`/api/documents/${encodeURIComponent(docId)}`)
}

export function getPage(docId: string, pageNo: number): Promise<PageDetail> {
  return apiFetch<PageDetail>(
    `/api/documents/${encodeURIComponent(docId)}/pages/${encodeURIComponent(String(pageNo))}`
  )
}

export function deleteDocument(docId: string): Promise<DeleteDocumentResponse> {
  return apiFetch<DeleteDocumentResponse>(`/api/documents/${encodeURIComponent(docId)}`, {
    method: 'DELETE',
  })
}

// ---------------------------------------------------------------- 检索（seekdb）

export interface RetrievalHit {
  chunk_id: string
  doc_id: string
  filename: string
  content_type: string
  title: string
  page_no: number
  page_id: string
  chunk_index: number
  char_start: number
  char_end: number
  text: string
  score: number
  score_kind: string
  matched_by: string
  coverage: number
  normalized_score: number
  relevance: number
  gate_passed: boolean
}

export interface RetrievalBackendInfo {
  endpoint: string
  database: string
  collection: string
  fts_analyzer: string
  vector_distance: string
  embedding_provider: string
  embedding_dimension: number
  stored_embedding_provider?: string
  /** embedding provider 与已入库向量不一致时的显式警告。 */
  warning?: string
}

export interface GateInfo {
  applied: boolean
  min_coverage: number
  vector_confidence: number
}

export interface Citation {
  citation_id: string
  chunk_id: string
  doc_id: string
  filename: string
  content_type: string
  page_no: number
  page_id: string
  char_start: number
  char_end: number
  quote: string
  score: number
  score_kind: string
  relevance: number
  coverage: number
  source: 'document'
}

export interface RetrievalResult {
  query: string
  mode: RetrievalMode
  hits: RetrievalHit[]
  elapsed_ms: number
  backend: RetrievalBackendInfo
  filters: Record<string, unknown>
  gate: GateInfo
  dropped_by_gate: number
  error: string | null
  citations: Citation[]
  relevant_count: number
}

export interface CompareResponse {
  query: string
  results: Record<RetrievalMode, RetrievalResult>
  ids: Record<RetrievalMode, string[]>
  overlap: {
    vector_and_fulltext: string[]
    hybrid_only: string[]
  }
  backend: RetrievalBackendInfo
}

export interface SearchParams {
  query: string
  mode?: RetrievalMode
  top_k?: number
  apply_gate?: boolean
  doc_id?: string | null
  content_type?: ContentType | null
  page_from?: number | null
  page_to?: number | null
}

export function searchDocuments(params: SearchParams): Promise<RetrievalResult> {
  return apiFetch<RetrievalResult>('/api/retrieval/search', jsonInit(compact(params)))
}

export function compareModes(params: SearchParams): Promise<CompareResponse> {
  return apiFetch<CompareResponse>('/api/retrieval/compare', jsonInit(compact(params)))
}

// ---------------------------------------------------------------- 问答

export interface Claim {
  statement: string
  label: ClaimLabel
  citation_ids: string[]
  downgraded: boolean
  downgrade_reason: string
}

export interface InvalidCitation {
  citation_id: string
  reason: string
  doc_id?: string
  page_no?: number
}

export interface LlmUsage extends LlmInfo {
  model_returned?: string
  prompt_tokens?: number | null
  completion_tokens?: number | null
  elapsed_ms?: number
  json_parsed?: boolean
}

/** QA 响应里的 memory 字段：正常时是 RestoreResponse，PowerContext 故障时退化为 fallback。 */
export interface QaMemoryFallback {
  available: false
  error: string
  source: 'memory'
}

export type QaMemory = RestoreResponse | QaMemoryFallback

export interface AskResponse {
  question: string
  mode: AnswerMode
  answerable: boolean
  answer: string
  claims: Claim[]
  citations: Citation[]
  used_citations: Citation[]
  invalid_citations: InvalidCitation[]
  missing: string
  retrieval: RetrievalResult
  memory: QaMemory | null
  llm: LlmUsage
  elapsed_ms: number
  label_summary: Record<ClaimLabel, number>
  unused_evidence: Citation[]
}

export interface AskParams {
  question: string
  mode?: RetrievalMode
  top_k?: number
  project_id?: string | null
  doc_id?: string | null
  content_type?: ContentType | null
  page_from?: number | null
  page_to?: number | null
}

export function askQuestion(params: AskParams): Promise<AskResponse> {
  return apiFetch<AskResponse>('/api/qa/ask', jsonInit(compact(params)))
}

// ---------------------------------------------------------------- 项目与任务记忆（PowerContext）

export interface Project {
  project_id: string
  title: string
  objective: string
  scope_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectListResponse {
  count: number
  projects: Project[]
}

export interface CreateProjectResponse extends Project {
  memory_bound: boolean
}

export interface EvidencePointer {
  doc_id: string
  filename: string
  page_no: number
  chunk_id: string
  quote: string
}

export interface ProgressSnapshot {
  v?: number
  project_id?: string
  title?: string
  objective?: string
  completed_work?: string[]
  decisions?: string[]
  key_evidence?: EvidencePointer[]
  open_questions?: string[]
  next_steps?: string[]
  note?: string
  confirmed_by?: string
  seq?: number
  updated_at?: string
  fingerprint?: string
  truncated?: boolean
  _artifact_id?: string
  _revision?: number
  _state?: string
}

export interface MemoryEntry {
  kind: string
  text: string
  seq: number
  updated_at: string
  artifact_id: string
  revision: number
  state: string
  source: string
  kind_label: string
}

export interface MemorySearchHit {
  kind: string
  text: string
  score: number
  artifact_id: string
  source: 'memory'
}

export interface PreparedContext {
  query: string
  recall_query: string
  recall_query_expanded: boolean
  status: string
  content_bytes: number
  content: string | null
  search_mode: string
  search_hits: MemorySearchHit[]
  source: 'memory'
  note: string
}

export interface RestoreResponse {
  project_id: string
  title: string
  scope_id: string | null
  memory_available: boolean
  snapshot: ProgressSnapshot | null
  entries: MemoryEntry[]
  grouped: Record<string, MemoryEntry[]>
  resume_brief: string
  prepared_context: PreparedContext
  memory_backend: {
    backend: string
    url: string
    scope_id: string | null
    role: string
    available?: boolean
    package_version?: string | null
  }
  error: string | null
  entry_count: number
  source: 'memory'
}

export interface ProjectDetail extends Project {
  memory_available: boolean
  snapshot: ProgressSnapshot | null
  resume_brief: string
  entry_count: number
  memory_error: string | null
}

export interface SaveProgressRequest {
  objective?: string
  title?: string
  completed_work: string[]
  decisions: string[]
  key_evidence: EvidencePointer[]
  open_questions: string[]
  next_steps: string[]
  note?: string
  confirmed_by?: string
}

export interface SaveProgressResponse {
  project_id: string
  scope_id: string
  seq: number
  updated_at: string
  written: number
  skipped_duplicates: number
  snapshot_artifact_id: string | null
  snapshot_revision: number | null
  snapshot_unchanged: boolean
  written_kinds: string[]
}

export interface MemoryHistoryResponse {
  project_id: string
  scope_id: string
  source: 'memory'
  entry_count: number
  snapshot_count: number
  entries: MemoryEntry[]
  grouped: Record<string, MemoryEntry[]>
}

export interface MemoryStatusResponse {
  backend: string
  role: string
  url: string
  available: boolean
  liveness?: string
  readiness?: string
  package_version?: string | null
  api_contract_version?: string | null
  server_id?: string | null
  database_ready?: boolean | null
  latency_ms?: number
  error?: string
  note: string
}

export interface CreateProjectParams {
  project_id?: string
  title: string
  objective?: string
}

export function listProjects(): Promise<ProjectListResponse> {
  return apiFetch<ProjectListResponse>('/api/projects')
}

export function createProject(params: CreateProjectParams): Promise<CreateProjectResponse> {
  return apiFetch<CreateProjectResponse>('/api/projects', jsonInit(compact(params)))
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`)
}

export function saveProgress(
  projectId: string,
  body: SaveProgressRequest
): Promise<SaveProgressResponse> {
  return apiFetch<SaveProgressResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory/save`,
    jsonInit(body)
  )
}

export function restoreProgress(projectId: string, query = ''): Promise<RestoreResponse> {
  const search = new URLSearchParams({ query })
  return apiFetch<RestoreResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory/restore?${search.toString()}`
  )
}

export function getMemoryHistory(projectId: string): Promise<MemoryHistoryResponse> {
  return apiFetch<MemoryHistoryResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory/history`
  )
}

export function getMemoryStatus(): Promise<MemoryStatusResponse> {
  return apiFetch<MemoryStatusResponse>('/api/memory/status')
}
