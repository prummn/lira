# 后台预译的正文范围

日期：2026-10-28

新建全文预译任务在首次识别到的附录、补充材料或参考文献章节之前停止，边界之后的内容都不入队。正文和图表说明仍按既有队列规则处理；手动选择的附录或参考文献段落不受此范围限制。

范围判断只读取本地章节元数据和原文块顺序，不调用模型，不依据正文中偶然出现的 Appendix/References 字样截断。判断也会读取阅读器过滤掉的标题块，避免附录总标题后直接出现编号小节时漏掉边界。没有识别到边界时保留全部可译段落，并在界面明确说明。

任务保存 `scope_total`、`scope_skipped`、`scope_reason`；阅读器和后台任务页共用范围提示。旧任务未记录范围时不冒充已经排除附录；新规则不重写旧任务或已有译文。

## 实际资料检查

用本机已保存论文的原文、PDF 版式和分段记录运行范围判断。以下是可译正文与被排除后续段落的数量，包含可用图注；没有为本轮验证新生成译文。

| 论文 | 保留段落 | 跳过段落 | 首个被跳过的章节 / PDF 页 |
| --- | ---: | ---: | --- |
| ReAct | 52 | 152 | REFERENCES / 10 |
| Reflexion | 70 | 106 | References / 10 |
| Generative Agents | 150 | 162 | REFERENCES / 19 |
| MemGPT | 58 | 94 | References / 9 |
| SWE-bench | 85 | 484 | REFERENCES / 12 |
| SWE-agent | 91 | 682 | References / 10 |

## 回归结果

- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`：924 passed。覆盖附录先于参考文献、阅读器移除总标题、英文与中文标题变体、未识别边界、手动选择后续段落、全局状态以及旧数据库升级。
- `npx playwright test tests/translation-reading.spec.ts`：25 passed。
- `npx playwright test tests/background-tasks.spec.ts`：5 passed。覆盖范围与跳过数量、旧任务不显示错误范围、无边界时的提示、手选任务不套用自动预译范围。
- `npm run build`：成功。
- `git diff --check` 及相关新增文件的行尾空白检查：通过。
- 人工查看桌面后台任务截图和 390px 阅读器截图；范围提示在现有进度区内，窄屏无横向溢出。

## 本地运行验证

升级前通过 SQLite backup 保存了 `.local-runtime/backups/before-pretranslation-scope-20261028-124450.db`，并确认没有运行中的问答、翻译、分析或研究任务后重启服务。

运行库现为 `0018_translation_scope`。对比升级前备份，以下表原有列的全部记录一致：41 篇论文、16,737 个原文块、5 条笔记、644 条译文、5 个翻译任务、606 个翻译项、13 个对话和 16 轮消息。数据库完整性与外键检查均通过。

运行中的前端 `http://127.0.0.1:5173` 返回 200，后端健康状态为 `ok`。单篇翻译任务接口及全局后台状态接口均返回范围字段。
