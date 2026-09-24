"""AI-callable entry point for the user-approved modular body rig."""
from maya_agent.tools.registry import ToolResult, obj_schema, tool


@tool(
    name="create_custom_body_rig",
    display_name="自定义身体绑定",
    description=(
        "创建「自定义身体绑定」：可调节 2–64 根骨骼及同数量控制器，默认四节保留原版行为。"
        "支持总高度，自动生成矩阵位置传递和旋转权重。用户说‘创建自定义身体绑定’时调用本工具。"
        "当前版本 1.2.0；可用 use_selection 按当前选择顺序，或 targets 显式列表，从腰至胸匹配物体并约束驱动。"
        "选择模式自动使用目标数量和位置/朝向；拒绝覆盖已有动画、驱动或锁定通道。不自动蒙皮。"
        "要求厘米场景。重复创建自动使用独立命名空间，保留已有绑定和动画。"
    ),
    parameters=obj_schema({
        "use_selection": {"type": "boolean", "default": False, "description": "按当前选择顺序创建并驱动；需要预先开启 Maya 选择顺序追踪"},
        "targets": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 64,
                    "description": "明确的物体完整路径列表，腰部到胸部；提供此参数即启用选择模式"},
        "segment_count": {"type": "integer", "minimum": 2, "maximum": 64, "default": 4,
                          "description": "骨骼和控制器总数量，包含髋部和胸部，两者数量相同"},
        "height": {"type": "number", "exclusiveMinimum": 0, "default": 6.0,
                   "description": "初始总高度（厘米），数量变化时总高度保持此值"},
        "namespace": {"type": "string", "default": "customBody", "description": "独立命名空间前缀，字母/数字/下划线"},
        "on_conflict": {"type": "string", "enum": ["increment", "error"], "default": "increment",
                        "description": "重名时自动编号，或报错停止"},
    }),
    category="rigging",
)
def create_custom_body_rig(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0,
                           use_selection=False, targets=None):
    from maya_agent.rigs.custom_body import build
    result = build(namespace=namespace, on_conflict=on_conflict, segment_count=segment_count, height=height,
                   use_selection=use_selection, targets=targets)
    return ToolResult(ok=True, data=result,
                      message="已创建自定义身体绑定 v{}：{}".format(result["version"], result["namespace"]))
