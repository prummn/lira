# 固定发布流程实际验收

已从项目根目录运行 `scripts/release.ps1`，而非手工拼接各阶段。

自动生成版本 `LIRA-2026.11.02.3-Windows-x64`，候选在 `.local-runtime/releases/` 中构建和解压；通过验收后发布到 `dist`。

- 后端发布相关回归 322 passed，模型设置界面 9 passed，前端生产构建通过。
- 新增发布门槛用例先观察到 11 failed，再实现后通过；补充失败保留报告及清单内私人文件拒绝测试，当前工作流测试共 13 passed。
- ZIP 文件清单和 SHA256、私人文件及凭证检查通过；最终 ZIP 独立运行验收和浏览器验收通过。
- 覆盖端口冲突、同时/重复启动、空库和凭证隔离、随包 CLI 未登录、PDF 阅读、专题/笔记/账号并发设置重启持久化、HTTP 私有路径隔离、1440/1080 布局和刷新。
- 本轮测试服务已关闭，开发服务仍健康；开发论文库仍为 46 篇、34,189 个文本块、5 条笔记。旧 .2 ZIP 哈希保持不变。
- 只有验收通过的 ZIP、SHA256 和 JSON/Markdown 报告晋升到 dist，latest.json 指向 .3。

ZIP SHA256：`d029a50fa6c7b6d8a6c6796fd6a650d9fe7547a5406d3560a192152f0968bbd8`。

阶段报告：`dist/LIRA-2026.11.02.3-Windows-x64.report.json`。

日志与截图：`.local-runtime/releases/LIRA-2026.11.02.3-Windows-x64-8f5db26e/`。报告中的 verification/checks 均为 true，浏览器无 pageerror/失败请求/模型生成 POST。

验收在当前 Windows 主机上进行，不代表另一台电脑或远端模型服务验证。此流程不自动上传、推送或发送文件。

## 独立审查后的第二轮验证

修复超时/中断时的父进程清理及发布后报告误报问题。新增三条失败回归先得到 3 failed，修复后发布工作流与便携测试共 20 passed。真实启动独立测试服务并触发阶段超时，父进程安全停止测试服务；拒绝操作其他安装目录。

再次从 scripts/release.ps1 完整执行，生成 .4 版本：327 项后端回归、9 项界面回归、构建、最终 ZIP 隔离运行和浏览器验收均通过。独立复审未发现剩余重要缺陷。

最新产物：dist/LIRA-2026.11.02.4-Windows-x64.zip

SHA256：dde0d8771dd9f9777bcc83e00fbebbde820ae0f8978f2d19165cdc11d6613a13

报告：dist/LIRA-2026.11.02.4-Windows-x64.report.json

运行目录：.local-runtime/releases/LIRA-2026.11.02.4-Windows-x64-c8e3018e。测试服务已停止，旧 ZIP 和个人库保持不变，正式开发服务健康。
