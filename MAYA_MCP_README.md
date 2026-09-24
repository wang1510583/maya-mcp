# Maya MCP 0.1.0

把当前项目的 Maya Agent 工具接到 Codex / 其他支持本地 stdio MCP 的客户端。
无需在 Maya Agent 设置大模型 API Key；推理由外部客户端负责。

## 安装和启动

Windows PowerShell 在项目目录运行：

```powershell
.\install_maya_mcp.ps1 -MayaVersion 2024
```

安装程序使用 uv 创建独立 Python 3.12 环境，准备 Maya 端的纯 Python PyYAML，
备份并追加 Maya 的 `userSetup.py`，然后注册 Codex MCP `maya-agent`。
原有 Maya Agent、其他启动脚本和 Blender MCP 配置保留。
项目目录是安装位置，安装后不要移动或删除；移动后重新运行安装程序。

已经打开 Maya：将本目录 **install_maya_mcp.mel** 拖入视口，无需重启或重开场景。
以后正常启动 Maya 会自动加载。工具架 **MayaMCP → Start / Stop** 可以开关连接。
第一次在 Codex 添加 MCP 后，在设置的 MCP 列表确认 `maya-agent` 已启用；
按客户端提供的重载方式刷新连接，必要时重新打开 Codex。

## 使用

- “查看 Maya 当前场景和选中物体。”
- “截取 Maya 当前视口。”
- “创建一个测试立方体，设置第 1 帧和第 24 帧的位置关键帧。”
- “查询自动绑定相关工具，先解释参数，不执行。”
- “把选中的物体导出为 FBX 到指定路径。”

直接提供 10 个 MCP 工具（现有 Maya Agent 工具共 117 个）：

| 工具 | 功能 |
| --- | --- |
| get_maya_status | 版本、连接的进程、场景、工具数量 |
| get_scene_info | 层级摘要、选择、相机、时间轴 |
| get_object_info | 物体层级和变换 |
| execute_maya_code | 主线程执行 Python，返回 result / stdout / stderr |
| execute_mel | 主线程执行 MEL |
| get_viewport_screenshot | 返回可被 AI 直接查看的 PNG 图像 |
| list_maya_tools | 按关键词/分类检索原插件工具及参数 |
| call_maya_tool | 调用检索到的工具（当前项目共 117 个） |
| undo_maya_operation | 仅撤销名称吻合且仍位于栈顶的 MCP 操作 |
| create_custom_body_rig | 创建「自定义身体绑定」，2–64 根骨骼及同数量控制器，总高度可调 |

`execute_maya_code` 中已提供 `cmds`，将结果赋给 `result` 可返回结构化数据。
每次脚本调用的命名空间独立；跨步骤保存状态请使用 Maya 场景节点。

### 自定义身体绑定 v1.1.0

例如：“创建自定义身体绑定，8 根骨骼和控制器，总高度 6 厘米。”
参数为 `segment_count=8`、`height=6.0`，默认仍为原版四节。
若客户端还缓存着旧版直接工具参数，请刷新 MCP 连接，或调用：

```json
{"name": "create_custom_body_rig", "arguments": {"namespace": "body8", "segment_count": 8, "height": 6.0}}
```

上述 JSON 用于 `call_maya_tool`。数量仅在新建时设置；已有动画和蒙皮不会被自动改造。
模块说明见 [自定义身体绑定](maya_agent/rigs/custom_body/README.md)。

## 其他 MCP 客户端

配置本地 stdio，示例路径需按实际位置修改：

```json
{
  "mcpServers": {
    "maya-agent": {
      "command": "D:/MAYA/MayaAgent-main/MayaAgent-main/.venv-mcp/Scripts/python.exe",
      "args": ["D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/run_maya_mcp.py"]
    }
  }
}
```

## 连接与执行规则

