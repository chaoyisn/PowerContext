# 待提交文件清单

- 仓库 `stepfun/` 中的 Web 应用、源码、依赖锁定文件、启动脚本、测试与 `docs/`。
- 一页技术说明：`docs/TECHNICAL_ONE_PAGE.md`。
- 封版后本地生成 `deliverables/EdgeSeek-StepFun-Final.zip`，生成方法及 SHA-256 见 `deliverables/package-manifest.json`；ZIP 与表单留在本地，不纳入 Git。
- ZIP 含源码、原创样例、V4 JSON/截图、选定测试日志和 SQL 执行边界证据；不含 `node_modules`、本地模型权重、数据库数据、`.env`、浏览器缓存、Git 目录或绝大多数临时日志。历史完整证据保留在仓库的 `benchmark/results/v2/` 和 `v3/`。
- 模型权重不随包提交：运行 `npm run fetch:model` 从固定 revision 获取并校验。提交前确认平台实际支持的格式、体积和仓库权限。
