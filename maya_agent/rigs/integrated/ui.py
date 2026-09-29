"""Independent part panel: left-load, right-settings, middle-clear."""
from PySide2 import QtCore,QtWidgets
import maya.cmds as c
from . import PARTS,VERSION

_instance=globals().get('_instance')
_root_state=globals().get('_root_state',dict(uuid=None,name=None))
_follow_state=globals().get('_follow_state',{key:dict(uuid=None,name=None) for key in ('chest','hips')})
_global_options=globals().get('_global_options',dict(copy_animation=True,live_alignment=True))
FOLLOW_LABELS={'chest':'胸部跟随对象','hips':'腰部跟随对象'}
_state=globals().get('_state',{key:dict(targets=[],uuids=[],connected=False,name=key,drive_targets=True,
                 copy_animation=True,sample_step=1.0) for key in PARTS})
for _key in PARTS:
    _state.setdefault(_key,dict(targets=[],uuids=[],connected=False,name=_key,drive_targets=True,copy_animation=True,sample_step=1.0))

# Discard saved pre-1.3 line switches when reloading the panel.
for _row in _state.values():_row['connected']=False

SPACE_OPTIONS={'head':[('space_head','头部多空间 → 胸部')],
               'body':[('space_chest','胸部多空间 → 腰部')],
               'arm':[('space_upper_arm','大臂多空间 → 胸部'),('space_wrist','手腕 FK 多空间 → 通用根 / 世界')],
               'leg':[('space_foot','脚部 IK 多空间 → 腰部'),('space_knee','膝盖多空间 → 同侧脚腕')]}

# Populate creation options even when the user never opens the details panel.
# Keep later explicit unchecks when the module is reloaded.
for _key,_row in _state.items():
    _row['copy_animation']=_global_options['copy_animation']
    if PARTS[_key]['kind'] in ('arm','leg'):_row['live_alignment']=_global_options['live_alignment']
    for _option,_label in SPACE_OPTIONS.get(_key,SPACE_OPTIONS.get(PARTS[_key]['kind'],[])):
        _row.setdefault(_option,True)


def targets(key):
    row=_state[key];result=[]
    for identity in row['uuids']:
        found=c.ls(identity,long=True) or []
        if len(found)!=1:raise ValueError(PARTS[key]['label']+'中有目标已删除，请重新载入。')
        result.append(found[0])
    return result


def validate_count(key,names):
    count=PARTS[key]['count']
    if (count and len(names)!=count) or (not count and not 2<=len(names)<=64):
        raise ValueError('{}请依次选择 {} 个骨骼或物体。'.format(PARTS[key]['label'],count or '2–64'))
    if any('.' in n or c.nodeType(n) not in ('joint','transform') for n in names):
        raise ValueError('请选骨骼或物体，不要选择组件。')


class PartButton(QtWidgets.QPushButton):
    settings=QtCore.Signal(str)
    unloaded=QtCore.Signal(str)
    def __init__(self,key,parent):
        super().__init__(parent);self.key=key
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip('左键：载入当前有序选择\n右键：打开本部位详细设置\n中键：清空本部位载入')
    def mousePressEvent(self,event):
        if event.button()==QtCore.Qt.RightButton:
            self.settings.emit(self.key);event.accept();return
        if event.button()==QtCore.Qt.MiddleButton:
            self.unloaded.emit(self.key);event.accept();return
        super().mousePressEvent(event)