- MCP 进程通过标准输入输出通信；Maya 端仅监听 `127.0.0.1:9877`。
- 连接凭据自动生成，存于安装时的 `%APPDATA%/MayaMCP/connection.json`，不写入仓库或 MCP 提示。
  `.maya-mcp-runtime.json` 只记录该文件的绝对路径，确保 Maya 和外部客户端使用同一个文件。
  Windows 打包应用可能把 APPDATA 重定向到 `LocalCache/Roaming`；固定路径可避免两端认证不一致。
  同一用户的本地程序可以读取该凭据；这不是针对同用户恶意程序的隔离沙箱。
- 所有 Maya 操作通过 Qt 定时器在主线程执行。不会在执行异常后改到后台线程重试。
- 排队超时的操作会取消；已开始的 Python/MEL 不能安全中断，超时后要先检查场景。
- 修改操作使用 Undo 分组，但文件写入、导出、部分插件操作不支持撤销。
- MCP 调用以外部客户端的授权为准，不弹原 Maya Agent 聊天面板的二次确认。
  Python/MEL 具有当前用户权限，请只连接信任的客户端。
- 同一端口只连接一个 Maya 进程；先用 `get_maya_status` 核对场景和 PID。
- Maya 端要求 Python 3 和 PySide2/PySide6，当前目标环境为 Maya 2024。
  Maya 2020 的 Python 2 环境不支持；其他版本尚未验证。

## 验证与故障排查

本机 Maya 2024 已完成交互式验证：标准 MCP 初始化、9 个工具的发现、
场景查询、主线程 Python、MEL、原插件工具调用和 PNG 视口截图均通过。
验证只执行读取操作，前后场景摘要一致。报告：`outputs/mcp-tests/live-verification.json`。
这不代表原插件的全部 116 个工具或复杂绑定效果都已逐项验证。
后续增加了第 10 个直接工具 `create_custom_body_rig`；已验证 2、3、4、6、8、64 节绑定及四节/六节撤销重做。
`outputs/` 内的本机场景和报告不提交到 GitHub，仓库保留可重复运行的测试脚本。
外部工具尚未刷新时，当前任务也可以通过本地 MCP 客户端连接；
要让新工具直接出现在 Codex 工具列表中，需要刷新该 MCP 连接。

重复执行只读实机验证：

```powershell
.venv-mcp/Scripts/python.exe scripts/verify_maya_mcp_live.py
```

发生加载问题时重新拖入 `install_maya_mcp.mel`：它会停止服务、重载模块、重新启动，
并把不含连接令牌的诊断信息写入 `outputs/mcp-runtime.json`。

协议测试（模拟 Maya 调度器，不等于 Maya 实机验证）：

```powershell
uv pip install --python .venv-mcp/Scripts/python.exe pytest
.venv-mcp/Scripts/python.exe -m pytest tests_mcp -q
```

Maya 独立进程集成测试（在独立空场景创建、打帧、撤销，不碰当前 GUI 场景）：

```powershell
.venv-mcp/Scripts/python.exe scripts/test_mcp_integration.py D:/maya2024/Maya2024/bin/mayapy.exe
```

报告写到 `outputs/mcp-tests/`。若 `import maya.standalone` 报 DLL 初始化失败，
这是独立 Maya 运行时启动问题；可在交互式 Maya 拖入安装脚本，再检查连接。
若 `Address already in use`，先检查另一个 Maya 进程是否占用了 9877。
若提示未连接，确保 Maya 不在模态窗口或长时间计算中，点击 Start 后重试只读查询。

## 停用 / 卸载

在 MayaMCP 工具架点击 Stop。删除启动钩子（不删除其他启动代码）：

```powershell
.venv-mcp/Scripts/python.exe -m maya_mcp.install --scripts-dir "$env:USERPROFILE/Documents/maya/2024/scripts" --remove
codex mcp remove maya-agent
```

在 Maya 工具架管理中删除 MayaMCP 页签。原始 userSetup 备份在同一 scripts 目录。

Codex 配置依据：[OpenAI 官方 MCP 文档](https://developers.openai.com/codex/mcp/)。
