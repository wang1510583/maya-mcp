"""Arm-style four-target leg UI, with an additional pivot adjustment section."""
from . import VERSION

WINDOW='CustomLegRigWindow'
_instance=None


class LegRigWindow:
    def __init__(self,extra_options=None):
        import maya.cmds as c
        from maya_agent.rigs import ui_common as layout
        self.c=c
        self.last_result=None
        self.targets=[]
        tracking=c.selectPref(q=True,trackSelectionOrder=True)
        c.selectPref(trackSelectionOrder=True)
        for name in (WINDOW,'CustomSoftLegRigWindow'):
            if c.window(name,exists=True):c.deleteUI(name)
        layout.begin(c,WINDOW,'腿部系统',VERSION,'按髋 → 膝 → 踝 → 脚趾的顺序，逐个选择 4 根骨骼或物体。')
        self.selection_frame,self.targets_list=layout.selection(c,self.refresh,self.reverse)
        self.namespace=layout.namespace(c,'customLeg')
        self.right_side=c.checkBox(label='R 右侧腿部（未勾选为 L 左侧）',value=False,
            annotation='按当前所选髋、膝、踝、脚趾的位置创建，控制器使用 R 命名。')
        self.drive_targets=c.checkBox(label='驱动所选骨骼 / 物体',value=True,changeCommand=self.toggle_animation)
        self.copy_animation=c.checkBox(label='拷贝动画至控制器',value=False,changeCommand=self.toggle_animation)
        self.animation_fields,self.frame_bounds,self.sample_step=layout.animation_fields(c)
        if extra_options:extra_options()
        self.create_button=layout.create_button(c,'按当前选择一键创建腿部系统',self.create)
        c.separator(height=10,style='in')
        self.rigs=c.optionMenu(label='调整已有系统',changeCommand=self.refresh_mode)
        c.rowLayout(numberOfColumns=2,adjustableColumn=2)
        c.button(label='载入选中的腿部系统',command=lambda *_:self.run(self.load_selected))
        c.button(label='刷新系统 / 撤销后同步',command=lambda *_:self.refresh_rigs())
        c.setParent('..')
        self.mode=c.checkBox(label='进入调整模式（关闭时应用并锁定）',value=False,
                             changeCommand=lambda value:self.run(lambda:self.toggle_mode(value)))
        c.text(label='调整时移动黄色支点标记，关闭后应用并锁定。\n支持已有或已拷贝动画：保留原运动，后续旋转使用新支点。',align='left',wordWrap=True,height=38)
        c.rowLayout(numberOfColumns=3)
        self.guides=[c.button(label=label,enable=False,command=lambda *_,k=key:self.run(lambda:self.pick(k)))
                     for key,label in [('heel','heel 脚跟'),('toe_end','toe_end 脚尖'),('toe','toe 脚趾')]]
        c.setParent('..')
        self.cancel=c.button(label='取消本轮调整并退出',enable=False,command=lambda *_:self.run(self.cancel_mode))
        self.status=layout.status(c,'就绪。' if tracking else '已开启选择顺序追踪，请按髋、膝、踝、脚趾重新逐个选择。')
        self.refresh()
        self.refresh_rigs()
        c.showWindow(WINDOW)

    def toggle_animation(self,*_):
        c=self.c
        enabled=c.checkBox(self.drive_targets,q=True,value=True)
        c.checkBox(self.copy_animation,e=True,enable=enabled)
        if not enabled:c.checkBox(self.copy_animation,e=True,value=False)
        c.columnLayout(self.animation_fields,e=True,enable=enabled and c.checkBox(self.copy_animation,q=True,value=True))

    def refresh(self,*_):
        self.targets=self.c.ls(orderedSelection=True,long=True) or []
        self.c.textScrollList(self.targets_list,e=True,removeAll=True)
        for i,n in enumerate(self.targets):
            role=('髋','膝','踝','脚趾')[i] if i<4 else '多余目标'
            self.c.textScrollList(self.targets_list,e=True,append='{}  {}  {}'.format(i+1,role,n))

    def reverse(self,*_):
        self.refresh()
        targets=list(reversed(self.targets))
        self.c.select(clear=True)
        for target in targets:self.c.select(target,add=True)
        self.refresh()

    def create(self,*_):
        from . import build_from_selection
        c=self.c
        self.refresh()
        try:
            self.last_result=build_from_selection(targets=list(self.targets),
                namespace=c.textFieldGrp(self.namespace,q=True,text=True).strip(),
                drive_targets=c.checkBox(self.drive_targets,q=True,value=True),
                copy_animation=c.checkBox(self.copy_animation,q=True,value=True),
                start_frame=c.floatFieldGrp(self.frame_bounds,q=True,value1=True),
                end_frame=c.floatFieldGrp(self.frame_bounds,q=True,value2=True),
                sample_step=c.floatFieldGrp(self.sample_step,q=True,value1=True),
                side='R' if c.checkBox(self.right_side,q=True,value=True) else 'L')
            rig=self.last_result
            message='已创建 {} {}腿部：{}\n大腿 {:.3f} cm / 小腿 {:.3f} cm / 脚部 {:.3f} cm。'.format(
                rig['side'],'右侧' if rig['side']=='R' else '左侧',rig['namespace'],*rig['lengths'])
            if rig['warnings']:message+='\n'+'\n'.join(rig['warnings'])
            if rig.get('animation_transfer'):message+='\n动画已转移：{} 个采样帧；原曲线已备份。'.format(rig['animation_transfer']['sample_count'])
            c.scrollField(self.status,e=True,text=message)
            self.refresh_rigs(rig['namespace'])
            c.select(rig['controls']['foot'],r=True)
            return rig
        except Exception as exc:
            c.scrollField(self.status,e=True,text=str(exc));c.warning(str(exc))
            return None

    def root(self):
        c=self.c
        if not c.optionMenu(self.rigs,exists=True):raise ValueError('腿部设置窗口已关闭，请重新右键打开。')
        index=c.optionMenu(self.rigs,q=True,select=True)-1
        names=getattr(self,'_rig_names',[])
        if not 0<=index<len(names):raise ValueError('请先创建一套腿部系统。')
        return names[index]+':rig_root'

    def refresh_mode(self,*_):
        c=self.c
        if getattr(self,'_refreshing_rigs',False) or not c.optionMenu(self.rigs,exists=True):return
        try:active=bool(c.getAttr(self.root()+'.adjustmentMode'))
        except Exception:active=False
        c.checkBox(self.mode,e=True,value=active)
        for button in self.guides:c.button(button,e=True,enable=active)
        c.button(self.cancel,e=True,enable=active)

    def refresh_rigs(self,preferred=None):
        c=self.c
        # Replaced L/R windows may still have queued callbacks. Never query an
        # old control or the text value of a menu whose items are being rebuilt.
        if getattr(self,'_refreshing_rigs',False) or not c.optionMenu(self.rigs,exists=True):return
        index=c.optionMenu(self.rigs,q=True,select=True)-1
        previous=getattr(self,'_rig_names',[])
        old=previous[index] if 0<=index<len(previous) else None
        roots=[n for n in c.ls('*.customLegVersion',objectsOnly=True,recursive=True) or [] if c.objExists(n+'.legSetupData')]
        names=sorted(set(n.rsplit('|',1)[-1].rsplit(':',1)[0] for n in roots))
        self._refreshing_rigs=True
        try:
            for item in c.optionMenu(self.rigs,q=True,itemListLong=True) or []:c.deleteUI(item)
            self._rig_names=names
            for name in names or ['（没有腿部系统）']:c.menuItem(label=name,parent=self.rigs)
            selected=preferred if preferred in names else old if old in names else None
            c.optionMenu(self.rigs,e=True,select=names.index(selected)+1 if selected else 1)
        finally:self._refreshing_rigs=False
        self.refresh_mode()

    def run(self,function):
        if not self.c.optionMenu(self.rigs,exists=True):return
        try:return function()
        except Exception as exc:
            self.c.warning(str(exc));self.c.scrollField(self.status,e=True,text=str(exc))
        finally:self.refresh_mode()

    def load_selected(self):
        from .adjustment import resolve
        selected=self.c.ls(sl=True,long=True) or []
        if not selected:raise ValueError('请选择本插件创建的腿部控制器或根组。')
        root,_=resolve(selected[0])
        self.refresh_rigs(root.rsplit('|',1)[-1].rsplit(':',1)[0])

    def toggle_mode(self,value):
        from . import set_adjustment_mode
        answer=set_adjustment_mode(self.root(),bool(value))
        self.c.scrollField(self.status,e=True,text='调整中：选择黄色标记，用 W 移动；关闭勾选后应用。' if value else '支点已应用并锁定，原动画已保留；后续旋转使用新支点。')
        return answer

    def cancel_mode(self):
        from . import set_adjustment_mode
        answer=set_adjustment_mode(self.root(),False,cancel=True)
        self.c.scrollField(self.status,e=True,text='已取消本轮支点调整。')
        return answer

    def pick(self,key):
        from .adjustment import resolve
        root,data=resolve(self.root())
        if not self.c.getAttr(root+'.adjustmentMode'):raise ValueError('请先进入调整模式。')
        self.c.select(data['guides'][key],r=True)
        self.c.setToolTo('moveSuperContext')


def show():
    global _instance
    _instance=LegRigWindow()
    return _instance