class Diagram(QtWidgets.QWidget):
    positions={'shoulder_R':(0,0),'head':(0,1),'shoulder_L':(0,2),
               'arm_R':(1,0),'body':(1,1),'arm_L':(1,2),'leg_R':(2,0),'leg_L':(2,2)}
    def __init__(self,window):
        super().__init__();self.window=window;self.buttons={};self.lines={}
        self.setMinimumSize(330,240)
        grid=QtWidgets.QGridLayout(self);grid.setContentsMargins(0,0,0,0);grid.setSpacing(5)
        for index in range(3):grid.setColumnStretch(index,1);grid.setRowStretch(index,1)
        for key in PARTS:
            button=PartButton(key,self);self.buttons[key]=button
            button.setMinimumSize(0,76);button.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Expanding)
            grid.addWidget(button,*self.positions[key])
            button.clicked.connect(lambda checked=False,k=key:window.safe(lambda:window.load(k)))
            button.settings.connect(lambda k:window.safe(lambda:window.details(k)))
            button.unloaded.connect(lambda k:window.safe(lambda:window.unload(k)))
        self.create_button=QtWidgets.QPushButton('开始创建',self)
        self.create_button.setMinimumSize(0,60)
        self.create_button.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Expanding)
        self.create_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.create_button.setStyleSheet('QPushButton {background:#397b80;color:white;font-size:20px;font-weight:bold;border:0;} QPushButton:hover {background:#478e94;} QPushButton:disabled {background:#656565;color:#999;}')
        self.create_button.clicked.connect(lambda:window.safe(window.create))
        grid.addWidget(self.create_button,2,1)
        self.refresh()
    def refresh(self):
        for key,button in self.buttons.items():
            n=len(_state[key]['uuids']);color='#8de1c3' if n else '#f0f0f0'
            button.setText(PARTS[key]['label']+'\n'+('● 已载入 '+str(n) if n else '○ 未载入'))
            button.setStyleSheet('QPushButton { color:'+color+'; background:#545454; border:0; font-size:18px; font-weight:600; } QPushButton:hover { background:#686868; }')
        self.update()


