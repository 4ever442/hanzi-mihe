"""
汉字谜盒 · Vercel 无状态后端
============================
配合部署在 Cloudflare Pages 的网页版前端（cfoo-esh.pages.dev/riddle/）。

协议（与前端 app.js 完全一致）：
    POST /api/chat
    请求头:  X-Site-Password: <访问口令>
    请求体:  { "messages": [ {"role":"user|assistant","content":"..."} ... ] }
    响应:     { "reply": "AI 的一句回复" }

设计要点：
    1. 无状态 —— 对话历史由前端 localStorage 维护并整包发来，
       后端不落盘。Vercel 是 serverless（硬盘临时、随冷启动），
       不能用本地文件存会话，所以这里故意不存。
    2. 口令校验 —— SITE_PASSWORD 放 Vercel 环境变量（设为 Secret），
       前端用 X-Site-Password 头传递，两者用定长比较，防止时序侧信道。
    3. Agnes 偶发限流 —— 对 429/5xx 做指数退避重试，尽量一次拿到 200。
"""

import os
import json
import time
import logging
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------------------------------------------------------------
# Agnes AI 配置（OpenAI 兼容接口）
#
# 取值优先级：环境变量 > 同目录 .env 文件（本地开发用）> 兜底。
# Vercel 走环境变量（在 Vercel 后台设置 AGNES_API_KEY / SITE_PASSWORD）；
# 本地开发可把密钥写进 .env（已在 .gitignore，不会上传）。
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    """极简 .env 读取：仅当环境变量未设置时才用文件里的值（文件不覆盖已有环境变量）。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(p):
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)   # setdefault：已有环境变量则不覆盖


_load_dotenv()

AGNES_BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "")
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-3.0-flash")

# 访问口令（Vercel 里设为 Secret 的 SITE_PASSWORD）
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "")

# 注意：即使本地没配 key 也要让模块能 import 起来（否则 Vercel/本地都无法启动）。
# 空 key 时 OpenAI 会拒绝构造，所以用占位符兜底；真正的 401 会在调用 Agnes 时暴露，
# 并由下面 /api/chat 里的配置检查提前拦下（返回 500 而非崩溃）。
client = OpenAI(
    api_key=AGNES_API_KEY or "unset",
    base_url=AGNES_BASE_URL,
    timeout=60.0,      # Vercel 函数执行上限 60s，这里略短，留点余量
    max_retries=1,
)

# ---------------------------------------------------------------------------
# 系统提示词（与本地 Python 版 / Cloudflare chat.js 保持一致）
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
# 角色定义
你是一个专门玩猜字谜的AI小助手，只进行字谜互动，不闲聊无关内容，全程纯文本交互，不使用表情符号。

## 核心能力
- 出字谜、判对错、给提示
- 记忆已用谜题，确保会话内不重复
- 简洁明快回应

## 出题规则（严格执行！）
1. 开场先友好打招呼，并随机出一道常见、简单、适合大众并必须符合逻辑推理的字谜，禁止使用生僻、低俗、网络烂梗。
2. 题目格式：“谜面”（打一字）。
3. 每次出题必须完全随机，禁止重复使用相同题目，也可以偶尔穿插使用，下面示例中的谜语。
4. 新出题目时, 不要提示, 用户需要提示时, 或者答错时, 再给予合理的提示。

## 判题规则（严格执行！）
1. 用户只回复一个字时，直接视为答案。
2. 答对：立即夸奖并揭晓谜底，格式如“太棒了！就是‘X’字！要不要再来一题？”
3. 答错：告知不对，可给一句简短提示，但不泄露答案。格式如“不对哦，再想想~”
4. 严禁在用户答错后直接公布答案！只有用户说“公布答案”或“不知道”等情况时才公布。

## 互动流程
1. 用户答对：夸奖 + 确认正确 + 询问“要不要再来一题？”
2. 用户答错：告知不对 + 简单提示 + 鼓励继续猜
3. 用户说“提示一下”：给出简短线索，不公布答案
4. 用户说“公布答案”或“不知道”：揭晓谜底并解释 + 询问“要不要再来一题？”
5. 用户说“换一题”“再来一题”：立即更换新字谜

## 回复风格约束
- 语气轻松有趣，但保持简洁
- 全程只围绕字谜，拒绝回答其他问题
- 回复不超过3句话
- 绝对不要在回复中说“这个出过了，我来个新的”或类似表述 — 直接给出新谜语即可
- 判题错误零容忍，不确定谜底时，先回复“我再想想”而不是乱判

## 常见谜语类型及谜底参考示例, 仅仅为参照示例
### 组合类
- 「一加一不是二」= 王
- 「二人不是天」= 夫
- 「十口不是田」= 古

### 包含类
- 「一人在内」= 肉
- 「口里有人」= 囚
- 「门里有口」= 问
- 「田里长草」= 苗
- 「心里有你」= 您
- 「山里有山」= 出
- 「王头上有人」= 全
- 「水上有石」= 泵

### 半取类
- 「半吃半拿」= 哈
- 「半真半假」= 值
- 「半青半紫」= 素
- 「半朋半友」= 有
- 「半推半就」= 扰
- 「半山半水」= 汕

### 象形类
- 「三人又重逢」= 众
- 「一口咬掉牛尾巴」= 告
- 「两座山」= 出
- 「三日又重逢」= 晶
"""

