import { useEffect, useState } from 'react'
import { EmptyState, ErrorState, LoadingState, Metric, Panel, SourceTag, StatusDot, formatNumber, formatTimestamp } from '../components/common'
import Icon from '../components/Icon'
import { useShell, useShellHeader } from '../components/Shell'
import '../styles/docs.css'

/** 已随仓库提交的验收运行记录（verification/acceptance-run/），不是本页生成的数据。 */
const ACCEPTANCE: { id: string; scene: string; checks: number; seconds: number }[] = [
  { id: 'T1', scene: '上传 PDF，全部物理页有稳定记录，seekdb 保存正确', checks: 20, seconds: 5.9 },
  { id: 'T2', scene: '明确问题 → 正确资料与真实页码', checks: 28, seconds: 2.3 },
  { id: 'T3', scene: '无答案问题 → 不伪造 citation', checks: 20, seconds: 2.1 },
  { id: 'T4', scene: '新建项目保存决策与 next_steps，PowerContext 实际写入', checks: 17, seconds: 0.6 },
  { id: 'T5', scene: '结束并重建会话恢复决策与 next_steps', checks: 14, seconds: 2.3 },
  { id: 'T6', scene: '重启服务后数据库与记忆仍可查询', checks: 11, seconds: 15.1 },
  { id: 'T7', scene: '断开 PowerContext 对比任务恢复能力', checks: 19, seconds: 19.5 },
  { id: 'T8', scene: '断开 seekdb 报真实错误而非预置答案', checks: 14, seconds: 15.8 },
  { id: 'T9-LLM', scene: '真实 LLM 证据问答 + citation 服务端校验', checks: 7, seconds: 2.4 },
]

const PYTEST_FILES: { file: string; covers: string }[] = [
  { file: 'tests/test_parsing.py', covers: '哈希 / 路径安全 / 分块偏移 / 解析 / 相关性门控 / 记忆模型（单元）' },
  { file: 'tests/test_seekdb_integration.py', covers: 'T1 / T2 / T3 / T8，打真实 seekdb' },
  { file: 'tests/test_memory_integration.py', covers: 'T4 / T5 / T7，打真实 PowerContext' },
  { file: 'tests/test_memory_zh.py', covers: '中文记忆召回回归（独立数据集驱动）' },
  { file: 'tests/test_qa.py', covers: 'citation 服务端校验、论断降级、仅检索模式、记忆分通道' },
  { file: 'tests/test_security.py', covers: '上传 / 解析 DoS / 提示注入 / SQL 注入 / 隔离 / CORS / 密钥' },
  { file: 'tests/test_heldout.py', covers: '保留集：多空白页 PDF、跨文档定位、并发、断连重连、LLM 重试' },
  { file: 'tests/test_api.py', covers: 'HTTP 契约、错误码、OpenAPI、上传与过滤校验' },
]

const LIMITS: { title: string; body: string }[] = [
  {
    title: '嵌入式 seekdb 在 Windows 不可用',
    body: '官方 wheel 仅 manylinux（_PYLIBSEEKDB_AVAILABLE=False）。本项目采用远程模式连 127.0.0.1:2881；Linux/macOS 可设 RF_SEEKDB_MODE=embedded。',
  },
  {
    title: 'PowerContext 纯中文记忆检索偏弱',
    body: 'fts5 unicode61 分词对纯中文不友好。恢复流程不依赖搜索（全量 list_memory_entries），并另加一层中文感知召回；限制在 UI 与 API 响应中如实展示。',
  },
  {
    title: '默认 embedding 为英文词表',
    body: '中文查询命中纯英文原文时相似度低。缓解：双语 demo 语料、默认 hybrid、门控含语义逃逸（vector_confidence=0.62），可用 RF_EMBEDDING_PROVIDER=openai 换真实中文 embedding 服务。',
  },
  {
    title: 'RRF 平分时顺序不稳定',
    body: 'demo 语料里 PDF 与 experiment_log.txt 对同一问题都是合法来源，因此 T2 对 fulltext/hybrid 断言「前 2 位」而不是「第 1 位」。',
  },
  {
    title: 'HNSW 写入后需要 refresh',
    body: '不刷新时新写入的向量可能不被 ANN 立即召回（实测 13 chunk 只返回 3）。入库后统一调用 collection.refresh_index()。',
  },
  {
    title: '窄屏只做 CSS 层验证',
    body: '侧边栏与证据栏在 ≤900px / ≤1240px 转为抽屉（媒体查询）。桌面端已逐页浏览器实测；窄屏未逐页截图，属于已知未覆盖项。',
  },
]

