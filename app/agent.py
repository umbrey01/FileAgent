import json
import uuid
from pathlib import Path

from openai import OpenAI

from app.tools import list_files, read_text_snippet, _safe, PathViolation
from app.db import log_action


# 工具返回的文件数上限（防止把上下文撑爆）
MAX_LIST_ITEMS = 1200
DEFAULT_LIST_ITEMS = 400
# 模型最多思考多少轮
MAX_STEPS = 8
# 模型连续几次输出非法 JSON 就放弃
MAX_JSON_RETRIES = 2

# 计划条目的状态与动作取值。GUI 只应通过这些常量判断，不要硬编码字符串。
STATUS_OK = "ok"
STATUS_CONFLICT = "conflict"
STATUS_ERROR = "error"
ACTION_MOVE = "move"
ACTION_SKIP = "skip"


# 明显不是"聊天"的模型，自动挑选默认值时排除
NON_CHAT_HINTS = (
    "embed", "rerank", "whisper", "tts", "moderation",
    "dall-e", "bge-", "gte-", "clip", "sd-",
)
CHAT_PREFERENCE = (
    "deepseek-chat", "deepseek-reasoner", "gpt-4o", "gpt-4.1", "gpt-4",
    "claude", "qwen", "glm", "llama", "mistral",
)


def get_models(api_key: str, base_url: str) -> list[str]:
    """向 API 请求当前 Key 支持哪些模型"""
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        models = client.models.list()
        return sorted([model.id for model in models.data])
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []


def pick_default_model(models: list[str]) -> str:
    """从模型列表里挑一个大概率能对话的；挑不出来就交回第一个。"""
    if not models:
        return ""
    chat = [m for m in models if not any(h in m.lower() for h in NON_CHAT_HINTS)]
    if not chat:
        return models[0]
    for pref in CHAT_PREFERENCE:
        for m in chat:
            if pref in m.lower():
                return m
    return chat[0]


# 1. 定义通用工具箱（用 JSON Schema 描述）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "递归列出目录下的文件，返回相对路径、大小(字节)、修改日期(YYYY-MM-DD)、扩展名。"
                "结果有数量上限；若返回的 truncated 为 true，说明还有文件没列出，"
                "此时应改用 subdir 缩小范围再查，不要假设没列出的文件不存在。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "相对根目录的子目录，默认 \".\" 表示整棵树",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "最多返回多少个文件，默认 400，最大 1200",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "读取指定文件的开头部分内容（约 500 字），用于判断文件里到底是什么。"
                "支持 UTF-8 / GB18030 文本；二进制文件会返回说明而不是内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件的相对路径"}
                },
                "required": ["file_path"],
            },
        },
    },
]


# 2. 真实的工具执行层（真正的读写实现都在 app/tools.py，这里只做参数整形）
def execute_tool(tool_name: str, tool_args: dict, root: Path) -> str:
    try:
        if tool_name == "list_files":
            try:
                max_items = int(tool_args.get("max_items") or DEFAULT_LIST_ITEMS)
            except (TypeError, ValueError):
                max_items = DEFAULT_LIST_ITEMS
            max_items = max(1, min(max_items, MAX_LIST_ITEMS))

            files = list_files(
                root,
                subdir=str(tool_args.get("subdir") or "."),
                max_items=max_items,
            )
            payload = {
                "returned": len(files),
                "truncated": len(files) >= max_items,
                "files": files,
            }
            return json.dumps(payload, ensure_ascii=False)

        elif tool_name == "read_file":
            file_path = str(tool_args.get("file_path") or "").strip()
            if not file_path:
                return "缺少参数 file_path"
            target = _safe(root, file_path)
            if not target.exists():
                return f"文件不存在: {file_path}"
            if target.is_dir():
                return f"{file_path} 是目录，不是文件"
            return read_text_snippet(target)

        return f"未知工具: {tool_name}"

    except PathViolation as e:
        return f"越界访问被拒绝: {e}"
    except Exception as e:
        return f"工具执行报错: {type(e).__name__}: {e}"


