# AI 商拍后端

未配置密钥时默认使用 `mock` 供应商，仅用于验证上传、排队、进度和结果流程，不代表真实 AI 商拍质量。

## 启动

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

打开 `http://localhost:8000/docs` 可查看接口。

本机日常使用请直接双击项目根目录的 `启动本地网站.cmd`。启动器会检查端口、后端健康状态和方舟 HTTPS 连通性；即使 AI 暂时离线，也会启动前端并打开浏览器，后端会继续自动重试。运行中的进程和 UTF-8 日志保存在 `.runtime/`；双击 `停止本地网站.cmd` 可按启动记录安全停止本项目进程。

影棚 Agent Plan 图片服务和模板合成的视觉策划服务使用与实际请求相同的代理设置做无密钥 GET 探测：启动时检查，运行中约每 5 秒复查，提交前再检查。`GET /api/ai/connections` 返回图片与策划客户端的脱敏状态；`/api/ai/connections/stream` 向页面持续推送状态变化，断线时页面每 5 秒尝试读取状态。文字策划默认 `DETAIL_PLAN_PROXY_MODE=direct`，确实依赖系统代理时可设为 `environment`。探测只证明网络可达，不验证密钥权限或额度，也不创建图片。提交前探测失败时不会发送生成 POST；生成 POST 已发出后发生网络错误，不会自动重复提交，避免重复计费。网络、代理或防火墙限制仍需由本机环境恢复。

## 安全配置 Agent Plan

不要把 Agent Plan API Key 发到聊天、写进前端或提交到 Git。请在项目根目录运行：

```powershell
.\configure-ark-key.ps1
```

脚本会在本机隐藏输入密钥，并写入不会被 Git 提交的 `backend/.env`。重启后端后，`/api/health` 的 `provider` 会从 `mock` 变为 `volcengine-agent-plan-seedream-skill`。

当前适配器通过 Agent Plan 的专用 `/api/plan/v3` 数据面调用套餐内置 `doubao-seedream-5.0-lite` Skill。它会按顺序提交产品主视角、补充视角、模特、场景和构图参考，最后只返回一张 2K 合成结果。正式商用前仍需用真实素材验证商品结构、人物姿态和接触区域的保真度。

## 四图融合接口

`POST /api/fusion/jobs` 使用 `multipart/form-data` 一次提交完整任务：

- `main_view`：商品/家具主视角（必传，最高保真优先级）
- `model_image`：模特参考（必传）
- `scene_image`：最终背景场景（必传）
- `composition_image`：构图、动作、机位和遮挡参考（必传）
- `extra_view`：同一商品的补充视角（选填）
- `guidance`：不超过 800 字的补充要求（选填）
- `aspect_ratio`：默认 `3:4`
- `resolution`：默认 `2K`

接口立即返回任务对象。使用 `GET /api/jobs/{job_id}` 轮询，状态为 `completed` 后从 `outputs[0].preview_url` 获取最终图片。未配置密钥时状态会是 `completed_mock`，只代表流程跑通。

## 爆款复刻（独立真实生成）

打开本地 `/replicate`。沿用本机 `ARK_API_KEY`、`ARK_IMAGE_MODEL` 和 Agent Plan 专用 `ARK_IMAGE_ENDPOINT`，不使用影棚的提示词、任务表或裁剪后处理。**没有有效配置就拒绝提交，不降级为模拟结果。** `configured` 仅表示本机配置存在，不代表鉴权、额度或画质验收成功。

### API

- `GET /api/replicate/capabilities`：本机配置状态，不返回密钥。
- `GET /api/replicate/connectivity?refresh=true`：执行不产生生成费用的 DNS/TCP/TLS/API 连通性检查，只返回脱敏状态和故障类别（如 DNS 失败、443 端口超时、TLS 失败）。网络、防火墙或代理需由本机环境恢复，后端不会擅自修改系统设置。
- 后端每次启动都会先执行一次最长 8 秒的非生成连通性探测，再对外提供服务；即使当时离线，也会继续每 15 秒在后台重试。`/api/health/ready` 仅在探测成功后返回就绪，探测不会验证密钥权限或消耗生成额度。

### 花型裂变

