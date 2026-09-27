# 买家秀：生活场景渲染提示词后端

## 部署范围

现有本地 FastAPI 单进程服务增加 `/api/buyer-show/*`。页面采用“先策划、后确认出图”的两阶段流程：点击“生成图片”先获得严格 JSON 并在弹窗中审阅、修改；只有点击“确认方案并生成图片”才会创建真实图片任务。图片调用复用本项目已经配置的本地 Agent Plan 图像适配器。

生成内容为引擎中立的英文提示词；负向字段由具体渲染引擎适配器处理。本实现不宣称各引擎都原生支持同一种负向提示接口。

## 配置

在 `backend/.env` 本地配置以下三项，再重启后端：

```dotenv
BUYER_PLAN_ENDPOINT=供应商提供的完整HTTPS聊天接口地址
BUYER_PLAN_MODEL=模型或接入点ID
BUYER_PLAN_API_KEY=对应的文字策划模型密钥
```

要求 messages/choices 格式聊天接口；上传产品图时模型必须支持图片理解。三项全部未填时，先尝试复用完整的 `DETAIL_PLAN_ENDPOINT`、`DETAIL_PLAN_MODEL`、`DETAIL_PLAN_API_KEY`。两组都未配置时使用本地规则策划模式，保证提示词流程可运行，但会明确标记为 `local_rule`，不冒充视觉模型识别。只配置部分 BUYER_PLAN_* 时明确报错，不混用不同接口的密钥。不会自动取图片专用 ARK_API_KEY。

真实密钥只留在本地后端，禁止放入前端、文档或 Git。部分或错误配置返回 503；完全未配置时本地模式不会调用供应商，也不会产生模型费用。

## 调用流程

1. `GET /api/buyer-show/capabilities`：策划可用状态、`planner_mode`（local_rule / external_vision）、风格、比例、分辨率、最大张数；`rendering_available` 表示图像模型是否已经配置。
2. 可选 `POST /api/buyer-show/assets`：multipart `file`、`clientId`，`Idempotency-Key=clientId`。返回 `{ "assetId": "..." }`。复用已有产品素材存储与上传校验；单图 ≤20MB、≤2400 万像素，JPEG/PNG/WEBP。
3. `POST /api/buyer-show/plans`：JSON 请求，下方示例；必须带客户端生成的唯一 `Idempotency-Key`。成功响应严格为用户要求的四个顶层字段，不加状态包装；响应头 X-Plan-Id 等于已知幂等键。
4. 超时或响应不确定后，只 `GET /api/buyer-show/plans/{id}` 查询。返回 running/completed/failed；completed 附带 plan，失败附带安全错误和 uncertain。
5. `GET /api/buyer-show/plans/{id}/output`：取已完成的纯方案 JSON，未完成则 409。
6. `GET /api/buyer-show/schema`：实时输出 JSON Schema，与 Pydantic 模型一致。
7. 用户在弹窗内修改 `project_title`、`scene_description`、`image_prompt` 或 `negative_prompt`。前端不会在此阶段创建图片任务。
8. `POST /api/buyer-show/tasks`：提交 `taskId`、原 `planId`、不可变的原始 `input` 和用户确认后的 `plan`。`Idempotency-Key` 必须等于 `taskId`。服务端验证策划来源、产品参数、素材、张数、顺序、语言、比例和分辨率后返回 202。
9. `GET /api/buyer-show/tasks/{taskId}`：查询每张图片 queued/rendering/completed/failed 状态。连接中断后只查询原任务，绝不自动重复提交。
10. `GET /api/buyer-show/tasks/{taskId}/images/{index}`：预览或下载单张结果；`GET /api/buyer-show/tasks/{taskId}/export`：导出确认方案、任务状态及按序命名的图片 ZIP。

```json
{
  "product_name": "木纹盖玻璃精华瓶",
  "product_features": "透明玻璃瓶装无色液体，瓶盖有木纹，瓶身为圆柱形",
  "material": "玻璃瓶身、木纹外盖；具体成分未提供",
  "style": "更真实",
  "image_count": 4,
  "aspect_ratio": "3:4",
  "resolution": "2K",
  "scene_preferences": "自然窗光下的家庭洗手台",
  "selling_points": "",
  "notes": "保留瓶身原有结构，不添加标签或文字",
  "assets": []
}
```

