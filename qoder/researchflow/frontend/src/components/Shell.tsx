import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { getHealth, type HealthResponse } from '../api/client'
import Icon, { type IconName } from './Icon'

type EvidenceState = 'open' | 'closed'
type SidebarState = 'open' | 'closed' | 'collapsed'
type Theme = 'light' | 'dark'

interface ShellValue {
  host: HTMLElement | null
  attachHost: (element: HTMLDivElement | null) => void
  evidence: EvidenceState
  setEvidence: (value: EvidenceState) => void
  toggleEvidence: () => void
  sidebar: SidebarState
  setSidebar: (value: SidebarState) => void
  theme: Theme
  toggleTheme: () => void
  /** 当前研究项目（侧栏与工作台共用同一个选择，跨页保持连续）。 */
  project: string
  setProject: (id: string) => void
  title: string
  setTitle: (title: string) => void
  subtitle: string
  setSubtitle: (subtitle: string) => void
  /** 单一 /api/health 轮询，供侧栏、首页与验证页共用。 */
  health: HealthResponse | null
  healthDown: boolean
  healthLoading: boolean
  refreshHealth: () => void
}

const ShellContext = createContext<ShellValue | null>(null)

const THEME_KEY = 'rf-theme'
const PROJECT_KEY = 'rf-project'
const HEALTH_POLL_MS = 20000

function initialTheme(): Theme {
  const stored = window.localStorage.getItem(THEME_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [host, setHost] = useState<HTMLElement | null>(null)
  const [evidence, setEvidence] = useState<EvidenceState>(() =>
    window.innerWidth <= 1240 ? 'closed' : 'open'
  )
  const [sidebar, setSidebar] = useState<SidebarState>(() => (window.innerWidth <= 900 ? 'closed' : 'open'))
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [project, setProject] = useState<string>(window.localStorage.getItem(PROJECT_KEY) ?? '')
  const [title, setTitle] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthDown, setHealthDown] = useState(false)
  const [healthLoading, setHealthLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await getHealth()
        if (cancelled) return
        setHealth(data)
        setHealthDown(false)
      } catch {
        if (cancelled) return
        setHealth(null)
        setHealthDown(true)
      } finally {
        if (!cancelled) setHealthLoading(false)
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), HEALTH_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const refreshHealth = useCallback(() => {
    setHealthLoading(true)
    getHealth()
      .then((data) => {
        setHealth(data)
        setHealthDown(false)
      })
      .catch(() => {
        setHealth(null)
        setHealthDown(true)
      })
      .finally(() => setHealthLoading(false))
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (project) window.localStorage.setItem(PROJECT_KEY, project)
    else window.localStorage.removeItem(PROJECT_KEY)
  }, [project])

  // 侧栏在三段布局与移动端抽屉之间切换时，收起态只应作用于桌面宽度。
  useEffect(() => {
    const wide = window.matchMedia('(min-width: 901px)')
    const sync = () => setSidebar((current) => (current === 'open' && !wide.matches ? 'closed' : current))
    sync()
    wide.addEventListener('change', sync)
    return () => wide.removeEventListener('change', sync)
  }, [])

  const attachHost = useCallback(
    (element: HTMLDivElement | null) => setHost((current) => (current === element ? current : element)),
    []
  )

  const toggleEvidence = useCallback(
    () => setEvidence((current) => (current === 'open' ? 'closed' : 'open')),
    []
  )

  const toggleTheme = useCallback(() => setTheme((current) => (current === 'light' ? 'dark' : 'light')), [])

  const value = useMemo<ShellValue>(
    () => ({
      host,
      attachHost,
      evidence,
      setEvidence,
      toggleEvidence,
      sidebar,
      setSidebar,
      theme,
      toggleTheme,
      project,
      setProject,
      title,
      setTitle,
      subtitle,
      setSubtitle,
      health,
      healthDown,
      healthLoading,
      refreshHealth,
    }),
    [
      host,
      attachHost,
      evidence,
      toggleEvidence,
      sidebar,
      theme,
      toggleTheme,
      project,
      title,
      subtitle,
      health,
      healthDown,
      healthLoading,
      refreshHealth,
    ]
  )

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell(): ShellValue {
  const value = useContext(ShellContext)
  if (!value) throw new Error('useShell 必须在 ShellProvider 内使用')
  return value
}

/** 页面声明顶栏标题；离开页面时清空，回落到路由默认标题。 */
export function useShellHeader(title: string, subtitle = ''): void {
  const shell = useShell()
  const { setTitle, setSubtitle } = shell
  useEffect(() => {
    setTitle(title)
    setSubtitle(subtitle)
    return () => {
      setTitle('')
      setSubtitle('')
    }
  }, [title, subtitle, setTitle, setSubtitle])
}

/** 页面把内容注入右侧 Evidence / Context 栏（桌面常驻列，<=1240px 变抽屉）。 */
export function EvidenceSlot({ children }: { children: ReactNode }) {
  const { host } = useShell()
  if (!host) return null
  return createPortal(<div className="rise">{children}</div>, host)
}

export function PanelSection({
  title,
  count,
  action,
  children,
}: {
  title: string
  count?: number | string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="ev-block">
      <div className="ev-block-title">
        <span>{title}</span>
        {count !== undefined ? <span>{count}</span> : null}
        {action}
      </div>
      {children}
    </section>
  )
}

export function IconButton({
  icon,
  label,
  onClick,
  active = false,
  className = '',
}: {
  icon: IconName
  label: string
  onClick: () => void
  active?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      className={`btn btn-icon btn-ghost ${className}`.trim()}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
    >
      <Icon name={icon} />
    </button>
  )
}