`POST /api/pattern/jobs` 接受图片、`request_id`（UUID）、生成张数（2/4/6/8）、变化幅度、配色处理、补充要求和操作类型，立即返回任务标识。图片模型按画面中可见面积最大的独立物品（不限家具，可为窗帘、床品等）生成花纹及配色变化；背景墙、地面等不当作目标物品。`GET /api/pattern/jobs/{id}` 返回逐张进度与已完成图片；`GET /api/pattern/jobs/{id}/results/{index}` 下载结果。同一个请求标识重复提交只返回原任务；任务状态写入本机，后端重启后可查看已完成结果。模型对物品边界和保真度的判断仍需人工验收。
- `POST /api/replicate/prepare`：JSON `{reference_width, reference_height, custom_notes}`，解析目标像素尺寸；纯本地校验，不请求 AI。
- `POST /api/replicate/jobs`：multipart 表单；`main_image`、`reference_image` 各一张必填，`extra_images` 可重复最多两次；`remove_text` 为 `true/false`，`custom_notes` 最长 800 字；`confirmed_width`、`confirmed_height` 必须与后端解析的目标尺寸相同。必须带 UUID 格式 `Idempotency-Key` 请求头。
- `GET /api/replicate/jobs/{id}`：任务状态、原图/参考图预览、结果 URL。状态包括 `queued/generating/downloading/validating/completed/failed/interrupted`。不显示虚构进度百分比。
- `GET /api/replicate/jobs/{id}/result?download=true`：下载本地保存的 PNG；没有通过图片解码、比例和尺寸检查，不会暴露成功下载地址。
- `POST /api/replicate/jobs/{id}/retry`：只允许失败或中断任务；JSON `{confirm_possible_charge: true}` 和新的 `Idempotency-Key`。返回独立子任务，原记录保留。网络中断后重复同一个重试请求标识不会再新建任务。

单文件最多 20MB，JPG/PNG/WEBP，单帧且能够安全解码；本地安全上限为宽高 64–16384、总像素 3600 万，**这不是供应商能力声明**。使用 EXIF 方向归一化为无损 PNG；归一化后仍不得超过 20MB，不偷偷缩小产品图。每个后台进程串行执行复刻生成；请保持本地单 worker 启动方式。

### 渲染规则与尺寸能力

产品主图 → 可选补充视角 → 单张场景参考图，按此顺序提交。默认清除参考图旧产品并替换，参考角度优先；去文字开关默认保护新产品 Logo。补充说明可覆盖渲染规则，但不能指示后端访问文件、密钥或执行工具。它是生成模型的条件，不代表实际执行过独立抠图、OCR 或光照分析算法。

默认目标为参考图实际方向的原始宽高。覆盖尺寸请明确写 `1200×1600 px`；含糊比例、4K 等词或多个冲突尺寸会被拒绝。前端显示目标像素并在提交时确认，后端再次核对。

尺寸处理不借用标准方舟或第三方转发服务的限制：首先提交原像素尺寸。**仅当当前 `/api/plan/v3/images/generations` 返回 HTTP 400、`InvalidParameter` 且明确指出尺寸的像素上/下限时**，从这条响应计算精确同比例的整数尺寸，并最多重新提交一次。其他参数错误、鉴权错误、限流、网络异常、超时、5xx 均不自动重试。不能读懂的尺寸限制会明确失败，不猜测。

接口返回图片后检查真实宽高比；比例一致才用等比缩放恢复目标尺寸，绝不使用裁剪或非等比拉伸。每个成功任务的 `metadata` 记录请求尺寸、返回尺寸、交付尺寸和限制来源，作为该次接口调用的实际证据。未进行真实调用前不宣称某个尺寸或密钥已经验证通过。接口参考：[Agent Plan 配置指南](https://www.volcengine.com/docs/82379/2375486?lang=zh)、[火山引擎官方生成 CLI 文档](https://github.com/volcengine/ark-cli/blob/main/skills/arkcli-gen/references/arkcli-gen.md)。

图片请求优先使用 `b64_json`，收到后立即校验并原子保存到 `backend/data/results/replicate/`。仅当供应商返回 URL 时才启用受限域名下载回退。默认 `ARK_PROXY_MODE=direct`，避免本机开发工具注入的代理造成 TLS 中断；确实依赖系统代理时可显式改为 `environment`。

### 安全、恢复与验收

复刻接口限制本机访问并校验浏览器来源；新增 `replica_jobs` 表，与旧商拍数据隔离。图片和结果默认可访问 7 天。请求参数错误、重复提交不会产生新生成；响应不确定时页面保留请求标识，仅查询状态或显式安全重发同一次提交。后端重启把未完成任务标记为中断，不自动重放。任何手动重试都须确认可能再次计费。

供应商错误原文不返回前端或写入任务记录；结果 URL 不带密钥请求，禁止内网/本机地址并逐次校验重定向。成功只代表收到且校验过图片，始终标记 `pending_review`，不声称 Logo、材质、文字保真或无痕融合已通过验收。

不消耗真实额度的测试：在项目根目录运行 `backend/.venv/Scripts/python.exe -m unittest backend.tests.test_replicate -v`。测试只使用临时数据库、合成素材及 HTTP 替身。真实效果必须另用用户选定的产品图、参考图点击生成后验收；不要将自动化通过视为实际画质或套餐权限已验证。
