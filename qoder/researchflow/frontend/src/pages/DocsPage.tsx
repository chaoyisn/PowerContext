import { useEffect, useState } from 'react'
import { getMeta, type MetaResponse } from '../api/client'
import { ErrorState, LoadingState, Metric, Panel, SourceTag } from '../components/common'
import Icon from '../components/Icon'
import { useShellHeader } from '../components/Shell'
import '../styles/docs.css'

const PIPELINE: { title: string; body: string; source?: 'seekdb' | 'powercontext' }[] = [
  {
    title: '上传与解析',
    body: 'PDF / Markdown / TXT 上传；PyMuPDF 按真实物理页取文（page.number + 1），空白页也写入一行页级身份。doc_id 是文件内容的 SHA-256，因此重复上传天然去重。',
    source: 'seekdb',
  },
  {
    title: '双索引写入',
    body: 'chunk 写入 pyseekdb collection：HNSW 向量索引（384 维 cosine）+ FULLTEXT 索引（ik 中文分析器）。写入后调用 refresh_index()，否则新向量可能不被 ANN 立即召回。',
    source: 'seekdb',
  },
  {
    title: '检索与门控',
    body: '向量 / 全文 / 混合（RRF k=60）三选一。词法覆盖率与语义相似度两条独立通道决定一条命中能否成为证据；未过门控的原始命中仍然返回，UI 可以解释它为什么没入选。',
    source: 'seekdb',
  },
  {
    title: '引用服务端核验',
    body: '模型给出的每个 citation 都回查 seekdb：不在本次检索结果里、或页码在 rf_pages 中不存在的引用一律剔除并记入 invalid_citations；失去引用的「资料直接支持」论断自动降级为「模型推断」。',
    source: 'seekdb',
  },
  {
    title: '任务记忆',
    body: '项目映射成 PowerContext Scope，进度写成 Atomic Memory + 带 revision 的 Artifact 快照。key_evidence 只保存指向 seekdb 的指针与摘录，不复制原文。',
    source: 'powercontext',
  },
  {
    title: '跨会话恢复',
    body: 'prepare_context + list_memory_entries + 最新 revision 快照 → 续研简报。恢复主路径不依赖关键词搜索，因为默认 fts5 unicode61 对纯中文召回弱。',
    source: 'powercontext',
  },
]

const MODES: { mode: string; impl: string; note: string }[] = [
  { mode: 'vector', impl: 'collection.query(query_embeddings=…)', note: '纯语义 ANN，score = cosine_similarity' },
  {
    mode: 'fulltext',
    impl: 'collection.hybrid_search(query={where_document.$contains}, knn=None)',
    note: '纯关键词 / ik 中文分词，score = fts_relevance',
  },
  {
    mode: 'hybrid',
    impl: 'collection.hybrid_search(query=…, knn=…, rank={"rrf":{}})',
    note: 'RRF 融合（默认），score = 融合排名分',
  },
]

const LABELS: { badge: string; title: string; body: string }[] = [
  {
    badge: 'badge-green',
    title: 'supported · 资料直接支持',
    body: '必须至少附一个真实 chunk_id，且该引用在服务端回查 seekdb 后仍然成立。',
  },
  {
    badge: 'badge-amber',
    title: 'inferred · 模型推断',
    body: '不得附引用；如果原本被标为直接支持但所有引用都没通过校验，会被自动降级到这里。',
  },
  {
    badge: 'badge-red',
    title: 'no_evidence · 尚无证据',
    body: '零命中时不进入 LLM，直接回答「知识库中没有相关材料」，不会为了给出答案而凑引用。',
  },
]

const SEEKDB_TABLES: { name: string; body: string }[] = [
  {
    name: 'rf_documents',
    body: 'doc_id CHAR(64) 主键（内容 SHA-256）· filename · content_type · page_count · chunk_count · status · error_message。内容寻址，重复上传得到同一行。',
  },
  {
    name: 'rf_pages',
    body: 'page_id = {sha256[:16]}:p{page_no:04d} · page_no 物理页号从 1 开始 · char_count · is_empty · content MEDIUMTEXT（「查看原文」读的就是这一列）· UNIQUE(doc_id, page_no)。空页也保留一行。',
  },
  {
    name: 'rf_chunks（pyseekdb collection）',
    body: 'id = {sha256[:16]}:p{page_no:04d}:c{chunk_idx:03d} 稳定幂等 · document 同时进 FULLTEXT · metadata 带 doc_id/page_no/page_id/char_start/char_end · embedding 384 维 HNSW cosine。',
  },
]

const PC_MAP: { concept: string; primitive: string }[] = [
  { concept: '科研项目 project_id', primitive: 'Scope，idempotency_key = researchflow:project:{project_id}' },
  {
    concept: '一条研究进度',
    primitive: 'Atomic Memory，kind ∈ goal / completed_work / decision / evidence / open_question / next_step',
  },
  { concept: '完整进度快照', primitive: 'Artifact，family=research-progress，带 revision + ETag，形成历史版本' },
  { concept: '新会话恢复', primitive: 'prepare_context(scope_id, query, max_bytes) + list_memory_entries + get_artifact' },
]

