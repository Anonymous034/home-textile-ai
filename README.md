# 家纺 AI 视觉工作台

这是可上传到 GitHub 的源码整理版。前端使用 Vinext/React，后端使用 FastAPI。包含首页、手机号验证码登录/注册、个人设置、花型创作、影棚、爆款复刻、详情页、模板、画稿生图、局部编辑、高清、买家秀、作品与积分页面，以及个人 API Key 的非生图验证和持续连通检查。

## 本地启动（Windows）

需要 Node.js 22.13+、pnpm 和 Python 3.11+。在项目根目录执行：

```powershell
pnpm install --frozen-lockfile
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
```

按需在本机 `backend/.env` 填写站点提供的 API Key、图片模型配置及视觉策划接口配置。这个文件已被 Git 忽略，不要提交密钥。示例配置的 `DEMO_LOGIN_ENABLED=1` 仅供本机演示：进入功能页后，点击功能卡片，使用手机号 `123` 和验证码 `123456` 登录，无需获取短信验证码；生产环境必须设为 `0`。普通手机号的 `DEMO_SMS_MODE=mock` 只用于联调，使用 `DEMO_SMS_CODE` 完成验证码流程；要向真实手机发短信，需要接入短信供应商并提供签名、模板和服务密钥。随后双击 `启动本地网站.cmd`，或执行 `./start-ai-studio.ps1`；前端为 `http://127.0.0.1:3000`，后端接口文档为 `http://127.0.0.1:8000/docs`。登录后可在 `/settings` 验证个人 API Key；它只用于当前浏览器会话，不会覆盖站点配置。

## 服务器部署准备

前端默认使用同源 `/api`，不再把浏览器请求发往访问者电脑的 `127.0.0.1:8000`。登录相关请求在本地由前端同源转发给 FastAPI；如后端不在 `127.0.0.1:8000`，可在未提交的 `.env.local` 中设置服务端变量 `STUDIO_API_INTERNAL_URL`。首页直接显示功能页；未登录时点功能卡片才弹出登录框。登录框始终提示演示账号 `123 / 123456`，但后端默认仅允许本机使用；隔离演示服务器如需开放，须显式设置 `DEMO_LOGIN_PUBLIC_ENABLED=1`，不可用于真实用户数据。部署时由反向代理把 `/api/`（以及 WebSocket `/ws/`）转发给运行在服务器上的 FastAPI；本地开发仍可在未提交的 `.env.local` 中设置 `NEXT_PUBLIC_STUDIO_API=http://localhost:8000` 供其他功能调用。详情页和买家秀默认使用同一地址，只有独立部署该服务时才需要设置 `NEXT_PUBLIC_DETAIL_API_URL`。完整的代理配置、安全设置及尚未接入的生产短信服务见 [服务器部署说明](docs/server-deployment.md)。

## 目录

- `app/`：页面和前端组件
- `backend/app/`：API、生成任务和密钥检查
- `backend/tests/`、`tests/`：后端和前端测试
- `public/`：首页视频、功能卡片及完整模板图库（`template-library/`）
- `backend/data/studio.sqlite3`：仅保留模板、模特、场景、构图等图库目录的可迁移数据库
- `backend/data/compositions/`、`model-ai-restored/`、`model-source-sheets/`、`preset-models/`、`preset-scenes/`、`preset-hd/`、`preset-thumbs/`、`template-thumbs/`：图库图片及预览
- `backend/data/library-sources.json`：图库来源索引
- `docs/`、`backend/README.md`：功能和接口说明

## 未包含的本机文件

`backend/.env`、`backend/本机API密钥.txt`、用户上传图片、用户生成作品、个人账户及任务记录、运行日志、虚拟环境、`node_modules/` 和构建产物均未打包。图库图片和只含图库目录的 SQLite 数据库已包含在本文件夹；首次启动时会自动把数据库里的相对图片路径定位到当前项目目录。上传到公开仓库前，请确认你拥有图库素材的发布权。

运行检查：`pnpm build`、`node --test tests/*.test.mjs`、`backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -p 'test_*.py'`。

上传时，在**本文件夹**内初始化 Git 仓库并推送到你自己的 GitHub 仓库；不要把外层工作目录一起上传。
