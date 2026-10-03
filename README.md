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

在本机 `backend/.env` 填写阿里云 AccessKey ID、Secret、已审核的短信签名、包含 `${code}` 的模板编号和随机生成的 `AUTH_OTP_PEPPER`；其他 AI 配置按需填写。这个文件已被 Git 忽略，不要提交密钥。登录页会向真实手机号发送随机六位数字验证码，并在服务端完成有效期、尝试次数与一次性校验。随后双击 `启动本地网站.cmd`，或执行 `./start-ai-studio.ps1`；前端为 `http://127.0.0.1:3000`，后端接口文档为 `http://127.0.0.1:8000/docs`。登录后可在 `/settings` 验证个人 API Key；它只用于当前浏览器会话，不会覆盖站点配置。

## 服务器部署准备

前端默认使用同源 `/api`，不会把浏览器请求发往访问者电脑的 `127.0.0.1:8000`。登录请求由同源接口转发给 FastAPI；如后端不在 `127.0.0.1:8000`，可在未提交的 `.env.local` 中设置服务端变量 `STUDIO_API_INTERNAL_URL`。首页直接显示功能页；未登录时点功能卡片才弹出登录框。部署时由反向代理把 `/api/`（以及 WebSocket `/ws/`）转发给服务器上的 FastAPI。本地开发仍可在未提交的 `.env.local` 中设置 `NEXT_PUBLIC_STUDIO_API=http://localhost:8000` 供其他功能调用。详情页和买家秀默认使用同一地址，只有独立部署该服务时才需要设置 `NEXT_PUBLIC_DETAIL_API_URL`。完整的代理配置和密钥设置见 [服务器部署说明](docs/server-deployment.md)。

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