const SECURITY: { title: string; body: string }[] = [
  {
    title: '文档内容不当作指令',
    body: '上传文档里的文本只作为证据语料，不进入系统提示的指令通道；提示注入用例在 tests/test_security.py 中固化。',
  },
  {
    title: '过滤值 fail-closed',
    body: '实测 seekdb 全文腿会静默丢弃含 SQL 元字符的 where 子句（表现与「无过滤」一致），因此 doc_id 必须是 64 位 hex、content_type 走白名单，非法直接 422，绝不放宽结果集。',
  },
  {
    title: '上传与解析的资源上限',
    body: '按扩展名白名单与 max_bytes 限制上传；解析有超时与大小保护，失败写 error_message 而不是吞异常。',
  },
  {
    title: '记忆与文档不跨用户',
    body: '记忆读写永远按 project → scope 定向；本项目没有多租户身份层，因此部署形态刻意留在内网/本机，不对外暴露私有服务。',
  },
  {
    title: '降级诚实报告',
    body: 'seekdb 不可达时 API 仍启动，/api/health 报 degraded 并给出真实原因，数据接口返回 503 + 驱动错误信息，而不是返回预置答案。',
  },
]

const API_ROWS: { method: string; path: string; body: string }[] = [
  { method: 'GET', path: '/api/health', body: '四个组件的真实可达性与计数；degraded 时给出原因' },
  { method: 'GET', path: '/api/meta', body: '非机密运行配置（模式、端点、表名、门控阈值、上传限制）' },
  { method: 'POST', path: '/api/documents/upload', body: '解析、分页、双索引写入；force=true 重灌' },
  { method: 'GET', path: '/api/documents · /api/documents/{doc_id}', body: '文档列表与页级身份明细（含空白页）' },
  { method: 'GET', path: '/api/documents/{doc_id}/pages/{page_no}', body: '读取 seekdb 中该物理页原文' },
  { method: 'DELETE', path: '/api/documents/{doc_id}', body: '删除文档及其页与 chunk' },
  { method: 'POST', path: '/api/retrieval/search', body: '三模式检索 + 门控 + 过滤（doc_id / content_type / 页码区间）' },
  { method: 'POST', path: '/api/retrieval/compare', body: '一次请求返回三种模式结果与 chunk_id 重叠分析' },
  { method: 'POST', path: '/api/qa/ask', body: '证据问答：检索 → LLM 打标 → 服务端 citation 复核 → 论断降级' },
  { method: 'GET/POST', path: '/api/projects', body: '项目注册表存于 seekdb；创建时尝试绑定 PowerContext scope' },
  { method: 'GET', path: '/api/projects/{id}', body: 'seekdb 项目信息 + PowerContext 记忆概览 + 续研简报' },
  { method: 'POST', path: '/api/projects/{id}/memory/save', body: '显式保存进度快照，幂等去重（written / skipped_duplicates）' },
  { method: 'GET', path: '/api/projects/{id}/memory/restore', body: '恢复快照与记忆条目，返回 resume_brief' },
  { method: 'GET', path: '/api/projects/{id}/memory/history', body: '按 kind 分组的记忆时间线（seq / artifact_id / revision / state）' },
  { method: 'GET', path: '/api/memory/status', body: 'PowerContext 能力与限制说明' },
]

