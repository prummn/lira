# 私有仓库与协作准备

仓库：<https://github.com/prummn/lira>，所有者 `prummn`，可见性为 private，默认分支 `main`。

## 上传边界

上传当前代码、测试、提示词、设计记录和发布脚本。保留已有 Git 历史以及本地 `develop`、`codex/science-review` 分支；不重写历史，不推送其他本地分支。

`.gitignore` 排除 SQLite 及其侧文件、PDF/CAJ、论文目录、环境配置、模型连接与账号状态、调试目录、依赖、日志、测试产物和发布 ZIP。忽略规则的代表性路径已用 `git check-ignore --no-index` 验证，`.env.example` 与应用源码仍可跟踪。本地原文件保留，不做删除或移动。

## 审计和验证

- Gitleaks v8.30.1 从官方发布下载，归档通过官方 SHA256 清单核验。
- 现有 49 次提交扫描无凭证发现；本次暂存改动扫描无凭证发现。
- 对历史和暂存区共 945 个 blob 进行本机凭证精确匹配检查，4 个本机凭证均无匹配。报告只记录计数，不保存或输出凭证值。
- 跟踪文件检查无论文 PDF、个人数据库、账号文件或运行目录。
- 后端完整回归：1131 项通过，1 条现有 Starlette/httpx 弃用提示。
- 前端 TypeScript 与生产构建通过，仍有原有较大 chunk 提示。
- 暂存差异通过空白检查。

审计日志保存在忽略目录 `.local-runtime/repository-bootstrap/`，不上传。

## 协作约定

新增 CONTRIBUTING、SECURITY、CODEOWNERS、PR 与 issue 模板、EditorConfig 以及 Windows 命令文件的换行约定。默认使用功能分支和 PR，合并后删除远端功能分支。

GitHub Actions 自动执行完整历史凭证扫描、Windows 后端回归和前端构建；隔离的 Windows 浏览器回归通过手动工作流启动，不使用个人账号与真实模型。依赖安全告警已开启。

尚未授予开源许可证，仓库保持私有。公开前仍需确定许可证，核对素材与 fixture 的许可、文档中的个人信息及完整历史。凭证扫描通过不能替代这些公开前检查。
