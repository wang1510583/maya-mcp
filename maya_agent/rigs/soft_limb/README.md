# 柔化拉伸肢体：场景复刻 v1.3.1

窗口布局已与身体、腿部工具统一，共用 `maya_agent.rigs.ui_common` 的尺寸、选择列表、动画字段、按钮及提示样式。原有创建、侧别与动画功能保持不变。

从用户提供的完整 Maya 场景中提取 79 个绑定节点，封装为独立的原生 Maya 节点模板。
这是现有结果的功能复刻；不能据此确认原工具的名称、作者或最初搭建操作。
本模块与「自定义身体绑定」分开，不替换脊柱工具。

```python
from maya_agent.rigs.soft_limb import build
rig = build(namespace='limbReplica', offset=(0, 0, 0))
```

重名自动编号；生成独立命名空间和 rig_root 分组。模板在包内，不需要原场景、原工具或临时导出文件。
要求厘米/deg，使用 Maya 自带的 quatNodes。逐条执行经过校验的原生节点创建命令，不调用场景导入，不触发文件打开/导入回调。模板不包含 scriptNode、原场景的时间/渲染设置、相机或 UUID。
所有节点名和连接显式映射到新命名空间。表达式从包内保存的可读数学源码重新编译，不能把 Maya 文件内部的 `.ixp` 字符串当作已编译表达式。

## 结构

- `shldrFK_L1 → armFK_L1 → handFK_L1`：输入 FK 链。
- `elb_L1`、`hand_L1`：中间关节方向和末端位置输入。
- `strech_ik_foot1`：长度、拉伸、柔化、伸直与弯曲下限参数。
- `base_IK_strech1` 下的定位器、表达式及 aim/point 约束：两段骨骼求解。表达式使用余弦定理计算中间关节，再根据柔化、拉伸与下限参数调整。
- `fin_jnt1/2/3`：求解结果，通过约束驱动原始输出链 `joint1/2/3`。
- `base_L1/2/3` 和 `joint4_twist_Base1`：读取输出链的相对旋转，经矩阵分解、四元数到欧拉角、倍率节点驱动 `elbow_roll1`。
- `elbow_roll1.rot_scale` 与 `envelope`：旋转分配比例和强度。

此模板保留原参数拼写（`strech`、`lenght`）及原数学表达式，未擅自替换算法。
没有新增 IK/FK 切换开关；修改输入 FK 链和现有参数即可检查原行为。
零距离/退化长度及极端参数仍可能触发原表达式的数学奇点，不宣称修复原模板的全部边界条件。

## Easy Rig 对齐兼容性

v1.0.1 补回原文件的 `blindDataTemplate` 类型 `recalculate_node`，以及 14 条有序的 visibility 元数据连接。v1.0.0 仅提取了求值图，遗漏此下游登记节点，导致 Easy Rig 的 `kurok_recalculate_system(0)` 找不到所选控制器的对齐配置并直接返回。

`easy_rig.py` 保存对应关系：`base_L1/2/3` 对应三个 FK 输入，`hand_L1` 归零，并登记五个需打关键帧的对象。命名空间内每套绑定都有自己的登记节点；无需修改用户的 Easy Rig 脚本。原脚本对齐操作会打关键帧，其行为保持原样。该修复不增加 IK/FK 切换开关。

v1.3.1 修复移动/旋转 armFK 后重复对齐漂移：肘部对齐参考改为**对齐前的 elb 控制器世界姿态**，让原 Easy Rig 流程先保存它，再在移动 FK 父级后还原。此前登记的 `locator3` 来自肘部扭转辅助链，可能偏离当前求解的弯曲平面；把它回写到 elb 会再次改变骨骼，造成需要再次对齐或持续漂移。现在对齐保持当前肘部方向，连续执行不再改变已求解姿态。

原 `locator3` 和 elbow_roll 辅助图保留，但普通对齐不再用它们改变肘部方向。14 条登记仍完整，支持 L/R、独立手臂、集成手臂和拷贝动画。新建自动生效；旧系统可以调用 `maya_agent.rigs.soft_limb.easy_rig.repair_recalculate_node('手臂命名空间')`，只更新肘部登记连接，保留姿态、曲线及蒙皮。此入口拒绝非本插件生成或登记已被自定义的系统。

回归 `scripts/test_arm_alignment_repeat_live.py` 覆盖左右侧、带动画、辅助点偏离弯曲平面的故障复现、旧系统修复和连续十次对齐的幂等性。

## 按三点一键创建（v1.1.0）

将项目根目录 `install_custom_arm_rig.py` 拖入 Maya，工具架出现「手臂系统」按钮并打开窗口。
打开窗口后按肩 → 肘 → 腕依次选择三个骨骼或物体，检查列表，点击「按当前选择一键创建手臂系统」。
默认驱动原目标；取消勾选可只生成匹配的独立系统。

```python
from maya_agent.rigs.soft_limb import build_from_selection, show_ui
show_ui()
rig = build_from_selection(targets=['|shoulder', '|elbow', '|wrist'])
```

AI 工具为 `create_custom_arm_rig`；也可通过 MCP `call_maya_tool` 调用。省略 targets 使用有序选择，必须提前开启选择顺序追踪。

