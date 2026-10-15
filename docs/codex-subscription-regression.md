# Codex 订阅接入验证

日期：2026-10-15。用户选择的是 ChatGPT Plus / Pro 等计划包含的 Codex 使用额度。

## 实现边界

- 官方 `codex-cli 0.147.0` 的 app-server 管理 OAuth、账户与额度；`codex exec` 承担单次研究请求。
- 使用独立 `.env.models.json.codex/` 和文件凭证存储。应用不读取、返回或转存令牌，不改变桌面 Codex 的账户。
- 子进程去掉继承的 `CODEX_*`、`OPENAI_*`、`PAPER_READER_*` 环境变量，仅设置自己的 `CODEX_HOME`，固定官方 provider 和 ChatGPT 登录方式。
- exec 使用临时空目录、忽略用户配置与项目规则、只读沙箱、关闭 shell/浏览器/子代理/插件/图像工具，单独设置 `web_search="disabled"`。论文经 stdin 传入；不记录原始 stderr 或上游错误。
- CLI 的输出预算是目标值，没有硬 token 上限。每次调用仍有时限、输出大小限制和进程清理；最终 JSON 与证据继续由现有研究流程核验。
- 多份 Codex 配置共用一个账户容量门。登录失败直接报告；临时账户服务故障、额度限制及网络失败可进入用户明确开启的备用路由。

## 自动验证

后端使用临时假的 CLI 进程验证真实 subprocess/RPC 边界，覆盖无密钥保存、密钥丢弃、API 连接保留、账户接口、OAuth 成功/失败/取消、非官方 URL 拒绝、敏感字段过滤、环境隔离、真实用量映射、超时、过大与未完成输出、账户容量共享、恢复后保留答案、服务关闭清理子进程、额度及账户超时转备用。

浏览器覆盖订阅连接类型、隐藏 API 字段、官方登录链接、完成后自动刷新、账户/额度显示、无 key 保存、退出、缺少 CLI、账户服务暂时失败后刷新恢复，以及原有多连接切换和并发保存。完整浏览器回归的真实联网导入用例按默认配置跳过。

独立审查找到并修复：内置网页搜索未单独关闭；CLI 重连警告误当终止失败；账户服务暂时错误误归为认证失败。复核确认修复，并独立运行恢复、关闭、额度备用与账户超时备用四项测试。

验证结果：

- 全量后端：`552 passed`。
- 全量浏览器：`62 passed, 1 skipped`；随后增加账户服务超时界面恢复用例，订阅与原有连接专项最终 `6 passed`。
- 最终生产构建：`npm run build` 通过。
- `git diff --check` 通过。

## 本机实际检查与待完成步骤

已用独立临时 home 验证官方 app-server 的初始化和账户读取，返回未登录。实际 LIRA 后端已在空闲时重启，新增未启用的“ChatGPT Codex”配置，并成功得到官方 OAuth 地址；原有中转主连接保持启用。没有复制现有 Codex 凭证。

用户仍需在设置中的官方页面亲自登录。真实订阅模型权限、官方额度返回以及一次小型推理请求尚未验证，不能将其记为已配置成功。完成授权后应载入最终后端代码，测试订阅连接，再启用；保留中转配置供用户手动或明确开启的自动备用使用。

官方依据：

- [认证方式](https://developers.openai.com/codex/auth/)
- [账户与额度协议](https://developers.openai.com/codex/app-server/)
- [非交互调用](https://developers.openai.com/codex/noninteractive/)
- [模型选择](https://developers.openai.com/codex/models/)
- [关闭内置网页搜索](https://developers.openai.com/codex/config-reference/)
