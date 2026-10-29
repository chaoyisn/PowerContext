import type { ReactNode } from 'react'
import { describeError } from '../api/client'
import Icon from './Icon'

/** 状态圆点：green / amber / red / grey。 */
export function StatusDot({ level, label }: { level: 'green' | 'amber' | 'red' | 'grey'; label?: string }) {
  return <span className={`dot dot-${level}`} role="img" aria-label={label ?? `状态：${level}`} />
}

/** 通道标签：文献证据（seekdb）与历史记忆（PowerContext）在 UI 中永远显式区分。 */
export function SourceTag({ source }: { source: 'seekdb' | 'powercontext' }) {
  if (source === 'seekdb') {
    return (
      <span className="source-tag source-tag-seekdb">
        <Icon name="book" size={13} />
        文献证据 · seekdb
      </span>
    )
  }
  return (
    <span className="source-tag source-tag-powercontext">
      <Icon name="brain" size={13} />
      历史记忆 · PowerContext
    </span>
  )
}

export function Spinner({ label = '处理中' }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label} />
}

export function Skeleton({ width = '100%', height = 14 }: { width?: number | string; height?: number }) {
  return <span className="skeleton" style={{ display: 'block', width, height }} aria-hidden="true" />
}

/** 骨架行：用于检索/回答生成中的占位，避免空白跳动。 */
export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  return (
    <div className="loading-state" role="status" style={{ textAlign: 'left', padding: 0 }}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          height={12}
          width={index === lines - 1 ? '62%' : `${88 - index * 6}%`}
        />
      ))}
    </div>
  )
}

export function Metric({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  tone?: 'default' | 'accent' | 'memory' | 'warn' | 'bad'
}) {
  return (
    <div className={`metric${tone === 'default' ? '' : ` metric-${tone}`}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {hint ? <div className="metric-hint">{hint}</div> : null}
    </div>
  )
}

export function Panel({
  title,
  subtitle,
  tags,
  actions,
  children,
  className = '',
}: {
  title: ReactNode
  subtitle?: ReactNode
  tags?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      <div className="panel-header">
        <div className="panel-title">
          <span className="panel-name">{title}</span>
          {tags}
          {subtitle ? <span className="panel-subtitle">{subtitle}</span> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function LoadingState({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="loading-state" role="status">
      {text}
    </div>
  )
}

export function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>
}

export function ErrorState({
  error,
  onRetry,
  retryLabel = '重试',
}: {
  error: unknown
  onRetry?: () => void
  retryLabel?: string
}) {
  const { title, message, requestId } = describeError(error)
  return (
    <div className="error-state" role="alert">
      <span className="error-title">{title}</span>
      <span>{message}</span>
      {requestId ? <span className="error-request-id">request_id: {requestId}</span> : null}
      {onRetry ? (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          {retryLabel}
        </button>
      ) : null}
    </div>
  )
}

/** 时间戳展示：兼容 "2026-10-29 02:39:00.123456" 与 ISO 两种后端格式。 */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const normalized = value.replace('T', ' ')
  const trimmed = normalized.replace(/\.\d+/, '').replace(/\+00:00$/, ' UTC')
  return trimmed
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return String(value)
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(4)
}

/** 检索模式中文名。 */
export const MODE_LABELS: Record<string, string> = {
  vector: '向量',
  fulltext: '全文',
  hybrid: '混合',
}

/** score_kind 中文名：三种模式的分数语义不同，必须显式标注避免误读。 */
export const SCORE_KIND_LABELS: Record<string, string> = {
  cosine_similarity: '余弦相似度',
  fts_relevance: '全文相关度',
  rrf: 'RRF 融合分',
  distance: '距离（越小越相关）',
  lookup: '按 chunk_id 精确查找',
}

export function scoreKindLabel(kind: string): string {
  return SCORE_KIND_LABELS[kind] ?? kind
}

/** 记忆条目 kind 中文名（与后端 KIND_LABELS 一致）。 */
export const MEMORY_KIND_LABELS: Record<string, string> = {
  goal: '研究目标',
  completed_work: '已完成工作',
  decision: '已确认决策',
  evidence: '关键证据',
  open_question: '未解决问题',
  next_step: '下一步',
  progress_snapshot: '进度快照',
}

export function memoryKindLabel(kind: string): string {
  return MEMORY_KIND_LABELS[kind] ?? kind
}

export const MEMORY_KIND_ORDER = [
  'goal',
  'completed_work',
  'decision',
  'evidence',
  'open_question',
  'next_step',
  'progress_snapshot',
] as const
