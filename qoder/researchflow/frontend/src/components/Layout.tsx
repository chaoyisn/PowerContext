import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { getHealth, type HealthResponse } from '../api/client'
import { describeError } from '../api/client'
import { StatusDot } from './common'
import './Layout.css'

const NAV_ITEMS = [
  { to: '/', label: '项目总览', end: true },
  { to: '/knowledge', label: '知识库', end: false },
  { to: '/workbench', label: 'AI 工作台', end: false },
  { to: '/memory', label: '任务记忆', end: false },
]

const HEALTH_POLL_MS = 20000

export default function Layout() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  const loadHealth = useCallback(async () => {
    try {
      const data = await getHealth()
      setHealth(data)
      setHealthError(null)
    } catch (err) {
      setHealth(null)
      setHealthError(describeError(err).message)
    }
  }, [])

  useEffect(() => {
    void loadHealth()
    const timer = window.setInterval(() => void loadHealth(), HEALTH_POLL_MS)
    return () => window.clearInterval(timer)
  }, [loadHealth])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-name">ResearchFlow</span>
          <span className="brand-sub">科研知识与任务连续性助手</span>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          <ul>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className={({ isActive }) => (isActive ? 'nav-link nav-link-active' : 'nav-link')}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-legend">
          <div className="legend-title">两个独立后端</div>
          <span className="source-tag source-tag-seekdb">文献证据 · seekdb</span>
          <span className="source-tag source-tag-powercontext">历史记忆 · PowerContext</span>
          <p className="legend-note">记忆永远单独标注，不会被当作原文证据展示。</p>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <HealthStrip health={health} error={healthError} onRetry={() => void loadHealth()} />
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function HealthStrip({
  health,
  error,
  onRetry,
}: {
  health: HealthResponse | null
  error: string | null
  onRetry: () => void
}) {
  if (error) {
    return (
      <div className="topbar-health" role="status">
        <span className="health-item health-item-bad" title={error}>
          <StatusDot level="red" label="后端未连接" />
          后端未连接
        </span>
        <span className="health-error-text">{error}</span>
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          重试
        </button>
      </div>
    )
  }
  if (!health) {
    return (
      <div className="topbar-health" role="status">
        <span className="health-item">
          <StatusDot level="grey" label="正在检测后端" />
          正在检测后端状态…
        </span>
      </div>
    )
  }

  const seekdb = health.components.seekdb
  const pc = health.components.powercontext
  const llm = health.components.llm

  return (
    <div className="topbar-health" role="status" aria-label="后端实时健康状态">
      <span
        className={seekdb.available ? 'health-item' : 'health-item health-item-bad'}
        title={
          seekdb.available
            ? `${seekdb.endpoint ?? ''} · ${seekdb.server_version ?? ''} · 文档 ${seekdb.counts?.documents ?? '—'} / 页 ${seekdb.counts?.pages ?? '—'} / chunks ${seekdb.counts?.chunks ?? '—'}`
            : seekdb.error ?? 'seekdb 不可用'
        }
      >
        <StatusDot level={seekdb.available ? 'green' : 'red'} />
        seekdb{seekdb.available ? '' : ' 不可用'}
      </span>
      <span
        className={pc.available ? 'health-item' : 'health-item health-item-bad'}
        title={pc.available ? `${pc.url ?? ''} · v${pc.package_version ?? '?'}` : pc.error ?? 'PowerContext 不可用'}
      >
        <StatusDot level={pc.available ? 'green' : 'red'} />
        PowerContext{pc.available ? '' : ' 不可用'}
      </span>
      <span
        className={llm.enabled ? 'health-item' : 'health-item health-item-warn'}
        title={llm.enabled ? `${llm.model} @ ${llm.base_url}` : llm.reason ?? 'LLM 未配置'}
      >
        <StatusDot level={llm.enabled ? 'green' : 'amber'} />
        LLM {llm.enabled ? llm.model : '未配置'}
      </span>
      <span className={`health-overall health-overall-${health.status}`}>
        {health.status === 'ok' ? '整体正常' : '整体降级'}
      </span>
    </div>
  )
}
