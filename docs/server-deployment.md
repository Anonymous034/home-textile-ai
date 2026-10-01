# 在服务器上部署

前端默认调用当前网站的 `/api/*`，不会调用访客电脑上的 `localhost:8000`。Python/FastAPI 后端仍然是必需的，只是由服务器内部运行并经反向代理提供同源接口。不要把本机的 `.env.local` 或 `backend/.env` 上传到服务器。

## 构建与运行

在服务器的干净仓库检出中安装 Node.js 22.13+、pnpm 和 Python 3.11+。不要设置 `NEXT_PUBLIC_STUDIO_API` 或 `NEXT_PUBLIC_DETAIL_API_URL`；它们留空时前端使用同源接口。这些变量在前端构建时确定，因此改动后必须重新构建。

```sh
pnpm install --frozen-lockfile
pnpm build
PORT=3000 pnpm start
```

另一个长期运行的服务启动后端，只监听服务器环回地址：

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

在服务器的 `backend/.env` 中至少设置 `FRONTEND_ORIGIN=https://你的域名`、`AUTH_COOKIE_SECURE=1`、`DEMO_LOGIN_ENABLED=0`、`DEMO_LOGIN_PUBLIC_ENABLED=0`、`LOCAL_CONFIG_ENABLED=0`，并使用随机的 `AUTH_OTP_PEPPER`。所需 AI 密钥只能配置在后端，不能写入 `NEXT_PUBLIC_*` 变量或仓库。数据库、上传文件和生成结果需要持久化存储及备份；不要随发布覆盖运行中的数据库。

## 同源反向代理

下面是放在已配置 HTTPS 证书的 Nginx `server` 块内的示例。实际域名、证书、进程守护和上传大小应按服务器环境调整。`/api/` 和 `/ws/` 交给 FastAPI，其余页面交给前端：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
    proxy_buffering off;
}

location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

部署后应确认首页能打开、浏览器请求的 `/api/auth/me` 指向网站域名、退出登录后点击功能会弹出登录框，以及 HTTPS 下会话 Cookie 带 `Secure` 属性。不要只凭首页显示成功就认定后端已就绪。

## 上线前必须完成

当前仓库的 `DEMO_SMS_MODE=provider` 仅提供适配器接口，尚未接入实际短信供应商；设为 `provider` 而不实现适配器会返回 503。登录框会显示 `123 / 123456` 演示提示，但后端默认拒绝公网演示登录。只有隔离、无真实用户数据的演示服务器才能同时设置 `DEMO_LOGIN_ENABLED=1` 和 `DEMO_LOGIN_PUBLIC_ENABLED=1`；这会开放一个所有访客共用的账号，不能作为正式身份验证。网页内配置密钥入口在公开服务器必须关闭。完成真实短信接入、后端访问控制审查、AI 服务密钥配置、数据持久化和 HTTPS 后再面向公众开放；本次前端改动本身并不等于完整网站已经上线。