export default function VerificationPage() {
  const shell = useShell()
  useShellHeader('验证记录', '真实服务回读 + 已提交验收日志')
  const { health, healthDown, healthLoading, refreshHealth } = shell
  const [checkedAt, setCheckedAt] = useState('')

  // /api/health 不回传检测时刻，用浏览器本地时间标注「这一次是什么时候读的」。
  useEffect(() => {
    if (health) setCheckedAt(new Date().toISOString())
  }, [health])

  return (
    <div className="page-inner page-inner-narrow scroll-thin">
      <div className="page-title-row">
        <h1>验证记录</h1>
        <SourceTag source="seekdb" />
        <SourceTag source="powercontext" />
      </div>
      <p className="page-desc">
        上半部分每次刷新都重新调用 <code>GET /api/health</code>；下半部分是随仓库提交的验收与测试结果，标注了原始日志路径。
      </p>

      <Panel
        title="后端健康状态"
        actions={
          <button type="button" className="btn btn-sm" onClick={refreshHealth}>
            <Icon name="refresh" size={14} /> 重新检测
          </button>
        }
      >
        {healthLoading && !health ? <LoadingState text="正在检测 seekdb / PowerContext / LLM / Embedding…" /> : null}
        {healthDown && !health ? <ErrorState error={new Error('后端未连接')} onRetry={refreshHealth} /> : null}
        {health ? (
          <>
            <div className="metric-row">
              <Metric
                label="seekdb server_version"
                value={health.components.seekdb.server_version ?? '—'}
                hint={health.components.seekdb.available ? `在线 · ${health.components.seekdb.latency_ms ?? '—'} ms` : '不可用'}
                tone={health.components.seekdb.available ? 'accent' : 'bad'}
              />
              <Metric
                label="全文分析器"
                value={health.components.seekdb.fts_analyzer ?? '—'}
                hint={`连接模式 ${health.components.seekdb.mode ?? '—'}`}
                tone="accent"
              />
              <Metric
                label="PowerContext"
                value={health.components.powercontext.package_version ?? '—'}
                hint={health.components.powercontext.available ? `在线 · ${health.components.powercontext.latency_ms ?? '—'} ms` : health.components.powercontext.error ?? '不可用'}
                tone={health.components.powercontext.available ? 'memory' : 'bad'}
              />
              <Metric
                label="Embedding"
                value={health.components.embedding.provider}
                hint={`${health.components.embedding.dimension} 维 · ${health.components.embedding.configured || '—'}`}
                tone={health.components.embedding.provider === 'hashing' ? 'warn' : 'accent'}
              />
            </div>

            <div className="metric-row">
              <Metric label="文档 documents" value={formatNumber(health.components.seekdb.counts?.documents ?? 0)} tone="accent" />
              <Metric label="物理页 pages" value={formatNumber(health.components.seekdb.counts?.pages ?? 0)} tone="accent" />
              <Metric label="分块 chunks" value={formatNumber(health.components.seekdb.counts?.chunks ?? 0)} tone="accent" />
              <Metric label="项目 projects" value={formatNumber(health.components.seekdb.counts?.projects ?? 0)} tone="accent" />
            </div>

            <div className={health.status === 'ok' ? 'banner banner-info' : 'banner banner-amber'} role="status" style={{ marginTop: 'var(--s-3)' }}>
              <StatusDot level={health.status === 'ok' ? 'green' : 'amber'} />
              <span>
                整体状态 {health.status} · 问答生成 {health.capabilities.qa_generates_answers ? '可用' : '不可用（仅检索模式）'} ·
                记忆读写 {health.capabilities.memory ? '可用' : '不可用'} · 文献检索 {health.capabilities.retrieval ? '可用' : '不可用'} ·
                上传入库 {health.capabilities.upload ? '可用' : '不可用'}
              </span>
            </div>
            <p className="field-hint" style={{ marginTop: 'var(--s-2)' }}>
              上面这些数字来自当前运行中的服务，不是截图或常量；停掉 PowerContext 时这里的
              available 与延迟会立即变成 false，而检索与引用仍然可用。
            </p>
            {health.components.seekdb.error ? (
              <div className="banner banner-red" role="alert">
                seekdb：{health.components.seekdb.error}
              </div>
            ) : null}
          </>
        ) : null}
      </Panel>

      <Panel title="端到端验收 T1–T9" subtitle="结果与逐用例日志已提交在 verification/acceptance-run/（acceptance-report.md / .json、T1.log … T9-LLM.log）" tags={<SourceTag source="seekdb" />}>
        <ol className="timeline">
          {ACCEPTANCE.map((item) => (
            <li key={item.id} className="tl-item">
              <span className="tl-dot" aria-hidden="true">
                <Icon name="check" size={12} />
              </span>
              <div className="tl-body">
                <div className="tl-head">
                  <strong className="mono">{item.id}</strong>
                  <span className="badge badge-green">PASS</span>
                  <span className="tl-meta">{item.checks} 项校验 · {item.seconds}s</span>
                </div>
                <p>{item.scene}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
          合计 150 项校验、0 失败（验收运行目录 logs/acceptance-20261029-100634/）。
          重新运行会另写一份带时间戳的报告，不会覆盖已提交的记录。
        </p>
      </Panel>

      <Panel title="后端测试" subtitle="149 个 pytest 用例全部通过，直接打真实 seekdb 与真实 PowerContext（不是 mock）">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">测试文件</th>
              <th scope="col">覆盖内容</th>
            </tr>
          </thead>
          <tbody>
            {PYTEST_FILES.map((row) => (
              <tr key={row.file}>
                <td className="mono">{row.file}</td>
                <td>{row.covers}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
          复现：<code>cd backend && .venv/Scripts/python -m pytest tests/ -q</code>
        </p>
      </Panel>

      <Panel title="已知限制" subtitle="如实记录，不做修饰">
        <ul className="limit-list">
          {LIMITS.map((item) => (
            <li key={item.title}>
              <strong>{item.title}</strong>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="提效测量口径" subtitle="区分 automated / script-proxy / human">
        <ul className="limit-list">
          <li>
            <strong>automated</strong>
            <p>pytest、验收脚本、Playwright 无头检查（如 scripts/verify_site.cjs）产生的计数，属于机器自测，可原样复现。</p>
          </li>
          <li>
            <strong>script-proxy</strong>
            <p>由脚本按预置问题提问、逐字记录响应耗时的采样（BENCHMARK.md）。它衡量的是链路耗时，不代表真实用户提效结论，界面与文档都不写成「用户提效」。</p>
          </li>
          <li>
            <strong>human</strong>
            <p>人工在浏览器里逐页核对引用与原文页的验证（VERIFICATION.md 3.3）。窄屏未逐页截图，这项明确标注为未覆盖。</p>
          </li>
        </ul>
      </Panel>

      <Panel title="复现与交付入口">
        {health ? (
          <div className="meta-grid">
            <span className="meta-item">
              <span className="meta-key">seekdb endpoint</span>
              <span className="meta-value mono">{health.components.seekdb.endpoint ?? '—'}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">database</span>
              <span className="meta-value mono">{health.components.seekdb.database ?? '—'}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">PowerContext url</span>
              <span className="meta-value mono">{health.components.powercontext.url ?? '—'}</span>
            </span>
            <span className="meta-item">
              <span className="meta-key">本次读取时间（浏览器本地）</span>
              <span className="meta-value">{formatTimestamp(checkedAt)}</span>
            </span>
          </div>
        ) : (
          <EmptyState text="暂时读不到健康信息：后端未连接时这一页会保持空状态，而不是显示预设数字。" />
        )}
        <p className="field-hint" style={{ marginTop: 'var(--s-3)' }}>
          启动与验收步骤见 RUN.md；架构与接口见本页（侧栏 Docs，站内 /architecture）；完整接口速览在 /docs 的 OpenAPI；安全边界见 SECURITY.md。
        </p>
      </Panel>
    </div>
  )
}
