# 可持续运行的逐段翻译

## 用户行为

手选若干段落后立即加入持久队列。已完成的任意段可直接打开，批量面板可以关闭，翻页、切换论文或刷新浏览器不取消工作。PDF 悬浮操作和段落列表区分待翻译、检查分段、翻译中、已完成和失败；直接选择排队段落会把它提到前面，避免重复请求。已有翻译继续可读。

全文入口为「后台预译全文」：明确使用后台设置中的官方连接，按正文顺序逐段处理正文与图表说明，略过参考文献和解析时已排除的页眉作者信息。用户无需把论文标为喜欢来隐式授权；点击该入口就是对这一篇的授权。预译可以暂停、继续、取消和重试失败项，停止不删除已完成译文。没有后台官方连接时显示设置指引，不转用付费备用 API。

批量选择界面继续保留当前页/全文范围与复选框，不改成新的管理大页面。队列进度独立于选择面板和当前译文；关闭选择面板不停止翻译。结果到达只更新缓存与状态，不抢走正在读的段落。切换模式或论文不导致排队丢失。

## 调度

沿用唯一 `BackgroundResearchWorker`，翻译队列作为可恢复的任务源。手选翻译是明确用户任务，可在阅读时逐段执行，不要求全局后台开关；提问、单段翻译及分析可以中断它，并在请求完成后续跑。全文预译同样在阅读时继续，要求后台开关及官方连接，遵守短窗口启停、长窗口保留、持久日预算和共享每小时调用限制。阅读心跳不触发翻译抢占，真正的前台模型工作拥有优先权；官方账号仍单并发。专题研究与知识维护继续等待闲置，仅在能够执行时才参与轮换。

同一篇论文重复提交相同段落复用活动任务和翻译缓存；手选优先于全文预译，段落被手动打开时可提升优先级。边界检查也属于模型调用，全文模式每次调用前均门控、记录并提交；不能用一次段落任务隐藏多次模型请求。手动任务不受闲时预算限制，但不可挤占正在进行的显式问答。按段持久化结果；服务退出时恢复未完成任务，不重做已保存内容。

整篇暂停后仍可选择原文、查看已完成译文；暂停中的未译段落不显示持续加载。明确点击「翻译此段」只授权这一段手选任务，保留整篇暂停，不能因选读或提升优先级恢复其余段落。

## 数据与安全

新增迁移 `0017_translation_queue`，保存翻译作业及段落项。作业记录论文、模式、固定模型连接/配置标识、状态、等待原因及调用记录；段落项记录原始和当前段落 ID、原文快照、来源 refs、顺序/优先级、阶段、错误、有限尝试和可复用的结果定位。凭证仍仅存在模型配置。

翻译缓存继续使用现有 `translations` 表与原文/模型/提示词身份，不另建副本。直接翻译与队列共用缓存存取。模型或原文变化须在调用前后检查，避免把旧结果写成新段落；分段合并通过 refs 和原文切片映射回新段落，更新 aliases，已合并的相邻项复用同一译文。失败的分段检查不得继续翻译碎片。取消与暂停在发布时复核，已返回的合法译文可保留为缓存，但不能把整批误标完成。失败项最多两次自动尝试，用户可以重试；暂时的前台抢占/容量门控不当作内容错误。

## API 合约

- `GET /api/papers/{paper_id}/translation-jobs` → `{jobs: TranslationJob[]}`。
- `POST /api/papers/{paper_id}/translation-jobs`，`{mode:'selected'|'full', paragraph_ids?:string[]}` → `TranslationJob`。
- `POST /api/translation-jobs/{job_id}/{action}`，action 为 pause/resume/cancel/retry → `TranslationJob`。
- `POST /api/papers/{paper_id}/translation-jobs/prioritize`，`{paragraph_id:string}` → `TranslationJob`，把已在队列中的段落提为手动优先。

`TranslationJob` 为 `{id,paper_id,mode,status,reason,error,model_name,completed,total,failed,items,created_at,updated_at}`；状态 queued/running/paused/completed/cancelled/failed。`items` 为 `{id,paragraph_id,original_paragraph_id,aliases:string[],status,phase,error,page,translation?:{text,model}}`。项状态 queued/running/completed/failed/cancelled；phase checking/translating 等补充正在做的事。reason 使用可解释的等待代码（reading、quota_reserve、daily_budget、disabled、profile_required 等）。接口最多返回当前及最近有限历史，不在轮询中重复传整份原文。

前端抽为 `useTranslationQueue`；轮询获取增量结果，合并译文、状态及分段重定向。发现新段落 ID 时重新读取 reading-paragraphs，并保留选段。批量及全文进度都可在阅读器看到；页面卸载仅停止轮询。

## 验证

自动覆盖：请求快速返回、逐段可读、活动去重/缓存跳过、混合失败、暂停取消重试、刷新和服务恢复、原文与配置变化、分段合并、手动提升、前台抢占、阅读不挡翻译、同一在途段落不重启、冷却任务不阻塞其他段落、共享预算包含分段检查、未知额度不执行、无付费回退、迁移保留既有数据。浏览器覆盖完成第一段时第二段仍运行但可展开第一段、离开返回、全文队列和窄屏无溢出。最后使用真实库与官方连接逐段试跑，核查持久结果和额度状态。