产品名称必填；`product_features` 与已上传 `assets` 至少有一项。图片引用为 `{"id":"上传时的clientId","assetId":"服务端返回ID","role":"main"}`，role 可用 main/detail/scene。文字描述充分时支持无图策划，但不能称为已完成视觉识别；传入图片时会将归一化缩略图作为模型视觉输入，不把浏览器 blob URL 发到后端。

外部视觉模型模式不猜测商品信息。素材说明、材质、偏好、卖点、备注都按数据隔离在 user 消息；system 规则不能由备注覆盖。产品图和描述冲突时提示模型指出待核对特征，不创造新的产品外观。

本地规则模式不声称看懂图片：英文 Prompt 使用“严格保持参考产品”的引用式描述和固定物理约束，产品标题来自文件名，套图按已选风格、张数、比例、分辨率规划。它能生成可审阅的引擎提示词，但不能替代视觉模型对具体材质、颜色与结构的识别。

## 输出与约束

```json
{
  "project_title": "产品名称与风格规划",
  "aspect_ratio": "3:4",
  "resolution": "2K",
  "image_plan": [
    {
      "index": 1,
      "shot_type": "全景体验图",
      "scene_description": "中文场景描述",
      "image_prompt": "English product details, environment, lighting, camera angle, material textures and realism instructions.",
      "negative_prompt": "blurry, fake reflections, bad hands, floating product"
    }
  ]
}
```

上面是字段示意，不是 AI 实际生成结果。

- 1–12 张；兼容原 UI 的 1K/2K/4K 以及 3:4、16:9、1:1、4:3、9:16。比例和分辨率是规划参数，不代表已经生成了相应像素的图片。
- 少于四张时按次序取所需景别；四张覆盖全景、功能中景、材质特写、人货交互；更多张数第二/第三轮配不同机位及动作，维持同一产品和套图的一致视觉方向。
- 服务端校验精确数量、原样返回的比例/分辨率、连续序号、预定景别；拒绝完全相同的规范化场景文本或提示词。语义上是否足够多样仍需人工审阅，不以字符串校验冒充视觉质量检测。
- 场景描述要求中文；渲染/负向词要求英文。拒绝 Markdown 围栏、无效 JSON、额外字段、空值、超长值、缺字段及错误编号。遇到错误不做第二次付费模型修复调用。
- 更真实：日常手机/无反快照、自然采光、适量生活痕迹、真实布褶，避免僵硬影棚感。
- 更精致：克制商业摄影、合理的 35mm/85mm 或材质特写机位、晨昏光影、精简且合适的高级材质道具；不改变产品固有外观，不强行添加品牌标识。
- 服务端在模型返回的英文脚本后附加固定产品保真、真实接触阴影、重力沉降、材质反射与环境光约束；同时补齐公共负向约束。这是提示词约束，不是物理模拟，也不能保证任意渲染引擎绝对保真。

## 稳定性和安全

策划先写 SQLite 持久化记录再调用模型，最多同时处理两个请求。确认出图后，每套任务最多并行生成两张，单张失败不自动重试，并保留其余成功图片。相同幂等键和相同输入返回原结果；不同输入 409；处理中重复提交返回带 uncertain=true 的 409。网络失败不自动重试；重启后把进行中的策划或出图标为失败/不确定，不重放可能已计费的请求。原始供应商错误、配置密钥不返回客户端。

复用本地服务的 loopback 限制、Origin 白名单、上传解码与体积限制。当前面向本地单用户、单 worker 部署；公开上线需另加身份与归属校验、存储清理和跨进程任务队列。

代码：`backend/app/buyer_show.py`（路由）、`buyer_show_models.py`（契约/景别计划）、`providers/buyer_show.py`（规则/模型适配）。测试：`backend/tests/test_buyer_show.py`。

自动化测试使用 HTTP 和模型替身，不发生真实付费 AI 调用。真实策划模型的连通性、视觉理解、商品保真及最终出图质量仍需在有效图片模型配置与额度下人工验收。
