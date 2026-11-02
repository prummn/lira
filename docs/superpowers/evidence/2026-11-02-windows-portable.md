# Windows 同学试用包验收

产物：`dist/LIRA-2026.11.02-Windows-x64.zip`，177,626,633 字节，约 169.4 MiB。

SHA256：`45ac6190e288f2ee870725ed0c2dcddd905f9093f4e8c0f161b4a2da4f8aef41`。

提供完整解压后的启动/停止 CMD，浏览器界面与 API 由同一本地服务提供。随包包括
Python 3.13.15、现有后端运行依赖、前端构建与源码、提示词、数据库迁移、官方
Codex 0.154.0 Windows 原生程序及第三方许可。没有要求使用者安装 Python/Node/npm。

## 自动检查

- 前端 `npm.cmd --prefix frontend run build` 成功；只有已有的大 chunk 提示。
- `backend/tests/test_portable_release.py`：4 passed，覆盖空库、继承凭证隔离、静态
  文件访问边界、停止令牌、允许清单、疑似密钥拒绝，以及 HTTP 不可用时禁止启动第二个 worker。
  新增 JavaScript MIME 与服务锁检查均先观察失败再修复。仅既有 Starlette/httpx 弃用提示。
- 打包采用明确的源码/运行组件允许清单；敏感文件与内容扫描通过。包内无数据库、PDF、
  账户文件、模型连接、`.env`、个人聊天、日志或原文缓存。共 1,622 个受检文件及独立 manifest，
  SHA256 与最终 ZIP 一致，启动器正文与当前源码一致。

## 最终 ZIP 的实际运行

从最终 ZIP 解压到 `.local-runtime/最终发布包验收 中文 空格`，使用完全独立的
`.local-runtime/最终发布包验收数据`。子进程 PATH 仅保留 Windows System32，
故意放入假的继承模型配置，验证不依赖开发用的 Python/Node/npm 或继承凭证。

- 两个同时发起的启动均成功，只生成同一个实例；重复启动继续复用。
- 故意占住首选端口，服务自动使用其他空闲端口。仅绑定 127.0.0.1。
- 第一次 `/api/papers` 与集合均为 0，模型配置为空，没有演示论文或预登录账户。
- 随包的 Codex app-server 可运行，`available=true`、`authenticated=false`、`error=null`；
  没有借用开发者的登录状态，没有进行真实登录或生成调用。
- 包内 PyMuPDF 生成两页测试 PDF，成功导入、提取阅读段落、取回原始 PDF，并创建专题和笔记。
  测试论文 ID 不存在于开发文献库中。
- 用停止 CMD 优雅关闭，再启动后论文、专题和笔记仍存在；SQLite integrity_check=ok。
- 未授权停止返回 403；源码、运行程序、配置和数据库路径无法从 HTTP 获取。

真实 Playwright 浏览器通过最终包的服务地址打开文献库、阅读器、已保存笔记和设置页，
刷新后重新打开 PDF 并找回笔记。PDF worker 正常渲染，1440/1080 宽度无横向溢出，
无 pageerror 或请求失败，未发出分析/翻译/提问的 POST。截图已人工检查。

独立运行发现并修复：CMD 换行导致的中文路径兼容问题、临时状态文件后缀错误，以及
Windows 注册表将 JavaScript 标为 text/plain 导致页面空白的问题。发布器统一生成
CRLF 批处理，启动器为 JS、MJS、字体等设置确定的 MIME；没有改动现有开发启动方式。

测试在当前 Windows 宿主的隔离目录进行，并非在另一台同学的电脑或全新虚拟机中测试。
智能服务仍需使用者自己的网络与账号；本轮未替同学登录，也未做新的模型生成回归。

复测脚本、结果 JSON、截图位于 `.local-runtime/verify-student-release.py`、
`.local-runtime/verify-student-release-ui.cjs`、`.local-runtime/student-release-*`。
正式开发服务保持运行，测试服务验收后单独停止。
