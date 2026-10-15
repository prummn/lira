# Codex 订阅连接

用户希望在 LIRA 使用 ChatGPT Plus / Pro 等计划中的 Codex 额度。它与 OpenAI Platform API 余额是两种认证和计量方式；现有 API key 表单不能完成订阅登录。

采用官方 Codex CLI：app-server 管理浏览器 OAuth、账户状态和只读额度查询；`codex exec` 提供无界面的模型调用。另一种可行方案是通过 app-server 完成全部推理，但当前应用已具有独立请求、缓存和证据校验流程，单次 exec 更容易保留这些边界。官方依据：

- https://developers.openai.com/codex/auth/
- https://developers.openai.com/codex/app-server/
- https://developers.openai.com/codex/noninteractive/
- https://developers.openai.com/codex/models/

设置页新增“Codex 订阅”连接类型。选择后展示官方登录按钮、登录中的授权链接、账户/计划、官方返回的用量窗口、刷新和退出入口。API 地址、密钥、HTTP 协议等字段不用于这个类型。模型默认沿用官方当前支持且用户偏好的 `gpt-6.1-sol`，推理强度和超时可设置。保存、启用、备用顺序与现有连接共用。

LIRA 使用与配置文件相邻、被 Git 忽略的独立 Codex home，强制文件凭证存储和 ChatGPT 登录，所有子进程固定官方 provider；父进程的 Codex 配置及账户不改变。令牌由 CLI 保存和刷新，应用不解析、返回或转存令牌。继承环境中的模型供应商凭证和端点覆盖会从子进程环境移除。

推理在独立临时工作目录中执行，禁用 shell、浏览器、外部工具和子代理，使用只读沙箱、临时会话和结构化最终输出。请求文本通过 stdin 传入，不出现在命令行或日志。仅解析白名单 JSONL 事件，记录实际 token 用量，设置超时并清理子进程。Codex 没有 HTTP 接口式的硬输出 token 参数；现有预算作为输出目标，调用次数和时间仍受 harness 限制。

每个应用订阅账户默认只允许一个同时请求；占用、额度暂时耗尽、连接故障进入现有可重试/备用逻辑，登录失败和无效模型直接报告。缓存区分 Codex 与 HTTP 连接，卡片、翻译、问答和 AI 文献员继续经过现有本地校验。

自动测试使用假的 CLI 子进程协议和临时账户目录，覆盖账户状态、OAuth 完成/取消/失败、敏感字段过滤、额度缺省、exec 成功/错误/超时、环境隔离、缓存及备用、界面登录和切换。登录前可完成这些验证；真实登录由用户在官方页面完成，然后进行一次小请求，并检查官方额度接口返回。
