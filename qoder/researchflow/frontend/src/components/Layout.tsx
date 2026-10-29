import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import { IconButton, useShell } from './Shell'
import '../styles/shell.css'

const FALLBACK_TITLES: Record<string, string> = {
  '/': '开始一个新问题',
  '/workbench': '研究对话',
  '/knowledge': '知识库',
  '/memory': '研究进度',
  '/verification': '验证记录',
  '/architecture': '架构与接口',
}

export default function Layout() {
  const shell = useShell()
  const location = useLocation()
  const heading = shell.title || FALLBACK_TITLES[location.pathname] || 'ResearchFlow'

  // 抽屉形态下 Esc 负责关闭；页面原文查看器自己处理 Esc，不能让一次按键同时关掉两层。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (document.querySelector('.page-viewer-overlay')) return
      if (shell.sidebar === 'open' && window.innerWidth <= 900) shell.setSidebar('closed')
      else if (shell.evidence === 'open' && window.innerWidth <= 1240) shell.setEvidence('closed')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shell])

  // 切换路由时收起抽屉，避免下一层内容仍被上一路由的面板遮住。
  useEffect(() => {
    if (window.innerWidth <= 900) shell.setSidebar('closed')
    if (window.innerWidth <= 1240) shell.setEvidence('closed')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  return (
    <div className="app-shell" data-sidebar={shell.sidebar} data-evidence={shell.evidence}>
      <Sidebar />

      <div className="main-column">
        <header className="topbar">
          <IconButton
            icon="menu"
            label="打开侧边栏"
            className="menu-btn"
            onClick={() => shell.setSidebar('open')}
          />
          <div className="topbar-title">
            <strong>{heading}</strong>
            {shell.subtitle ? <span>{shell.subtitle}</span> : null}
          </div>
          <div className="topbar-actions">
            <IconButton
              icon="panelRight"
              label={shell.evidence === 'open' ? '收起证据面板' : '展开证据面板'}
              active={shell.evidence === 'open'}
              onClick={shell.toggleEvidence}
            />
            <IconButton
              icon={shell.theme === 'light' ? 'moon' : 'sun'}
              label={shell.theme === 'light' ? '切换到深色主题' : '切换到浅色主题'}
              onClick={shell.toggleTheme}
            />
          </div>
        </header>

        <main className="view">
          <Outlet />
        </main>
      </div>

      <aside className="evidence" aria-label="证据与上下文面板">
        <div className="evidence-head">
          <h2>Evidence / Context</h2>
          <IconButton
            icon="close"
            label="收起证据面板"
            className="evidence-close"
            onClick={shell.toggleEvidence}
          />
        </div>
        <div className="evidence-body scroll-thin" ref={shell.attachHost} />
      </aside>

      {shell.evidence === 'open' ? (
        <div className="overlay overlay-evidence" onClick={shell.toggleEvidence} aria-hidden="true" />
      ) : null}
      {shell.sidebar === 'open' ? (
        <div className="overlay overlay-sidebar" onClick={() => shell.setSidebar('closed')} aria-hidden="true" />
      ) : null}
    </div>
  )
}
