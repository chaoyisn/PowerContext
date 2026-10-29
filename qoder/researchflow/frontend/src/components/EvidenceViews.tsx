import type { Citation, PreparedContext, ProgressSnapshot, QaMemory, RestoreResponse, RetrievalHit } from '../api/client'
import { SourceTag, formatScore, memoryKindLabel, scoreKindLabel } from './common'
import Icon from './Icon'
import { PanelSection } from './Shell'

export interface PageTarget {
  docId: string
  pageNo: number
  filename?: string
}

/** 引用证据卡：每条都能回到 seekdb 中真实存在的物理页与 chunk。 */
export function CitationCard({
  citation,
  highlighted,
  onOpenPage,
  onFocus,
}: {
  citation: Citation
  highlighted: boolean
  onOpenPage: (target: PageTarget) => void
  onFocus: (id: string) => void
}) {
  return (
    <li
      id={`citation-${citation.citation_id}`}
      className={highlighted ? 'citation-card citation-highlight' : 'citation-card'}
    >
      <div className="citation-head">
        <button
          type="button"
          className="cite-chip cite-chip-lg"
          onClick={() => onFocus(citation.citation_id)}
          aria-label={`引用 ${citation.citation_id}`}
        >
          [{citation.citation_id}]
        </button>
        <span className="citation-filename" title={citation.filename || citation.doc_id}>
          {citation.filename || citation.doc_id}
        </span>
        <span className="badge badge-accent">
          <Icon name="page" size={12} />第 {citation.page_no} 页
        </span>
        <button
          type="button"
          className="btn btn-sm citation-view"
          onClick={() => onOpenPage({ docId: citation.doc_id, pageNo: citation.page_no, filename: citation.filename })}
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
          <em>{scoreKindLabel(citation.score_kind)}</em>
        </span>
      </div>
      <div className="citation-ids">
        <span>
          chunk_id <code>{citation.chunk_id}</code>
        </span>
        <span>
          page_id <code>{citation.page_id}</code>
        </span>
      </div>
      <blockquote className="citation-quote">{citation.quote}</blockquote>
    </li>
  )
}

export function CitationPanel({
  citations,
  unused,
  highlighted,
  onOpenPage,
  onFocus,
}: {
  citations: Citation[]
  unused: Citation[]
  highlighted: string | null
  onOpenPage: (target: PageTarget) => void
  onFocus: (id: string) => void
}) {
  return (
    <PanelSection title="本轮使用的资料" count={citations.length}>
      {citations.length === 0 ? (
        <p className="side-empty">
          本次回答没有产生任何引用：没有证据通过 seekdb 的相关性与覆盖率门控。系统不会为了凑引用而编造页码。
        </p>
      ) : (
        <ul className="citation-list">
          {citations.map((citation) => (
            <CitationCard
              key={citation.citation_id}
              citation={citation}
              highlighted={highlighted === citation.citation_id}
              onOpenPage={onOpenPage}
              onFocus={onFocus}
            />
          ))}
        </ul>
      )}

      {unused.length > 0 ? (
        <details className="collapsible" style={{ marginTop: 'var(--s-3)' }}>
          <summary>检索到但未被引用（{unused.length}）</summary>
          <ul className="citation-list" style={{ marginTop: 'var(--s-2)' }}>
            {unused.map((citation) => (
              <CitationCard
                key={citation.citation_id}
                citation={citation}
                highlighted={false}
                onOpenPage={onOpenPage}
                onFocus={onFocus}
              />
            ))}
          </ul>
        </details>
      ) : null}
    </PanelSection>
  )
}