export default function DocsPage() {
  useShellHeader('架构与接口', '本项目的真实链路与契约')
  const [meta, setMeta] = useState<MetaResponse | null>(null)
  const [metaError, setMetaError] = useState<unknown | null>(null)

  useEffect(() => {
    getMeta()
      .then((data) => {
        setMeta(data)
        setMetaError(null)
      })
      .catch((err) => {
        setMeta(null)
        setMetaError(err)
      })
  }, [])

  return (
    <div className="page-inner page-inner-narrow scroll-thin">
      <div className="page-title-row">
        <h1>架构与接口</h1>
      </div>
      <p className="page-desc">
        seekdb 负责原文、页、chunk 与向量，是唯一能产生引用的来源；PowerContext 负责研究目标、决策、证据指针与下一步。
        这一页说明链路怎么走、数据落在哪、接口是什么，以及安全边界在哪里。
      </p>

      <Panel title="运行配置（实时读取 /api/meta）" subtitle="非机密配置回读，用来确认界面此刻连的是哪个服务">
        {metaError ? <ErrorState error={metaError} onRetry={() => void getMeta().then(setMeta)} /> : null}
        {meta ? (
          <>
            <div className="metric-row">
              <Metric label="app" value={`${meta.app} ${meta.version}`} tone="accent" />
              <Metric label="seekdb" value={meta.seekdb.mode as string} hint={`${meta.seekdb.endpoint} · db ${meta.seekdb.database}`} tone="accent" />
              <Metric label="PowerContext" value={meta.powercontext.url as string} hint={`integration ${meta.powercontext.integration}`} tone="memory" />
              <Metric label="LLM" value={meta.llm.enabled ? (meta.llm.model as string) : '未配置'} hint={meta.llm.base_url as string} tone={meta.llm.enabled ? 'accent' : 'warn'} />
            </div>
            <div className="meta-grid" style={{ marginTop: 'var(--s-3)' }}>
              {Object.entries(meta.retrieval).map(([key, value]) => (
                <span className="meta-item" key={key}>
                  <span className="meta-key">retrieval.{key}</span>
                  <span className="meta-value mono">{Array.isArray(value) ? value.join(' / ') : String(value)}</span>
                </span>
              ))}
              {Object.entries(meta.upload).map(([key, value]) => (
                <span className="meta-item" key={key}>
                  <span className="meta-key">upload.{key}</span>
                  <span className="meta-value mono">{Array.isArray(value) ? value.join(' / ') : String(value)}</span>
                </span>
              ))}
              <span className="meta-item">
                <span className="meta-key">seekdb.collection</span>
                <span className="meta-value mono">{String(meta.seekdb.collection)}</span>
              </span>
              <span className="meta-item">
                <span className="meta-key">seekdb.tables</span>
                <span className="meta-value mono">{Object.values(meta.seekdb.tables as Record<string, string>).join(' · ')}</span>
              </span>
            </div>
          </>
        ) : (
          <LoadingState text="正在读取运行配置…" />
        )}
      </Panel>

      <Panel title="链路">
        <ol className="timeline">
          {PIPELINE.map((step, index) => (
            <li key={step.title} className="tl-item">
              <span className="tl-dot tl-dot-num" aria-hidden="true">
                {index + 1}
              </span>
              <div className="tl-body">
                <div className="tl-head">
                  <strong>{step.title}</strong>
                  {step.source ? <SourceTag source={step.source} /> : null}
                </div>
                <p>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      <Panel title="检索模式" subtitle="三种模式走同一个 collection，可切换也可一次对比" tags={<SourceTag source="seekdb" />}>
        <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">模式</th>
              <th scope="col">SDK 调用</th>
              <th scope="col">说明</th>
            </tr>
          </thead>
          <tbody>
            {MODES.map((row) => (
              <tr key={row.mode}>
                <td className="mono">{row.mode}</td>
                <td className="mono">{row.impl}</td>
                <td>{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Panel>

      <Panel title="论断三级标注" subtitle="每条结论都注明它凭什么成立" tags={<SourceTag source="seekdb" />}>
        <div className="label-grid">
          {LABELS.map((item) => (
            <div className="label-card" key={item.title}>
              <span className={`badge ${item.badge}`}>{item.title}</span>
              <p>{item.body}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="数据模型 · seekdb" tags={<SourceTag source="seekdb" />}>
        <ul className="limit-list">
          {SEEKDB_TABLES.map((item) => (
            <li key={item.name}>
              <strong className="mono">{item.name}</strong>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
        <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
          表名统一带前缀（默认 <code>rf_</code>），不触碰同库其他赛题对象；重复上传走 upsert，行数不增长。
        </p>
      </Panel>

      <Panel title="数据模型 · PowerContext" tags={<SourceTag source="powercontext" />}>
        <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">ResearchFlow 概念</th>
              <th scope="col">PowerContext 原语</th>
            </tr>
          </thead>
          <tbody>
            {PC_MAP.map((row) => (
              <tr key={row.concept}>
                <td>{row.concept}</td>
                <td className="mono">{row.primitive}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
          界面上这两个通道永远分色、分别标注来源：记忆内容不会伪装成文献原文，引用也不会指向记忆。
        </p>
      </Panel>

      <Panel title="接口清单" subtitle="前端全部数据都经这些接口取得，没有内置假数据">
        <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">方法</th>
              <th scope="col">路径</th>
              <th scope="col">作用</th>
            </tr>
          </thead>
          <tbody>
            {API_ROWS.map((row) => (
              <tr key={row.path}>
                <td className="mono">{row.method}</td>
                <td className="mono">{row.path}</td>
                <td>{row.body}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Panel>

      <Panel title="安全边界">
        <ul className="limit-list">
          {SECURITY.map((item) => (
            <li key={item.title}>
              <strong>
                <Icon name="shield" size={13} /> {item.title}
              </strong>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="部署形态">
        <p className="docs-p">
          本地/内网：FastAPI 同源提供 <code>frontend/dist</code>，前端路由深链（如 <code>/workbench</code>、
          <code>/architecture</code>）回落到 <code>index.html</code>，因此刷新与直链都可用。
          <code>/docs</code> 保留给 FastAPI 自带的 OpenAPI(Swagger)，SPA 路由不与它同名。
        </p>
        <p className="docs-p">
          Qoder Sites：公开的是<b>纯静态展示站</b>（真实截图与真实验收数字），它不连数据库、不提供模拟查询。
          完整应用依赖自托管的 seekdb 与 PowerContext，属于私有服务，因此没有直接暴露到公网。
        </p>
        <p className="docs-p">
          更细的模块划分、配置项与复现步骤见仓库里的 <code>ARCHITECTURE.md</code> / <code>RUN.md</code> /
          <code>SECURITY.md</code>；本页只保留读界面时需要知道的那一层。
        </p>
      </Panel>
    </div>
  )
}
