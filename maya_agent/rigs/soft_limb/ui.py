"""One-click Maya UI for the three-target arm system."""
from . import VERSION

WINDOW = 'CustomArmRigWindow'
_instance = None


class ArmRigWindow:
    def __init__(self,extra_options=None):
        import maya.cmds as c
        from maya_agent.rigs import ui_common as layout
        self.c = c
        self.last_result = None
        self.targets = []
        tracking = c.selectPref(q=True, trackSelectionOrder=True)
        c.selectPref(trackSelectionOrder=True)
        layout.begin(c,WINDOW,'手臂系统',VERSION,'按肩 → 肘 → 腕的顺序，逐个选择 3 根骨骼或物体。')
        self.selection_frame,self.targets_list=layout.selection(c,self.refresh,self.reverse)
        self.namespace=layout.namespace(c,'customArm')
        self.right_side = c.checkBox(label='R 右侧手臂（未勾选为 L 左侧）',value=False,
            annotation='按当前所选肩、肘、腕的位置创建，控制器使用 R 命名。')
        self.drive_targets = c.checkBox(label='驱动所选骨骼 / 物体', value=True,changeCommand=self.toggle_animation)
        self.copy_animation = c.checkBox(label='拷贝动画至控制器',value=False,changeCommand=self.toggle_animation)
        self.animation_fields,self.frame_bounds,self.sample_step=layout.animation_fields(c)
        if extra_options:extra_options()
        self.create_button=layout.create_button(c,'按当前选择一键创建手臂系统',self.create)
        self.status=layout.status(c,'就绪。' if tracking else '已开启选择顺序追踪，请按肩、肘、腕重新逐个选择。')
        self.refresh()
        c.showWindow(WINDOW)

    def toggle_animation(self, *_):
        enabled=self.c.checkBox(self.drive_targets,q=True,value=True)
        self.c.checkBox(self.copy_animation,edit=True,enable=enabled)
        if not enabled:self.c.checkBox(self.copy_animation,edit=True,value=False)
        self.c.columnLayout(self.animation_fields,edit=True,
            enable=enabled and self.c.checkBox(self.copy_animation,q=True,value=True))

    def refresh(self, *_):
        from .selection import ordered_selection
        self.targets = ordered_selection()
        self.c.textScrollList(self.targets_list, edit=True, removeAll=True)
        for i,n in enumerate(self.targets):
            role = ('肩','肘','腕')[i] if i<3 else '多余目标'
            self.c.textScrollList(self.targets_list, edit=True, append='{}  {}  {}'.format(i+1,role,n))

    def reverse(self, *_):
        self.refresh()
        targets = list(reversed(self.targets))
        self.c.select(clear=True)
        for target in targets: self.c.select(target, add=True)
        self.refresh()

    def create(self, *_):
        from . import build_from_selection
        c = self.c
        self.refresh()
        try:
            self.last_result = build_from_selection(targets=list(self.targets),
                namespace=c.textFieldGrp(self.namespace,q=True,text=True).strip(),
                drive_targets=c.checkBox(self.drive_targets,q=True,value=True),
                copy_animation=c.checkBox(self.copy_animation,q=True,value=True),
                start_frame=c.floatFieldGrp(self.frame_bounds,q=True,value1=True),
                end_frame=c.floatFieldGrp(self.frame_bounds,q=True,value2=True),
                sample_step=c.floatFieldGrp(self.sample_step,q=True,value1=True),
                side='R' if c.checkBox(self.right_side,q=True,value=True) else 'L')
            rig = self.last_result
            message = '已创建 {} {}手臂：{}\n上臂 {:.3f} cm / 前臂 {:.3f} cm。'.format(
                rig['side'],'右侧' if rig['side']=='R' else '左侧',rig['namespace'],*rig['lengths'])
            if rig['warnings']: message += '\n'+'\n'.join(rig['warnings'])
            if rig.get('animation_transfer'):
                report=rig['animation_transfer']
                message+='\n动画已转移：{} 个采样帧；原曲线已备份。'.format(report['sample_count'])
            c.scrollField(self.status,edit=True,text=message)
            c.select(rig['controls']['end_locator'], replace=True)
            return rig
        except Exception as exc:
            c.scrollField(self.status,edit=True,text=str(exc))
            c.warning(str(exc))
            return None


def show():
    global _instance
    _instance = ArmRigWindow()
    return _instance
