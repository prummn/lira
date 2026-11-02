# 专题文章与闲时研究验收 · 2026-10-24

实现已接入现有 LIRA 服务与 SQLite。仅为现有「Memory初探-入门」启用后台研究，使用现有官方 ChatGPT Codex 连接；当前阅读模型路由未切换。默认空闲 180 秒、短窗口启动剩余 >50%、停止 <=35%、长窗口保留 >30%、每小时最多 6 次尝试。

## 真实试跑

以现有 Generative Agents 和 MemGPT 为材料，完成研读论证、写作、审读并发布第 1 版：

> 长期记忆不是仓库：Generative Agents 与 MemGPT 如何让过去进入下一次决策

正文浏览器提取 4,604 字符，18 处引用指向 16 个原文片段。全部存储引语均匹配相应原文，引用目标均存在，两篇论文均参与论证。原文预算选入 Generative Agents 71,316 / 129,958 字符（约55%），MemGPT 54,289 / 54,289 字符；文章主动说明选读边界，文末可查看每篇覆盖。

独立审查确认：文章以信息可访问性与行为/语义状态的区别组织论证；TrueSkill 的嵌套消融、Cohen's d、70%/100% 示例阈值与引用相符；架构组合明确作为待验证假设，而非已有结论。

试跑共记录 5 次步骤尝试：3 个阶段成功、1 次真实前台抢占、1 次旧调度在前台仍运行时过早恢复而遇到本地容量限制。该问题已补上前台请求持有计数并通过回归测试。成功步骤记录输入130,384、输出16,447 tokens；中断阶段的消耗未知，不能当作退还额度，亦不能用这些 token 推算订阅余额。

## 优先级和恢复

在审读阶段发起现有官方连接的前台测试请求，后台于约 **0.44秒** 后进入 paused；前台 HTTP200，随后后台从审读步骤恢复并发布。耗时为本次本机实测，不承诺所有环境的固定延迟。

实现与回归还覆盖：多桶额度及未知窗口、无额度时暂停、单账号不重叠、仅官方连接的原子选择、研究方向回退、历史版本保留、无效引文与各种 Markdown 引用目标、材料中途变化、保存失败后恢复、有限重试与小时预算、关闭服务取消。

服务重启后文章与任务保留，材料未变没有新增模型调用。发布前后的 papers、notes、knowledge_candidates、knowledge_relations 数量分别保持40、5、82、56，SQLite foreign_key_check 为空。迁移前通过 SQLite backup API 保存快照。

## 界面与检查

- `backend/.venv/Scripts/python.exe -m pytest -q`：**741 passed**。保留一项已有 Starlette/httpx 弃用提示。
- 相关浏览器回归52项：51项通过，1项真实PDF可选夹具跳过。来源浮窗的焦点恢复问题修正后，专题文章2项再次通过；新增的额度刷新也通过。
- `npm run build`：通过。仍有既有的包体积提示。
- 实际浏览器：无 pageerror；1440px浅色、深色、430px窄屏检查通过；430px下 document宽430、文章宽338，无横向溢出。
- 点击真实引文进入PDF，再返回文章恢复scrollTop2144；版本选择、导出Markdown、键盘关闭浮窗与应用内设置通过。
- 本地健康检查通过，服务地址 `http://127.0.0.1:5173`，API8000。

本地试验记录与截图位于 `.local-runtime/research-20261024/`（已忽略提交），包括 `foreground-preemption.json`、`memory-essay-live.json`、`browser-verification.json`、`final-live-state.json` 以及浅色、深色、窄屏、原文、PDF和设置截图。使用方法写入README，架构与表结构同步更新。

## 第一版边界

本版维护专题主文章和有限更新任务；论证提纲由模型安排。没有开放无限派生任务、外部文献自动追踪或自动改动知识目录。每专题最多40篇，长文选读范围公开展示；匹配引文和模型审读不能代替研究者判断。

官方额度接口按 [app-server 文档](https://developers.openai.com/codex/app-server/) 的 `account/rateLimits/read` 与多桶字段解析。额度与实际模型/上下文相关，参见 [Codex pricing](https://developers.openai.com/codex/pricing/)，未硬编码套餐窗口，也未把token换算为订阅百分比。