# ---------------------------------------------------------------------------
# 前端契约：请求体
# ---------------------------------------------------------------------------
MAX_MESSAGES = 24          # 最多接受的历史条数（与 Cloudflare chat.js 一致）
MAX_CHARS = 2000          # 单条消息最大字数


class ChatRequest(BaseModel):
    # 前端发来的是整段历史，最后一条必须来自 user
    messages: list[dict[str, Any]]


app = FastAPI(title="汉字谜盒 Vercel 后端")

# CORS：允许 Cloudflare Pages 前端跨域调用；本地调试时也可放行
CORS_ORIGINS = [
    "https://cfoo-esh.pages.dev",   # 你的 Cloudflare 前端
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],           # 放行 X-Site-Password
)


def _const_time_equal(a: str, b: str) -> bool:
    """定长比较口令，避免从响应时间猜出口令长度/内容。"""
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a.encode(), b.encode()):
        diff |= x ^ y
    return diff == 0


@app.get("/")
def root():
    """健康检查，Vercel 部署后浏览器打开应能看到这里，而不是 404。"""
    return {"status": "ok", "service": "汉字谜盒 Vercel 后端"}


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    # 0. 服务端配置检查
    if not AGNES_API_KEY:
        raise HTTPException(500, "服务端未配置 AGNES_API_KEY")
    if not SITE_PASSWORD:
        raise HTTPException(500, "服务端未配置 SITE_PASSWORD")

    # 1. 口令校验
    given = request.headers.get("X-Site-Password", "")
    if not _const_time_equal(given, SITE_PASSWORD):
        raise HTTPException(401, "口令不正确")

    # 2. 清洗请求体：只留 role/content，防客户端塞多余字段干扰模型
    clean = []
    for m in req.messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") not in ("user", "assistant"):
            continue
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        content = content[: MAX_CHARS]
        clean.append({"role": m["role"], "content": content})

    if not clean:
        raise HTTPException(400, "没有有效的消息内容")
    if len(clean) > MAX_MESSAGES:
        clean = clean[-MAX_MESSAGES:]
    if clean[-1]["role"] != "user":
        raise HTTPException(400, "最后一条消息必须来自 user")

    # 3. 系统提示词由服务端强制注入，客户端无法覆盖
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *clean]

    # 4. 调用 Agnes（带退避重试，应对偶发限流 / 冷启动慢）
    RETRY_DELAYS = [1.0, 2.0, 3.0]
    upstream_reply = None
    last_err = ""

    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt > 0:
            time.sleep(RETRY_DELAYS[attempt - 1])
        try:
            resp = client.chat.completions.create(
                model=AGNES_MODEL,
                messages=full_messages,
                stream=False,
                temperature=1.2,
            )
            upstream_reply = resp.choices[0].message.content
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logging.warning("Agnes 调用失败（第 %d 次）: %s", attempt + 1, last_err)
            # openai 库已内置 1 次重试；这里再加退避，针对 429/5xx/超时
            continue

    if upstream_reply is None:
        # 明确告知是「上游 AI 被限流」，前端据此提示用户稍后再试
        raise HTTPException(
            429,
            "AI 服务方暂时拒绝了请求（限流），与你的操作频率无关，可稍后重试。"
        )

    return {"reply": upstream_reply.strip() if isinstance(upstream_reply, str) else ""}


@app.exception_handler(Exception)
async def _exc_handler(request: Request, exc: Exception):
    logging.error("请求异常 %s %s: %s", request.method, request.url, exc)
    return JSONResponse(status_code=500, content={"error": "服务器异常，请稍后重试"})
