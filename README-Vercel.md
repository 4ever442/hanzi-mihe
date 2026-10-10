# 汉字谜盒 · Vercel 部署（FastAPI 无状态后端）

把 AI 后端放到 Vercel，配合 Cloudflare Pages 上的网页版前端（`cfoo-esh.pages.dev/riddle/`）联动。
后端是**无状态**的：对话历史存在浏览器 `localStorage`，前端每次整包发给后端，后端不落盘
（Vercel 是 serverless，硬盘是临时的，存不住）。

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | Vercel 上跑的 FastAPI 后端（**不动**原来的 `main.py`） |
| `vercel.json` | 告诉 Vercel 用 `@vercel/python` 运行时、函数最长跑 60s |
| `requirements.txt` | 依赖（fastapi / uvicorn / openai / pydantic / requests） |
| `main.py` | 原来的有状态后端，本地和旧方案继续用，本次未改 |

## 一、推送代码到 GitHub

```bash
cd 汉字迷盒
git add app.py vercel.json requirements.txt .gitignore
git commit -m "Vercel 无状态 FastAPI 后端（app.py）"
git push
```

`.env`（含密钥）已被 `.gitignore` 排除，不会上传 —— 密钥只放 Vercel 环境变量。

## 二、在 Vercel 建项目并配环境变量

1. https://vercel.com/ → **Add New → Project** → 选你刚推的仓库。
2. Framework Preset 选 **Python**（Vercel 会自动读 `vercel.json`）。
3. 在部署前的 **Environment Variables** 面板（或 Deploy 后 Settings → Environment Variables）填 3 个，
   同时勾上 **Production / Preview / Development** 三个环境：

   | 变量 | 值 | 类型 |
   |---|---|---|
   | `AGNES_API_KEY` | 你 `.env` 里那个 `sk-...` | **Secret（加密）** |
   | `SITE_PASSWORD` | 你前端用的访问口令（如 `zx9800`） | **Secret（加密）** |
   | `AGNES_MODEL` | `agnes-3.0-flash`（可不填，有默认值） | 普通 |

4. 部署。成功后得到一个地址，形如 `https://hanzi-mihe-xxx.vercel.app`。

## 三、验证后端单独能通

浏览器直接打开 `https://你的地址.vercel.app/`，应看到：
```
{"status":"ok","service":"汉字谜盒 Vercel 后端"}
```
再手动测一次 AI 调用（把口令换成你的）：
```bash
curl -X POST "https://你的地址.vercel.app/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-Site-Password: zx9800" \
  -d '{"messages":[{"role":"user","content":"开始"}]}'
```
返回 `{"reply":"..."}` 说明 Vercel 这条链路（非 Cloudflare 出口 IP）能通 Agnes。

> ⚠️ 如果这条一直 429/超时，说明 Vercel 出口 IP 也被 Agnes 限流了（和 Cloudflare 同类问题），
> 那就得换出口 IP（见下方"备选"）。先跑通这步再改前端。

## 四、把前端指向 Vercel 后端（关键联动）

前端现在发的是**相对路径** `/api/chat`（发向它所在的 Cloudflare 域）。要改用 Vercel 后端，
需要让前端把 AI 请求发到 Vercel 的绝对地址。两种方式，选一种：

**方式 A（改前端一行，最稳）**：编辑 `汉字迷盒网页版/public/riddle/app.js`，把
```js
const res = await fetch('/api/chat', { ... });
```
改成（把 `你的地址` 换成 Vercel 给的）：
```js
const API = 'https://你的地址.vercel.app';
const res = await fetch(API + '/api/chat', { ... });
```
然后重新 `wrangler pages deploy`。这样前端仍在 Cloudflare，AI 走 Vercel，密钥仍在 Vercel。

**方式 B（纯前端直连 Agnes，免 Vercel）**：如果你愿意把 `AGNES_API_KEY` 暴露给浏览器，
可以前端直接调 Agnes、彻底去掉后端。但密钥会出现在网页源码里、任何人都能抠走滥用，
不推荐（除非你接受这个风险）。

## 备选：如果 Vercel 出口也被 Agnes 限流

1. **Render（免费常驻跑 FastAPI，出口 IP 不同于 Cloudflare/Vercel）** —— 大概率能过限流，
   但免费版闲置会休眠。把 `app.py` 放 Render 按 Web Service 部署，`SITE_PASSWORD`/`AGNES_API_KEY`
   填 Render 环境变量，前端方式 A 指向 Render 地址即可。
2. **Cloudflare R2 / KV**：把会话持久化（非必需，本方案已无状态）。
3. **换出口 IP 的免费代理层**再转发到 Agnes。

## 注意

- **密钥只放 Vercel 环境变量（Secret）**，绝不进代码、不进 GitHub、不进前端。
- Vercel 免费版函数单次执行上限 60s（`vercel.json` 里 `maxDuration:60`），Agnes 冷启动慢时
  `app.py` 已内置退避重试。若偶尔超时，属正常，前端会自动提示"服务繁忙"。
- 会话记录只在浏览器 localStorage，清浏览器缓存会丢；要跨设备保存需另接对象存储。
