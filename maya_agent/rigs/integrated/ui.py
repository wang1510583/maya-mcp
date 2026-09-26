"""Independent part panel: left-load, right-settings, middle-clear."""
from PySide2 import QtCore,QtWidgets
import maya.cmds as c
from . import PARTS,VERSION

_instance=globals().get('_instance')
_root_state=globals().get('_root_state',dict(uuid=None,name=None))
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
    positions={'head':(.5,.10),'body':(.5,.45),'shoulder_R':(.29,.32),'shoulder_L':(.71,.32),
               'arm_R':(.10,.50),'arm_L':(.90,.50),'leg_R':(.29,.85),'leg_L':(.71,.85)}
    def __init__(self,window):
        super().__init__();self.window=window;self.buttons={};self.lines={}
        self.setMinimumSize(700,470)
        for key in PARTS:
            button=PartButton(key,self);self.buttons[key]=button
            button.clicked.connect(lambda checked=False,k=key:window.safe(lambda:window.load(k)))
            button.settings.connect(lambda k:window.safe(lambda:window.details(k)))
            button.unloaded.connect(lambda k:window.safe(lambda:window.unload(k)))
        self.refresh()
    def refresh(self):
        for key,button in self.buttons.items():
            n=len(_state[key]['uuids']);color='#8de1c3' if n else '#f0f0f0'
            button.setText(PARTS[key]['label']+'\n'+('● 已载入 '+str(n) if n else '○ 未载入'))
            button.setStyleSheet('QPushButton { color:'+color+'; background:transparent; border:0; font-size:18px; font-weight:600; } QPushButton:hover { background:#686868; border-radius:8px; }')
        self.update()
    def resizeEvent(self,event):
        for key,(x,y) in self.positions.items():self.buttons[key].setGeometry(round(self.width()*x)-65,round(self.height()*y)-32,130,64)
        super().resizeEvent(event)


