# Maya MCP

通过 MCP 用自然语言控制 Autodesk Maya，包含本地桥接、Maya Agent 工具库，以及模块化的「自定义身体绑定」。

本项目基于随附的 Maya Agent 1.3.1 扩展，保留其 MIT 许可。原插件介绍见 [Maya Agent 文档](docs/MAYA_AGENT_README.md)。

## 功能

- 10 个直接 MCP 工具：场景与对象查询、Python / MEL 执行、视口截图、工具检索与调用、受保护的撤销、自定义身体绑定。
- 通过注册器调用 117 个 Maya 工具，覆盖建模、UV、绑定、动画、材质、灯光和导出。
- 「自定义身体绑定 v1.1.0」支持 2–64 根骨骼及同数量控制器，总高度可调。默认四节保留已验证的原版行为。
- 在 Maya 主线程执行操作，使用独立命名空间和 Undo 分组；重复创建保留现有绑定及动画。
- 外部 MCP 客户端负责 AI 推理，桥接本身无需模型 API Key。原 Maya Agent 聊天界面可另行配置模型服务。

## 安装

已实测 Windows + Maya 2024.2。Maya 端使用其自带 Python 3 / PySide2；外部 MCP 服务使用 Python 3.12。其他 Maya 版本尚未验证。

1. 下载或克隆仓库，放到准备长期使用的目录。
2. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，并确保 MCP 客户端可用。
3. 在项目目录运行：

```powershell
.\install_maya_mcp.ps1 -MayaVersion 2024
```

该命令准备依赖、保留并追加 Maya 启动脚本，同时注册 Codex MCP。其他客户端可加 `-SkipCodex`，然后按 [MCP 安装说明](MAYA_MCP_README.md) 配置 stdio。

4. 将 `install_maya_mcp.mel` 拖入已打开的 Maya 视口；MayaMCP 工具架提供 Start / Stop。
5. 刷新客户端的 MCP 连接，再查询当前 Maya 场景确认连接。

## 使用示例

- “查看 Maya 当前场景。”
- “创建一个立方体，让它跳一下。”
- “创建自定义身体绑定，8 根骨骼和控制器，总高度 6 厘米。”

Maya Python 也可以直接调用绑定模块：

```python
from maya_agent.rigs.custom_body import build
rig = build(namespace="body8", segment_count=8, height=6.0)
```

骨骼与控制器数量相同，包含髋部和胸部。数量和高度是在新建时设置的参数，不会在已有动画或蒙皮上直接增删骨骼。

[完整 MCP 说明](MAYA_MCP_README.md) · [绑定模块与扩展说明](maya_agent/rigs/custom_body/README.md)

## 目录

| 目录 | 内容 |
| --- | --- |
| `maya_mcp/` | 本地 socket 桥接、Maya 主线程调度与 stdio MCP 服务 |
| `maya_agent/` | 原插件工具库、可选聊天 UI，以及模块化绑定 |
| `maya_agent/rigs/custom_body/` | 绑定组件、参数化拓扑及包内版本化数据 |
| `scripts/` | 安装、启动、热更新与验证脚本 |
| `tests_mcp/` | 离线协议、导入及绑定定义回归测试 |

## 验证

```powershell
uv pip install --python .venv-mcp/Scripts/python.exe pytest
.venv-mcp/Scripts/python.exe -m pytest tests_mcp -q
```

Maya 2024 交互式测试覆盖 2、3、4、6、8、64 节绑定，位移分配、旋转混合、中段弯曲、实例独立及撤销重做。并非原工具库的全部工具都已逐项实测。

实机场景只读检查：`scripts/verify_maya_mcp_live.py`。绑定验证：`scripts/run_custom_body_tests.py`、`scripts/run_custom_body_adjustable_tests.py`。绑定测试会创建并清理自身临时节点，并检查用户已有内容保持不变。

## 本地数据与许可

桥接只监听 `127.0.0.1:9877`，使用本机随机凭据。运行环境、凭据、场景、截图、备份与 `outputs/` 不进入仓库。Python / MEL 执行具有当前用户权限，只连接信任的 MCP 客户端。

采用 [MIT License](LICENSE)，保留原 Maya Agent Contributors 版权声明。
