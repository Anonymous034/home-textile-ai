# 详情页：先确认文字方案，再生成整套图片

## 当前实现

`/detail-page` 保留原有左画布、右参数的界面及原有样式。入口仍只有“生成图片”，不恢复已删除的“生成详情页方案”按钮。

点击后打开暗色原生 dialog：

1. 上传真实产品素材，调用文字策划模型，只生成方案 JSON，不调用图片模型。
2. 列出按顺序编排的卡片：主题、图片展示内容、风格、画面标题/正文、文字位置、参考素材编号。
3. 用户直接打字修改；可拖拽或用上下箭头排序，支持增删，最多 12 张。关闭审阅弹窗可暂存在当前页面内；相同参数再次点击继续编辑。参数改变则重新策划。
4. 只有点击“确认方案，生成 N 张图片”才 POST 图片任务。提交的是编辑后的完整快照，使用实际卡片数量。
5. 以最多 2 张并发生成，显示成功数和已处理进度；结果保留方案顺序，不按完成先后排序。
6. 完成后可逐张下载或导出 ZIP；关闭弹窗后，画布依次展示成功的详情图。

这里的整套输出是商品详情页图片序列，不是软件流程图。未增加新的主页面布局。原积分展示保留为估算；新接口不执行账户扣分，供应商调用费用以供应商记录为准。

## 配置前提（真实 AI 尚待验收）

现有 ARK_IMAGE_* 配置供图片生成使用。文字策划需要单独配置支持图片输入的 messages/choices 格式聊天接口，在 backend/.env 中设置：

```dotenv
DETAIL_PLAN_ENDPOINT=供应商提供的完整HTTPS聊天接口地址
DETAIL_PLAN_MODEL=具备图片理解能力的模型或接入点ID
DETAIL_PLAN_API_KEY=该接口对应的密钥
```

不猜测模型名称、不把图片专用密钥发送给未知文字接口、不用确定性模板代替 AI 方案。缺少配置时明确返回 503，说明所缺配置，且不发起图片任务。配置后需重启后端。密钥不可写进前端或提交 Git。

文字适配器传入缩小后的产品参考图和用户资料，要求返回严格 JSON，再执行 Pydantic 校验；格式错误不会自动重新请求模型。图片适配器复用已有安全下载、比例校验和出图通道，但使用独立的详情页提示词，不套用“爆款复刻”提示词。

当前图片上的文字由图像模型生成，不能保证逐字准确；完成界面明确要求核对字样和产品细节。严格排版引擎、多语言字体嵌入属于后续工作，不宣称已实现。

## 文件

- app/ui/DetailPageLab.tsx：原页面入口、上传 File 保留、结果画布。
- app/ui/DetailPageLab.css：原样式未改。
- app/ui/DetailPlanDialog.tsx / .css：两阶段弹窗、可编辑方案、排序、进度、导出。
- app/detail-page/models.ts：InputParams、PlanItem、PlanDocument、GenerateTask；1–12 张和原页面的比例/分辨率。
- app/detail-page/api.ts：HTTP 适配、幂等标识、结果地址约束、超时查询。
- backend/app/detail_models.py：服务端输入、顺序、素材引用和终版参数校验。
- backend/app/detail.py：素材、策划、任务、结果文件、ZIP 路由及 SQLite 持久化。
- backend/app/providers/detail.py：文字模型和详情图生成适配。
- app/ui/DetailSuiteWorkflow.tsx：旧独立参考组件，仍未挂载；其中单卡 AI 改写/重绘入口不是当前正式功能。

## 状态与数据约束

```text
原页面 → 弹窗 planning → review（手动编辑/排序）
                         ↓ 明确确认
                      submitting → rendering → finished
策划失败 → error（显示真实错误，不自动出图）
POST 结果不确定 → GET 原请求编号（不重复 POST）
```

PlanDocument 固定 schemaVersion=1.0，正式接口只接受 source=ai。PlanItem 含 id、order、theme、visualDescription、stylePrompt、textOverlay、sourceImageIds。完整格式见 detail-plan.schema.json 和 detail-plan.example.json。Schema 同时保留 template 枚举仅供离线示例；在线后端拒绝 template。

稳定卡片 ID 不因排序改变；order 必须从 1 连续排列；items 数量必须与 input.imageCount 一致。编辑增加 revision。后端验证 planId 曾完成策划、素材和产品参数未被替换、引用的产品图均属于该方案。允许编辑卡片和增删张数，不允许偷偷更换产品参数。

图片任务接收终版 plan、相同 input、asset 映射以及浏览器创建的 taskId。先落盘快照，再派发生成。相同幂等键/请求体返回原记录，不同内容返回 409。不自动重试已发出的模型请求；继承的图片适配器仅在明确的尺寸拒绝提供了限制证据时做一次等比例参数修正。

## 已实现接口

| 方法 | 路径 | 响应 |
| --- | --- | --- |
| POST | /api/detail/assets | 200 { assetId }；multipart file/clientId |
| POST | /api/detail/plans | 200 PlanDocument；input/assets |
| GET | /api/detail/plans/{id} | running/completed/failed；完成附 plan |
| POST | /api/detail/tasks | 202 GenerateTask；确认的 RenderRequest |
| GET | /api/detail/tasks/{id} | 当前任务状态 |
| GET | /api/detail/tasks/{id}/images/{itemId} | 图片，?download=true 为附件 |
| GET | /api/detail/tasks/{id}/export | ZIP，含有序 PNG、终版方案与任务状态 |

POST 都使用 Idempotency-Key。错误响应为：
```json
{"detail":{"message":"面向用户的安全说明","uncertain":false}}
```

不直接输出供应商原始响应或密钥。前端只接受 /api/detail/ 范围内的结果地址。

## 并发、持久化与限制

- 本地 FastAPI **单进程**运行；最多两个策划任务、两个套件任务，图片全局并发 2。
- SQLite detail_records 独立保存素材、幂等摘要、方案、终版快照、每图状态。文件存 backend/data/detail。
- 重启后把未完成调用标为失败/不确定，不自动重放付费请求；已完成图保留。
- 成功+失败数量决定处理进度；100% 已处理不代表全部成功。partial 可导出成功项，并在 ZIP 的 task-status.json 中保留失败说明；图片编号不因失败项而重排。
- 前端草稿和当前任务引用仍保存在当前页面内，刷新会丢失这些引用；处理中有离开页面提醒。服务端记录不随刷新丢失，但尚无用户任务历史/恢复界面。
- 仅允许本机调用和配置的前端 Origin；验证上传内容，单张 ≤20MB、≤2400 万像素；模型返回文件安全验证后才公开。
- 图片尺寸按选定比例精确等比计算，长边目标为 1024/2048/4096；输出下载前验证。非整数比例尺寸采用最大不超过目标长边的整数倍。
- 当前为本地工具，不含生产级登录、配额结算、清理策略和跨进程队列。生产部署前应接入持久化队列、身份与数据归属校验。
- 单卡 AI 重策划/单图重绘尚未接入当前弹窗，本次按最新需求实现人工编辑后整套生成。

## 验证

后端替身测试覆盖：确认前无图片任务、修改文案/画面描述后传给渲染器、排序与 ZIP 顺序、重复提交不重复调用、过期参数/未知素材/错误顺序拒绝、部分失败、重启不重放、来源与上传校验、缺失策划配置。

前端测试覆盖顺序、稳定 ID、原页面 12 张/1K/9:16 参数、接口错误与不确定提交处理。替身测试不会调用真实付费模型，不能视作 AI 质量或真实密钥/模型权限验收。
