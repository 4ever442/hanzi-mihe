# 汉字谜盒（FastAPI + Agnes AI 字谜互动）

一个基于 FastAPI 的猜字谜互动小站：前端 `static/`，后端 `main.py`，
每次聊天由服务端调用 Agnes AI（`agnes-3.0-flash`）出题/判题，会话存到 `sessions/`。

## 本地运行

```bash
pip install -r requirements.txt
# 配置密钥（二选一）
#   1) 同目录 .env 文件：AGNES_API_KEY=你的Key
#   2) 环境变量：AGNES_API_KEY=你的Key
python main.py            # 监听 0.0.0.0:8000
```

浏览器打开 `http://127.0.0.1:8000`。

> `.env` 已被 `.gitignore` 排除，切勿提交密钥。

## 发布到公网（完整可玩：前端 + AI 后端）

完整可玩需要一个**能常驻跑 Python 的后端**。推荐路线：
**Render（免费跑 FastAPI）+ Cloudflare Worker（免费子域反代）**。

```
用户浏览器
  └─→ xxx.workers.dev   (Cloudflare Worker，免费子域，唤醒+反代)
        └─→ 你的服务.onrender.com   (Render 上的 FastAPI 后端)
              ├─ / , /static  前端
              └─ /api/*       调 Agnes AI + 存 sessions/
```

前端 `app.js` 里 `API_BASE_URL = '/api'` 是相对路径，只要前后端同域即可，无需改代码。

### 1. 推到 GitHub

```bash
git init
git add main.py static sessions requirements.txt cloudflare-worker.js README.md
git commit -m "汉字谜盒 后端 + 前端 + 部署文件"
# 在 GitHub 新建空仓库后：
git remote add origin https://github.com/你的用户名/hanzi-mihe.git
git push -u origin main
```

### 2. 部署 Render（Web Service）

Render 控制台 → New → **Web Service** → 连上面的 GitHub 仓库：

- Runtime：`Python`
- Build Command：留空（自动 `pip install -r requirements.txt`）
- **Start Command：`uvicorn main:app --host 0.0.0.0 --port $PORT`**
  ⚠️ 必须用 `$PORT`，不能写死 8000。
- Env Variables：加 `AGNES_API_KEY`（= 本地 `.env` 里那个密钥）。
  可选 `AGNES_MODEL`，不填默认 `agnes-3.0-flash`。

部署后得到 `https://你的服务.onrender.com`，浏览器打开应能看到界面并能出字谜。

### 3. （可选，推荐）套 Cloudflare Worker 拿免费子域

1. Cloudflare 控制台 → Workers & Pages → Create Worker（如 `hanzi`）。
2. 把 `cloudflare-worker.js` 的内容贴进去，改顶部的 `ONRENDER` 为你的 Render 子域。
3. Settings → Domains & Routes 绑定免费的 `你的worker名.workers.dev`。
4. 用户访问 `https://你的worker名.workers.dev` 即可完整游玩。

## 注意事项

- **密钥只放服务端**：本地走 `.env`，线上走 Render 的 Env Variables，都不要进前端/GitHub。
- **Render 免费版会休眠**：闲置约 15 分钟进眠，再访问冷启动几秒。需要可加定时 ping 保活（先不做）。
- **会话存储**：存 Render 本地盘，实例重建后 `sessions/` 会被清；需要永久存可迁到 Cloudflare R2。
