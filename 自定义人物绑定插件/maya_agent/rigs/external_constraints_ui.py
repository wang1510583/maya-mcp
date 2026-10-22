"""Explicit, removable external constraints for existing character controls."""
from PySide2 import QtCore, QtWidgets
import maya.cmds as c
from . import external_constraints as backend

_window = globals().get('_window')


class ExternalConstraintsWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('手臂 / 脚腕外部约束'); self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        self.resize(480, 330); self.identities = {}
        layout = QtWidgets.QVBoxLayout(self)
        tip = QtWidgets.QLabel('先选外部目标、最后选大臂 / 小臂 / 肘部 / 手腕 / 脚腕，可直接使用 Maya 父 / 点 / 方向约束。\n大小臂作用于 FK 输入；手腕 global=0 使用 FK，global=1 使用 IK。IK 弯曲方向由肘部控制器控制。')
        tip.setWordWrap(True); layout.addWidget(tip)
        self.labels = {}
        for key, title in (('target', '载入外部目标'), ('control', '载入肢体控制器')):
            row = QtWidgets.QHBoxLayout(); button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, k=key: self.safe(lambda: self.load(k)))
            row.addWidget(button); label = QtWidgets.QLabel('未载入'); label.setWordWrap(True)
            self.labels[key] = label; row.addWidget(label, 1); layout.addLayout(row)
        row = QtWidgets.QHBoxLayout(); self.kind = QtWidgets.QComboBox()
        for title, kind in (('父约束（移动和旋转）', 'parent'), ('点约束（移动）', 'point'), ('方向约束（旋转）', 'orient')):
            self.kind.addItem(title, kind)
        row.addWidget(self.kind)
        add = QtWidgets.QPushButton('添加临时约束'); add.clicked.connect(lambda: self.safe(self.attach)); row.addWidget(add)
        layout.addLayout(row)
        remove = QtWidgets.QPushButton('移除外部约束，恢复原绑定')
        remove.setToolTip('选中手脚控制器、约束节点或下面的列表项后移除。恢复原空间和原动画，姿态可能返回约束前的动画位置；支持撤销。')
        remove.clicked.connect(lambda: self.safe(self.remove)); layout.addWidget(remove)
        self.entries = QtWidgets.QListWidget(); layout.addWidget(self.entries)
        refresh = QtWidgets.QPushButton('刷新约束列表'); refresh.clicked.connect(self.refresh); layout.addWidget(refresh)
        self.status = QtWidgets.QLabel('原动画曲线保留。添加、移除均支持撤销 / 重做。')
        self.status.setWordWrap(True); layout.addWidget(self.status); self.refresh()

    def safe(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.status.setText(str(exc)); c.warning(str(exc))

    def load(self, key):
        nodes = c.ls(sl=True, long=True, objectsOnly=True) or []
        if len(nodes) != 1:
            raise ValueError('请只选择一个物体后载入。')
        node = backend.resolve(nodes[0])['control'] if key == 'control' else backend._node(nodes[0])
        self.identities[key] = c.ls(node, uuid=True)[0]
        self.labels[key].setText(node.rsplit('|', 1)[-1])

    def loaded(self, key):
        nodes = c.ls(self.identities.get(key, ''), long=True) or []
        if len(nodes) != 1:
            raise ValueError('请重新载入' + ('外部目标' if key == 'target' else '手脚控制器'))
        return nodes[0]

    def attach(self):
        result = backend.attach(self.loaded('control'), self.loaded('target'), self.kind.currentData())
        self.refresh(); self.status.setText('已添加 ' + result['mode'] + ' 临时约束。原动画保留；可随时移除并恢复。')

    def remove(self):
        selected = c.ls(sl=True, long=True) or []
        owner = backend.registry(selected[0]) if len(selected) == 1 else None
        if not owner and self.entries.currentItem():
            nodes = c.ls(self.entries.currentItem().data(QtCore.Qt.UserRole)) or []
            owner = nodes[0] if len(nodes) == 1 else None
        if not owner:
            raise ValueError('请选择已约束的手脚控制器或列表中的约束。')
        backend.remove(owner); self.refresh()
        self.status.setText('外部约束已移除，已恢复原绑定空间和动画。可撤销此次移除。')

    def refresh(self):
        self.entries.clear()
        for owner in c.ls('::*.' + backend.DATA, objectsOnly=True) or []:
            control, target = backend._link(owner, 'control'), backend._link(owner, 'target')
            item = QtWidgets.QListWidgetItem((control or '控制器已删除') + ' ← ' + (target or '目标已删除'))
            item.setData(QtCore.Qt.UserRole, c.ls(owner, uuid=True)[0]); self.entries.addItem(item)


def show():
    from maya import OpenMayaUI
    from shiboken2 import wrapInstance
    global _window
    if _window is not None:
        try:
            _window.close(); _window.deleteLater()
        except RuntimeError:
            pass
    parent = wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()), QtWidgets.QWidget)
    _window = ExternalConstraintsWindow(parent); _window.show(); return _window
