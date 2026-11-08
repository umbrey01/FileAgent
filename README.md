# FileAgent - 受限文件整理智能体 (Restricted File Agent)

一个基于大语言模型（LLM）的本地桌面端智能文件整理工具。采用 **ReAct（Reasoning and Acting）** 架构与 **Function Calling** 技术，让 AI 能够理解复杂的自然语言指令，并动态调用本地工具进行文件整理。

## 🌟 核心特性 (Features)

*   **原生 Function Calling**：大模型根据提供的 Tool Schema，自主决定调用 `list_files` 或 `read_file` 等底层工具来收集信息。
*   **安全边界控制 (Guardrails)**：采用“路径围栏”技术，模型的所有操作被严格限制在用户指定的根目录内，彻底防止越权访问。
*   **人类审批机制 (Human-in-the-loop)**：模型仅负责生成 Diff 计划，必须经过用户的“批准”才会真正在本地硬盘上执行文件移动。
*   **物理二次校验**：在执行前强制检查文件物理状态，解决 UI 缓存或跨进程文件锁定导致的数据不一致问题。
*   **Trace 审计链**：基于 SQLite 记录大模型思考过程、工具调用与最终执行结果，做到全程可追溯。

## 🏗️ 架构设计与解耦 (Architecture & Decoupling)

本项目严格遵循“表现层与逻辑层分离”的设计原则：
*   `gui.py` (表现层)：基于 Tkinter 构建的 UI，负责接收指令与展示审批表格。**（高度可迁移：如需迁移至 PyQt 或 Web 端，只需重写此文件，核心 Agent 逻辑无需改动）**
*   `agent.py` (规划层)：基于 ReAct 循环的核心大脑，负责与大模型通信并管理思维链，原生支持兼容 OpenAI 格式的 API。
*   `tools.py` (执行与安全层)：提供受限的操作工具，内置防越权路径校验与异常处理，完全独立于 UI。
*   `db.py` (持久层)：存储操作审计日志，保证操作的可追溯性。

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保已安装 Python 3.10+。
```bash
# 克隆仓库
git clone https://github.com/umbrey01/FileAgent.git
cd FileAgent

# 安装依赖 (推荐使用 uv，也可使用 pip)
uv sync
# 或 pip install -r requirements.txt
