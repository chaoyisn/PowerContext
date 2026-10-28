import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getPage, type PageDetail } from '../api/client'
import { ErrorState, LoadingState, SourceTag } from './common'
import './PageViewer.css'

export interface PageViewerTarget {
  docId: string
  pageNo: number
  filename?: string
}

/**
 * 页面原文查看器：展示 seekdb 中存储的某一物理页的原文。
 * 404 表示该页不存在 —— 直接呈现服务端的 error.message 与 detail.page_count，绝不显示笼统失败。
 */
export default function PageViewer({
  target,
  onClose,
}: {
  target: PageViewerTarget
  onClose: () => void
}) {
  const [page, setPage] = useState<PageDetail | null>(null)
  const [error, setError] = useState<unknown | null>(null)
  const [loading, setLoading] = useState(true)
  const closeRef = useRef<HTMLButtonElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getPage(target.docId, target.pageNo)
      setPage(data)
    } catch (err) {
      setPage(null)
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [target.docId, target.pageNo])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const notFoundDetail =
    error instanceof ApiError && error.status === 404
      ? {
          pageCount: typeof error.detail.page_count === 'number' ? error.detail.page_count : null,
          requestedPage:
            typeof error.detail.requested_page === 'number' ? error.detail.requested_page : null,
        }
      : null

  return (
    <div
      className="page-viewer-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="page-viewer-dialog" role="dialog" aria-modal="true" aria-label={`第 ${target.pageNo} 页原文`}>
        <div className="page-viewer-header">
          <div className="page-viewer-title">
            <span>页面原文 · 第 {target.pageNo} 页</span>
            <SourceTag source="seekdb" />
          </div>
          <button type="button" className="btn btn-sm" ref={closeRef} onClick={onClose} aria-label="关闭页面查看器">
            关闭（Esc）
          </button>
        </div>
        <div className="page-viewer-meta">
          <span className="meta-item">
            <span className="meta-key">文件名</span>
            <span className="meta-value">{page?.filename ?? target.filename ?? '—'}</span>
          </span>
          <span className="meta-item">
            <span className="meta-key">doc_id</span>
            <span className="meta-value mono">{target.docId}</span>
          </span>
        </div>
        <div className="page-viewer-body">
          {loading ? <LoadingState text="正在从 seekdb 读取页面原文…" /> : null}
          {!loading && error ? (
            <div className="page-viewer-error">
              <ErrorState error={error} onRetry={() => void load()} retryLabel="重试" />
              {notFoundDetail ? (
                <div className="page-notfound-extra">
                  该文档共 <strong>{notFoundDetail.pageCount ?? '—'}</strong> 页，请求的页码为{' '}
                  <strong>{notFoundDetail.requestedPage ?? target.pageNo}</strong>
                  。页码来自文档解析时的真实物理页，系统不会合成不存在的页。
                </div>
              ) : null}
            </div>
          ) : null}
          {!loading && page ? (
            <>
              <div className="page-viewer-facts">
                <span className="meta-item">
                  <span className="meta-key">page_id</span>
                  <span className="meta-value mono">{page.page_id}</span>
                </span>
                <span className="meta-item">
                  <span className="meta-key">char_count</span>
                  <span className="meta-value">{page.char_count}</span>
                </span>
                <span className="meta-item">
                  <span className="meta-key">content_type</span>
                  <span className="meta-value">{page.content_type || '—'}</span>
                </span>
                {page.is_empty ? <span className="badge badge-amber">空白页（保留页级身份）</span> : null}
              </div>
              {page.is_empty ? (
                <div className="page-viewer-empty">
                  此页在原始文档中物理存在但没有可提取文本。页级身份（page_id / page_no）已保留，
                  因此引用该系统页码时不会发生错位。
                </div>
              ) : (
                <pre className="page-viewer-content">{page.content}</pre>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}