/** 检索命中列表（/api/retrieval/search 与 /api/retrieval/compare 的真实返回）。 */
export function HitRows({ hits, onOpenPage }: { hits: RetrievalHit[]; onOpenPage: (target: PageTarget) => void }) {
  if (hits.length === 0) {
    return <p className="side-empty">这一轮没有命中任何 chunk。</p>
  }
  return (
    <div>
      {hits.slice(0, 8).map((hit, index) => (
        <div className="ev-hit-row" key={hit.chunk_id}>
          <span className="ev-hit-rank">{index + 1}</span>
          <span className="ev-hit-main">
            <button
              type="button"
              className="ev-hit-text"
              style={{ border: 'none', background: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', font: 'inherit' }}
              onClick={() => onOpenPage({ docId: hit.doc_id, pageNo: hit.page_no, filename: hit.filename })}
              title={`${hit.chunk_id}\n点击打开 seekdb 中该页原文`}
            >
              {hit.text}
            </button>
            <span style={{ display: 'block', marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
              {hit.filename || hit.doc_id} · 第 {hit.page_no} 页 · {formatScore(hit.score)}{' '}
              {scoreKindLabel(hit.score_kind)}
              {hit.gate_passed ? ' · 通过门控' : ' · 未过门控'}
            </span>
          </span>
        </div>
      ))}
    </div>
  )
}

function SnapshotCards({ snapshot }: { snapshot: ProgressSnapshot }) {
  const blocks: { label: string; items: string[] }[] = [
    { label: '研究目标', items: snapshot.objective ? [snapshot.objective] : [] },
    { label: '已确认决策', items: snapshot.decisions ?? [] },
    { label: '已完成工作', items: snapshot.completed_work ?? [] },
    { label: '未解决问题', items: snapshot.open_questions ?? [] },
    { label: '下一步', items: snapshot.next_steps ?? [] },
  ].filter((block) => block.items.length > 0)

  return (
    <>
      {blocks.map((block) => (
        <div className="ev-mem-card" key={block.label}>
          <div className="ev-mem-label">{block.label}</div>
          <ul className="ev-mem-list">
            {block.items.map((item, index) => (
              <li key={index}>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {snapshot.key_evidence && snapshot.key_evidence.length > 0 ? (
        <div className="ev-mem-card">
          <div className="ev-mem-label">关键证据指针（指向 seekdb）</div>
          <ul className="ev-mem-list">
            {snapshot.key_evidence.map((item, index) => (
              <li key={index}>
                <span>
                  {item.filename || item.doc_id} 第 {item.page_no} 页 · <code>{item.chunk_id}</code>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
        快照 seq {snapshot.seq ?? '—'} · 更新于 {snapshot.updated_at ?? '—'} · confirmed_by{' '}
        {snapshot.confirmed_by ?? '—'}
      </p>
    </>
  )
}

function PreparedContextDetails({ context }: { context: PreparedContext }) {
  return (
    <details className="collapsible" style={{ marginTop: 'var(--s-2)' }}>
      <summary>召回细节 prepared_context</summary>
      <div className="meta-grid" style={{ marginTop: 'var(--s-2)' }}>
        <span className="meta-item">
          <span className="meta-key">status</span>
          <span className="meta-value mono">{context.status || '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">search_mode</span>
          <span className="meta-value mono">{context.search_mode || '—'}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">content_bytes</span>
          <span className="meta-value">{context.content_bytes}</span>
        </span>
        <span className="meta-item">
          <span className="meta-key">recall_query_expanded</span>
          <span className="meta-value">
            {context.recall_query_expanded ? '是（已用 ASCII 锚点扩展）' : '否'}
          </span>
        </span>
      </div>
      <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
        recall_query：<code>{context.recall_query}</code>
      </p>
      {context.search_hits.length > 0 ? (
        <ul className="citation-list" style={{ marginTop: 'var(--s-2)' }}>
          {context.search_hits.map((hit, index) => (
            <li className="ev-mem-card" key={`${hit.artifact_id}-${index}`} style={{ listStyle: 'none' }}>
              <div className="ev-mem-label">
                {memoryKindLabel(hit.kind)} · score {formatScore(hit.score)}
              </div>
              <div style={{ fontSize: 'var(--fs-sm)' }}>{hit.text}</div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-hint">
          search_memory 没有命中；完整记忆通过 list_memory_entries 全量读取，不依赖关键词搜索。
        </p>
      )}
      <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
        {context.note}
      </p>
    </details>
  )
}

/** 记忆区块：明确标注来源是 PowerContext，而不是文献原文证据。 */
export function MemoryPanelBody({ restored }: { restored: RestoreResponse }) {
  return (
    <>
      <div style={{ marginBottom: 'var(--s-3)' }}>
        <span className="recovered-pill">
          <Icon name="brain" size={13} />
          Recovered from memory · {restored.entry_count} 条
        </span>
      </div>
      {restored.resume_brief ? <pre className="memory-brief">{restored.resume_brief}</pre> : null}
      {restored.snapshot ? <SnapshotCards snapshot={restored.snapshot} /> : null}
      {restored.prepared_context ? <PreparedContextDetails context={restored.prepared_context} /> : null}
    </>
  )
}

export function MemoryUnavailable({ reason }: { reason?: string }) {
  return (
    <div className="banner banner-amber" role="status">
      PowerContext 当前不可用；文献检索与问答只依赖 seekdb，不受影响。
      {reason ? <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>原因：{reason}</span> : null}
    </div>
  )
}

export function QaMemorySection({ memory }: { memory: QaMemory }) {
  if (!('memory_available' in memory)) {
    return (
      <PanelSection title="研究记忆">
        <SourceTag source="powercontext" />
        <div style={{ height: 8 }} />
        <MemoryUnavailable reason={memory.error} />
      </PanelSection>
    )
  }
  const restored = memory as RestoreResponse
  if (!restored.memory_available) {
    return (
      <PanelSection title="研究记忆">
        <MemoryUnavailable reason={restored.error ?? undefined} />
      </PanelSection>
    )
  }
  return (
    <PanelSection title="研究记忆（随本次提问一并召回）" count={restored.entry_count}>
      <MemoryPanelBody restored={restored} />
      <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
        以上内容来自 PowerContext 历史记忆，不是文献原文证据。
      </p>
    </PanelSection>
  )
}
