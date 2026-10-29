import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { createProject, listProjects, type Project } from '../api/client'
import Icon, { type IconName } from './Icon'
import { IconButton, useShell } from './Shell'
import { clearSessions, loadSessions, removeSession, type ChatSession } from '../state/sessions'
import { useErrorToast, useToast } from './Toast'

const NAV: { to: string; label: string; icon: IconName; aliases?: string[] }[] = [
  { to: '/', label: 'Chat 对话', icon: 'chat', aliases: ['/workbench'] },
  { to: '/knowledge', label: 'Knowledge 文献', icon: 'book' },
  { to: '/memory', label: 'Memory 研究进度', icon: 'brain' },
  { to: '/verification', label: 'Verification 验证', icon: 'shield' },
  { to: '/architecture', label: 'Docs 架构与接口', icon: 'docs' },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const shell = useShell()
  const toast = useToast()
  const toastError = useErrorToast()

  const health = shell.health
  const healthDown = shell.healthDown

  const [projects, setProjects] = useState<Project[]>([])
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions())
  const [creating, setCreating] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [saving, setSaving] = useState(false)

  const refreshProjects = useCallback(async () => {
    try {
      const data = await listProjects()
      setProjects(data.projects)
    } catch {
      setProjects([])
    }
  }, [])

  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects])

  // 其他页面（知识库上传、记忆保存）会改变后端状态，路由切换时轻量刷新。
  useEffect(() => {
    void refreshProjects()
    setSessions(loadSessions())
  }, [location.pathname, refreshProjects])

  const submitProject = async (event: FormEvent) => {
    event.preventDefault()
    if (!draftTitle.trim()) return
    setSaving(true)
    try {
      const created = await createProject({ title: draftTitle.trim() })
      setDraftTitle('')
      setCreating(false)
      shell.setProject(created.project_id)
      toast({
        kind: 'success',
        title: '研究项目已创建',
        message: created.memory_bound
          ? `${created.project_id} · 已绑定 PowerContext scope`
          : `${created.project_id} · PowerContext 暂不可用，scope 将在下次保存时绑定`,
      })
      await refreshProjects()
    } catch (err) {
      toastError(err, '创建项目失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="sidebar" aria-label="侧边栏">
      <div className="sidebar-head">
        <span className="brand-mark" aria-hidden="true">
          R
        </span>
        <span className="brand-block">
          <span className="brand-name">ResearchFlow</span>
          <span className="brand-sub">seekdb + PowerContext</span>
        </span>
        <IconButton
          className="sidebar-collapse"
          icon="chevronLeft"
          label="收起侧边栏"
          onClick={() => shell.setSidebar('collapsed')}
        />
      </div>

      <div className="sidebar-scroll scroll-thin">
        {shell.sidebar === 'collapsed' ? (
          <IconButton
            icon="chevronRight"
            label="展开侧边栏"
            onClick={() => shell.setSidebar('open')}
            className="sidebar-expand"
          />
        ) : (
          <button
            type="button"
            className="new-chat"
            onClick={() => {
              navigate('/')
              shell.setSidebar(window.innerWidth <= 900 ? 'closed' : shell.sidebar)
            }}
          >
            <Icon name="plus" size={16} />
            <span className="nav-label new-chat-label">新会话</span>
          </button>
        )}

        <nav className="sidebar-nav" aria-label="主导航">
          <ul>
            {NAV.map((item) => {
              const active =
                location.pathname === item.to || (item.aliases ?? []).includes(location.pathname)
              return (
                <li key={item.to}>
                  <button
                    type="button"
                    className={active ? 'nav-item nav-item-active' : 'nav-item'}
                    onClick={() => {
                      navigate(item.to)
                      if (window.innerWidth <= 900) shell.setSidebar('closed')
                    }}
                    aria-current={active ? 'page' : undefined}
                  >
                    <Icon name={item.icon} size={17} />
                    <span className="nav-label">{item.label}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        {shell.sidebar !== 'collapsed' ? (
          <>
            <section className="sidebar-section">
              <div className="sidebar-section-head">
                <span>研究项目 · seekdb</span>
                <button
                  type="button"
                  className="chip"
                  style={{ padding: '1px 8px' }}
                  onClick={() => setCreating((current) => !current)}
                  aria-expanded={creating}
                >
                  <Icon name="plus" size={12} />
                  新建
                </button>
              </div>
              {creating ? (
                <form className="side-new-form" onSubmit={submitProject}>
                  <label className="visually-hidden" htmlFor="sidebar-project-title">
                    新研究项目标题
                  </label>
                  <input
                    id="sidebar-project-title"
                    className="input"
                    value={draftTitle}
                    maxLength={256}
                    placeholder="例如：混合检索在知识库的召回评测"
                    onChange={(event) => setDraftTitle(event.target.value)}
                  />
                  <div className="form-row">
                    <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
                      {saving ? '创建中…' : '创建并选中'}
                    </button>
                    <button type="button" className="btn btn-sm" onClick={() => setCreating(false)}>
                      取消
                    </button>
                  </div>
                </form>
              ) : null}
              {projects.length === 0 ? (
                <p className="side-empty">还没有研究项目，新建一个才能把进度存进 PowerContext。</p>
              ) : (
                <ul className="side-list">
                  {projects.map((project) => (
                    <li key={project.project_id}>
                      <button
                        type="button"
                        className={
                          project.project_id === shell.project
                            ? 'side-row side-row-active'
                            : 'side-row'
                        }
                        onClick={() => shell.setProject(project.project_id)}
                        aria-pressed={project.project_id === shell.project}
                        title={project.objective || project.project_id}
                      >
                        <span className="side-row-title">{project.title || project.project_id}</span>
                        {!project.scope_id ? (
                          <span className="side-row-sub">未绑定记忆空间，下次保存时补绑</span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="sidebar-section">
              <div className="sidebar-section-head">
                <span>最近会话 · 本机</span>
                {sessions.length > 0 ? (
                  <button
                    type="button"
                    className="chip"
                    style={{ padding: '1px 8px' }}
                    onClick={() => setSessions(clearSessions())}
                  >
                    清空
                  </button>
                ) : null}
              </div>
              {sessions.length === 0 ? (
                <p className="side-empty">还没有会话。记录只存在这台浏览器里，最多 12 条。</p>
              ) : (
                <ul className="side-list">
                  {sessions.map((session) => (
                    <li key={session.id}>
                      <button
                        type="button"
                        className="side-row"
                        onClick={() => {
                          navigate(`/workbench?s=${encodeURIComponent(session.id)}`)
                          if (window.innerWidth <= 900) shell.setSidebar('closed')
                        }}
                      >
                        <span className="side-row-title">{session.title || session.exchanges[0]?.question}</span>
                        <span className="side-row-sub">
                          {session.exchanges.length} 轮 · {formatRelative(session.updatedAt)}
                        </span>
                      </button>
                      <button
                        type="button"
                        className="side-row-delete"
                        aria-label={`删除会话 ${session.title}`}
                        onClick={() => setSessions(removeSession(session.id))}
                      >
                        <Icon name="close" size={12} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}
      </div>

      <div className="sidebar-foot">
        <div className="health-chips">
          {health ? (
            <>
              <HealthChip
                ok={health.components.seekdb.available}
                label="seekdb"
                detail={
                  health.components.seekdb.available
                    ? `${health.components.seekdb.counts?.documents ?? '—'} 文档 · ${
                        health.components.seekdb.counts?.pages ?? '—'
                      } 页 · ${health.components.seekdb.counts?.chunks ?? '—'} chunks`
                    : health.components.seekdb.error ?? '不可用'
                }
              />
              <HealthChip
                ok={health.components.powercontext.available}
                label="PowerContext"
                detail={
                  health.components.powercontext.available
                    ? `v${health.components.powercontext.package_version ?? '?'}`
                    : health.components.powercontext.error ?? '不可用'
                }
              />
              <HealthChip
                ok={health.components.llm.enabled}
                warn={!health.components.llm.enabled}
                label={health.components.llm.enabled ? health.components.llm.model : 'LLM 未配置'}
                detail={health.components.llm.enabled ? health.components.llm.base_url : health.components.llm.reason ?? '未配置'}
              />
            </>
          ) : (
            <span className={`health-chip ${healthDown ? 'health-chip-bad' : ''}`}>
              {healthDown ? '后端未连接' : '正在检测后端…'}
            </span>
          )}
        </div>
      </div>
    </aside>
  )
}

function HealthChip({
  ok,
  warn = false,
  label,
  detail,
}: {
  ok: boolean
  warn?: boolean
  label: string
  detail: string
}) {
  const className = ok ? 'health-chip' : warn ? 'health-chip health-chip-warn' : 'health-chip health-chip-bad'
  return (
    <span className={className} title={detail}>
      <span className={`dot ${ok ? 'dot-green' : warn ? 'dot-amber' : 'dot-red'}`} />
      {label}
    </span>
  )
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.round(hours / 24)} 天前`
}
