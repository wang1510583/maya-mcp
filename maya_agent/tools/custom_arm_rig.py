"""AI entry point for the fitted FK / soft stretch arm system."""
from maya_agent.tools.registry import ToolResult, obj_schema, tool


@tool(
    name='create_custom_arm_rig', display_name='自定义手臂系统', category='rigging',
    description=('按肩、肘、腕的顺序选择恰好三个骨骼或物体，创建匹配位置和长度的手臂系统。'
                 '保留原 FK、柔化伸缩、肘旋转和 Easy Rig 对齐登记；默认父约束驱动所选目标。'
                 '使用当前有序选择或显式 targets；不覆盖已有动画、驱动、蒙皮；不重新蒙皮。'
                 'copy_animation=True 可将普通 TR 动画烘焙至控制器并备份原曲线；正值等比缩放动画保留。'
                 'side 默认 L；R 使用右侧命名，按所选目标位置创建，不自动镜像。'
                 '要求厘米/度，拒绝重合点、引用、锁定通道、非均匀/负缩放及剪切。'),
    parameters=obj_schema({
        'targets': {'type':'array','items':{'type':'string'},'minItems':3,'maxItems':3,
                    'description':'完整路径，依次为肩、肘、腕；省略时读取当前有序选择'},
        'namespace': {'type':'string','default':'customArm','description':'命名空间，重名自动编号'},
        'side': {'type':'string','enum':['L','R'],'default':'L','description':'左侧 L 或右侧 R；保持所选目标位置'},
        'drive_targets': {'type':'boolean','default':True,'description':'创建保持原姿态的父约束驱动目标'},
        'copy_animation': {'type':'boolean','default':False,'description':'转移普通 TR 动画至控制器，原曲线备份'},
        'start_frame': {'type':'number','description':'默认播放范围起始帧'},
        'end_frame': {'type':'number','description':'默认播放范围结束帧'},
        'sample_step': {'type':'number','exclusiveMinimum':0,'default':1.0,'description':'采样间隔，只保证采样帧姿态'},
    }))
def create_custom_arm_rig(targets=None, namespace='customArm', drive_targets=True,copy_animation=False,
                          start_frame=None,end_frame=None,sample_step=1.0,side='L'):
    from maya_agent.rigs.soft_limb import build_from_selection
    rig = build_from_selection(targets=targets, namespace=namespace, drive_targets=drive_targets,
        copy_animation=copy_animation,start_frame=start_frame,end_frame=end_frame,sample_step=sample_step,side=side)
    return ToolResult(ok=True, data=rig, message='已创建手臂系统：'+rig['namespace'])
