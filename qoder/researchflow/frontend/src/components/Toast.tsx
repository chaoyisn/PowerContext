import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { describeError } from '../api/client'
import './Toast.css'

export interface ToastInput {
  kind: 'error' | 'success' | 'info'
  title: string
  message?: string
  requestId?: string
}

interface ToastItem extends ToastInput {
  id: number
}

type PushToast = (toast: ToastInput) => void

const ToastContext = createContext<PushToast>(() => undefined)

/** 在任意组件里推送全局 toast。 */
export function useToast(): PushToast {
  return useContext(ToastContext)
}

/** 把未知异常转成 error toast（含 request_id，便于对照后端日志）。 */
export function useErrorToast(): (err: unknown, title?: string) => void {
  const push = useToast()
  return useCallback(
    (err: unknown, title?: string) => {
      const described = describeError(err)
      push({
        kind: 'error',
        title: title ?? described.title,
        message: described.message,
        requestId: described.requestId,
      })
    },
    [push]
  )
}

const AUTO_DISMISS_MS = 9000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = useCallback<PushToast>((toast) => {
    const id = nextId.current++
    setToasts((current) => [...current.slice(-4), { ...toast, id }])
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-region" role="region" aria-label="全局通知">
        <div aria-live="polite" aria-atomic="false" className="toast-list">
          {toasts.map((toast) => (
            <ToastRow key={toast.id} toast={toast} onDismiss={dismiss} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  )
}

function ToastRow({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(toast.id), AUTO_DISMISS_MS)
    return () => window.clearTimeout(timer)
  }, [toast.id, onDismiss])

  return (
    <div className={`toast toast-${toast.kind}`}>
      <div className="toast-content">
        <div className="toast-title">{toast.title}</div>
        {toast.message ? <div className="toast-message">{toast.message}</div> : null}
        {toast.requestId ? (
          <div className="toast-request-id">request_id: {toast.requestId}</div>
        ) : null}
      </div>
      <button
        type="button"
        className="toast-close"
        aria-label="关闭通知"
        onClick={() => onDismiss(toast.id)}
      >
        ×
      </button>
    </div>
  )
}
