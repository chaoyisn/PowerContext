import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import model from "../../model.json";
import { api, post, type KnowledgeBase, type SearchResult, type StoredDocument } from "./api";
import { EmbeddingClient, type EmbeddingStatus, type Precision } from "./embedding";
import { chunkText, sha256Text } from "./text-utils.mjs";
import { downloadPerf, readPerf, recordPerf, type PerfRecord } from "./perf";
import { compressionRatio } from "../../benchmark/performance.mjs";
import { embeddingSpace } from "./embedding-space.mjs";

type Page = "home" | "search" | "documents" | "performance";
const pages: { id: Page; label: string; glyph: string }[] = [
  { id: "home", label: "知识库", glyph: "▦" },
  { id: "search", label: "智能检索", glyph: "⌕" },
  { id: "documents", label: "文档管理", glyph: "▤" },
  { id: "performance", label: "性能记录", glyph: "◷" },
];

export function App() {
  const [page, setPage] = useState<Page>("home");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [activeKbId, setActiveKbId] = useState(() => localStorage.getItem("edgeseek.active-kb") ?? "");
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<StoredDocument | null>(null);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"hybrid" | "vector" | "fulltext">("hybrid");
  const [topK, setTopK] = useState(5);
  const [precision, setPrecision] = useState<Precision>(() => (localStorage.getItem("edgeseek.precision") as Precision) || "auto");
  const [batchSize, setBatchSize] = useState(4);
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null>(null);
  const [modelState, setModelState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelProgress, setModelProgress] = useState<Record<string, unknown> | null>(null);
  const [databaseReady, setDatabaseReady] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [newKbName, setNewKbName] = useState("");
  const [showNewKb, setShowNewKb] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("edgeseek.theme") === "dark");
  const [performanceRows, setPerformanceRows] = useState<PerfRecord[]>(readPerf);
  const workerRef = useRef<EmbeddingClient | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const assetDownloads = useRef(new Map<string, number>());
  const assetSizes = useRef(new Map<string, number>());
  const activeKb = kbs.find((kb) => kb.id === activeKbId) ?? null;

  useEffect(() => {
    void refreshKbs();
    void api<{ ok: boolean }>("/api/health").then(({ data }) => setDatabaseReady(data.ok)).catch(() => setDatabaseReady(false));
    const update = () => setPerformanceRows(readPerf());
    window.addEventListener("edgeseek:performance", update);
    return () => {
      window.removeEventListener("edgeseek:performance", update);
      workerRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (activeKbId) void refreshDocuments(activeKbId);
    else setDocuments([]);
  }, [activeKbId]);

  function refreshKbs(preferredId?: string) {
    return api<{ kbs: KnowledgeBase[] }>("/api/kbs").then(({ data }) => {
      setKbs(data.kbs);
      const stored = localStorage.getItem("edgeseek.active-kb");
      const next = data.kbs.some((kb) => kb.id === preferredId) ? preferredId! : data.kbs.some((kb) => kb.id === activeKbId) ? activeKbId : data.kbs.some((kb) => kb.id === stored) ? stored! : data.kbs[0]?.id ?? "";
      setActiveKbId(next);
      if (next) localStorage.setItem("edgeseek.active-kb", next);
    }).catch((reason: Error) => setError(reason.message));
  }

  function refreshDocuments(kbId = activeKbId) {
    if (!kbId) return Promise.resolve();
    return api<{ documents: StoredDocument[] }>(`/api/kbs/${kbId}/documents`)
      .then(({ data }) => setDocuments(data.documents))
      .catch((reason: Error) => setError(reason.message));
  }

  function worker() {
    if (!workerRef.current) {
      const instance = new EmbeddingClient();
      instance.onProgress = (progress) => {
        setModelProgress(progress);
        if (progress.phase === "worker-start" && progress.kind === "embed" && typeof progress.queueMs === "number") recordPerf("worker.queue", { durationMs: progress.queueMs });
        if (progress.phase === "model-load" && typeof progress.file === "string") {
          const file = progress.file;
          if (progress.status === "download") assetDownloads.current.set(file, performance.now());
          if (typeof progress.total === "number" && progress.total > 0) assetSizes.current.set(file, progress.total);
          if (progress.status === "done") {
            const started = assetDownloads.current.get(file);
            recordPerf("model.asset", {
              file, bytes: assetSizes.current.get(file),
              acquisitionMs: started === undefined ? undefined : Number((performance.now() - started).toFixed(2)),
              modelId: model.id, revision: model.revision,
            });
          }
        }
      };
      workerRef.current = instance;
    }
    return workerRef.current;
  }

  async function ensureModel(requested: Precision = precision) {
    if (modelState === "loading") throw new Error("本地模型正在加载，请稍候");
    const workerResident = modelState === "ready" && Boolean(embedding) && (requested === "auto" || (requested === "int8" ? "q8" : requested) === embedding?.dtype);
    setModelState("loading");
    setError("");
    assetDownloads.current.clear();
    assetSizes.current.clear();
    try {
      const start = performance.now();
      const state = await worker().initialize(requested);
      const bytes = [...assetSizes.current.values()].reduce((sum, value) => sum + value, 0);
      const firstUse = localStorage.getItem(`edgeseek.model.loaded.${state.dtype}`) !== "true";
      localStorage.setItem(`edgeseek.model.loaded.${state.dtype}`, "true");
      setEmbedding(state);
      setModelState("ready");
      recordPerf("model.load", {
        modelId: state.modelId, revision: model.revision, modelKey: state.modelKey,
        backend: state.backend, dtype: state.dtype, dimension: state.dimension,
        durationMs: Number((performance.now() - start).toFixed(2)), workerInitMs: Number(state.initMs.toFixed(2)),
        modelAssetBytes: bytes,
        cacheState: workerResident ? "worker-resident" : bytes ? "asset-size-reported" : firstUse ? "first-use-size-unreported" : "browser-cache-or-unknown",
        fallback: Boolean(state.fallbackReason),
      });
      recordMeasuredCompression();
      return state;
    } catch (reason) {
      workerRef.current?.close();
      workerRef.current = null;
      setModelState("error");
      throw reason;
    }
  }

  function recordMeasuredCompression() {
    const rows = readPerf().filter((row) => row.name === "model.asset" && row.modelId === model.id && row.revision === model.revision && Number(row.bytes) > 0);
    const latestSize = (filename: string) => rows.filter((row) => String(row.file).split(/[?#]/)[0].split("/").at(-1) === filename).map((row) => Number(row.bytes)).at(-1);
    const fp32Bytes = latestSize("model.onnx");
    const int8Bytes = latestSize("model_quantized.onnx");
    const ratio = compressionRatio(fp32Bytes, int8Bytes);
    if (ratio !== null) recordPerf("model.compression", { modelId: model.id, revision: model.revision, original: "model.onnx", quantized: "model_quantized.onnx", fp32Bytes, int8Bytes, fp32ToInt8Ratio: ratio });
  }

  async function embedTexts(texts: string[], size = batchSize) {
    if (modelState !== "ready" || !embedding) await ensureModel();
    const started = performance.now();
    let batch;
    try { batch = await worker().embed(texts, size); }
    catch (reason) {
      workerRef.current?.close();
      workerRef.current = null;
      setModelState("error");
      setEmbedding(null);
      throw reason;
    }
    if (embedding?.backend !== batch.backend || embedding?.dtype !== batch.dtype) {
      setEmbedding((current) => current ? { ...current, backend: batch.backend, dtype: batch.dtype, fallbackReason: batch.fallbackReason } : current);
    }
    recordPerf("embedding.batch", {
      items: texts.length, batchSize: batch.batchSize, durationMs: Number(batch.elapsedMs.toFixed(2)),
      wallMs: Number((performance.now() - started).toFixed(2)), itemsPerSecond: Number((texts.length / Math.max(batch.elapsedMs / 1000, 0.001)).toFixed(2)),
      backend: batch.backend, dtype: batch.dtype, dimension: model.dimension,
    });
    return batch;
  }

  async function createKb(event: FormEvent) {
    event.preventDefault();
    if (!newKbName.trim()) return;
    setBusy("kb");
    setError("");
    try {
      const state = await ensureModel();
      const modelKey = embeddingSpace(model.modelKey, model.revision, state.backend, state.dtype);
      const { data } = await post<{ kb: KnowledgeBase }>("/api/kbs", { name: newKbName, modelKey });
      setNewKbName("");
      localStorage.setItem("edgeseek.active-kb", data.kb.id);
      setActiveKbId(data.kb.id);
      setShowNewKb(false);
      await refreshKbs(data.kb.id);
      setNotice(`已创建知识库「${data.kb.name}」`);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function importFiles(filesLike: FileList | File[]) {
    const files = Array.from(filesLike);
    if (!activeKb || !files.length) return;
    setBusy("import");
    setError("");
    setNotice("");
    try {
      const candidates = [] as { file: File; content: string; sha256: string }[];
      for (const file of files) {
        if (!/\.(txt|md)$/i.test(file.name)) throw new Error(`${file.name}：只支持 TXT 和 Markdown 文档`);
        if (file.size > 5 * 1024 * 1024) throw new Error(`${file.name}：超过单文件 5 MB 限制`);
        const content = await file.text();
        candidates.push({ file, content, sha256: await sha256Text(content) });
      }
      const check = await post<{ duplicates: string[] }>(`/api/kbs/${activeKb.id}/deduplicate`, { hashes: candidates.map((doc) => doc.sha256) });
      recordPerf("network.deduplicate", { durationMs: Number(check.requestMs.toFixed(2)), files: candidates.length });
      const duplicates = new Set(check.data.duplicates);
      const selectedHashes = new Set<string>();
      const fresh = candidates.filter((doc) => {
        if (duplicates.has(doc.sha256) || selectedHashes.has(doc.sha256)) return false;
        selectedHashes.add(doc.sha256);
        return true;
      });
      if (!fresh.length) {
        setNotice(`所选 ${files.length} 份文档都已导入，未重复计算向量`);
        return;
      }

      if (fresh.length > 100) throw new Error("单次最多导入 100 份文档，请分批选择");
      const prepared: { filename: string; content: string; sha256: string; modelKey: string; backend: string; dtype: string; chunks: { text: string; embedding: number[] }[] }[] = [];
      for (const [index, item] of fresh.entries()) {
        const chunks = chunkText(item.content);
        if (!chunks.length) throw new Error(`${item.file.name}：文档内容为空`);
        setNotice(`正在处理 ${index + 1}/${fresh.length}：${item.file.name} · ${chunks.length} 个分块`);
        const vectors = await embedTexts(chunks);
        const modelKey = embeddingSpace(model.modelKey, model.revision, vectors.backend, vectors.dtype);
        if (modelKey !== activeKb.modelKey) throw new Error("当前推理配置与知识库向量空间不一致，请切换到匹配的知识库或重新创建并导入文档");
        prepared.push({ filename: item.file.name, content: item.content, sha256: item.sha256, modelKey, backend: vectors.backend, dtype: vectors.dtype, chunks: chunks.map((text, i) => ({ text, embedding: vectors.embeddings[i] })) });
      }
      setNotice(`正在批量写入 ${prepared.length} 份文档并刷新索引`);
      const { data, requestMs } = await post<{ results: { duplicate: boolean; documentId: string; chunks: number; writeMs?: number }[]; refreshMs: number; visibilityMs: number }>(`/api/kbs/${activeKb.id}/documents/batch`, { documents: prepared });
      const imported = data.results.filter((item) => !item.duplicate).length;
      const totalChunks = data.results.reduce((sum, item) => sum + item.chunks, 0);
      recordPerf("network.document-write", { durationMs: Number(requestMs.toFixed(2)), bytes: fresh.reduce((sum, item) => sum + item.file.size, 0), chunks: totalChunks, files: fresh.length });
      for (const item of data.results.filter((result) => !result.duplicate)) recordPerf("seekdb.write", { durationMs: Number((item.writeMs ?? 0).toFixed(2)), chunks: item.chunks });
      recordPerf("seekdb.index-refresh", { durationMs: Number(data.refreshMs.toFixed(2)), visibleMs: Number(data.visibilityMs.toFixed(2)), chunks: totalChunks, files: imported });
      await refreshDocuments();
      await refreshKbs();
      setNotice(`已导入 ${imported} 份新文档；重复文档跳过 ${files.length - fresh.length + data.results.filter((item) => item.duplicate).length} 份`);
    } catch (reason) {
      setError((reason as Error).message);
      setNotice("导入未完成；未确认完成的文档可重新导入恢复。");
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function runSearch(event?: React.FormEvent) {
    event?.preventDefault();
    if (!activeKb || !query.trim()) return;
    setBusy("search");
    setError("");
    setResults([]);
    const endToEndStart = performance.now();
    try {
      const vector = await embedTexts([query.trim()], 1);
      const modelKey = embeddingSpace(model.modelKey, model.revision, vector.backend, vector.dtype);
      if (modelKey !== activeKb.modelKey) throw new Error("当前推理配置与知识库向量空间不一致，请切换到匹配的知识库或重新创建并导入文档");
      recordPerf("query.embedding", { durationMs: Number(vector.elapsedMs.toFixed(2)), backend: vector.backend, dtype: vector.dtype });
      const { data, requestMs, timings } = await post<{ results: SearchResult[]; dbMs: number; mode: string }>(`/api/kbs/${activeKb.id}/search`, {
        query: query.trim(), embedding: vector.embeddings[0], modelKey, backend: vector.backend, dtype: vector.dtype, mode, topK,
      });
      recordPerf("seekdb.search", { mode: data.mode, dbMs: Number(data.dbMs.toFixed(2)), networkMs: Number(Math.max(0, requestMs - data.dbMs).toFixed(2)), outboundMs: timings.outboundMs, serverMs: timings.serverMs, inboundHeadersMs: timings.inboundHeadersMs, inboundBodyParsedMs: timings.inboundBodyParsedMs, resultCount: data.results.length });
      setResults(data.results);
      requestAnimationFrame(() => recordPerf("query.end-to-end", { mode, durationMs: Number((performance.now() - endToEndStart).toFixed(2)), resultCount: data.results.length }));
      setNotice(`seekdb 返回 ${data.results.length} 条真实结果`);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function openDocument(id: string) {
    if (!activeKb) return;
    try {
      const { data } = await api<{ document: StoredDocument }>(`/api/kbs/${activeKb.id}/documents/${id}`);
      setSelectedDocument(data.document);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  async function benchmarkPrecision(value: Precision) {
    setBusy("benchmark");
    setError("");
    try {
      const state = await ensureModel(value);
      await embedTexts(["A local benchmark sample verifies model loading and normalized embedding output."], 1);
      setNotice(`${state.backend} · ${state.dtype} 实测完成，结果已计入性能记录`);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  function changePrecision(value: Precision) {
    workerRef.current?.close();
    workerRef.current = null;
    setPrecision(value);
    localStorage.setItem("edgeseek.precision", value);
    setModelState("idle");
    setEmbedding(null);
  }

  function changeKb(id: string) {
    setActiveKbId(id);
    localStorage.setItem("edgeseek.active-kb", id);
    setSelectedDocument(null);
    setResults([]);
  }

  const recentEvents = useMemo(() => [...performanceRows].reverse().slice(0, 12), [performanceRows]);
  const onDrop = (event: DragEvent) => { event.preventDefault(); setDropActive(false); void importFiles(event.dataTransfer.files); };

  return (
    <div className={`app-shell ${dark ? "theme-dark" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><span>e</span></div><div><b>EdgeSeek</b><small>LOCAL KNOWLEDGE</small></div></div>
        <div className="nav-label">工作区</div>
        <nav aria-label="主导航">
          {pages.map((item) => <button key={item.id} className={`nav-item ${page === item.id ? "active" : ""}`} onClick={() => setPage(item.id)}><span className="nav-glyph">{item.glyph}</span>{item.label}{page === item.id && <span className="nav-indicator" />}</button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card"><span className="privacy-icon">◉</span><div><b>端侧向量化</b><small>文档与查询在浏览器处理</small></div></div>
          <div className="account-row"><div className="account-avatar">ES</div><div className="account-text"><b>本地工作区</b><small>seekdb · 127.0.0.1</small></div><button className="theme-toggle" aria-label="切换深色模式" onClick={() => { const value = !dark; setDark(value); localStorage.setItem("edgeseek.theme", value ? "dark" : "light"); }}>{dark ? "☼" : "◐"}</button></div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand"><div className="brand-mark"><span>e</span></div><b>EdgeSeek</b></div>
          <div className="breadcrumb"><span>工作区</span><i>/</i><strong>{pages.find((item) => item.id === page)?.label}</strong></div>
          <div className="topbar-right">
            <label className="kb-switcher"><span className="kb-dot" />
              <select aria-label="切换知识库" value={activeKbId} onChange={(event) => changeKb(event.target.value)} disabled={!kbs.length || Boolean(busy)}>
                {!kbs.length && <option value="">暂无知识库</option>}
                {kbs.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
              </select>
            </label>
            <button className="kb-add" onClick={() => setShowNewKb(true)} disabled={Boolean(busy)} aria-label="新建知识库" title="新建知识库">＋</button>
            <div className={`status-pill ${databaseReady ? "is-ready" : "is-error"}`}><span />{databaseReady ? "seekdb 已连接" : "数据库未连接"}</div>
            <div className={`model-pill ${modelState === "ready" ? "is-ready" : ""}`} title={embedding ? `${embedding.modelId} · ${embedding.dtype} · ${embedding.dimension} 维` : model.id}>
              <span className="model-dot" />{embedding ? `${embedding.backend} · ${embedding.dtype}` : modelState === "loading" ? "模型加载中" : "端侧模型未加载"}
            </div>
          </div>
        </header>

        <div className="page-wrap">
          <input ref={fileRef} hidden type="file" multiple accept=".txt,.md,text/plain,text/markdown" onChange={(event) => void importFiles(event.target.files ?? [])} />
          {(error || notice) && <div className={`toast ${error ? "toast-error" : "toast-success"}`} role={error ? "alert" : "status"}><span>{error ? "!" : "✓"}</span><div>{error || notice}</div><button onClick={() => { setError(""); setNotice(""); }} aria-label="关闭提示">×</button></div>}

          {page === "home" && <>
            <section className="welcome-row">
              <div><div className="eyebrow"><span className="eyebrow-line" /> YOUR PRIVATE SEARCH SPACE</div><h1>让知识，随时可检索。</h1><p>文档在浏览器本地向量化，原文与向量存入 seekdb。没有云端推理。</p></div>
              <div className="welcome-orb"><div className="orb-core">e</div><i className="orbit orbit-one" /><i className="orbit orbit-two" /><i className="orb-dot dot-one" /><i className="orb-dot dot-two" /></div>
            </section>

            <section className="model-banner">
              <div className="model-banner-icon">✳</div><div className="model-banner-copy"><b>{modelState === "ready" ? "浏览器模型已就绪" : modelState === "loading" ? "正在加载端侧模型" : "端侧向量模型"}</b><span>{embedding ? `${embedding.modelId} · ${embedding.dimension} 维 · ${embedding.backend} ${embedding.dtype}` : `${model.id} · ${model.dimension} 维 · 首次运行会下载公开 ONNX 权重`}</span></div>
              <div className="model-progress-wrap">{modelState === "loading" ? <><div className="progress-track"><span style={{ width: `${Number(modelProgress?.progress ?? 4)}%` }} /></div><small>{typeof modelProgress?.file === "string" ? modelProgress.file : "初始化推理运行时"}</small></> : <button className="button button-soft" onClick={() => void ensureModel().catch((reason) => setError(reason.message))}>{modelState === "ready" ? "重新检测" : "加载模型"}<span>↗</span></button>}</div>
            </section>

            <div className="section-heading"><div><h2>知识库</h2><p>不同知识库使用独立索引，向量不会串用。</p></div><span className="count-badge">{kbs.length} 个空间</span></div>
            <section className="workspace-grid">
              <div className="panel kb-panel">
                <div className="panel-heading"><div className="panel-icon lavender">▦</div><div><h3>{activeKb?.name ?? "创建第一个知识库"}</h3><p>{activeKb ? `${activeKb.documentCount} 份文档 · ${activeKb.dimension} 维向量` : "为你的资料建立独立检索空间"}</p></div><span className="panel-menu">···</span></div>
                {activeKb ? <div className="kb-meta"><span><i className="tiny-green" />索引正常</span><span>模型已锁定</span></div> : <form className="create-kb-form" onSubmit={(event) => void createKb(event)}><input value={newKbName} onChange={(event) => setNewKbName(event.target.value)} placeholder="例如：产品文档" aria-label="知识库名称" /><button className="button button-primary" disabled={busy === "kb" || !newKbName.trim()}>{busy === "kb" ? "创建中…" : "创建知识库"}</button></form>}
                <div className="kb-footer"><span>模型配置</span><code>{model.id.split("/").at(-1)} · {model.dimension}d</code></div>
              </div>

              <div className={`panel import-panel ${dropActive ? "drop-active" : ""}`} onDragOver={(event) => { event.preventDefault(); setDropActive(true); }} onDragLeave={() => setDropActive(false)} onDrop={onDrop}>
                <div className="upload-illustration"><div className="upload-sheet">MD</div><div className="upload-arrow">↑</div><div className="upload-ring" /></div>
                <div className="upload-copy"><h3>导入你的文档</h3><p>支持 TXT 与 Markdown，可多选或拖放</p></div>
                <button className="button button-primary" disabled={!activeKb || busy === "import"} onClick={() => fileRef.current?.click()}>{busy === "import" ? "正在向量化…" : "选择文件"}<span>＋</span></button>
                <small className="upload-note">单文件最大 5 MB · SHA-256 自动去重</small>
              </div>
            </section>

            <div className="section-heading recent-heading"><div><h2>最近文档</h2><p>原文与分块都保存在当前 seekdb 知识库。</p></div><button className="text-button" onClick={() => setPage("documents")}>查看全部 <span>→</span></button></div>
            <DocumentTable documents={documents.slice(0, 4)} open={openDocument} />
          </>}

          {page === "search" && <section className="search-view">
            <div className="search-intro"><div className="eyebrow"><span className="eyebrow-line" /> SEARCH IN YOUR KNOWLEDGE</div><h1>你想找什么？</h1><p>语义向量与全文索引在 seekdb 内完成检索与融合。</p></div>
            <form className="search-composer" onSubmit={(event) => void runSearch(event)}>
              <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="用自然语言描述你要找的内容…" aria-label="检索内容" rows={3} />
              <div className="composer-bottom"><div className="search-modes" role="tablist" aria-label="检索方式">
                {([ ["hybrid", "混合检索"], ["vector", "向量"], ["fulltext", "全文"] ] as const).map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={mode === value} className={mode === value ? "selected" : ""} onClick={() => setMode(value)}>{label}</button>)}
              </div><div className="composer-tools"><label>Top K <select value={topK} onChange={(event) => setTopK(Number(event.target.value))}><option value={3}>3</option><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option></select></label><button className="search-submit" disabled={!activeKb || !query.trim() || busy === "search"} aria-label="开始检索">{busy === "search" ? "…" : "↗"}</button></div></div>
            </form>
            <div className="search-meta"><span className="online-indicator" />{activeKb ? `检索范围：${activeKb.name}` : "请先创建知识库并导入文档"}<span className="meta-separator">·</span>{mode === "hybrid" ? "seekdb 内部 RRF 融合" : mode === "fulltext" ? "seekdb 全文索引" : "seekdb 向量索引"}</div>
            <div className="results-heading"><div><h2>检索结果</h2><p>{results.length ? `显示 ${results.length} 条数据库返回结果` : "输入查询后，这里将显示来自 seekdb 的结果"}</p></div>{results.length > 0 && <span className="count-badge">TOP {results.length}</span>}</div>
            {results.length ? <div className="results-list">{results.map((result, index) => <article className="result-card" key={result.id}><div className="result-rank">{String(index + 1).padStart(2, "0")}</div><div className="result-body"><div className="result-source"><span className="source-icon">▤</span><span>{String(result.metadata?.filename ?? "来源文档")}</span><span className="source-dot">·</span><span>分块 {Number(result.metadata?.chunkIndex ?? 0) + 1}</span></div><p>{result.document}</p><div className="result-tags"><span>{mode === "hybrid" ? "向量 + 全文" : mode === "vector" ? "向量匹配" : "全文匹配"}</span><code>{result.id.slice(0, 12)}…</code></div></div><div className="result-score"><small>数据库得分</small><b>{result.score === null ? "—" : result.score.toFixed(4)}</b></div></article>)}</div> : <div className="empty-results"><div className="empty-search-icon">⌕</div><b>结果会显示在这里</b><span>切换混合、向量或全文模式，比较 seekdb 返回的真实检索结果。</span></div>}
          </section>}

          {page === "documents" && <section className="documents-view">
            <div className="page-title-row"><div><div className="eyebrow"><span className="eyebrow-line" /> SOURCE LIBRARY</div><h1>文档管理</h1><p>查看已保存的原文、SHA-256 与索引分块状态。</p></div><button className="button button-primary" onClick={() => { setPage("home"); setTimeout(() => fileRef.current?.click(), 0); }} disabled={!activeKb}>＋ 导入文档</button></div>
            <DocumentTable documents={documents} open={openDocument} />
            {selectedDocument && <div className="document-detail panel"><div className="detail-heading"><div><span className="source-icon">▤</span><h2>{selectedDocument.filename}</h2></div><button className="icon-button" onClick={() => setSelectedDocument(null)} aria-label="关闭原文">×</button></div><div className="detail-meta"><span>{selectedDocument.chunkCount} 个分块</span><code>SHA-256 {selectedDocument.sha256}</code><span>{selectedDocument.status}</span></div><pre>{selectedDocument.content}</pre></div>}
          </section>}

          {page === "performance" && <section className="performance-view">
            <div className="page-title-row"><div><div className="eyebrow"><span className="eyebrow-line" /> RUNTIME & MEASUREMENTS</div><h1>性能记录</h1><p>计时来自浏览器 Worker 与实际 seekdb 调用，不预填加速比或质量分数。</p></div><div className="export-actions"><button className="button button-soft" onClick={() => downloadPerf("csv")}>导出 CSV</button><button className="button button-primary" onClick={() => downloadPerf("json")}>导出 JSON</button></div></div>
            <div className="panel performance-controls"><div><h3>推理配置</h3><p>切换精度会在浏览器 Worker 中重新加载模型权重。</p></div><label>精度<select value={precision} disabled={Boolean(busy) || modelState === "loading"} onChange={(event) => changePrecision(event.target.value as Precision)}><option value="auto">自动 · WebGPU 优先</option><option value="fp32">FP32 · WASM</option><option value="int8">INT8 · WASM</option><option value="fp16">FP16 · WebGPU（失败时降级）</option></select></label><label>Batch<select value={batchSize} disabled={Boolean(busy)} onChange={(event) => setBatchSize(Number(event.target.value))}><option value={1}>1</option><option value={4}>4</option><option value={8}>8</option><option value={16}>16</option></select></label><button className="button button-primary" disabled={Boolean(busy) || modelState === "loading"} onClick={() => void benchmarkPrecision(precision)}>{busy === "benchmark" ? "运行中…" : "加载并计时"}</button></div>
            <div className="metric-grid"><Metric label="当前推理后端" value={embedding ? `${embedding.backend} · ${embedding.dtype}` : "尚未加载"} detail={embedding ? `${embedding.dimension} 维 · ${embedding.modelId}` : model.id} /><Metric label="记录条数" value={String(performanceRows.length)} detail="保存在当前浏览器" /><Metric label="文档分块" value={String(documents.reduce((sum, doc) => sum + doc.chunkCount, 0))} detail="当前知识库" /><Metric label="数据库状态" value={databaseReady ? "已连接" : "未连接"} detail="seekdb-js · 本机 seekdb" />
            </div>
            {embedding?.fallbackReason && <div className="fallback-note"><b>WebGPU 回退已记录</b><span>{embedding.fallbackReason}</span></div>}
            <div className="section-heading perf-table-heading"><div><h2>原始计时记录</h2><p>包含模型文件字节数、端侧推理、数据库处理和网络往返。</p></div></div>
            <div className="panel perf-table-wrap"><table className="data-table"><thead><tr><th>阶段</th><th>时间</th><th>耗时</th><th>详情</th></tr></thead><tbody>{recentEvents.map((row, index) => <tr key={`${row.at}-${index}`}><td><span className="event-tag">{row.name}</span></td><td>{new Date(row.at).toLocaleTimeString()}</td><td>{typeof row.durationMs === "number" ? `${row.durationMs.toFixed(2)} ms` : typeof row.dbMs === "number" ? `${row.dbMs.toFixed(2)} ms` : "—"}</td><td className="event-detail">{Object.entries(row).filter(([key]) => !["at", "name", "durationMs", "dbMs"].includes(key)).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</td></tr>)}{!recentEvents.length && <tr><td colSpan={4} className="no-records">还没有性能数据。加载模型、导入文档或提交查询后，真实计时会出现在这里。</td></tr>}</tbody></table></div>
            <div className="model-provenance"><span className="provenance-icon">i</span><div><b>模型来源与文件体积</b><p>{model.id} · revision <code>{model.revision}</code> · 384 维。文件大小与压缩比只在浏览器真实加载相应权重后记录；不会预填估算值。</p></div></div>
          </section>}
          {showNewKb && <div className="modal-scrim" onClick={() => setShowNewKb(false)}><form className="modal-card" onSubmit={(event) => void createKb(event)} onClick={(event) => event.stopPropagation()}><button type="button" className="modal-close" onClick={() => setShowNewKb(false)} aria-label="关闭">×</button><div className="panel-icon lavender">▦</div><h2>新建知识库</h2><p>知识库将使用当前固定模型版本与独立 seekdb 索引。</p><label>知识库名称<input autoFocus value={newKbName} onChange={(event) => setNewKbName(event.target.value)} placeholder="例如：产品文档" /></label><div className="modal-actions"><button type="button" className="button button-soft" onClick={() => setShowNewKb(false)}>取消</button><button className="button button-primary" disabled={busy === "kb" || !newKbName.trim()}>{busy === "kb" ? "创建中…" : "创建知识库"}</button></div></form></div>}
        </div>
      </main>
    </div>
  );
}

function DocumentTable({ documents, open }: { documents: StoredDocument[]; open: (id: string) => void }) {
  return <div className="panel table-panel"><table className="data-table"><thead><tr><th>文档名称</th><th>状态</th><th>分块</th><th>摘要</th><th>创建时间</th><th /></tr></thead><tbody>{documents.map((doc) => <tr key={doc.id} onClick={() => open(doc.id)} className="clickable-row"><td><span className="file-badge">{doc.filename.toLowerCase().endsWith(".md") ? "MD" : "TXT"}</span><b>{doc.filename}</b></td><td><span className={`doc-status ${doc.status === "imported" ? "complete" : "pending"}`}><i />{doc.status === "imported" ? "已索引" : "待恢复"}</span></td><td>{doc.chunkCount}</td><td><code title={doc.sha256}>{doc.sha256.slice(0, 12)}…</code></td><td>{new Date(doc.createdAt).toLocaleDateString()}</td><td><span className="row-arrow">→</span></td></tr>)}{!documents.length && <tr><td colSpan={6} className="no-records">当前知识库还没有文档。支持 TXT 与 Markdown 文件。</td></tr>}</tbody></table></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="panel metric-card"><span>{label}</span><b>{value}</b><small>{detail}</small></div>;
}
