"""MCP entries for the independent leg rig and explicit pivot setup mode."""
from maya_agent.tools.registry import tool,ToolResult,obj_schema


@tool(name='create_custom_leg_rig',display_name='自定义腿部系统',category='rigging',
      description='仅按髋、膝、踝、脚趾四个选择目标创建腿系统。支持 L/R 命名及显式动画转移，保留原姿态与蒙皮。',
      parameters=obj_schema({
          'targets':{'type':'array','items':{'type':'string'},'minItems':4,'maxItems':4},
          'namespace':{'type':'string','default':'customLeg'},
          'drive_targets':{'type':'boolean','default':True},
          'side':{'type':'string','enum':['L','R'],'default':'L'},
          'copy_animation':{'type':'boolean','default':False},
          'start_frame':{'type':'number'},'end_frame':{'type':'number'},
          'sample_step':{'type':'number','exclusiveMinimum':0,'default':1.0},
      }))
def create_custom_leg_rig(targets=None,namespace='customLeg',drive_targets=True,side='L',copy_animation=False,
                          start_frame=None,end_frame=None,sample_step=1.0):
    from maya_agent.rigs.soft_leg import build_from_selection
    rig=build_from_selection(targets,namespace,drive_targets,copy_animation,start_frame,end_frame,sample_step,side)
    return ToolResult(ok=True,data=rig,message='已创建腿部系统：'+rig['namespace'])


@tool(name='set_leg_adjustment_mode',display_name='腿部支点调整模式',category='rigging',
      description='进入后移动返回的 guides，退出时应用 heel/toe_end/toe 轴心并锁定。支持已有普通关键帧及已拷贝动画，自动补偿保留原运动，后续旋转使用新支点。cancel=True 放弃本轮调整。只作用于本插件创建的系统。',
      parameters=obj_schema({'rig':{'type':'string','description':'腿系统根组或其控制器'},
          'enabled':{'type':'boolean'},'cancel':{'type':'boolean','default':False}},required=['rig','enabled']))
def set_leg_adjustment_mode(rig,enabled,cancel=False):
    from maya_agent.rigs.soft_leg import set_adjustment_mode
    data=set_adjustment_mode(rig,enabled,cancel)
    return ToolResult(ok=True,data=data,message='已进入调整模式' if enabled else '已退出调整模式')