- 使用世界旋转轴心的位置计算两段长度及弯曲平面；共线输入使用肩部局部 Y 的投影（平行时改用世界轴），可移动 `elb_L1` 调整。
- 完全重合/肩腕重合拒绝创建。需要厘米/度；不支持引用、实例、已有动画/驱动、锁定 TR、非均匀/负缩放或剪切。
- 保留目标朝向、原父子层级、蒙皮和缩放，以保持偏移的父约束驱动，不从目标动态反读输入，避免循环。
- `shldrFK_L1 / armFK_L1 / handFK_L1` 操作 FK，`hand_L1` 操作末端，`elb_L1` 操作肘部方向，`strech_ik_foot1` 调整柔化/伸缩参数。
- 独立命名空间、多套共存；新增肩部位置跟随，原始 `build()` 复刻行为保持不变。整体缩放父组不属于本版本支持范围。
- `selection.py` 负责几何匹配、约束及失败恢复；通用目标前置检查复用 `custom_body.targets`。一次创建可整体撤销。
- 默认不复制动画。原 Easy Rig 对齐会打帧；未勾选动画转移时，生成本身不会打帧。

回归入口：`scripts/test_custom_arm_selection_live.py`（在 Maya 中执行 `verify()`）、`scripts/test_custom_arm_ui_mcp.py`（外部 Python，通过已启动的 MCP bridge）。覆盖不同空间方向、不等长、直线、带 jointOrient 的蒙皮链、等比缩放父级、目标姿态保留、FK/末端驱动、Easy Rig 重新对齐、非法输入、失败回滚及跨请求撤销重做。

原生模板读取时将锁定通道的连接拆成解锁、连接、复锁三步，以保证 Maya 2024 重做。表达式通过显式 `createNode` 后编辑可读源码创建，避免重做时丢失命名空间。失败清理先删本次约束，再删除内部驱动节点，防止 Maya 连带删除受约束的空 transform。

## 拷贝动画至控制器（v1.2.0）

选择三个有普通关键帧的目标，勾选「驱动所选骨骼 / 物体」和「拷贝动画至控制器」，设置起止帧及采样间隔后创建。默认使用播放范围、间隔 1 帧；支持分数帧，最多 10001 个采样帧。

```python
rig = build_from_selection(targets=['|shoulder','|elbow','|wrist'], copy_animation=True,
                           start_frame=1, end_frame=120, sample_step=1)
```

`animation.py` 先用临时定位器记录原世界运动，再断开并备份目标 TR 曲线，建立输出约束，烘焙 FK 控制器、肘定位器及骨骼长度。普通物体的独立旋转不一定与骨骼弯曲平面一致，因此三个 FK 控制器增加「动画补偿位移 / 旋转」通道，驱动骨骼下的三个输出变换，完整保留目标的姿态；没有额外可见控制器。

- `sourceAnimationBackup` 保存原曲线 message 连接和原连接表，原关键帧、切线及区间外动画均保留备份。转移不等于逐条复制原曲线布局。
- 缩放曲线保留在原目标/父级上，每个采样帧检查正值等比缩放。支持带动画父级、不同旋转顺序、jointOrient、静态轴心偏移及蒙皮；动画层、已有约束/表达式/驱动、锁定通道、非均匀/负缩放和剪切仍拒绝。
- 输出使用线性烘焙关键帧，**仅保证指定范围内采样帧的世界姿态**。采样之间及范围外不保证完全匹配，必要时减小采样间隔。
- 完成前后逐帧比较目标世界矩阵，容差 1e-4；临时定位器删除。失败时先释放备份 message 连接，再移除本次约束/节点并接回原动画；可整次撤销/重做。
- 返回 `animation_transfer` 包含采样数量、最大矩阵误差、原曲线数和备份节点。已有手臂系统不会自动升级；此选项用于按所选原目标新建系统。

测试：`scripts/test_custom_arm_animation_live.py` 的 `run_case()`，以及外部运行 `scripts/test_custom_arm_ui_mcp.py --animation`，覆盖动画、蒙皮、等比缩放、失败回滚、UI 创建、原曲线撤销恢复及重做后运动校验。

## 左右侧命名（v1.3.0）

窗口新增「R 右侧手臂（未勾选为 L 左侧）」。按肩 → 肘 → 腕选择右臂三个目标并勾选，即按其当前位置创建右侧系统；此选项不对左臂做空间镜像。未勾选时保留原 L 命名。

Python / AI 工具参数为 `side='L'`（默认）或 `side='R'`。右侧主要控制器为 `shldrFK_R1`、`armFK_R1`、`handFK_R1`、`hand_R1`、`elb_R1`；相关 base、形状、集合及新烘焙曲线同步改为 R。中性名称（joint1、strech_ik_foot1 等）不加侧标，使用独立命名空间区分多套系统。

`sides.py` 在生成完成后只重命名本次命名空间内的节点，更新返回值中的节点映射和动画控制器列表；不改原目标、原动画曲线名称。根组 `armSide` 记录 L / R。左右侧均保留动画转移、Easy Rig 对齐及整次撤销重做。固定模板 `build()` 仍保留原名称；侧别参数用于 `build_from_selection()`。

右侧回归：`scripts/test_custom_arm_side_live.py` 的 `verify()` 和 `scripts/test_custom_arm_ui_mcp.py --right --animation`。
