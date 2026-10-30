# EdgeSeek V4 审核记录

## 已取得的证据

- 浏览器本地 q8 与物理 WebGPU FP16；有窗口 Chrome、Edge 完整交互与隔离 TCP 代理数据库中断/恢复。
- 刷新中断后 processing、稳定 document ID、重复跳过、六并发查询、有界停滞与启动失败：`benchmark/results/v4/disconnect-queue-final.json`。
- GPU 推理中途受控失败、q8 整批重算和不兼容空间拦截；20 次 FP16 推理的 L2、余弦与 Top 5：`gpu-runtime.json`、`gpu-stability.json`。真实 Device Lost 未复现。
- 100 文档、30 查询、三种精度、向量与混合结果：`quality-*.json`；模型冷/热、缓存证明、五次查询与应用批处理：`summary.json` 和相应原始文件。
- V4 SQL 执行边界生成语句与执行语句哈希一致，结果 ID/原文/得分/顺序一致：`trace-verification.json`。
- 2026-10-30 最终队列版本 TypeScript/生产构建、unit 4/4、seekdb integration 3/3、Chrome/Edge E2E 2/2 通过；两种有窗口浏览器分别通过 API 重启、隔离代理断连及恢复回归，详见 `benchmark/results/v4/v41-*-recovery.json`。

## 交付限制

- 连接故障采用独立 TCP 代理，未停止数据库容器；不是物理机器或真实 GPU 故障。
- GPU 内存与真实进程峰值 UNKNOWN；工作集只报告采样最大值。冷/热初始化各一次；查询及导入策略各五次。
- 冻结质量集为原创合成事实，标签按构造生成而非独立人工标注；跨语言召回较低。
- 提交 SHA 与最终打包记录在封版后生成的本地 `deliverables/FINAL_FORM.md` 和 `package-manifest.json` 中；实际平台表单字段由参赛者核对。
- 按用户提供的 StepFun 赛题原文映射三类产物：可运行 Web 应用、完整源码、一页技术说明；无需引入云端 Embedding API 或其他赛题的发布要求。

## ZIP

ZIP 由 `python scripts/package-v4.py` 生成，并执行 CRC、实际解压及逐文件 SHA-256 比较；最终文件列表和压缩包 SHA-256 写在 ZIP 外的 `deliverables/package-manifest.json`。提交到平台须由用户手动操作。
