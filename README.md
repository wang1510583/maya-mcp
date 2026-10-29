# Maya MCP

通过 MCP 用自然语言控制 Autodesk Maya，包含本地桥接、Maya Agent 工具库，以及模块化的「自定义身体绑定」。

本项目基于随附的 Maya Agent 1.3.1 扩展，保留其 MIT 许可。原插件介绍见 [Maya Agent 文档](docs/MAYA_AGENT_README.md)。

## 功能

- 10 个直接 MCP 工具：场景与对象查询、Python / MEL 执行、视口截图、工具检索与调用、受保护的撤销、自定义身体绑定。
- 通过注册器调用 120 个 Maya 工具，覆盖建模、UV、绑定、动画、材质、灯光和导出。
- 「自定义身体绑定 v1.3.2」支持 2–64 根骨骼及同数量控制器，总高度可调。独立 Maya 窗口可按选择顺序匹配物体并驱动；「拷贝动画至控制器」按帧范围转移普通 TR 动画并保留原曲线备份，普通缩放关键帧保留在原物体上。默认四节保留已验证的原版行为。
- 在 Maya 主线程执行操作，使用独立命名空间和 Undo 分组；重复创建保留现有绑定及动画。
- 外部 MCP 客户端负责 AI 推理，桥接本身无需模型 API Key。原 Maya Agent 聊天界面可另行配置模型服务。

## 集成角色绑定 v1.26.28

将 `自定义人物绑定插件/安装插件.py` 拖入 Maya（外层 `install_integrated_rig.py` 仍可用），可在一个面板中创建身体、头颈、左右肩膀、手臂和腿部。左键载入所选目标，右键设置，中键清空；未载入部位跳过。动画拷贝及多空间默认勾选，支持通用根控制器和有动画时调整腿部支点。

新建角色包含原点总控制圆环，平移和旋转带动全身及 IK 手脚；使用“整体缩放”属性等比例缩放骨骼、控制器和蒙皮，原 Scale XYZ 保持锁定。已有角色须显式点击“添加 / 升级 / 选择总控制圆环”升级，不在打开窗口时自动修改场景。

整个 `自定义人物绑定插件/` 文件夹可独立复制分发，普通绑定无需 MCP 或网络。安装细节见 [使用说明](自定义人物绑定插件/使用说明.md)。

最新版本保留引用角色的控制器操作及普通 S 键兼容；脚跟、脚尖支点、脚掌的视口移动和旋转补偿位移统一记录到脚腕，移动超过可达范围时实际输入停止向外累积。旧支点位移动画不自动清零，通道栏直接输入保持原行为。

### 本草角色绑定助手 1.0.6

发给动画师时，只需提供 [本草角色绑定.py](本草角色绑定.py) 和角色场景；下载原始文件后拖入 Maya，即可创建“本草绑定”工具架及启动按钮。助手界面只有“已开启 / 已关闭”按钮，不需要另带 `maya_agent` 文件夹、MCP 或网络。

也提供 [文件夹版压缩包](本草角色绑定.zip)、[助手使用说明](runtime_assistant/给动画师的使用说明.md) 和 [运行助手源码](runtime_assistant/)。升级前保存工作并重启 Maya，再拖入新版。文件校验见 [SHA256SUMS.txt](SHA256SUMS.txt)，验证范围见 [发布验证记录](docs/releases/1.26.28.json)。

“载入胸部跟随对象”和“载入腰部跟随对象”：单独创建部位时分别载入 `spine_03` / `pelvis`；通用根仅用于整体移动。

部位总组独立，肩膀连接胸部、髋起点跟随腰部，脚部 IK 保持独立。修复手臂重复对齐漂移和腿部设置菜单刷新；控制器空间属性统一命名 `global`，膝盖可跟随同侧脚腕。

只建立用于隐藏辅助物体的 `NoDisplay` 层；身体不再生成 `layer1/2/3`，原颜色保留。详见 [集成面板说明](自定义人物绑定插件/maya_agent/rigs/integrated/README.md)。独立入口为 `install_custom_body_rig.mel`、`install_custom_arm_rig.py`、`install_custom_leg_rig.py`。

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

只使用身体绑定界面时，将 `install_custom_body_rig.mel` 拖入 Maya 即可；无需启动 MCP 或配置模型。
详见 [独立脚本插件说明](CUSTOM_BODY_PLUGIN_README.md)。

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
| `maya_agent/` | 原插件工具库、可选聊天 UI，以及独立绑定包路径入口 |
| `自定义人物绑定插件/` | 独立安装器、绑定组件、Max BIP 转换依赖及版本化模板 |
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

桥接只监听 `127.0.0.1:9877`，使用本机随机凭据。运行环境、凭据、用户场景、截图、备份与 `outputs/` 不进入仓库；`rigs/soft_limb/data/limb_v1.ma` 和 `rigs/soft_leg/data/leg_v1.ma` 是运行所需的精简绑定模板，随代码发布。Python / MEL 执行具有当前用户权限，只连接信任的 MCP 客户端。

采用 [MIT License](LICENSE)，保留原 Maya Agent Contributors 版权声明。
