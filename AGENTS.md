# Project custom Maya tools

- 用户说「创建自定义身体绑定」「新增自定义身体绑定」时，调用 MCP `create_custom_body_rig`。
  如果当前客户端尚未刷新直接工具，使用 `call_maya_tool(name="create_custom_body_rig", arguments={})`。
- 对应独立 Python 模块：`maya_agent.rigs.custom_body`，公开入口 `build()`，中文名称「自定义身体绑定」。
- 这是用户已确认的自定义脊柱绑定；默认四节，支持 `segment_count`（2–64，骨骼/控制器同数量）和 `height`（总高度，默认 6 厘米）。v1.2.0 新增 `show_ui()`，及 `use_selection=True` / `targets=[有序完整路径]` 匹配并驱动目标。不要替换为默认 biped、auto_rig_character 或 AdvancedSkeleton。
- 选择模式从腰部到胸部；数量由目标列表决定。先核对选择顺序；默认不覆盖已有动画。v1.3.0 新增 `copy_animation`（默认 False）及 `start_frame`、`end_frame`、`sample_step`：用户明确要求时，将普通 TR 动画转移到控制器，原曲线断开并备份。拒绝动画层、已有约束/驱动或锁定通道。打开 UI 会开启选择顺序追踪。
- 先查询当前 Maya 场景；保留现有动画、蒙皮及绑定。重复创建使用独立命名空间，不删除旧绑定。
- 新增功能先读 `maya_agent/rigs/custom_body/README.md`。修改相应组件和版本化模板，并验证已有行为。
- 模块数据在包内，不能重新依赖 `outputs/scene-study` 或临时脚本。不要覆盖已有 Maya 文件。

## 三点手臂系统

- 用户要根据 3 根骨骼/物体创建手臂系统时，使用 `create_custom_arm_rig`，或 MCP `call_maya_tool(name="create_custom_arm_rig", arguments={...})`。顺序为肩、肘、腕；不要改用自定义身体绑定。
- 独立模块为 `maya_agent.rigs.soft_limb`；`build_from_selection()` 匹配并驱动目标，`show_ui()` 打开窗口；`build()` 仅复刻固定模板。
- 先读模块 README。保留现有动画、父子关系和蒙皮；默认拒绝有动画/驱动的目标。UI 开启选择顺序追踪，可预览和反转选择顺序。
- 保留 Easy Rig 的 `recalculate_node` 和 14 条对应连接；新功能验证 Easy Rig 对齐及撤销重做。失败清理必须先删本次约束，避免删除内部驱动时连带删除目标。
- 手臂 v1.2.0 支持 `copy_animation`、`start_frame`、`end_frame`、`sample_step`；必须明确启用动画转移才断开 TR 原曲线并备份。缩放动画保留原目标；FK 控制器的 animationOffset 通道保留独立目标旋转。仅保证采样帧姿态，失败先释放备份 message 再清理并接回原曲线。
- 手臂 v1.3.0 增加 `side='L'/'R'`，默认 L。UI 勾选 R 后按所选右臂目标位置创建并使用 R 命名，不自动空间镜像；通过返回的 controls / target_mapping 操作，不硬编码 `_L1`。
- 手臂 v1.3.1 修复重复对齐漂移：`recalculate_node.translate_orient_pivot3` 必须读取当前 `elb_L/R1.visibility`，先快照当前肘部世界方向再重排 FK；不能重新接回扭转辅助图的 `locator3`。旧系统用 `soft_limb.easy_rig.repair_recalculate_node(namespace)` 修复，保留原曲线和姿态。回归需连续多次对齐，不能只测单次。

## 四点腿部系统及统一窗口

- 腿部系统使用 `maya_agent.rigs.soft_leg.build_from_selection()` 或 MCP `create_custom_leg_rig`；先读该模块 README。只能按髋、膝、踝、脚趾四个有序目标创建；不在 UI/MCP 提供固定模板创建。
- 支持 `side='L'/'R'` 和显式 `copy_animation`、起止帧、采样间隔。保留蒙皮、父级和缩放曲线，转移 TR 原曲线备份。不得用补偿输出掩盖错误的 IK 解算；同时核对求解骨骼位置和目标世界矩阵。
- `set_adjustment_mode(rig, enabled, cancel=False)` 操作本模块创建的系统。进入后编辑 heel/toe_end/toe 的黄色 guide，退出时保姿态更新轴心并锁定。v1.1.0 支持已有普通关键帧/已拷贝动画，使用独立曲线快照和原生节点连续补偿，保留原动画且后续旋转使用新支点；兼容 v1.0.0 场景，不得直接改参考系统。
- 腿部保留 `recalculate_node` 的 13 条登记连接及 `straight_leg_tool`、`barn_easy_IK_system`。验证静态/动画、左右侧、模式撤销重做和 Easy Rig 发现/对齐。
- 身体、手臂、腿部 UI 共用 `maya_agent.rigs.ui_common`；保持布局、尺寸、选择列表、动画设置和按钮样式一致，专有选项留在各模块。身体保留标准数量/高度模式及列表编辑功能。

