![CodexMCP](./images/title.png)

<div align="center">

**让 Claude Code 与 Codex 无缝协作**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT) [![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/) [![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

[English](./docs/README_EN.md) | 简体中文

> Fork from [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp) | Refactored by Claude Opus 4.5

</div>

---

## 快速开始

### 前置要求

- **Claude Code** v2.0.56+
- **Codex CLI** v0.61.0+
- **uv** 包管理器

### 安装

```bash
# 移除旧版本（如已安装）
claude mcp remove codex

# 安装
claude mcp add codex -s user --transport stdio -- uvx --from git+https://github.com/shiharuharu/codexmcp.git codexmcp

# 验证
claude mcp list
```

---

## 环境变量

精简设计，仅 **4 个** 环境变量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CODEXMCP_LOG_LEVEL` | 日志级别，设为 `DEBUG` 启用详细输出 | `WARNING` |
| `CODEXMCP_LOG_FILE` | 日志文件路径，`auto` 自动生成 | *(空)* |
| `CODEXMCP_LIVE_UI` | 启用 GUI 实时查看器 | `false` |
| `CODEXMCP_VIEW_ALL` | 显示所有事件详情 | `false` |

```bash
# 开发调试模式
CODEXMCP_LOG_LEVEL=DEBUG CODEXMCP_LIVE_UI=1 codexmcp

# 生产环境（零配置）
codexmcp
```

---

## Codex 工具

### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:----:|--------|------|
| `PROMPT` | `str` | ✅ | - | 任务指令 |
| `cd` | `Path` | ✅ | - | 工作目录 |
| `sandbox` | `str` | | `read-only` | 沙箱策略 |
| `SESSION_ID` | `str` | | `""` | 恢复会话 ID |
| `return_all_messages` | `bool` | | `false` | 返回所有 agent_message |
| `image` | `List[Path]` | | `[]` | 附加图片 |
| `model` | `str` | | `""` | 指定模型 |
| `yolo` | `bool` | | `false` | 无审批模式 |
| `profile` | `str` | | `""` | 配置文件名 |
| `skip_git_repo_check` | `bool` | | `true` | 跳过 Git 检查 |

### 沙箱策略

| 策略 | 说明 |
|------|------|
| `read-only` | **推荐** - 只读访问 |
| `workspace-write` | 允许写入工作目录 |
| `danger-full-access` | 完全访问（危险） |

### 返回值

```json
// 正常响应
{
  "success": true,
  "SESSION_ID": "sess_abc123",
  "agent_messages": "最后一条 agent 回复",
  "log_file": "/tmp/codexmcp-xxx.jsonl"
}

// return_all_messages=true 时
{
  "success": true,
  "SESSION_ID": "sess_abc123",
  "agent_messages": "最后一条 agent 回复",
  "all_messages": [
    {"type": "agent_message", "text": "第一条回复..."},
    {"type": "agent_message", "text": "最后一条回复..."}
  ],
  "log_file": "/tmp/codexmcp-xxx.jsonl"
}

// LOG_LEVEL=DEBUG 时额外返回
{
  ...,
  "debug_info": {
    "request_id": "abc123",
    "live": { ... }
  }
}
```

---

## GUI 实时监控

启用后显示 Codex 事件流，暗色主题 + 语法着色：

```bash
export CODEXMCP_LIVE_UI=1
```

### 着色方案

| 类型 | 颜色 | 示例 |
|------|------|------|
| `[PROMPT]` | 🔵 蓝 + 🟢 亮绿 | `[PROMPT] 用户输入` |
| `[ASSISTANT]` | ⚪ 近白 | `[ASSISTANT] AI 回复` |
| `[COMMAND]` | 🔵 蓝 + 🟠 橙 | `[COMMAND] ✓ git status` |
| `[TOOL]` | 🔵 蓝 + ⚫ 灰 | `[TOOL] Read 参数...` |
| `[TODO]` | 🔵 蓝 + 🟢 浅绿 | `[TODO] 2/5 done` |
| `[MCP]` | 🔵 蓝 + 🟣 紫 | `[MCP] server/tool ✓` |
| `[ERROR]` | 🔴 红 | `[ERROR] 错误信息` |

### 显示格式

```
[#efgh5678] [THREAD] 019b2293-7741-71f2-bd38-df366ebcd402
[#efgh5678] [COMMAND] ✓ ls -la
[#efgh5678] [TODO] 2/5 done
  ✓ 任务1
  ○ 任务2
  ○ 任务3
[#efgh5678] [ASSISTANT] Here is the result!
[#efgh5678] [TURN COMPLETED] [in=100 cached=50 out=30]
```

---

## 项目结构

```
codexmcp/
├── config.py      # 常量、logging
├── formatters.py  # 事件格式化（富文本着色）
├── sinks.py       # 输出管理（文件、stderr、GUI）
├── shell.py       # 进程管理
├── live_view.py   # GUI 查看器
├── server.py      # MCP Server
└── __init__.py    # 包导出
```

---

## 开发

```bash
git clone https://github.com/shiharuharu/codexmcp.git
cd codexmcp
uv sync
uv run python -c "from codexmcp import *; print('OK')"
```

### 测试 GUI

```bash
# 使用测试数据
uv run python -m codexmcp.live_view --file test_events.jsonl --keep-open

# 实时监控
CODEXMCP_LIVE_UI=1 CODEXMCP_VIEW_ALL=1 codexmcp
```

---

## 许可证

MIT License - Fork from [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp)
