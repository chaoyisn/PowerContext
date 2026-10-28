import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createProject,
  getHealth,
  getProject,
  listProjects,
  type HealthResponse,
  type Project,
  type ProjectDetail,
} from '../api/client'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  SourceTag,
  StatusDot,
  formatTimestamp,
} from '../components/common'
import { useErrorToast, useToast } from '../components/Toast'
import './OverviewPage.css'

export default function OverviewPage() {
  const toast = useToast()
  const toastError = useErrorToast()

  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<unknown | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)

  const [projects, setProjects] = useState<Project[]>([])
  const [projectsError, setProjectsError] = useState<unknown | null>(null)
  const [projectsLoading, setProjectsLoading] = useState(true)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [detailError, setDetailError] = useState<unknown | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadHealth = useCallback(async () => {
    setHealthLoading(true)
    try {
      setHealth(await getHealth())
      setHealthError(null)
    } catch (err) {
      setHealth(null)
      setHealthError(err)
    } finally {
      setHealthLoading(false)
    }
  }, [])

  const loadProjects = useCallback(async () => {
    setProjectsLoading(true)
    try {
      const data = await listProjects()
      setProjects(data.projects)
      setProjectsError(null)
    } catch (err) {
      setProjects([])
      setProjectsError(err)
    } finally {
      setProjectsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadHealth()
    void loadProjects()
  }, [loadHealth, loadProjects])

  const loadDetail = useCallback(
    async (projectId: string) => {
      setDetailLoading(true)
      try {
        setDetail(await getProject(projectId))
        setDetailError(null)
      } catch (err) {
        setDetail(null)
        setDetailError(err)
        toastError(err, '加载项目详情失败')
      } finally {
        setDetailLoading(false)
      }
    },
    [toastError]
  )

  const selectProject = (projectId: string) => {
    setSelectedId(projectId)
    void loadDetail(projectId)
  }

  return (
    <div>
      <div className="page-title-row">
        <h1>项目总览</h1>
      </div>
      <p className="page-desc">
        项目注册表存于 seekdb（即使 PowerContext 断开也能列出），任务记忆存于
        PowerContext。点击项目卡片查看合并后的记忆概览与续研简报。
      </p>

      <HealthPanel health={health} error={healthError} loading={healthLoading} onRetry={() => void loadHealth()} />

      <CreateProjectForm
        onCreated={(project) => {
          toast({
            kind: 'success',
            title: '项目已创建',
            message: project.memory_bound
              ? `${project.project_id}（已绑定 PowerContext scope：${project.scope_id ?? '—'}）`
              : `${project.project_id}（PowerContext 暂不可用，scope 将在下次保存/恢复时绑定）`,
          })
          void loadProjects()
          selectProject(project.project_id)
        }}
        onError={toastError}
      />

      <Panel
        title="项目列表"
        subtitle={`共 ${projects.length} 个`}
        tags={<SourceTag source="seekdb" />}
        actions={
          <button type="button" className="btn btn-sm" onClick={() => void loadProjects()}>
            刷新
          </button>
        }
      >
        {projectsLoading ? <LoadingState text="正在加载项目列表…" /> : null}
        {!projectsLoading && projectsError ? (
          <ErrorState error={projectsError} onRetry={() => void loadProjects()} />
        ) : null}
        {!projectsLoading && !projectsError && projects.length === 0 ? (
          <EmptyState text="还没有项目。用上方表单创建第一个研究项目。" />
        ) : null}
        {!projectsLoading && !projectsError && projects.length > 0 ? (
          <ul className="project-grid">
            {projects.map((project) => (
              <li key={project.project_id}>
                <button
                  type="button"
                  className={
                    project.project_id === selectedId
                      ? 'project-card project-card-selected'
                      : 'project-card'
                  }
                  onClick={() => selectProject(project.project_id)}
                  aria-pressed={project.project_id === selectedId}
                >
                  <span className="project-card-title">{project.title || project.project_id}</span>
                  <span className="project-card-id mono">{project.project_id}</span>
                  {project.objective ? (
                    <span className="project-card-objective">{project.objective}</span>
                  ) : null}
                  <span className="project-card-meta">
                    <span>
                      scope_id：
                      {project.scope_id ? <code>{project.scope_id}</code> : <em>未绑定</em>}
                    </span>
                    <span>更新于 {formatTimestamp(project.updated_at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      {selectedId ? (
        <ProjectDetailPanel
          projectId={selectedId}
          detail={detail}
          error={detailError}
          loading={detailLoading}
          onRetry={() => void loadDetail(selectedId)}
        />
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------- 健康面板

function HealthPanel({
  health,
  error,
  loading,
  onRetry,
}: {
  health: HealthResponse | null
  error: unknown | null
  loading: boolean
  onRetry: () => void
}) {
  if (loading) {
    return (
      <Panel title="后端健康状态">
        <LoadingState text="正在检测 seekdb / PowerContext / LLM / Embedding…" />
      </Panel>
    )
  }
  if (error || !health) {
    return (
      <Panel title="后端健康状态" actions={<RetryButton onClick={onRetry} />}>
        <ErrorState error={error ?? new Error('健康检查无结果')} onRetry={onRetry} />
      </Panel>
    )
  }

  const { seekdb, powercontext, llm, embedding } = health.components
  const embeddingIsFallback = embedding.provider === 'hashing'

  return (
    <Panel
      title="后端健康状态"
      subtitle={`整体：${health.status === 'ok' ? '正常' : '降级'}`}
      actions={<RetryButton onClick={onRetry} />}
    >
      {!health.capabilities.qa_generates_answers ? (
        <div className="banner banner-amber" role="status">
          <StatusDot level="amber" />
          未配置 LLM，问答将进入仅检索模式（{llm.reason ?? '原因未知'}）。检索、引用与任务记忆功能不受影响。
        </div>
      ) : null}
      <div className="health-grid">
        <div className="health-card">
          <div className="health-card-head">
            <StatusDot level={seekdb.available ? 'green' : 'red'} />
            <strong>seekdb</strong>
            <span className="health-card-role">文献证据存储</span>
          </div>
          {seekdb.available ? (
            <dl className="health-card-body">
              <div>
                <dt>server_version</dt>
                <dd className="mono">{seekdb.server_version ?? '—'}</dd>
              </div>
              <div>
                <dt>endpoint</dt>
                <dd className="mono">
                  {seekdb.endpoint ?? '—'} / {seekdb.database ?? '—'}
                </dd>
              </div>
              <div>
                <dt>全文分析器</dt>
                <dd className="mono">{seekdb.fts_analyzer ?? '—'}</dd>
              </div>
              <div>
                <dt>数据量</dt>
                <dd>
                  文档 {seekdb.counts?.documents ?? '—'} · 页 {seekdb.counts?.pages ?? '—'} · chunks{' '}
                  {seekdb.counts?.chunks ?? '—'} · 项目 {seekdb.counts?.projects ?? '—'}
                </dd>
              </div>
              <div>
                <dt>延迟</dt>
                <dd>{seekdb.latency_ms ?? '—'} ms</dd>
              </div>
            </dl>
          ) : (
            <div className="health-card-error">{seekdb.error ?? 'seekdb 不可用'}</div>
          )}
        </div>

        <div className="health-card">
          <div className="health-card-head">
            <StatusDot level={powercontext.available ? 'green' : 'red'} />
            <strong>PowerContext</strong>
            <span className="health-card-role">任务记忆存储</span>
          </div>
          {powercontext.available ? (
            <dl className="health-card-body">
              <div>
                <dt>package_version</dt>
                <dd className="mono">{powercontext.package_version ?? '—'}</dd>
              </div>
              <div>
                <dt>url</dt>
                <dd className="mono">{powercontext.url ?? '—'}</dd>
              </div>
              <div>
                <dt>liveness / readiness</dt>
                <dd className="mono">
                  {powercontext.liveness ?? '—'} / {powercontext.readiness ?? '—'}
                </dd>
              </div>
              <div>
                <dt>延迟</dt>
                <dd>{powercontext.latency_ms ?? '—'} ms</dd>
              </div>
            </dl>
          ) : (
            <div className="health-card-error">
              {powercontext.error ?? 'PowerContext 不可用'}
              <div className="health-card-note">文献检索与问答只依赖 seekdb，不受影响。</div>
            </div>
          )}
        </div>

        <div className="health-card">
          <div className="health-card-head">
            <StatusDot level={llm.enabled ? 'green' : 'amber'} />
            <strong>LLM</strong>
            <span className="health-card-role">证据问答生成</span>
          </div>
          {llm.enabled ? (
            <dl className="health-card-body">
              <div>
                <dt>model</dt>
                <dd className="mono">{llm.model}</dd>
              </div>
              <div>
                <dt>base_url</dt>
                <dd className="mono">{llm.base_url}</dd>
              </div>
              <div>
                <dt>provider</dt>
                <dd>{llm.provider}</dd>
              </div>
            </dl>
          ) : (
            <div className="health-card-error health-card-warn">
              {llm.reason ?? 'LLM 未启用'}
              <div className="health-card-note">问答将进入「仅检索模式」，只返回原始证据，不生成回答。</div>
            </div>
          )}
        </div>

        <div className="health-card">
          <div className="health-card-head">
            <StatusDot level={embeddingIsFallback ? 'amber' : 'green'} />
            <strong>Embedding</strong>
            <span className="health-card-role">向量化</span>
          </div>
          <dl className="health-card-body">
            <div>
              <dt>provider</dt>
              <dd className="mono">{embedding.provider}</dd>
            </div>
            <div>
              <dt>dimension</dt>
              <dd>{embedding.dimension}</dd>
            </div>
            <div>
              <dt>配置项</dt>
              <dd className="mono">{embedding.configured || '—'}</dd>
            </div>
            {embedding.note ? (
              <div>
                <dt>note</dt>
                <dd>{embedding.note}</dd>
              </div>
            ) : null}
          </dl>
          {embeddingIsFallback ? (
            <div className="health-card-note health-card-note-warn">
              当前为 hashing 回退向量，仅保证功能可用；配置真实 embedding 后需重新入库才有语义检索效果。
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  )
}

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn btn-sm" onClick={onClick}>
      刷新
    </button>
  )
}

// ---------------------------------------------------------------- 创建项目

function CreateProjectForm({
  onCreated,
  onError,
}: {
  onCreated: (project: Project & { memory_bound: boolean }) => void
  onError: (err: unknown, title?: string) => void
}) {
  const [title, setTitle] = useState('')
  const [projectId, setProjectId] = useState('')
  const [objective, setObjective] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim()) {
      setFormError('项目标题不能为空')
      return
    }
    setFormError(null)
    setSubmitting(true)
    try {
      const created = await createProject({
        title: title.trim(),
        project_id: projectId.trim() || undefined,
        objective: objective.trim() || undefined,
      })
      setTitle('')
      setProjectId('')
      setObjective('')
      onCreated(created)
    } catch (err) {
      onError(err, '创建项目失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Panel title="新建项目" subtitle="注册到 seekdb，并绑定 PowerContext scope 作为任务记忆空间">
      <form onSubmit={submit} noValidate>
        <div className="form-row">
          <div className="field">
            <label htmlFor="np-title">项目标题（必填）</label>
            <input
              id="np-title"
              className="input"
              value={title}
              maxLength={256}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：向量数据库检索性能对比研究"
            />
          </div>
          <div className="field">
            <label htmlFor="np-id">
              project_id（可选）
            </label>
            <input
              id="np-id"
              className="input mono-input"
              value={projectId}
              maxLength={64}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="留空则按标题自动生成（a-z 0-9 _ -）"
            />
          </div>
        </div>
        <div className="field" style={{ marginTop: 'var(--sp-2)' }}>
          <label htmlFor="np-objective">研究目标 objective（可选）</label>
          <textarea
            id="np-objective"
            className="textarea"
            value={objective}
            maxLength={2000}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="一句话说明这个项目要回答什么问题"
          />
        </div>
        {formError ? (
          <div className="banner banner-red" style={{ marginTop: 'var(--sp-1)' }} role="alert">
            {formError}
          </div>
        ) : null}
        <div style={{ marginTop: 'var(--sp-2)' }}>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? '正在创建…' : '创建项目'}
          </button>
        </div>
      </form>
    </Panel>
  )
}

// ---------------------------------------------------------------- 项目详情

function ProjectDetailPanel({
  projectId,
  detail,
  error,
  loading,
  onRetry,
}: {
  projectId: string
  detail: ProjectDetail | null
  error: unknown | null
  loading: boolean
  onRetry: () => void
}) {
  return (
    <Panel
      title={`项目详情：${detail?.title ?? projectId}`}
      tags={<SourceTag source="powercontext" />}
      subtitle="记忆概览来自 PowerContext，项目注册信息来自 seekdb"
      actions={<RetryButton onClick={onRetry} />}
    >
      {loading ? <LoadingState text="正在合并 seekdb 项目信息与 PowerContext 记忆…" /> : null}
      {!loading && error ? <ErrorState error={error} onRetry={onRetry} /> : null}
      {!loading && detail ? (
        <div className="project-detail">
          <div className="meta-grid" style={{ marginBottom: 'var(--sp-2)' }}>
            <span className="meta-item">
              <span className="meta-key">project_id</span>
              <span className="meta-value mono">{detail.project_id}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">scope_id</span>
              <span className="meta-value mono">{detail.scope_id ?? '未绑定'}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">记忆条数 entry_count</span>
              <span className="meta-value">{detail.entry_count}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">记忆可用性</span>
              <span className="meta-value">
                {detail.memory_available ? (
                  <span className="badge badge-green">PowerContext 可用</span>
                ) : (
                  <span className="badge badge-red">PowerContext 不可用</span>
                )}
              </span>
            </span>
          </div>

          {!detail.memory_available ? (
            <div className="banner banner-amber" role="status">
              PowerContext 不可用，任务记忆暂不能读取；文献检索与问答不受影响。
              {detail.memory_error ? <div className="mono">原因：{detail.memory_error}</div> : null}
            </div>
          ) : null}

          <h3 className="detail-section-title">续研简报 resume_brief</h3>
          {detail.resume_brief ? (
            <pre className="resume-brief">{detail.resume_brief}</pre>
          ) : (
            <EmptyState text="暂无记忆内容。到「任务记忆」页显式保存一次研究进度后，这里会出现续研简报。" />
          )}

          {detail.snapshot ? (
            <div className="todo-columns">
              <ReadonlyTodoList
                title="下一步 next_steps"
                items={detail.snapshot.next_steps ?? []}
                emptyText="快照中没有记录下一步"
              />
              <ReadonlyTodoList
                title="未解决问题 open_questions"
                items={detail.snapshot.open_questions ?? []}
                emptyText="快照中没有记录未解决问题"
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  )
}

function ReadonlyTodoList({ title, items, emptyText }: { title: string; items: string[]; emptyText: string }) {
  return (
    <div className="todo-panel">
      <div className="todo-panel-head">
        <h4>{title}</h4>
        <SourceTag source="powercontext" />
      </div>
      {items.length === 0 ? (
        <p className="todo-empty">{emptyText}</p>
      ) : (
        <ul className="todo-list">
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>
              <label className="todo-item">
                <input
                  type="checkbox"
                  disabled
                  checked={false}
                  aria-label={`来自历史记忆的待办（只读）：${item}`}
                />
                <span>{item}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="todo-note">以上条目来自 PowerContext 历史记忆，仅作展示，不是可操作的任务接口。</p>
    </div>
  )
}