class IntegratedWindow(QtWidgets.QDialog):
    def __init__(self):
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
        super().__init__(wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()),QtWidgets.QWidget))
        self.setObjectName('IntegratedCharacterRigWindow');self.setWindowTitle('集成角色绑定 v'+VERSION)
        self.setWindowFlags(self.windowFlags()|QtCore.Qt.Window)
        self.resize(780,760);self.last_result=None;self.details_windows={}
        c.selectPref(trackSelectionOrder=True)
        self.setStyleSheet('QDialog { background:#595959; color:#ededed; } QLabel {color:#ededed;} QLineEdit {background:#414141;color:white;padding:6px;border:1px solid #777;}')
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(20,16,20,16)
        label=QtWidgets.QLabel('左键载入 · 右键设置 · 中键清空载入 · 自动连接部位起点');layout.addWidget(label)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('名称前缀'))
        self.namespace=QtWidgets.QLineEdit('customCharacter');row.addWidget(self.namespace)
        clear=QtWidgets.QPushButton('清空载入');clear.clicked.connect(self.clear);row.addWidget(clear);layout.addLayout(row)
        root_row=QtWidgets.QHBoxLayout()
        self.root_button=PartButton('_root',self)
        self.root_button.setToolTip('左键载入一个骨骼或控制器：各部位平级跟随通用根，彼此不关联。\n中键：清空通用根载入。')
        self.root_button.clicked.connect(lambda:self.safe(self.load_root));root_row.addWidget(self.root_button)
        self.root_button.unloaded.connect(lambda _:self.clear_root())
        root_clear=QtWidgets.QPushButton('清除根');root_clear.clicked.connect(self.clear_root);root_row.addWidget(root_clear)
        layout.addLayout(root_row)
        self.diagram=Diagram(self);layout.addWidget(self.diagram,1)
        hint=QtWidgets.QLabel('部位总组分开：肩膀接胸部，手臂起点接肩膀，髋部接腰部，脚 IK 独立。\n头部独立旋转，颈部混合胸与头的方向；多空间在右键设置中。')
        hint.setStyleSheet('color:#d0d0d0;font-size:12px;');layout.addWidget(hint)
        self.create_button=QtWidgets.QPushButton('开始创建');self.create_button.setMinimumHeight(48)
        self.create_button.setStyleSheet('background:#397b80;color:white;font-size:21px;font-weight:bold;border-radius:5px;')
        self.create_button.clicked.connect(lambda:self.safe(self.create));layout.addWidget(self.create_button)
        self.status=QtWidgets.QLabel('尚未载入部位。');self.status.setWordWrap(True);self.status.setMinimumHeight(40);layout.addWidget(self.status)
        self.refresh_root()
    def message(self,text):self.status.setText(text)
    def safe(self,callback):
        try:return callback()
        except Exception as exc:self.message(str(exc));c.warning(str(exc))
    def load(self,key):
        names=c.ls(orderedSelection=True,long=True) or [];validate_count(key,names)
        _state[key]['targets']=names;_state[key]['uuids']=[c.ls(n,uuid=True)[0] for n in names]
        _state[key]['load_revision']=_state[key].get('load_revision',0)+1
        self.diagram.refresh();self.message('已载入'+PARTS[key]['label']+'：'+str(len(names))+' 个目标。右键可检查顺序和动画设置。')
    def clear(self):
        for row in _state.values():row['targets']=[];row['uuids']=[];row['load_revision']=row.get('load_revision',0)+1
        self.clear_root()
        self.diagram.refresh();self.message('已清空所有载入部位；场景不受影响。')
    def refresh_root(self):
        name=_root_state['name']
        self.root_button.setText('载入通用根骨骼 / 控制器 · '+('已载入 '+name.rsplit('|',1)[-1] if name else '未载入'))
    def load_root(self):
        names=c.ls(sl=True,long=True) or []
        if len(names)!=1 or c.nodeType(names[0]) not in ('joint','transform'):raise ValueError('请只选择一个通用根控制器。')
        _root_state.update(uuid=c.ls(names[0],uuid=True)[0],name=names[0]);self.refresh_root();self.diagram.refresh()
        self.message('通用根已载入；各部位将平级跟随它，彼此不关联。')
    def clear_root(self):
        _root_state.update(uuid=None,name=None);self.refresh_root();self.diagram.refresh()
        self.message('已清空通用根载入；场景物体保留。')
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
        c.checkBox(w.copy_animation,e=True,value=opt.get('copy_animation',True))
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
                       copy_animation=c.checkBox(w.copy_animation,q=True,value=True),
                       start_frame=c.floatFieldGrp(w.frame_bounds,q=True,value1=True),end_frame=c.floatFieldGrp(w.frame_bounds,q=True,value2=True),
                       sample_step=c.floatFieldGrp(w.sample_step,q=True,value1=True))
            for option,field in fields.items():opt[option]=c.checkBox(field,q=True,value=True)
            if kind in ('shoulder','head'):opt['control_size']=c.floatFieldGrp(w.control_size,q=True,value1=True)
            self.diagram.refresh();self.message(PARTS[key]['label']+'设置已保存。');c.deleteUI(WINDOW)
        c.button(w.create_button,e=True,label='保存部位设置（返回集成面板）',command=lambda *_:self.safe(save))
        c.button(label='清除此部位载入',parent=c.control(w.create_button,q=True,parent=True),
                 command=lambda *_:(self.unload(key),c.deleteUI(WINDOW)))
        self.details_windows[key]=w
        return w
    def create(self):
        from . import build
        config={k:dict(row,targets=targets(k)) for k,row in _state.items() if row['uuids']}
        self.create_button.setEnabled(False)
        try:
            root=None
            if _root_state['uuid']:
                found=c.ls(_root_state['uuid'],long=True) or []
                if len(found)!=1:raise ValueError('通用根控制器已删除，请重新载入。')
                root=found[0]
            self.last_result=build(config,namespace=self.namespace.text().strip(),general_root=root)
            self.message('已创建 '+str(len(self.last_result['parts']))+' 个部位，已按参考结构连接控制器和部位起点。 Ctrl+Z 可整体撤销。')
            return self.last_result
        finally:self.create_button.setEnabled(True)


def show():
    global _instance
    if _instance is not None:
        try:_instance.close();_instance.deleteLater()
        except RuntimeError:pass
    _instance=IntegratedWindow();_instance.show();return _instance
