# 参与开发

LIRA 当前为私有协作项目。项目代码、测试和发布脚本进入 Git；个人论文库、阅读记录、模型连接和账号状态留在各自电脑上。

## 准备环境

需要 Python 3.11+、Node.js 20+ 和 Git。Windows 下克隆仓库后，在根目录运行：

```powershell
git clone https://github.com/prummn/lira.git
cd lira
.\scripts\start.ps1
```

启动脚本准备后端虚拟环境及前端依赖。模型连接通过应用内设置配置，不需要向维护者索取配置文件。只阅读、搜索和记笔记时可以不配置模型。完整操作见 [README](README.md)。

## 分支与提交

`main` 保存可协作的当前版本。每项改动从最新 `main` 新建分支，完成后提交 Pull Request：

```powershell
git switch main
git pull --ff-only
git switch -c feat/short-description
```

修复、文档和维护可使用 `fix/`、`docs/`、`chore/` 前缀。提交说明交代具体变化；PR 说明问题、改动和验证结果。涉及阅读器交互时附截图，涉及后台调度时说明优先级、并发和失败恢复行为。不要顺手重排无关代码。

## 验证

在项目根目录运行后端测试和前端构建：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd --prefix frontend run build
```

首次运行浏览器测试，需要安装 Chromium：

```powershell
Push-Location frontend
npx.cmd playwright install chromium
npm.cmd run test:e2e
Pop-Location
```

浏览器测试会启动独立服务，并核验临时数据库及文件目录的身份。8010/5177 端口被占用时先检查原因，不要改成正在使用的个人工作台端口。测试应使用合成数据或最小化、来源明确的文本 fixture；需要真实 PDF 的实测资料保存在忽略目录中。

GitHub Actions 检查历史凭证、后端测试和前端构建。Windows 浏览器回归可从 Actions 手动运行。CI 不配置个人 API key、不登录个人官方账号，也不以真实模型调用作为合并前提。

## 数据和发布

提交前检查 `git diff --cached --stat` 和 `git diff --cached`。不要使用 `git add -f` 绕过论文、数据库、模型配置或登录状态的忽略规则。复现问题时先将资料脱敏；数据库和 `.env` 不能作为 issue 附件。

数据库结构变化通过 Alembic migration 交付，验证空库和已有数据库升级，保留个人笔记及人工知识决定。模型回复必须保留来源校验；不要通过降低校验条件来掩盖失败。

Windows 分发使用 `.\scripts\release.ps1`。只分发已验证的 ZIP，不直接压缩开发目录，详见 [发布流程](docs/DISTRIBUTION.md)。Git 仓库不存放构建产物。

## 开源前

当前尚未选择开源许可证，仓库可见性保持私有。公开前需要由维护者确定许可证、核对依赖许可和品牌素材来源，并重新检查完整 Git 历史、文档及测试 fixture 的可公开范围。新增协作者由仓库所有者在 GitHub 邀请。
