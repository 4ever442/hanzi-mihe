import os
import json
from typing import Any
from fastapi import FastAPI
from pydantic import BaseModel
from requests import Request
from starlette.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from openai import OpenAI
import logging

# 配置日志信息
# %(asctime)s : 时间；%(levelname)s : 日志级别；%(filename)s:%(lineno)d : 文件名：行号；%(message)s : 日志信息
logging.basicConfig(
    level=logging.ERROR, # 设置日志级别
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s" # 设置日志格式，时间，级别，详细信息
    )

# 创建FastAPI实例
app = FastAPI(title="汉字迷盒")
"""
    1. 创建会话
    2. 与ai交互
"""
# 挂载静态文件资源存放目录
# 第一个static 是任何以static开头的目录，都会被挂载到/static目录下 第二个参数是静态文件存放的目录 第三个参数是目录名称，叫什么都行
app.mount("/static", StaticFiles(directory="static"), name="static")

# 创建会话存放的目录 sessions
os.makedirs("sessions", exist_ok=True)

# 生成会话标识
def create_session_id():
    # 拿取现在的时间 格式化
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# 更具session_id 来获取文件名
def get_session_file_name(session_id):
    return f"sessions/{session_id}.json"


# 系统提示词 - 适配Agnes 3.0 Flash
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
- **绝对不要在回复中说“这个出过了，我来个新的”或类似表述** — 直接给出新谜语即可
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

# ==================== Agnes AI 配置 ====================
# 模型服务地址（OpenAI 兼容接口，末尾的 /v1 不能省略）
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
# 兜底配置：建议改用环境变量或同目录下的 .env 文件
AGNES_API_KEY_FALLBACK = ""
AGNES_MODEL_FALLBACK = "agnes-3.0-flash"


def read_env(name: str) -> str:
    """读取配置：优先环境变量，其次同目录下的 .env 文件（形如 NAME=value）"""
    value = os.getenv(name, "").strip()
    if value:
        return value

    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip() == name:
                    return val.strip().strip('"').strip("'")

    return ""


# 加载 API Key 和模型名
AGNES_API_KEY = read_env("AGNES_API_KEY") or AGNES_API_KEY_FALLBACK
AGNES_MODEL = read_env("AGNES_MODEL") or AGNES_MODEL_FALLBACK


# 创建与AI大模型交互的客户端对象（Agnes AI，OpenAI 兼容接口）
client = OpenAI(
    api_key=AGNES_API_KEY,
    base_url=AGNES_BASE_URL,
    timeout=120.0,  # 单次请求超时（秒），Agnes 高峰期响应可能较慢
    max_retries=1,  # 失败重试次数
)

# 生成数据模型
class ApiResponse(BaseModel):
    code: int
    message: str
    data: Any

class ChatRequest(BaseModel):
    session_id: str
    message: str



# 定义api接口 路径操作函数
@app.get("/")
def root():
    logging.info("访问项目首页")
    return FileResponse("static/index.html")

# 创建会话
@app.post("/api/sessions")
def create_session()-> ApiResponse:
    logging.info("创建会话")
    # 1.生成会话标识
    session_id = create_session_id()

    # 2.组装会话信息，保存到文件中
    session_data = {
        "current_session": session_id,
        "messages": []
    }
    with open(f"sessions/{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    # 3.返回数据
    # return {"code":200,"message":"创建会话成功","data": session_id}
    return ApiResponse(code=200, message="创建会话成功", data=session_id)


# 与ai交互
@app.post("/api/chat")
def chat(request: ChatRequest)-> ApiResponse:
    logging.info(f"与ai交互:{request.session_id} : {request.message}")

    # 逻辑实现
    # 0、检查 API Key 是否已配置
    if not AGNES_API_KEY:
        return ApiResponse(
            code=500,
            message="未配置 Agnes API Key，请设置环境变量 AGNES_API_KEY，或在项目目录下新建 .env 文件写入 AGNES_API_KEY=你的Key",
            data=None,
        )

    # 1、加载json会话数据
    session_path = get_session_file_name(request.session_id)
    with open(session_path, "r", encoding="utf-8") as f:
        session_data = json.load(f)

    # 2、创建与AI大模型交互的数据
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 添加历史消息
    for msg in session_data["messages"]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    # 添加当前用户消息
    messages.append({"role": "user", "content": request.message})

    logging.info(f"请求大模型数据：{messages}")
    # 3、调用AI大模型（Agnes AI）
    response = client.chat.completions.create(
        model=AGNES_MODEL,  # Agnes 3.0 Flash
        messages=messages,
        stream=False,   # 流式输出
        temperature=1.2,  # 模型温度，生成随机性（字谜随机性靠温度提升）
    )

    # 4、获取响应数据
    ai_response = response.choices[0].message.content
    logging.info(f"响应数据：{ai_response}")

    # 5、更新消息列表中的消息
    messages.pop(0)  # 删除系统提示词
    messages.append({"role": "assistant", "content": ai_response})
    session_data["messages"] = messages  # 保存用户和助手的对话
    logging.info(f"保存数据成功{session_data}" )

    # 6、保存数据到json文件中
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    # 7、返回数据
    return ApiResponse(code=200, message="获取会话列表成功", data=ai_response)

# 获取指定会话信息 ---> 统配，匹配任意字符串，不管什么东西都会给到session_id
@app.get("/api/sessions/{session_id}")
def get_session(session_id: str)-> ApiResponse:
    logging.info(f"获取指定会话信息：{session_id}")
    # 1、获取会话文件名
    session_path = get_session_file_name(session_id)

    # 2、读取会话文件
    with open(session_path, "r", encoding="utf-8") as f:
        session_data = json.load(f)

    # 3、返回数据
    return ApiResponse(code=200, message="获取会话信息成功", data=session_data)


# 获取会话列表
@app.get("/api/sessions")
def get_sessions()-> ApiResponse:
    logging.info("获取会话列表")
    # 逻辑实现
    # 1、获取所有会话文件
    session_files = os.listdir("sessions")
    # 2、获取会话列表
    session_ids = [file.split(".")[0] for file in session_files]
    session_ids.sort(reverse=True)
    # 3、返回数据
    return ApiResponse(code=200, message="获取成功", data=session_ids)


# 删除会话
@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str)-> ApiResponse:
    logging.info(f"删除会话：{session_id}")
    session_path = get_session_file_name(session_id)
    if os.path.exists(session_path):
        os.remove(session_path)
        logging.info("删除成功")
    else:
        logging.info("删除失败")
    return ApiResponse(code=200, message="删除成功",data=None)


# 异常处理器
@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    logging.error(f"路径异常：{request.url}异常：{exc}")
    return JSONResponse(status_code=500, content={"code": 500, "message": "服务器异常，请联系管理员~", "data": None})




# 启动服务
if __name__ == "__main__":
    import uvicorn
    # HF Spaces 通过环境变量 PORT 注入监听端口（默认 7860）
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
    logging.info(create_session_id())