## 集成角色绑定

- 模块 `maya_agent.rigs.integrated`，`show_ui()` 打开图形面板；安装器 `install_integrated_rig.py`。修改前读模块 README。
- `build(parts, namespace='customCharacter', general_root=None)` 仅创建已载入的部位。部位键为 body、head、shoulder_L/R、arm_L/R、leg_L/R；左右由键确定。肩膀每侧只选 1 根锁骨，不能重复使用手臂三目标中的上臂。
- 集成 v1.4.0 按用户新参考场景恢复精确的部位起点关联，不能恢复旧版整组挂身体：肩膀控制器零组挂胸部，肩膀定位器只点约束手臂起点，腰部只带动腿部髋起点；脚部 IK 总组独立。`hierarchy.py` 管理这些连接，`attachments.point_link` 用独立原运动参考保留动画。连线开关仍移除；旧 `connected` 参数不用于整组关联。
- 头颈改用独立 `maya_agent.rigs.head_neck` 模块，2–64 个有序目标，末端是头、前面是颈骨。先读模块 README。颈部位置沿链跟随，方向在胸部和头部之间混合，单颈权重各半；头部旋转独立、位置跟随颈部。头平移必须直接点约束到控制器通道，不能把跟随平移放到其父矩阵，否则颈部方向读取头部父矩阵会产生循环。动画平移残差保存为头部 `positionOffset` 通道。头多空间只切换旋转，保留点跟随位置。
- 头颈 v1.1.0 / 集成 v1.4.1：旋转位置跟随必须使用父级下的 `neckXX_anchor` / `head_anchor`，pointConstraint offset=0；不能用 pointConstraint maintainOffset 代替骨骼端点旋转位移。控制器统一角色朝向，用 `chest_orientation` 归一胸部，用 `output_frame*` 保存骨骼绑定轴向差异。回归必须改变胸、颈、头的 XYZ 旋转并与参考输出逐项比较，不能仅验证初始姿态和拷贝动画。
- 左键载入、右键设置、中键清空。可选通用根仍保留：载入后所有部位平级跟随通用根，使用动画参考补偿避免双重运动。原骨架父级、蒙皮和动画保护不变。修改旧场景需保留世界姿态及动画，不能仅相对重设父级导致跳变。
- 多空间创建开关为 space_head、space_chest、space_upper_arm、space_wrist、space_foot。集成 v1.4.2 按用户要求 UI 全部默认勾选，且不打开详细设置直接创建也必须生效；允许单独取消。Python API 仍需显式启用。控制器长名及显示名均为 `global`，不附中文注释。global=0 保留本地动画，global=1 跟随另一空间；使用明确的双目标权重和 reverse，禁止按 listAttr 最后一项猜权重。
- 必须先捕获所有部位原始运动，再通过代理构建并统一驱动原目标，避免同一骨架的父子部位互相污染。动画转移只在 copy_animation=True 时进行。清理先释放原曲线备份 message、删所有新约束，再删除本次命名空间。不得删除用户场景或原绑定。
- 集成 v1.4.3 新增默认勾选的 `space_knee`：Knee 控制器 global 的另一个空间必须是同一 rig 的 controls['foot']，不是腰部；与 space_foot 独立开关。global=0 保留原动画空间，=1 跟随同侧脚腕平移与旋转。验证 L/R、已有动画、脚腕旋转和对侧不受影响。
- 集成 v1.5.0 自动调用 `integrated.display.apply`，按参考脚本隐藏已知伸缩、内部膝盖、手腕末端、连接定位器和扭转辅助形状到本套 `NoDisplay` 层，关闭 base 骨骼局部轴。层以绑定根 UUID 标记归属，重复调用复用；不能删除用户已有同名层、隐藏主要控制器或修改 visibility 驱动连接。不要将 knee_ctrl 与可动画的 Knee 控制器混淆，不附带修改 FK 曲线形状。
- 用户已要求集成面板所有部位默认开启「拷贝动画至控制器」，各部位仍可单独取消。仅修改集成 UI 默认值；Python 构建 API 和原独立工具的默认值保持不变。
- 集成 v1.2.1 在开启动画拷贝时允许所选目标的父级已有 TR / offsetParentMatrix 驱动（例如先建身体再建腿）。通过共享检查的 `allow_parent_drivers=True` 开启，只采样父级影响，不断开父级连接；所选目标本身的已有约束保护保持有效。验证实际世界运动和父级原连接、曲线均保留。

- 身体 v1.3.2 不再创建模板的 layer1/2/3；由 topology 将层颜色和显示属性转为 DAG 直接覆盖，保持控制器外观。集成只保留有实际隐藏用途的 NoDisplay。