class IntegratedWindow(QtWidgets.QDialog):
    def __init__(self):
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
        super().__init__(wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()),QtWidgets.QWidget))
        self.setObjectName('IntegratedCharacterRigWindow');self.setWindowTitle('集成角色绑定 v'+VERSION)
        self.setWindowFlags(self.windowFlags()|QtCore.Qt.Window)
        self.resize(420,520);self.last_result=None;self.details_windows={}
        c.selectPref(trackSelectionOrder=True)
        self.setStyleSheet('QDialog { background:#595959; color:#ededed; } QLabel {color:#ededed;} QLineEdit {background:#414141;color:white;padding:6px;border:1px solid #777;}')
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(12,12,12,12);layout.setSpacing(9)
        label=QtWidgets.QLabel('左键载入 · 右键设置 · 中键清空');layout.addWidget(label)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('名称前缀'))
        self.namespace=QtWidgets.QLineEdit('customCharacter');row.addWidget(self.namespace)
        clear=QtWidgets.QPushButton('清空载入');clear.clicked.connect(self.clear);row.addWidget(clear);layout.addLayout(row)
        root_row=QtWidgets.QHBoxLayout()
        self.root_button=PartButton('_root',self)
        self.root_button.setToolTip('左键载入人物总控制器：整体移动包含 IK 手脚。胸腰局部跟随请用下面两个按钮。\n中键：清空通用根载入。')
        self.root_button.clicked.connect(lambda:self.safe(self.load_root));root_row.addWidget(self.root_button,1)
        self.root_button.unloaded.connect(lambda _:self.clear_root())
        self.follow_buttons={}
        for key in ('chest','hips'):
            button=PartButton(key,self);self.follow_buttons[key]=button
            example='spine_03；用于肩膀、手臂及头颈' if key=='chest' else 'pelvis；只带动腿部髋起点'
            button.setToolTip('左键载入一个骨骼或物体，例如 '+example+'。\n有新建身体时自动使用身体控制器；中键清空载入。')
            button.clicked.connect(lambda checked=False,k=key:self.safe(lambda:self.load_follow(k)))
            button.unloaded.connect(self.clear_follow)
            root_row.addWidget(button,1)
        for button in [self.root_button]+list(self.follow_buttons.values()):
            button.setMinimumSize(0,68)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
            button.setStyleSheet('QPushButton {color:#f0a34a;background:transparent;border:0;font-size:13px;font-weight:600;} QPushButton:hover {background:#686868;}')
        layout.addLayout(root_row)
        self.diagram=Diagram(self);layout.addWidget(self.diagram,1)
        self.create_button=self.diagram.create_button
        self.add_global_options()
        panel_button=QtWidgets.QPushButton('创建 / 显示模式切换面板',self)
        panel_button.setToolTip('在已创建角色右侧生成场景滑块；选择圆圈后按 W，沿横轴拖动切换。')
        panel_button.clicked.connect(lambda:self.safe(self.create_switch_panel));layout.addWidget(panel_button)
        hint=QtWidgets.QLabel('通用根控制整体移动；胸 / 腰用于部位跟随。\n右键设置动画范围、多空间及腿部支点调整。')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#d0d0d0;font-size:12px;');layout.addWidget(hint)
        self.status=QtWidgets.QLabel('尚未载入部位。');self.status.setWordWrap(True);self.status.setMinimumHeight(40);layout.addWidget(self.status)
        self.refresh_root()
        self.refresh_follow()
    def message(self,text):self.status.setText(text)
    def safe(self,callback):
        try:return callback()
        except Exception as exc:self.message(str(exc));c.warning(str(exc))
    def add_global_options(self):
        options_row=QtWidgets.QHBoxLayout();self.global_checkboxes={}
        for option,label,tip in (
                ('copy_animation','拷贝动画至控制器','统一应用到所有已载入部位；动画范围和采样间隔在各部位右键设置。'),
                ('live_alignment','实时对齐','统一应用到已载入的左右手臂和腿部，拖动及播放时贴合骨骼。')):
            checkbox=QtWidgets.QCheckBox(label,self);checkbox.setChecked(_global_options[option])
            checkbox.setToolTip(tip)
            checkbox.toggled.connect(lambda value,k=option:self.set_global_option(k,value))
            self.global_checkboxes[option]=checkbox;options_row.addWidget(checkbox)
        options_row.addStretch()
        self.layout().insertLayout(self.layout().indexOf(self.diagram)+1,options_row)
    def set_global_option(self,option,value):
        _global_options[option]=bool(value)
        for key,row in _state.items():
            if option=='copy_animation' or PARTS[key]['kind'] in ('arm','leg'):row[option]=bool(value)
        # Details can remain open while the main panel switch changes.
        for window in self.details_windows.values():
            self.sync_global_details(window)
    def sync_global_details(self,window):
        if not c.checkBox(window.copy_animation,exists=True):return
        c.checkBox(window.copy_animation,e=True,value=_global_options['copy_animation'],visible=False,manage=False)
        if hasattr(window,'live_alignment') and c.checkBox(window.live_alignment,exists=True):
            c.checkBox(window.live_alignment,e=True,value=_global_options['live_alignment'],visible=False,manage=False)
        window.toggle_animation()
        if hasattr(window,'drive_targets'):
            c.checkBox(window.drive_targets,e=True,changeCommand=lambda *_:self.sync_global_details(window))
    def load(self,key):
        names=c.ls(orderedSelection=True,long=True) or [];validate_count(key,names)
        _state[key]['targets']=names;_state[key]['uuids']=[c.ls(n,uuid=True)[0] for n in names]
        _state[key]['load_revision']=_state[key].get('load_revision',0)+1
        self.diagram.refresh();self.message('已载入'+PARTS[key]['label']+'：'+str(len(names))+' 个目标。右键可检查顺序和动画设置。')
    def clear(self):
        for row in _state.values():row['targets']=[];row['uuids']=[];row['load_revision']=row.get('load_revision',0)+1
        self.clear_root()
        for key in _follow_state:self.clear_follow(key)
        self.diagram.refresh();self.message('已清空所有载入部位；场景不受影响。')
    def refresh_root(self):
        name=_root_state['name']
        self.anchor_text(self.root_button,'载入根',name)
    def anchor_text(self,button,label,name):
        status='已载入 '+name.rsplit('|',1)[-1] if name else '○ 未载入'
        status=button.fontMetrics().elidedText(status,QtCore.Qt.ElideMiddle,max(button.width()-12,84))
        button.setText(label+'\n'+status)
        help_text=button.toolTip().split('\n对象：',1)[0]
        button.setToolTip(help_text+('\n对象：'+name if name else ''))
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'follow_buttons'):
            self.refresh_root();self.refresh_follow()
    def load_root(self):
        names=c.ls(sl=True,long=True) or []
        if len(names)!=1 or c.nodeType(names[0]) not in ('joint','transform'):raise ValueError('请只选择一个通用根控制器。')
        _root_state.update(uuid=c.ls(names[0],uuid=True)[0],name=names[0]);self.refresh_root();self.diagram.refresh()
        self.message('通用根已载入；整体移动包含 IK 手脚。胸腰局部跟随请使用下面两个按钮。')
    def clear_root(self):
        _root_state.update(uuid=None,name=None);self.refresh_root();self.diagram.refresh()
        self.message('已清空通用根载入；场景物体保留。')
    def refresh_follow(self):
        for key,button in self.follow_buttons.items():
            name=_follow_state[key]['name']
            self.anchor_text(button,'载入胸' if key=='chest' else '载入腰',name)
    def load_follow(self,key):
        names=c.ls(sl=True,long=True) or []
        if len(names)!=1 or c.nodeType(names[0]) not in ('joint','transform'):
            raise ValueError('请只选择一个'+FOLLOW_LABELS[key]+'。')
        _follow_state[key].update(uuid=c.ls(names[0],uuid=True)[0],name=names[0]);self.refresh_follow()
        self.message('已载入'+FOLLOW_LABELS[key]+'；单独创建部位时使用，有身体时自动使用新建身体。')
    def clear_follow(self,key):
        _follow_state[key].update(uuid=None,name=None);self.refresh_follow()
        self.message('已清空'+FOLLOW_LABELS[key]+'；场景物体保留。')
    def follow_target(self,key):
        identity=_follow_state[key]['uuid']
        if not identity:return None
        found=c.ls(identity,long=True) or []
        if len(found)!=1:raise ValueError(FOLLOW_LABELS[key]+'已删除，请重新载入。')
        return found[0]
    def unload(self,key):
        _state[key]['targets']=[];_state[key]['uuids']=[];self.diagram.refresh()
        _state[key]['load_revision']=_state[key].get('load_revision',0)+1
        self.message('已清除'+PARTS[key]['label']+'的载入。')
    def details(self,key):
        kind=PARTS[key]['kind'];opt=_state[key]
        load_revision=opt.get('load_revision',0)
        fields={}
        space_options=SPACE_OPTIONS.get(key,SPACE_OPTIONS.get(kind,[]))
        def extra_options():
            if not space_options:return
            c.frameLayout(label='多空间约束（创建时启用）',collapsable=False)
            c.columnLayout(adjustableColumn=True,rowSpacing=5)
            c.text(label='global = 0 保持本地；global = 1 跟随指定空间。',align='left')
            for option,label in space_options:
                fields[option]=c.checkBox(label=label,value=opt.get(option,True))
            c.setParent('..');c.setParent('..')
        names=targets(key)
        c.select(names,r=True) if names else c.select(clear=True)
        if kind=='body':
            from maya_agent.rigs.custom_body.ui import BodyRigWindow,WINDOW
            w=BodyRigWindow(extra_options);c.checkBox(w.selection_mode,e=True,value=True);w.toggle_selection()
            c.checkBox(w.selection_mode,e=True,enable=False)
            w.targets=names;w.refresh_list()
        elif kind=='head':
            from maya_agent.rigs.head_neck.ui import HeadNeckWindow,WINDOW
            w=HeadNeckWindow(extra_options)
        elif kind=='arm':
            from maya_agent.rigs.soft_limb.ui import ArmRigWindow,WINDOW
            w=ArmRigWindow(extra_options)
        elif kind=='leg':
            from maya_agent.rigs.soft_leg.ui import LegRigWindow,WINDOW
            w=LegRigWindow(extra_options)
        else:
            from .shoulder_ui import ShoulderWindow,WINDOW
            w=ShoulderWindow()
        if kind!='body':
            if kind in ('arm','leg'):c.checkBox(w.right_side,e=True,value=PARTS[key]['side']=='R',visible=False,manage=False)
            c.checkBox(w.drive_targets,e=True,value=opt.get('drive_targets',True))
        if kind in ('shoulder','head'):c.floatFieldGrp(w.control_size,e=True,value1=opt.get('control_size',1.0))
        c.window(WINDOW,e=True,title=PARTS[key]['label']+' · 详细设置')
        c.textFieldGrp(w.namespace,e=True,label='部位名称',text=opt['name'])
        self.sync_global_details(w)
        c.floatFieldGrp(w.frame_bounds,e=True,value1=opt.get('start_frame',c.playbackOptions(q=True,minTime=True)),
                        value2=opt.get('end_frame',c.playbackOptions(q=True,maxTime=True)))
        c.floatFieldGrp(w.sample_step,e=True,value1=opt.get('sample_step',1));w.toggle_animation()
        if kind=='leg':
            rig=(self.last_result or {}).get('parts',{}).get(key)
            if rig and c.objExists(rig['root']):w.refresh_rigs(rig['namespace'])
        w.space_fields=fields
        def save(*_):
            if opt.get('load_revision',0)!=load_revision:
                raise ValueError('此部位的载入已改变，请重新右键打开设置。')
            if w.targets:validate_count(key,w.targets)
            opt['targets']=list(w.targets);opt['uuids']=[c.ls(n,uuid=True)[0] for n in w.targets]
            opt.update(name=c.textFieldGrp(w.namespace,q=True,text=True).strip(),
                       drive_targets=True if kind=='body' else c.checkBox(w.drive_targets,q=True,value=True),
                       copy_animation=_global_options['copy_animation'],
                       start_frame=c.floatFieldGrp(w.frame_bounds,q=True,value1=True),end_frame=c.floatFieldGrp(w.frame_bounds,q=True,value2=True),
                       sample_step=c.floatFieldGrp(w.sample_step,q=True,value1=True))
            for option,field in fields.items():opt[option]=c.checkBox(field,q=True,value=True)
            if kind in ('arm','leg'):opt['live_alignment']=_global_options['live_alignment']
            if kind in ('shoulder','head'):opt['control_size']=c.floatFieldGrp(w.control_size,q=True,value1=True)
            self.diagram.refresh();self.message(PARTS[key]['label']+'设置已保存。');c.deleteUI(WINDOW)
        c.button(w.create_button,e=True,label='保存部位设置（返回集成面板）',command=lambda *_:self.safe(save))
        c.button(label='清除此部位载入',parent=c.control(w.create_button,q=True,parent=True),
                 command=lambda *_:(self.unload(key),c.deleteUI(WINDOW)))
        self.details_windows[key]=w
        return w
    def create_switch_panel(self):
        from maya_agent.rigs.switch_panel import build_selected
        panel=build_selected();c.select(panel['root'],r=True)
        self.message('模式切换面板已就绪：选圆圈，W 左右拖动；左 0、右 1。')
        return panel
    def create(self):
        from . import build
        config={k:dict(row,targets=targets(k)) for k,row in _state.items() if row['uuids']}
        for key,row in config.items():
            row['copy_animation']=_global_options['copy_animation']
            if PARTS[key]['kind'] in ('arm','leg'):row['live_alignment']=_global_options['live_alignment']
        self.create_button.setEnabled(False)
        c.undoInfo(openChunk=True,chunkName='CreateIntegratedRigWithPanel')
        try:
            root=None
            if _root_state['uuid']:
                found=c.ls(_root_state['uuid'],long=True) or []
                if len(found)!=1:raise ValueError('通用根控制器已删除，请重新载入。')
                root=found[0]
            chest=self.follow_target('chest') if 'body' not in config else None
            hips=self.follow_target('hips') if 'body' not in config else None
            self.last_result=build(config,namespace=self.namespace.text().strip(),general_root=root,
                                   chest_follow=chest,hips_follow=hips,zero_controls=True)
            from maya_agent.rigs.switch_panel import build as build_switch_panel,targets as panel_targets
            if panel_targets(self.last_result):build_switch_panel(self.last_result['root'])
            self.message('已创建 '+str(len(self.last_result['parts']))+' 个部位，已按参考结构连接控制器和部位起点。 Ctrl+Z 可整体撤销。')
            return self.last_result
        finally:
            self.create_button.setEnabled(True);c.undoInfo(closeChunk=True)


def show():
    from maya_agent.rigs.live_edit import install
    install()
    from maya_agent.rigs.arm_ik import install as install_arm_ik
    install_arm_ik()
    global _instance
    if _instance is not None:
        try:_instance.close();_instance.deleteLater()
        except RuntimeError:pass
    _instance=IntegratedWindow();_instance.show();return _instance
