import type { AskResponse, RetrievalMode, RetrievalResult } from '../api/client'

/**
 * 本机会话记录：存在浏览器 localStorage，不是后端数据。
 * 保存的是真实 API 返回原文，重新打开时按同一份响应回放，不重新生成、不伪造。
 */

export type Exchange = {
  question: string
  askedAt: string
} & (
  | { kind: 'qa'; response: AskResponse }
  /** 「仅检索」模式没有后端问答接口，直接回放 /api/retrieval/search 的真实结果。 */
  | { kind: 'retrieval'; response: RetrievalResult }
)

export interface ChatSession {
  id: string
  title: string
  projectId: string
  mode: RetrievalMode
  createdAt: string
  updatedAt: string
  exchanges: Exchange[]
}

const STORAGE_KEY = 'rf-sessions'
const MAX_SESSIONS = 12
const MAX_EXCHANGES = 8

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 只做结构自检：localStorage 可能被旧版本或其他应用污染。 */
function looksLikeSession(value: unknown): value is ChatSession {
  if (!isRecord(value)) return false
  return (
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    Array.isArray(value.exchanges) &&
    value.exchanges.every(
      (item) => isRecord(item) && typeof item.question === 'string' && isRecord(item.response)
    )
  )
}

export function loadSessions(): ChatSession[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(looksLikeSession)
  } catch {
    return []
  }
}

function persist(sessions: ChatSession[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  } catch {
    // 容量写满时放弃持久化：会话仍存在于内存，不应打断提问。
  }
}

export function saveExchange(
  session: ChatSession,
  exchange: Exchange
): ChatSession[] {
  const now = new Date().toISOString()
  const merged: ChatSession = {
    ...session,
    title: session.title || exchange.question.slice(0, 46),
    updatedAt: now,
    exchanges: [...session.exchanges, exchange].slice(-MAX_EXCHANGES),
  }
  const next = [merged, ...loadSessions().filter((item) => item.id !== merged.id)].slice(0, MAX_SESSIONS)
  persist(next)
  return next
}

export function removeSession(id: string): ChatSession[] {
  const next = loadSessions().filter((item) => item.id !== id)
  persist(next)
  return next
}

export function clearSessions(): ChatSession[] {
  persist([])
  return []
}

export function getSession(id: string): ChatSession | null {
  return loadSessions().find((item) => item.id === id) ?? null
}

export function createDraft(projectId: string, mode: RetrievalMode): ChatSession {
  const now = new Date().toISOString()
  return {
    id: `local-${now.slice(0, 19).replace(/[-:T]/g, '')}-${Math.random().toString(36).slice(2, 7)}`,
    title: '',
    projectId,
    mode,
    createdAt: now,
    updatedAt: now,
    exchanges: [],
  }
}
