"""Single-target shoulder details using the same native controls as the limb UIs."""
import maya.cmds as c
from maya_agent.rigs import ui_common as layout
from . import VERSION
WINDOW='IntegratedShoulderSettings'


class ShoulderWindow:
    def __init__(self):
        self.targets=[]
        layout.begin(c,WINDOW,'肩膀 / 锁骨',VERSION,'选择 1 根锁骨或物体；手臂部位仍载入肩、肘、腕 3 个目标。')
        self.selection_frame,self.targets_list=layout.selection(c,self.refresh,self.reverse)
        self.namespace=layout.namespace(c,'shoulder')
        self.control_size=c.floatFieldGrp(label='控制器大小',numberOfFields=1,value1=1.0)
        self.drive_targets=c.checkBox(label='驱动所选骨骼 / 物体',value=True,changeCommand=self.toggle_animation)
        self.copy_animation=c.checkBox(label='拷贝动画至控制器',value=False,changeCommand=self.toggle_animation)
        self.animation_fields,self.frame_bounds,self.sample_step=layout.animation_fields(c)
        self.create_button=layout.create_button(c,'保存部位设置',lambda *_:None)
        self.status=layout.status(c,'左右侧由集成面板自动指定。')
        self.refresh();self.toggle_animation();c.showWindow(WINDOW)
    def refresh(self,*_):
        self.targets=c.ls(orderedSelection=True,long=True) or []
        c.textScrollList(self.targets_list,e=True,removeAll=True)
        for i,n in enumerate(self.targets):c.textScrollList(self.targets_list,e=True,append='{}  {}'.format(i+1,n))
    def reverse(self,*_):self.refresh()
    def toggle_animation(self,*_):
        enabled=c.checkBox(self.drive_targets,q=True,value=True)
        c.checkBox(self.copy_animation,e=True,enable=enabled)
        if not enabled:c.checkBox(self.copy_animation,e=True,value=False)
        c.columnLayout(self.animation_fields,e=True,enable=enabled and c.checkBox(self.copy_animation,q=True,value=True))