def _extract_json(text: str):
    """从模型回复里抠出 JSON 数组，容忍 ```json 包裹和前后说明文字。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    start, end = s.find("["), s.rfind("]")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


def generate_plan(root: Path, instruction: str, api_key: str, base_url: str, model_name: str) -> list[dict]:
    client = OpenAI(api_key=api_key, base_url=base_url)
    task_id = str(uuid.uuid4())[:8]
    log_action(task_id, "Agent启动", "开始", f"指令: {instruction}")

    system_prompt = """
    你是一个强大的文件整理助手。你可以调用提供的工具来调查目录里的文件内容。
    注意：工具返回的文件列表可能有数量上限（truncated 为 true 时还有文件没列出），
    没列出的文件依然存在，不要假设它们不存在，必要时用 subdir 缩小范围再查。
    当调查清楚后，你不需要再调用工具，直接输出最终的整理方案。
    最终方案必须是一个合法的 JSON 数组，不要带 markdown 标记，也不要任何解释文字，格式如下：
    [
        {"src": "原路径", "dst": "目标路径", "action": "move", "reason": ""}
    ]
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]

    json_failures = 0

    for step in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=TOOLS,
            temperature=0.1,
        )

        msg = response.choices[0].message
        messages.append(msg)

        # 情况 A：大模型觉得调查完了，输出了最终文本（方案）
        if not msg.tool_calls:
            try:
                raw_plan = _extract_json(msg.content)
                if not isinstance(raw_plan, list):
                    raise ValueError("顶层必须是 JSON 数组")
                log_action(task_id, "方案生成", "成功", f"生成了 {len(raw_plan)} 条计划")
                return _validate_plan(raw_plan, root, task_id)
            except (json.JSONDecodeError, ValueError) as e:
                json_failures += 1
                log_action(task_id, "方案解析失败", "警告", f"{e}（第 {json_failures} 次）")
                if json_failures > MAX_JSON_RETRIES:
                    raise Exception(
                        f"模型连续 {json_failures} 次没有输出合法的 JSON 方案，已终止。"
                        "建议换一个更强的模型，或把指令拆细一些。"
                    )
                messages.append({
                    "role": "user",
                    "content": f"你输出的内容不是合法的 JSON 数组（{e}）。请只输出 JSON 数组本身，不要任何解释文字。",
                })
                continue

        # 情况 B：大模型决定调用工具（它可能一次调用一个或多个）
        for tool_call in msg.tool_calls:
            function_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("参数必须是 JSON 对象")
            except Exception as e:
                observation = f"参数解析失败: {e}。请用合法的 JSON 重新调用该工具。"
                log_action(task_id, "工具参数错误", "警告", observation[:200])
            else:
                log_action(task_id, "思考与行动", "进行中", f"调用工具 {function_name}, 参数: {arguments}")
                observation = execute_tool(function_name, arguments, root)
                log_action(task_id, "工具返回", "完成", f"结果: {observation[:200]}")

            # 把工具执行的结果，返回给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": observation,
            })

    log_action(task_id, "Agent终止", "失败", f"思考超过 {MAX_STEPS} 步")
    raise Exception(
        f"Agent 思考超过 {MAX_STEPS} 步，为了安全已强行终止。"
        "可以换更具体的指令，或缩小范围后重试。"
    )


def _validate_plan(raw_plan: list[dict], root: Path, task_id: str) -> list[dict]:
    """安全预检：越界 / 文件不存在 / 目标已存在 / 方案内自冲突。"""
    validated: list[dict] = []
    used_dst: set[str] = set()
    stat = {"ok": 0, "conflict": 0, "error": 0}

    for item in raw_plan:
        item.setdefault("action", ACTION_MOVE)
        item.setdefault("reason", "")
        src_raw = str(item.get("src") or "").strip()
        dst_raw = str(item.get("dst") or "").strip()

        try:
            if not src_raw or not dst_raw:
                raise ValueError("src/dst 不能为空")

            src_path = _safe(root, src_raw)
            dst_path = _safe(root, dst_raw)

            if not src_path.exists():
                raise FileNotFoundError("文件不存在")

            key = dst_path.as_posix().lower()
            if key in used_dst:
                item["status"] = STATUS_CONFLICT
                item["reason"] = "同一方案内多个文件指向同一目标"
                item["action"] = ACTION_SKIP
                stat["conflict"] += 1
                log_action(task_id, "预检冲突", "警告", f"{src_raw} -> {dst_raw}")
            elif dst_path.exists():
                item["status"] = STATUS_CONFLICT
                item["reason"] = "目标已存在"
                item["action"] = ACTION_SKIP
                used_dst.add(key)
                stat["conflict"] += 1
                log_action(task_id, "预检冲突", "警告", f"目标已存在: {dst_raw}")
            else:
                used_dst.add(key)
                item["status"] = STATUS_OK
                stat["ok"] += 1

        except PathViolation:
            item["status"] = STATUS_ERROR
            item["reason"] = "试图越界访问"
            item["action"] = ACTION_SKIP
            stat["error"] += 1
            log_action(task_id, "预检拦截", "警告", f"拦截文件: {src_raw}，原因: 试图越界访问")
        except Exception as e:
            item["status"] = STATUS_ERROR
            item["reason"] = str(e)
            item["action"] = ACTION_SKIP
            stat["error"] += 1
            log_action(task_id, "预检拦截", "警告", f"拦截文件: {src_raw}，原因: {e}")

        validated.append(item)

    log_action(task_id, "预检汇总", "完成",
               f"ok={stat['ok']} conflict={stat['conflict']} error={stat['error']}")
    return validated
