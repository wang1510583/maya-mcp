# 自定义身体绑定 v1.1.0

以用户确认的四节脊柱绑定为基础，支持在创建时指定 2–64 根骨骼及同数量控制器。
不依赖示例场景、outputs 目录、AdvancedSkeleton 或 AI API。

## 调用

直接说 **“创建自定义身体绑定”**。

- MCP 直接工具：`create_custom_body_rig`。
- 原 Maya Agent 工具：`create_custom_body_rig`，显示名 **自定义身体绑定**，分类 `rigging`。
- 若客户端未刷新工具列表：`call_maya_tool(name="create_custom_body_rig", arguments={})`。

Maya Python：

```python
from maya_agent.rigs.custom_body import build
rig = build()  # customBody；重名后生成 customBody_02、customBody_03...
rig = build(namespace="heroBody", on_conflict="error")
rig = build(namespace="heroBody6", segment_count=6, height=10.0)
```

也可以直接说：**“创建自定义身体绑定，6 根骨骼和 6 个控制器，总高度 10 厘米。”**

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `segment_count` | `4` | 骨骼和控制器总数，包含髋部、胸部，整数 2–64 |
| `height` | `6.0` | 初始髋部到胸部总高度，正数，厘米 |
| `namespace` | `customBody` | 新绑定的独立命名空间 |
| `on_conflict` | `increment` | 重名时编号；`error` 则报错 |

数量与高度是**新建参数**。已生成绑定的数量标签只读；本版本不在已有动画或蒙皮上动态增删骨骼。
骨骼与控制器数量相同，暂不支持两者分别指定。控制器外观尺寸保持原版，不随高度自动缩放。

返回名称、版本、命名空间、数量、总高度、控制器映射、关节列表和创建的节点列表。
版本信息同时保存在 `命名空间:hips_zero.customBodyRigVersion`。

## 当前行为

- 默认四节仍为四个曲线控制器、四根骨骼、45 个模板节点、121 条逻辑连接。
- 非四节按数量生成骨骼链及中段 zero / driven / connect / ctrl 层级；中段使用 spine01、spine02 等名字。
- 保持总高度，初始间距为 `height / (segment_count - 1)`。
- 非四节的中段胸部位移比例为 `i / (segment_count - 1)`，髋/胸旋转权重为 `(segment_count - 1 - i):i`。
- 原有 zero / driven / connect 层级、控制器形状和显示颜色。
- 四节模式中上下脊柱分别按髋/胸 1:2、2:1 混合旋转，保留原版约束插值。
- 四节模式中胸部局部平移分别按 0.333 / 0.667 分配给下/上脊柱。
- 矩阵链的 pickMatrix 仅传递位置。
- 原生节点生成后，无需本 Python 模块常驻即可操作和保存场景。

当前仅创建绑定，不自动适配角色网格或蒙皮；单位要求为厘米。
版本 1.1.0 保留原版局部空间计算，不宣称支持任意父级变换或整体缩放。

## 模块分工

| 文件 | 扩展位置 |
| --- | --- |
| `definition.py` | 名称、版本、模板加载及参数检查 |
| `data/body_v1.json` | 版本化节点参数、连接、控制器 CV、骨骼定义 |
| `data/body_v2.json` | 可调版本配方元数据及参数范围 |
| `topology.py` | 由包内原版节点原型生成可调拓扑；默认四节兼容分支 |
| `controls.py` | 控制器、分组层级、用户参数 |
| `skeleton.py` | 骨骼结构 |
| `drivers.py` | 矩阵、旋转混合、约束节点和连线 |
| `display.py` | 独立显示层 |
| `nodes.py` | 共用原生节点创建和属性恢复 |
| `context.py` | 名称映射、创建清单、失败清理 |
| `builder.py` | 分阶段组装、Undo、版本标签、返回结果 |
| `../../tools/custom_body_rig.py` | AI 工具参数和中文说明 |

## 新增功能约定

1. 用户提出新功能后，先明确它影响控制器、骨架、驱动还是显示。
2. 在对应模块扩展；新增系统可增加组件文件并插入 `builder.COMPONENTS`。
3. 拓扑或节点规则改变时增加模板版本，更新 VERSION，不静默改写已创建的旧场景。
4. 返回结果继续保留 `namespace/controls/joints/nodes/version`，供下游工具调用。
5. 注册器只负责参数和工具说明，MCP 只负责转发；绑定逻辑保留在本目录。
6. 新建节点必须登记到 `ctx.created`，让失败清理和批量测试可追踪。
7. 显示层编号由 Maya 分配，不能重用捕获文件中的 layerManager 索引。
8. 修改后验证基准姿态、髋/胸平移、旋转混合、独立中段控制及重复创建互不影响。

本机 Maya 2024 实测通过：注册调用、曲线形状、平移分配、旋转混合、重复创建互相独立、
重名拒绝、失败清理，以及独立 MCP 请求中的整次撤销/重做（包括曲线和显示层）。
验证报告在项目 `outputs/custom-body-tests/`，运行本模块不需要这些报告。

v1.1.0 已在 Maya 2024 实测 2、3、4、6、8、64 节，不同高度、端点位移/旋转、中段独立平移和弯曲、不同节数共存、非法参数拒绝，以及四节/六节 MCP 撤销重做。
自动化入口：`scripts/run_custom_body_adjustable_tests.py`、`scripts/test_custom_body_mcp.py 6 10`。
离线回归包含默认四节节点参数与连接同原版模板逐项相等检查。

默认不会覆盖现有节点、修改现有动画、切换场景或自动保存文件。
一次创建为一个 Undo 分组；失败只清理本次创建的命名空间和节点。

## 打包

`pyproject.toml` 包含本目录 JSON 数据。目录可随 Maya Agent 项目一起迁移。
只运行本模块时需要 Maya Python；它不使用 httpx、模型服务或原插件聊天界面。
