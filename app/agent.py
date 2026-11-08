import os
import json
import uuid
import time
from pathlib import Path
from openai import OpenAI
from app.tools import list_files, _safe, PathViolation
from app.db import log_action

def get_models(api_key: str, base_url: str) -> list[str]:
    """向 API 请求当前 Key 支持哪些模型"""
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        models = client.models.list()
        return sorted([model.id for model in models.data])
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []
# 1. 定义通用工具箱（用 JSON Schema 描述）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "递归获取当前文件夹下的所有文件和它们的相对路径、大小、修改时间。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的前500个字符内容（用于查看文件内部是什么，比如 JSON 里的 email 或者 TXT 里的文字）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件的相对路径"}
                },
                "required": ["file_path"]
            }
        }
    }
]


# 2. 真实的工具执行层
def execute_tool(tool_name: str, tool_args: dict, root: Path) -> str:
    try:
        if tool_name == "list_files":
            files = list_files(root)
            return json.dumps(files, ensure_ascii=False)

        elif tool_name == "read_file":
            file_path = tool_args.get("file_path", "")
            target = _safe(root, file_path)
            if not target.exists():
                return "文件不存在"
            with open(target, "r", encoding="utf-8") as f:
                return f.read(500)
        return "未知工具"
    except Exception as e:
        return f"工具执行报错: {e}"


def generate_plan(root: Path, instruction: str, api_key: str, base_url: str, model_name: str) -> list[dict]:
    client = OpenAI(api_key=api_key, base_url=base_url)
    task_id = str(uuid.uuid4())[:8]
    log_action(task_id, "Agent启动", "开始", f"指令: {instruction}")

    # Prompt 里只规定最终输出格式，不再规定思考动作
    system_prompt = """
    你是一个强大的文件整理助手。你可以调用提供的工具来调查目录里的文件内容。
    当调查清楚后，你不需要再调用工具，直接输出最终的整理方案。
    最终方案必须是一个合法的 JSON 数组，不要带 markdown 标记，格式如下：
    [
        {"src": "原路径", "dst": "目标路径", "action": "move", "reason": ""}
    ]
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction}
    ]

    max_steps = 5
    for step in range(max_steps):
        # 调用 API 时，把工具箱（TOOLS）一并传进
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=TOOLS,  # 自动决定要不要用工具
            temperature=0.1
        )

        msg = response.choices[0].message
        # 把大模型的回复加入历史
        messages.append(msg)

        # 情况 A：大模型觉得调查完了，输出了最终文本（方案）
        if not msg.tool_calls:
            content = msg.content.strip()
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]

            try:
                raw_plan = json.loads(content)
                log_action(task_id, "方案生成", "成功", f"生成了 {len(raw_plan)} 条计划")
                return _validate_plan(raw_plan, root, task_id)
            except json.JSONDecodeError:
                messages.append({"role": "user", "content": "你输出的不是合法的 JSON，请重试。"})
                continue

        # 情况 B：大模型决定调用工具（它可能一次调用一个或多个）
        for tool_call in msg.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            self_log = f"调用工具 {function_name}, 参数: {arguments}"
            log_action(task_id, "思考与行动", "进行中", self_log)

            # 代码替大模型执行工具
            observation = execute_tool(function_name, arguments, root)

            log_action(task_id, "工具返回", "完成", f"结果: {observation[:50]}...")

            # 把工具执行的结果，返回给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": observation
            })

    raise Exception("Agent 思考超限，为了安全已强行终止。")


def _validate_plan(raw_plan: list[dict], root: Path, task_id: str) -> list[dict]:
    """安全预检：检查大模型生成的方案是否合法"""
    validated_plan = []
    for item in raw_plan:
        try:
            src_path = _safe(root, item["src"])
            if not src_path.exists():
                item["status"] = "error"
                item["reason"] = "文件不存在"
            else:
                _safe(root, item["dst"])
                item["status"] = "ok"
        except PathViolation:
            item["status"] = "error"
            item["reason"] = "试图越界访问"
        except Exception as e:
            item["status"] = "error"
            item["reason"] = str(e)

        # 如果出错，强制动作变为 skip
        if item["status"] == "error":
            item["action"] = "skip"
            log_action(task_id, "预检拦截", "警告", f"拦截文件: {item['src']}，原因: {item['reason']}")

        validated_plan.append(item)
    return validated_plan

# _validate_plan 函数保持不变（和你之前的一样）