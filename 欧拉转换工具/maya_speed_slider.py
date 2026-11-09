"""
Maya Speed Slider + Motion Trail Tool + Euler Tool
播放速度滑块 + 运动轨迹追踪工具 + 旋转欧拉工具

使用方法:
1. 在 Maya Script Editor 中粘贴此代码
2. 执行代码即可打开工具窗口
3. 左侧滑块控制播放速度
4. 右侧开关控制运动轨迹追踪
5. 最右侧按钮控制旋转欧拉计算与转换
"""

__author__ = "Christian UNterberg, Tetsuo Animation Studio"
__copyright__ = "Copyright 2024, Tetsuo Animation Studio"
__credits__ = ["Christian Unterberg"]
__license__ = "GNU Affero General Public License v3.0"
__version__ = "0.0.12-native-filter"
__maintainer__ = "Christian Unterbergt"
__email__ = "chris@tetsuoanimation.com"
__links__ = ["https://www.tetsuoanimation.com", "https://tetsuoanimation.gumroad.com/l/mayaspeedslider"]
__status__ = "Release"

import os
import sys
import time
import logging

import maya.cmds as cmds
import maya.mel as mel
from maya.api.OpenMaya import MMatrix, MPoint
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt
    from shiboken2 import wrapInstance


# ============================================================================
# Configuration
# ============================================================================
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger('Motion Trail')

TOOL_NAME = 'motion_trail'
TRAIL_NAME = 'trail'
TRAILSHAPE_NAME = 'agora_trail'
REFRESHRATE = 2

# 旋转顺序常量
ROTATE_ORDERS = ['xyz', 'yzx', 'zxy', 'xzy', 'yxz', 'zyx']

# 全局变量
_main_window = None


# ============================================================================
# Euler Tool Functions
# ============================================================================

# Rig-aware Euler backend (2026-11-04), bundled for standalone use.
"""Euler operations in the solver's rotation space, including zero surfaces.

No constraints or world-space feedback are introduced. Order conversion preserves
poses at the union of existing XYZ rotation key times, without interval sampling.
Between-key interpolation is left to Maya. Maya 2024, degree angle units.
"""
import json
import math
import maya.cmds as cmds
import maya.api.OpenMaya as om

ORDERS = ('xyz', 'yzx', 'zxy', 'xzy', 'yxz', 'zyx')
ATTRS = ('rotateX', 'rotateY', 'rotateZ')


def describe(node, editable=False):
    names = cmds.ls(node, long=True) or []
    if len(names) != 1 or cmds.nodeType(names[0]) not in ('transform', 'joint'):
        raise ValueError('请选择唯一的控制器或变换节点：' + node)
    node = names[0]
    if cmds.currentUnit(q=True, angle=True) != 'deg':
        raise ValueError('请先将 Maya 角度单位设为度。')
    offsets = [0.0] * 3
    source = node
    if cmds.objExists(node + '.zeroChannelData'):
        data = json.loads(cmds.getAttr(node + '.zeroChannelData'))
        source = data['source']
        for i, attr in enumerate(ATTRS):
            if attr not in data['offsets']:
                raise ValueError('此零位控制器没有完整的 XYZ 旋转通道：' + node)
            offsets[i] = data['offsets'][attr]
            edge = cmds.connectionInfo(source + '.' + attr, sfd=True)
            blend = edge.rsplit('.', 1)[0]
            if (not blend or cmds.nodeType(blend) != 'animBlendNodeAdditiveDA'
                    or not cmds.isConnected(node + '.' + attr, blend + '.inputA')
                    or cmds.connectionInfo(blend + '.inputB', sfd=True)
                    or cmds.connectionInfo(blend + '.weightA', sfd=True)
                    or cmds.connectionInfo(blend + '.weightB', sfd=True)
                    or abs(cmds.getAttr(blend + '.inputB') - offsets[i]) > 1e-7
                    or abs(cmds.getAttr(blend + '.weightA') - 1) > 1e-9
                    or abs(cmds.getAttr(blend + '.weightB') - 1) > 1e-9):
                raise ValueError('归零旋转连接已变化，未修改：' + node)
        if not cmds.isConnected(node + '.rotateOrder', source + '.rotateOrder'):
            raise ValueError('归零控制器与输入旋转顺序未连接：' + node)
    curves = []
    times = []
    if editable and (cmds.getAttr(node + '.rotateOrder', lock=True)
                     or cmds.connectionInfo(node + '.rotateOrder', sfd=True)):
        raise ValueError('旋转顺序被锁定或驱动：' + node)
    for attr in ATTRS:
        plug = node + '.' + attr
        edge = cmds.connectionInfo(plug, sfd=True)
        curve = edge.rsplit('.', 1)[0] if edge else None
        if editable:
            if cmds.getAttr(plug, lock=True):
                raise ValueError('旋转通道已锁定：' + plug)
            if curve and cmds.nodeType(curve) != 'animCurveTA':
                raise ValueError('暂不覆盖动画层、约束或表达式驱动：' + plug)
            if curve:
                if not cmds.keyframe(curve, q=True, kc=True):
                    raise ValueError('旋转动画曲线为空：' + curve)
                consumers = cmds.listConnections(curve + '.output', s=False, d=True, p=True) or []
                if len(consumers) != 1 or cmds.lockNode(curve, q=True, lock=True)[0]:
                    raise ValueError('动画曲线共享或锁定，未修改：' + curve)
                # Time warps and cycle/linear infinity need their own conversion.
                driver = cmds.connectionInfo(curve + '.input', sfd=True)
                if driver and cmds.nodeType(driver.split('.')[0]) != 'time':
                    raise ValueError('不支持重映射时间曲线：' + curve)
        curves.append(curve)
        times.append(sorted(set(cmds.keyframe(plug, q=True, tc=True) or [])))
    return dict(node=node, source=source, offsets=offsets, curves=curves,
                times=times, order=cmds.getAttr(node + '.rotateOrder'))


def actual_values(info, frame):
    return [cmds.getAttr(info['node'] + '.' + a, time=frame) + o
            for a, o in zip(ATTRS, info['offsets'])]


def euler(values, order):
    return om.MEulerRotation(*[math.radians(v) for v in values], order)


def rotation_error(a, ao, b, bo):
    qa, qb = euler(a, ao).asQuaternion(), euler(b, bo).asQuaternion()
    dot = abs(qa.x*qb.x + qa.y*qb.y + qa.z*qb.z + qa.w*qb.w)
    return math.degrees(2 * math.acos(min(1.0, dot)))


def tolerances(node, frame):
    info = describe(node)
    original = euler(actual_values(info, frame), info['order'])
    result = []
    for order, label in enumerate(ORDERS):
        converted = om.MEulerRotation(original)
        converted.reorderIt(order)
        middle = math.degrees(converted['xyz'.index(label[1])])
        result.append(abs(((middle + 90) % 180) - 90) / 90)
    return result


def _key_times(info):
    times = sorted(set(t for axis in info['times'] for t in axis))
    if not times:
        return [cmds.currentTime(q=True)]
    return times


def _transaction(infos, operation):
    """Keep curve identities, connections and full backup curves for rollback."""
    if not cmds.undoInfo(q=True, state=True):
        raise ValueError('请先启用 Maya 撤销，以便撤销旋转转换。')
    saved = []
    auto = cmds.autoKeyframe(q=True, state=True)
    cmds.undoInfo(openChunk=True, chunkName='RigAwareEuler')
    try:
        cmds.autoKeyframe(state=False)
        for info in infos:
            row = dict(info=info, values=[cmds.getAttr(info['node']+'.'+a) for a in ATTRS], copies=[])
            saved.append(row)
            for curve in info['curves']:
                row['copies'].append(cmds.duplicate(curve, name='__rigEulerBackup#')[0] if curve else None)
        try:
            return operation()
        except Exception:
            for row in saved:
                info = row['info']
                cmds.setAttr(info['node']+'.rotateOrder', info['order'])
                for attr, curve, backup, value in zip(ATTRS, info['curves'], row['copies'], row['values']):
                    plug = info['node']+'.'+attr
                    if curve:
                        cmds.copyKey(backup)
                        cmds.pasteKey(curve, option='replaceCompletely')
                    else:
                        edge = cmds.connectionInfo(plug, sfd=True)
                        if edge and cmds.nodeType(edge.split('.')[0]) == 'animCurveTA':
                            cmds.delete(edge.split('.')[0])
                        cmds.setAttr(plug, value)
            raise
    finally:
        for row in saved:
            for backup in row['copies']:
                if backup and cmds.objExists(backup):
                    cmds.delete(backup)
        cmds.autoKeyframe(state=auto)
        cmds.undoInfo(closeChunk=True)


def filter_euler(objects=None):
    """Filter full XYZ curves after adding offsets, then subtract offsets."""
    objects = objects or cmds.ls(sl=True, long=True) or []
    if not objects:
        raise ValueError('请选择需要过滤的控制器。')
    infos = [describe(n, editable=True) for n in dict.fromkeys(objects)]
    for info in infos:
        if not all(info['curves']) or not info['times'][0] or not all(t == info['times'][0] for t in info['times']):
            raise ValueError('欧拉过滤要求 XYZ 三轴关键帧时间一致：' + info['node'])
    def apply():
        reports = []
        for info in infos:
            temp = None
            copies = []
            try:
                temp = cmds.createNode('transform', name='__rigEulerFilter#', skipSelect=True)
                cmds.setAttr(temp+'.rotateOrder', info['order'])
                before = [actual_values(info, t) for t in info['times'][0]]
                for attr, curve, offset in zip(ATTRS, info['curves'], info['offsets']):
                    copy = cmds.duplicate(curve, name='__rigEulerCurve#')[0]
                    copies.append(copy)
                    cmds.connectAttr(copy+'.output', temp+'.'+attr)
                    cmds.keyframe(copy, e=True, relative=True, valueChange=offset)
                cmds.filterCurve(*copies, filter='euler')
                values = [cmds.keyframe(k, q=True, vc=True) for k in copies]
                error = max(rotation_error(old, info['order'], new, info['order'])
                            for old, new in zip(before, zip(*values)))
                if error > 1e-4:
                    raise RuntimeError('过滤姿态校验失败：' + info['node'])
                for curve, offset, axis_values in zip(info['curves'], info['offsets'], values):
                    for i, value in enumerate(axis_values):
                        cmds.keyframe(curve, e=True, index=(i, i), valueChange=value-offset)
                reports.append(dict(node=info['node'], keys=len(before), max_error_degrees=error))
            finally:
                for n in copies + ([temp] if temp else []):
                    if cmds.objExists(n):
                        cmds.delete(n)
        return reports
    return _transaction(infos, apply)


def switch_order(objects, order):
    """Convert at existing rotation key times only; keep existing tangent types."""
    if order not in ORDERS:
        raise ValueError('无效的旋转顺序。')
    if not objects:
        raise ValueError('请选择物体。')
    target = ORDERS.index(order)
    infos = [describe(n, editable=True) for n in dict.fromkeys(objects)]
    infos = [info for info in infos if info['order'] != target]
    for info in infos:
        for curve in info['curves']:
            if curve and (cmds.getAttr(curve+'.preInfinity') or cmds.getAttr(curve+'.postInfinity')):
                raise ValueError('转换前请将循环/线性无限动画烘焙为关键帧：' + curve)
        times = _key_times(info)
        values = [actual_values(info, t) for t in times]
        converted = []
        previous = None
        for value in values:
            current = euler(value, info['order'])
            current.reorderIt(target)
            if previous is not None:
                current = current.closestSolution(previous)
                current = current.closestCut(previous)
            previous = current
            converted.append([math.degrees(v)-o for v, o in zip(current, info['offsets'])])
        info.update(samples=times, before=values, converted=converted)
    if not infos:
        return []
    def apply():
        reports = []
        for info in infos:
            node = info['node']
            cmds.setAttr(node+'.rotateOrder', target)
            animated = any(info['times'])
            if animated:
                for t, values in zip(info['samples'], info['converted']):
                    for attr, value, old_times in zip(ATTRS, values, info['times']):
                        if t in old_times:
                            cmds.keyframe(node+'.'+attr, e=True, time=(t,t), valueChange=value)
                        else:
                            # Euler axes are coupled. Complete XYZ at existing
                            # rotation times only; never add in-between frames.
                            cmds.setKeyframe(node, at=attr, time=t, value=value,
                                             itt='auto', ott='auto')
                for attr in ATTRS:
                    if cmds.keyframe(node+'.'+attr, q=True, tc=True) != info['samples']:
                        raise RuntimeError('关键帧时间校验失败，已恢复：'+node)
            else:
                for attr, value in zip(ATTRS, info['converted'][0]):
                    cmds.setAttr(node+'.'+attr, value)
            error = max(rotation_error(before, info['order'], actual_values(info, t), target)
                        for t, before in zip(info['samples'], info['before']))
            if error > 1e-4:
                raise RuntimeError('转换姿态校验失败，已恢复：' + node)
            reports.append(dict(node=node, order=order, keys=len(info['samples']) if animated else 0,
                                max_error_degrees=error, mode='existing_keys'))
        return reports
    return _transaction(infos, apply)


def get_time_slider_range():
    """Return the highlighted Maya time slider range, or None when there is no range."""
    try:
        playback_slider = mel.eval('$tmp = $gPlayBackSlider')
        if not cmds.timeControl(playback_slider, query=True, rangeVisible=True):
            return None

        range_values = cmds.timeControl(playback_slider, query=True, rangeArray=True)
        if not range_values or len(range_values) < 2:
            return None

        start_time, end_time = sorted(range_values[:2])
        if abs(end_time - start_time) < 0.001:
            return None
        return start_time, end_time
    except Exception:
        return None

def get_euler_keyframes(obj):
    """Use highlighted time-slider frames when present; otherwise use all rotate keys."""
    rotate_attrs = ['rotateX', 'rotateY', 'rotateZ']
    selected_keyframes = cmds.keyframe(
        obj, attribute=rotate_attrs, query=True, selected=True, timeChange=True
    ) or []
    if selected_keyframes:
        return sorted(set(selected_keyframes))

    keyframes = cmds.keyframe(obj, attribute=rotate_attrs, query=True, timeChange=True) or []
    keyframes = sorted(set(keyframes))

    selected_range = get_time_slider_range()
    if selected_range:
        start_time, end_time = selected_range
        return [
            frame for frame in keyframes
            if start_time - 0.001 <= frame <= end_time + 0.001
        ]

    return keyframes

def calculate_euler_for_object(obj):
    """Analyse the actual FK rotation, including this rig's zero offsets."""
    info = describe(obj)
    current_ro = ORDERS[info['order']]
    now = cmds.currentTime(q=True)
    frames = get_euler_keyframes(obj) or [now]
    samples = [tolerances(obj, frame) for frame in frames]
    averages = [sum(row[i] for row in samples)/len(samples) for i in range(6)]
    current = tolerances(obj, now)
    best = ORDERS[averages.index(min(averages))]
    lines = ['分析了 %d 个采样帧（内部实际旋转）' % len(frames)]
    for label, avg, cur in zip(ORDERS, averages, current):
        lines.append('%s: 平均%d%% 当前帧%d%%%s' % (label, int(avg*100), int(cur*100), ' [推荐]' if label == best else ''))
    lines.append('综合推荐: '+best)
    return current_ro, best, '\n'.join(lines)


def switch_euler_order(objects, rot_order):
    """Convert the entire rotation animation, not only a highlighted range."""
    try:
        reports = switch_order(objects, rot_order)
        cmds.inViewMessage(amg='旋转顺序已转换：保留原关键帧时间与姿态，不补中间帧；Ctrl+Z 撤销。', pos='midCenter', fade=True)
        return True
    except Exception as exc:
        cmds.warning(str(exc))
        return False


def native_euler_filter_selected(selection_connection=None):
    """Use the same selection connection and MEL procedure as Maya's menu."""
    import json
    temporary = None
    opened = False
    try:
        # QPushButton.clicked supplies a bool, not a selection connection.
        connection = selection_connection if isinstance(selection_connection, str) else None
        if not connection:
            panels = [p for p in cmds.getPanel(type='scriptedPanel') or []
                      if cmds.scriptedPanel(p,q=True,type=True)=='graphEditor']
            visible = cmds.getPanel(visiblePanels=True) or []
            focus = cmds.getPanel(withFocus=True)
            panels.sort(key=lambda p: (p!=focus, p not in visible, p!='graphEditor1', p))
            for panel in panels:
                outline = panel+'OutlineEd'
                if cmds.editor(outline,exists=True):
                    candidate = cmds.editor(outline,q=True,selectionConnection=True)
                    if candidate and mel.eval('findAnimCurves('+json.dumps(candidate)+')'):
                        connection = candidate
                        break
        if not connection:
            # Also usable without an open Graph Editor. Let Maya resolve
            # selected curves/objects, including custom rotation attributes.
            objects = cmds.keyframe(q=True,sl=True,name=True) or cmds.ls(sl=True,long=True) or []
            if not objects:
                cmds.warning('请选择图表编辑器中的曲线或场景控制器。')
                return None
            temporary = cmds.selectionConnection()
            for obj in objects:
                cmds.selectionConnection(temporary,e=True,select=obj)
            connection = temporary
        curves = mel.eval('findAnimCurves('+json.dumps(connection)+')') or []
        if not curves:
            cmds.warning('当前选择中没有可过滤的动画曲线。')
            return None
        cmds.undoInfo(openChunk=True, chunkName='NativeEulerFilter')
        opened = True
        mel.eval('performEulerFilter('+json.dumps(connection)+')')
        cmds.inViewMessage(amg='普通欧拉过滤完成；Ctrl+Z 撤销。', pos='midCenter', fade=True)
        return curves
    except Exception as exc:
        cmds.warning(str(exc))
        return None
    finally:
        if opened:
            cmds.undoInfo(closeChunk=True)
        if temporary:
            cmds.deleteUI(temporary)


def safe_euler_filter_selected():
    try:
        reports = filter_euler()
        cmds.inViewMessage(amg='安全欧拉过滤完成：关键帧姿态已核对，请检查帧间运动。', pos='midCenter', fade=True)
        return reports
    except Exception as exc:
        cmds.warning(str(exc))
        return None


# ============================================================================
# Motion Trail Core Class
# ============================================================================

class MotionTrailAgora(object):
    """运动轨迹核心类"""

    def __init__(self):
        self.check_idle_job = 0
        self.range = []
        self.trail = None
        self.trailshape = None
        self.range_to_process = [1, 2, 3, 4]
        self.ready = True
        self.tracked_object = []
        self.reference_matrix = 'world'
        self.trail_length = 0
        self.first_tracked_frame = 0
        self.trail_points = []
        self.keyvisual_group = None
        self.dummytrail = None
        self.dummytrailshape = None
        self.delete_trail()

    def define_object(self):
        """定义要追踪的物体"""
        selection = cmds.ls(selection=True)
        if not selection:
            if self.trail and cmds.objExists(self.trail):
                cmds.warning('请至少选择一个物体。')
            return []

        if (len(selection) == 1 and cmds.objectType(selection[0]) == 'mesh'):
            self.mesh_tracker()
        else:
            self.tracked_object = selection
            if self.trail and cmds.objExists(self.trail):
                self.create_dummy_point()

        return self.tracked_object

    def mesh_tracker(self):
        """网格追踪模式"""
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            to_delete = list(filter(cmds.objExists, ['dummyMover', 'trail_keyvisual']))
            if to_delete:
                cmds.delete(to_delete)
            cmds.select(cmds.ls(selection=True, flatten=True)[0])
            mel.eval('Rivet')
            tracker = cmds.rename('pinOutput', 'agora_trail_mesh_tracker')
            cmds.select(tracker)
            cmds.setAttr('{}.visibility'.format(tracker), False)
            cmds.setAttr('{}.hiddenInOutliner'.format(tracker), True)
            self.tracked_object = ['agora_trail_mesh_tracker']
        finally:
            cmds.undoInfo(stateWithoutFlush=True, undoName='MotionTrail')
        return self.tracked_object

    def delete_trail(self):
        """删除轨迹"""
        try:
            if cmds.objExists('dummyMover'):
                cmds.delete('dummyMover')
            if cmds.objExists('trail_keyvisual'):
                cmds.delete('trail_keyvisual')
            if self.trail and cmds.objExists(self.trail):
                cmds.delete(self.trail)
        except:
            pass
        
        self.trail = None
        self.trailshape = None
        self.keyvisual_group = None
        self.dummytrail = None
        self.dummytrailshape = None
        
        tool_group = get_tool_group()
        if cmds.objExists(tool_group):
            try:
                trails = cmds.ls('{}|{}*'.format(tool_group, TRAIL_NAME))
                for trail in trails:
                    if cmds.objExists(trail):
                        cmds.delete(trail)
            except:
                pass

    def create_trail_node(self):
        """创建轨迹节点"""
        tool_group = get_tool_group()
        self.trail = cmds.createNode('transform', n=TRAIL_NAME, parent=tool_group, skipSelect=True)
        self.trailshape = cmds.createNode('motionTrailShape', parent=self.trail, n=TRAILSHAPE_NAME, skipSelect=True)
        
        self.set_curve_prettiness()
        cmds.setAttr('{}.hiddenInOutliner'.format(self.trail), True)

        current_selection = cmds.ls(selection=True)
        if cmds.objExists('agora_trail_mesh_tracker'):
            cmds.setAttr('agora_trail_mesh_tracker.hiddenInOutliner', True)
            cmds.parent('agora_trail_mesh_tracker', self.trail)
        cmds.select(current_selection)

    def set_curve_prettiness(self):
        """设置曲线外观"""
        if not self.trailshape or not cmds.objExists(self.trailshape):
            return
            
        cmds.setAttr('{}.trailColor'.format(self.trailshape), 1.0, 0.0, 0.0, type='double3')
        cmds.setAttr('{}.extraTrailColor'.format(self.trailshape), 1.0, 1.0, 1.0, type='double3')
        cmds.setAttr('{}.trailDrawMode'.format(self.trailshape), 1)
        cmds.setAttr('{}.template'.format(self.trailshape), True)
        self.set_faded_frames('all')
        cmds.setAttr('{}.increment'.format(self.trailshape), 1)

    def set_faded_frames(self, number):
        """设置淡入淡出帧数"""
        if not self.trailshape or not cmds.objExists(self.trailshape):
            return
            
        if number == 'all':
            setting = 0
        else:
            setting = int(number)
        cmds.setAttr('{}.postFrame'.format(self.trailshape), setting)
        cmds.setAttr('{}.preFrame'.format(self.trailshape), setting)
        cmds.setAttr('{}.fadeInoutFrames'.format(self.trailshape), setting)

    def isIdle(self):
        """空闲时处理一帧"""
        if len(self.range_to_process) > 0:
            frame = self.range_to_process.pop(0)
            self.set_frame_point(frame)

    def get_range(self):
        """获取待处理范围"""
        return self.range_to_process

    def prioritize_timeline(self):
        """优先处理当前帧附近的帧"""
        in_time = int(cmds.playbackOptions(query=True, minTime=True))
        out_time = int(cmds.playbackOptions(query=True, maxTime=True))
        cur_time = cmds.currentTime(q=True)
        list_of_keys = range(in_time, out_time + 1)
        self.range_to_process = sorted(list_of_keys, key=lambda x: abs(cur_time - x))
        self.trail_length = len(self.range_to_process)
        self.first_tracked_frame = min(self.range_to_process)
        return self.range_to_process

    def create_dummy_point(self):
        """创建虚拟点（当前帧指示器）"""
        if not self.tracked_object:
            return
        
        if not self.trail or not cmds.objExists(self.trail):
            return

        to_delete = list(filter(cmds.objExists, ['dummyMover', 'trail_keyvisual']))
        if to_delete:
            try:
                cmds.delete(to_delete)
            except:
                pass

        try:
            self.keyvisual_group = cmds.createNode('transform', name='dummyMover', parent=self.trail, skipSelect=True)
            cmds.setAttr('{}.displayHandle'.format(self.keyvisual_group), True)
            cmds.setAttr('{}.overrideEnabled'.format(self.keyvisual_group), True)
            cmds.setAttr('{}.overrideDisplayType'.format(self.keyvisual_group), 2)
            
            self.dummytrail = cmds.createNode('transform', name='trail_keyvisual', parent='dummyMover', skipSelect=True)
            self.dummytrailshape = cmds.createNode('motionTrailShape', parent=self.dummytrail, name='trail_keyvisualshape', skipSelect=True)
            
            cmds.setAttr('{}.keyframeFlags'.format(self.dummytrailshape), 2, type='Int32Array')
            cmds.setAttr('{}.points'.format(self.dummytrailshape), 2, (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, 1.0), type='pointArray')
            cmds.setAttr('{}.increment'.format(self.dummytrailshape), 1.0)
            cmds.setAttr('{}.startTime'.format(self.dummytrailshape), 1.0)
            cmds.setAttr('{}.keyframeColor'.format(self.dummytrailshape), 0, 0, 0, type='double3')
            cmds.setAttr('{}.overrideEnabled'.format(self.dummytrailshape), True)
            cmds.setAttr('{}.overrideDisplayType'.format(self.dummytrailshape), 2)
            
            cmds.connectAttr('{}.message'.format(self.keyvisual_group), '{}.transformToMove'.format(self.dummytrailshape))
            cmds.setAttr('{}.keyframeTimes'.format(self.dummytrailshape), 1, type='doubleArray')
            
            self.constraint_dummy_point()
        except Exception as e:
            self.keyvisual_group = None
            self.dummytrail = None
            self.dummytrailshape = None

    def constraint_dummy_point(self):
        """约束虚拟点到追踪物体"""
        if not self.tracked_object or not self.keyvisual_group:
            return
            
        if not cmds.objExists(self.keyvisual_group):
            return

        try:
            target_object = self.tracked_object[0]
            constrained_object = self.keyvisual_group

            matrix_constraint = cmds.createNode('multMatrix', skipSelect=True)
            cmds.connectAttr(target_object + '.worldMatrix[0]', matrix_constraint + '.matrixIn[0]')
            cmds.connectAttr(matrix_constraint + '.matrixSum', constrained_object + '.offsetParentMatrix')
        except:
            pass

    def prepare_pointarray(self, range_time):
        """准备点数组"""
        if not self.trailshape or not cmds.objExists(self.trailshape):
            return
            
        if self.reference_matrix != 'world':
            self.attach_trail_to_cam()
        
        original = cmds.getAttr('{}.points'.format(self.trailshape)) or []
        
        if not self.tracked_object or not cmds.objExists(self.tracked_object[0]):
            return
            
        curmatrix = cmds.getAttr(('{}.worldMatrix'.format(self.tracked_object[0])), time=cmds.currentTime(q=True))[12:15]
        
        if len(original) < len(range_time):
            original = [curmatrix] * len(range_time)
        
        self.trail_points = original
        cmds.setAttr('{}.startTime'.format(self.trailshape), min(range_time))
        self.set_trail_per_camera_visibility()

    def set_frame_point(self, frame):
        """设置某一帧的点位置"""
        if not self.trailshape or not cmds.objExists(self.trailshape):
            return
            
        if not self.tracked_object or not cmds.objExists(self.tracked_object[0]):
            return
            
        try:
            matrixx = cmds.getAttr(('{}.worldMatrix'.format(self.tracked_object[0])), time=frame)[12:16]

            trail_length = self.trail_length
            if self.reference_matrix != 'world' and validate_camera_existance(self.reference_matrix):
                cam_matrixx = cmds.getAttr(('{}.worldMatrix'.format(self.reference_matrix)), time=frame)
                matrix_point = list(MPoint(matrixx) * MMatrix(cam_matrixx).inverse())[:3]
            else:
                self.reference_matrix = 'world'
                matrix_point = matrixx[:3]
            
            self.trail_points[frame - int(self.first_tracked_frame)] = matrix_point
            
            cmds.undoInfo(stateWithoutFlush=False)
            try:
                cmds.setAttr(
                    '{}.points'.format(self.trailshape),
                    trail_length,
                    *self.trail_points[:trail_length],
                    type='pointArray'
                )
            finally:
                cmds.undoInfo(stateWithoutFlush=True, undoName='MotionTrail')
        except:
            pass

    def set_camera_reference(self, camera):
        """设置相机参考"""
        self.reference_matrix = camera
        
        if not self.trail or not cmds.objExists(self.trail):
            return
            
        offset_matrix_attribute = '{}.offsetParentMatrix'.format(self.trail)
        
        connected_attribute = cmds.listConnections(offset_matrix_attribute, plugs=True)
        
        if connected_attribute is not None:
            cmds.disconnectAttr(connected_attribute[0], offset_matrix_attribute)
        
        cmds.setAttr(offset_matrix_attribute,
                     [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                     type="matrix")

    def attach_trail_to_cam(self):
        """将轨迹附加到相机"""
        if not self.trail or not cmds.objExists(self.trail):
            return
            
        cam_name = self.reference_matrix
        offset_matrix_attribute = '{}.offsetParentMatrix'.format(self.trail)
        
        if cmds.objExists(cam_name):
            connected_attribute = cmds.listConnections(offset_matrix_attribute, plugs=True)
            if connected_attribute is None:
                cmds.connectAttr('{}.worldMatrix[0]'.format(cam_name), offset_matrix_attribute)

    def set_trail_per_camera_visibility(self):
        """设置每个相机的可见性"""
        if not self.trail or not cmds.objExists(self.trail):
            return
            
        cam_name = self.reference_matrix
        for camera in query_cameras():
            if camera != 'world':
                try:
                    cmds.perCameraVisibility(self.trail, camera=camera, hide=True, remove=True)
                except:
                    pass
        
        if cam_name != 'world':
            try:
                mel_command = 'perCameraVisibility -c {} -q -hi'.format(cam_name)
                mel.eval(mel_command)
                for other_camera in query_cameras():
                    if other_camera != cam_name:
                        cmds.perCameraVisibility(self.trail, camera=other_camera, hide=True)
            except:
                pass


# ============================================================================
# Utility Functions
# ============================================================================

def maya_main_window():
    main_window = omui.MQtUtil.mainWindow()
    if sys.version_info.major >= 3:
        return wrapInstance(int(main_window), QtWidgets.QWidget)
    else:
        return wrapInstance(long(main_window), QtWidgets.QWidget)

def get_viewport_widget():
    """获取Maya视口的QWidget"""
    view = omui.M3dView.active3dView()
    view_widget = omui.M3dView.active3dView().widget()
    return wrapInstance(int(view_widget), QtWidgets.QWidget)

def get_tool_group():
    """获取或创建工具组"""
    group_name = 'motion_trail_group'
    if not cmds.objExists(group_name):
        group_name = cmds.createNode('transform', name=group_name, skipSelect=True)
        cmds.setAttr('{}.hiddenInOutliner'.format(group_name), True)
    return group_name

def validate_camera_existance(camera):
    """验证相机是否存在"""
    if cmds.objExists(camera) or camera == 'world':
        return True
    return False

def query_cameras():
    """查询所有相机"""
    try:
        return cmds.listCameras(p=True)
    except:
        return []

def condition_exists(condition_name):
    """检查条件是否存在"""
    try:
        cmds.condition(condition_name, query=True, state=True)
        return True
    except:
        return False

def kill_jobs():
    """终止所有脚本任务"""
    if condition_exists('run_trail_job'):
        try:
            cmds.condition('run_trail_job', delete=True)
        except:
            pass

    try:
        for job in cmds.scriptJob(listJobs=True):
            if 'motion_trail' in job.lower() or 'update_trail' in job:
                try:
                    job_id = int(job.split(':')[0])
                    cmds.scriptJob(kill=job_id, force=True)
                except:
                    pass
    except:
        pass

def kill_auto_selection_job():
    """终止自动选择任务"""
    try:
        for job in cmds.scriptJob(listJobs=True):
            if 'define_object' in job or 'auto_selection' in job:
                try:
                    job_id = int(job.split(':')[0])
                    cmds.scriptJob(kill=job_id, force=True)
                except:
                    pass
    except:
        pass

def get_maya_icon(icon_name):
    """获取Maya内置图标"""
    try:
        icon_path = cmds.resourceManager(nameFilter=icon_name + '*')
        if icon_path:
            return QtGui.QIcon(':/' + icon_path[0])
    except:
        pass
    return QtGui.QIcon(':/gear.png')


# ============================================================================
# Custom Slider with Right-Click Support
# ============================================================================

class SubframeSlider(QtWidgets.QSlider):
    """自定义滑块，支持右键切换子帧显示"""
    
    subframe_toggled = QtCore.Signal(bool)
    
    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super(SubframeSlider, self).__init__(orientation, parent)
        self.subframe_enabled = True
        self.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
    
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton:
            # 切换子帧状态
            self.subframe_enabled = not self.subframe_enabled
            self.subframe_toggled.emit(self.subframe_enabled)
            self.update_handle_style()
            event.accept()
        else:
            super(SubframeSlider, self).mousePressEvent(event)
    
    def update_handle_style(self):
        """更新滑块球样式"""
        if self.subframe_enabled:
            self.setStyleSheet("""
                QSlider::handle:horizontal {
                    background: #1a1a1a;
                    border: 1px solid #4a4a4a;
                    width: 10px;
                    margin: -4px 0;
                    border-radius: 5px;
                }
                QSlider::handle:horizontal:hover {
                    background: #2a2a2a;
                }
            """)
        else:
            self.setStyleSheet("""
                QSlider::handle:horizontal {
                    background: #5a5a5a;
                    border: 1px solid #4a4a4a;
                    width: 10px;
                    margin: -4px 0;
                    border-radius: 5px;
                }
                QSlider::handle:horizontal:hover {
                    background: #6a6a6a;
                }
            """)


# ============================================================================
# Main UI Class
# ============================================================================

class TempoSlider(QtWidgets.QWidget):
    DARK_STYLE = """
        QSlider::groove:horizontal {
            border: 1px solid #3d3d3d;
            height: 4px;
            background: #1a1a1a;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #5a5a5a;
            border: 1px solid #4a4a4a;
            width: 10px;
            margin: -4px 0;
            border-radius: 5px;
        }
        QSlider::handle:horizontal:hover {
            background: #6a6a6a;
        }
        QCheckBox {
            color: #cccccc;
            spacing: 0px;
        }
        QCheckBox::indicator {
            width: 12px;
            height: 12px;
            border: 1px solid #4a4a4a;
            border-radius: 2px;
            background: transparent;
        }
        QCheckBox::indicator:checked {
            background: #1a1a1a;
            border: 1px solid #4a4a4a;
        }
        QCheckBox#trail_checkbox::indicator {
            width: 12px;
            height: 12px;
            border: 1px solid #4a4a4a;
            border-radius: 2px;
            background: transparent;
        }
        QCheckBox#trail_checkbox::indicator:checked {
            background: #1a1a1a;
            border: 1px solid #4a4a4a;
        }
        QPushButton#trail_settings {
            background: transparent;
            background-color: transparent;
            border: none;
            padding: 2px;
        }
        QPushButton#trail_settings:hover {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
        }
        QLabel#euler_btn {
            color: #ffffff;
            padding: 2px;
        }
        QToolTip {
            color: #000000;
            background-color: #f0f0f0;
            border: 1px solid #808080;
        }
    """
    
    def __init__(self):
        super(TempoSlider, self).__init__(maya_main_window())
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(150, 26)
        self.setStyleSheet(self.DARK_STYLE)
        
        self._opacity = 0.01
        self._drag_pos = None
        
        # Motion Trail
        self.trail = MotionTrailAgora()
        self.auto_select_enabled = True
        self.fade_setting = 'all'
        self.idle_job = 0
        self.settings_window = None
        
        # Euler Tool
        self.euler_window = None
        self.current_euler = '---'
        self.best_euler = '---'
        
        self.create_ui()
        self.set_defaults()
        self.create_connections()
        self.move_to_viewport_corner()
        
    def move_to_viewport_corner(self):
        """将窗口移动到视口左上角"""
        try:
            viewport = get_viewport_widget()
            viewport_pos = viewport.mapToGlobal(QtCore.QPoint(0, 0))
            self.move(viewport_pos.x() + 10, viewport_pos.y() + 10)
        except:
            pass
        
    def create_ui(self):
        # 滑块（右键切换子帧显示）
        self.wgt_temposlider = SubframeSlider(orientation=QtCore.Qt.Horizontal)
        self.wgt_temposlider.setMinimum(0)
        self.wgt_temposlider.setMaximum(1000)
        self.wgt_temposlider.setValue(1000)
        self.wgt_temposlider.setFixedWidth(80)
        self.wgt_temposlider.setToolTip("拖拽调整播放速度，右键切换子帧显示")
        self.wgt_temposlider.subframe_toggled.connect(self.on_subframe_toggled)
        self.wgt_temposlider.update_handle_style()
        
        # 运动轨迹开关
        self.trail_checkbox = QtWidgets.QCheckBox()
        self.trail_checkbox.setObjectName('trail_checkbox')
        self.trail_checkbox.setToolTip("左键开启/关闭运动轨迹，右键打开设置")
        self.trail_checkbox.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        self.trail_checkbox.mousePressEvent = self.trail_checkbox_mouse_press
        
        # 欧拉按钮 - 当前欧拉（左键计算，右键打开完整工具）
        self.euler_current_btn = QtWidgets.QLabel(self.current_euler)
        self.euler_current_btn.setObjectName('euler_btn')
        self.euler_current_btn.setToolTip("左键计算最佳欧拉，中键转换，右键打开完整工具")
        self.euler_current_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.euler_current_btn.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        self.euler_current_btn.mousePressEvent = self.euler_btn_mouse_press
        
        # 布局
        lyt_main = QtWidgets.QHBoxLayout(self)
        lyt_main.setContentsMargins(6, 5, 6, 5)
        lyt_main.setSpacing(4)
        lyt_main.addWidget(self.wgt_temposlider)
        lyt_main.addWidget(self.trail_checkbox)
        lyt_main.addWidget(self.euler_current_btn)
    
    def create_connections(self):
        self.wgt_temposlider.valueChanged.connect(self.slider_value_changed)

    def set_defaults(self):
        pass

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        bg_color = QtGui.QColor(43, 43, 43, int(255 * self._opacity))
        border_color = QtGui.QColor(61, 61, 61, int(255 * self._opacity))
        
        painter.setBrush(bg_color)
        painter.setPen(QtGui.QPen(border_color, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        
    def slider_value_changed(self):
        val = round(self.wgt_temposlider.value() / 1000, 2)
        self.set_playrate(val)

    def on_subframe_toggled(self, enabled):
        """子帧显示切换回调"""
        val = round(self.wgt_temposlider.value() / 1000, 2)
        self.set_playrate(val)
    
    def set_playrate(self, target_rate):
        if target_rate < 1 and self.wgt_temposlider.subframe_enabled:
            cmds.playbackOptions(maxPlaybackSpeed=target_rate)
            cmds.playbackOptions(playbackSpeed=0)
            cmds.playbackOptions(by=target_rate)
        else:
            cmds.playbackOptions(playbackSpeed=target_rate)
            cmds.playbackOptions(by=target_rate)
    
    # 拖拽移动窗口
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        self._drag_pos = None
    
    # 右键关闭
    def contextMenuEvent(self, event):
        self.close()
        event.accept()
    
    # 滚轮调整透明度
    def wheelEvent(self, event):
        slider_rect = self.wgt_temposlider.geometry()
        if not slider_rect.contains(event.pos()):
            delta = event.angleDelta().y()
            if delta > 0:
                self._opacity = min(1.0, self._opacity + 0.05)
            else:
                self._opacity = max(0.1, self._opacity - 0.05)
            self.update()
            event.accept()
        else:
            super(TempoSlider, self).wheelEvent(event)

    def closeEvent(self, event):
        """关闭窗口时清理"""
        try:
            kill_jobs()
            kill_auto_selection_job()
            if self.trail:
                self.trail.delete_trail()
            if self.settings_window:
                self.settings_window.close()
            if self.euler_window:
                self.euler_window.close()
        except:
            pass
        event.accept()

    # ========== Euler Tool Methods ==========
    
    def trail_checkbox_mouse_press(self, event):
        """处理运动轨迹checkbox的鼠标点击"""
        if event.button() == QtCore.Qt.LeftButton:
            # 切换checkbox状态并触发toggle_trail
            self.trail_checkbox.setChecked(not self.trail_checkbox.isChecked())
            self.toggle_trail()
        elif event.button() == QtCore.Qt.RightButton:
            self.show_settings()
            event.accept()
    
    def euler_btn_mouse_press(self, event):
        """处理欧拉按钮的鼠标点击"""
        if event.button() == QtCore.Qt.LeftButton:
            self.calculate_euler()
        elif event.button() == QtCore.Qt.RightButton:
            self.show_euler_window()
            event.accept()
        elif event.button() == QtCore.Qt.MiddleButton:
            self.switch_to_best_euler()
            event.accept()
    
    def switch_to_best_euler(self):
        """直接转换到推荐欧拉"""
        sel = cmds.ls(sl=True)
        if not sel:
            cmds.warning('请选择物体')
            return
        
        # 如果还没计算过推荐欧拉，先计算
        # Always recompute for the current selection.
        if sel:
            if len(sel) == 1:
                _, self.best_euler, _ = calculate_euler_for_object(sel[0])
            else:
                cmds.warning('请先左键点击计算推荐欧拉')
                return
        
        # 转换到推荐欧拉
        if not switch_euler_order(sel, self.best_euler):
            return
        
        # 更新显示
        self.current_euler = self.best_euler
        self.euler_current_btn.setText(self.best_euler)
        self.euler_current_btn.setStyleSheet("QLabel { color: #ffffff; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        
        cmds.select(sel)
    
    def calculate_euler(self):
        """计算欧拉 - 左键点击"""
        sel = cmds.ls(sl=True)
        if not sel or len(sel) != 1:
            cmds.warning('请选择单个物体')
            return
        
        obj = sel[0]
        current_ro, best_ro, _ = calculate_euler_for_object(obj)
        
        self.current_euler = current_ro
        self.best_euler = best_ro
        
        # 更新按钮显示
        self.euler_current_btn.setText(current_ro)
        
        # 如果当前欧拉和推荐欧拉不同，显示红色
        if current_ro != best_ro:
            self.euler_current_btn.setStyleSheet("QLabel { color: #ff4444; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        else:
            self.euler_current_btn.setStyleSheet("QLabel { color: #ffffff; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        
        cmds.select(sel)
    
    def show_euler_window(self):
        """显示完整欧拉工具窗口"""
        if self.euler_window and self.euler_window.isVisible():
            self.euler_window.close()
            self.euler_window = None
            return
            
        self.euler_window = EulerToolWindow(self)
        pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        self.euler_window.move(pos)
        self.euler_window.show()

    # ========== Motion Trail Methods ==========
    
    def toggle_trail(self):
        """切换轨迹开关"""
        status = self.trail_checkbox.isChecked()
        if status:
            sel = self.trail.define_object()
            if not sel:
                self.trail_checkbox.setChecked(False)
                cmds.warning('需要选择一个物体来追踪')
            else:
                self.trail_on()
                if self.auto_select_enabled:
                    self.auto_selection_setup()
        else:
            self.trail.delete_trail()
            kill_jobs()
            kill_auto_selection_job()

    def trail_on(self):
        """启动轨迹追踪"""
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            self.trail.define_object()
            self.trail.delete_trail()
            self.trail.create_trail_node()
            self.trail.create_dummy_point()
        finally:
            cmds.undoInfo(stateWithoutFlush=True, undoName='MotionTrail')

        self.idle_job = cmds.scriptJob(
            event=['idle', self.update_trail], 
            compressUndo=True, 
            killWithScene=True
        )
        
        cmds.scriptJob(event=['DragRelease', self.auto_process_timeline], compressUndo=True, killWithScene=True)
        cmds.scriptJob(event=['ModelPanelSetFocus', self.auto_process_timeline], compressUndo=True, killWithScene=True)
        cmds.scriptJob(event=['graphEditorChanged', self.auto_process_timeline], compressUndo=True, killWithScene=True)
        cmds.scriptJob(event=['Undo', self.update_trail], compressUndo=True, killWithScene=True)
        cmds.scriptJob(event=['playingBack', self.auto_process_timeline], compressUndo=True, killWithScene=True)
        
        self.auto_process_timeline()

    def update_trail(self):
        """更新轨迹"""
        if not self.trail:
            return
        try:
            if round(time.time() * 1000) % REFRESHRATE != 0:
                return
            toprocess = self.trail.get_range()
            if len(toprocess) != 0:
                self.trail.isIdle()
        except:
            pass

    def auto_process_timeline(self):
        """自动处理时间轴"""
        try:
            cmds.undoInfo(stateWithoutFlush=False)
            self.manual_process_timeline()
        except ValueError:
            self.trail.delete_trail()
            cmds.warning("找不到追踪物体。关闭运动轨迹")
            cmds.evalDeferred(kill_jobs)
        except:
            pass
        finally:
            cmds.undoInfo(stateWithoutFlush=True, undoName='MotionTrail')

    def manual_process_timeline(self):
        """手动处理时间轴"""
        if self.trail and self.trail.tracked_object:
            try:
                range_time = self.trail.prioritize_timeline()
                self.trail.prepare_pointarray(range_time)
            except:
                pass

    def auto_selection_setup(self):
        """设置自动选择"""
        if self.auto_select_enabled:
            cmds.scriptJob(
                event=['SelectionChanged', self.auto_selection_execute],
                compressUndo=True,
            )

    def auto_selection_execute(self):
        """执行自动选择"""
        if self.auto_select_enabled and self.trail_checkbox.isChecked():
            self.trail.define_object()
            self.auto_process_timeline()

    def show_settings(self):
        """显示设置窗口"""
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.close()
            self.settings_window = None
            return
            
        self.settings_window = TrailSettingsWindow(self)
        pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        self.settings_window.move(pos)
        self.settings_window.show()


# ============================================================================
# Euler Tool Window
# ============================================================================

class EulerToolWindow(QtWidgets.QWidget):
    """旋转欧拉完整工具窗口"""
    
    STYLE = """
        QWidget {
            background-color: #3d3d3d;
            color: #cccccc;
            font-size: 11px;
        }
        QPushButton {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            border-radius: 3px;
            color: #ffffff;
            padding: 4px 8px;
        }
        QPushButton:hover {
            background-color: #5a5a5a;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton#calc_btn {
            background-color: #e67e22;
            border-color: #d35400;
        }
        QPushButton#calc_btn:hover {
            background-color: #f39c12;
        }
        QPushButton#switch_btn {
            background-color: #3498db;
            border-color: #2980b9;
        }
        QPushButton#switch_btn:hover {
            background-color: #5dade2;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #5a5a5a;
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }
        QComboBox {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            border-radius: 3px;
            color: #ffffff;
            padding: 3px 6px;
            min-height: 18px;
        }
        QComboBox:hover {
            background-color: #5a5a5a;
        }
        QComboBox::drop-down {
            border: none;
            width: 16px;
        }
        QComboBox QAbstractItemView {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            color: #ffffff;
            selection-background-color: #4a90d9;
        }
        QTextEdit {
            background-color: #2a2a2a;
            border: 1px solid #4a4a4a;
            border-radius: 3px;
            color: #cccccc;
        }
        QLabel#euler_label {
            font-size: 14px;
            font-weight: bold;
            padding: 4px;
            background-color: #2a2a2a;
            border: 1px solid #4a4a4a;
            border-radius: 3px;
        }
    """
    
    def __init__(self, parent_slider):
        super(EulerToolWindow, self).__init__(maya_main_window())
        self.parent_slider = parent_slider
        
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        self.setFixedSize(240, 358)
        self.setStyleSheet(self.STYLE)
        
        self.create_ui()
        self.create_connections()
        
    def create_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        
        # 显示区域 - 当前欧拉和推荐欧拉并排
        display_group = QtWidgets.QGroupBox('欧拉信息')
        display_layout = QtWidgets.QHBoxLayout()
        display_layout.setContentsMargins(6, 10, 6, 6)
        display_layout.setSpacing(10)
        
        # 当前欧拉
        current_layout = QtWidgets.QVBoxLayout()
        current_label = QtWidgets.QLabel('当前欧拉')
        current_label.setAlignment(QtCore.Qt.AlignCenter)
        self.current_euler_label = QtWidgets.QLabel(self.parent_slider.current_euler)
        self.current_euler_label.setObjectName('euler_label')
        self.current_euler_label.setAlignment(QtCore.Qt.AlignCenter)
        current_layout.addWidget(current_label)
        current_layout.addWidget(self.current_euler_label)
        
        # 推荐欧拉
        best_layout = QtWidgets.QVBoxLayout()
        best_label = QtWidgets.QLabel('推荐欧拉')
        best_label.setAlignment(QtCore.Qt.AlignCenter)
        self.best_euler_label = QtWidgets.QLabel(self.parent_slider.best_euler)
        self.best_euler_label.setObjectName('euler_label')
        self.best_euler_label.setAlignment(QtCore.Qt.AlignCenter)
        best_layout.addWidget(best_label)
        best_layout.addWidget(self.best_euler_label)
        
        display_layout.addLayout(current_layout)
        display_layout.addLayout(best_layout)
        display_group.setLayout(display_layout)
        
        # 计算结果
        result_group = QtWidgets.QGroupBox('计算结果')
        result_layout = QtWidgets.QVBoxLayout()
        result_layout.setContentsMargins(6, 10, 6, 6)
        
        self.result_text = QtWidgets.QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFixedHeight(120)
        result_layout.addWidget(self.result_text)
        result_group.setLayout(result_layout)
        
        # 转换设置和按钮合并一行
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(6)
        
        # 目标欧拉下拉框
        self.rot_order_combo = QtWidgets.QComboBox()
        self.rot_order_combo.setFixedWidth(60)
        for ro in ROTATE_ORDERS:
            self.rot_order_combo.addItem(ro)
        
        self.calc_btn = QtWidgets.QPushButton('计算')
        self.calc_btn.setObjectName('calc_btn')
        self.calc_btn.setFixedHeight(24)
        
        self.switch_btn = QtWidgets.QPushButton('转换')
        self.switch_btn.setObjectName('switch_btn')
        self.switch_btn.setFixedHeight(24)
        
        bottom_layout.addWidget(self.rot_order_combo)
        bottom_layout.addWidget(self.calc_btn)
        bottom_layout.addWidget(self.switch_btn)
        
        main_layout.addWidget(display_group)
        main_layout.addWidget(result_group)
        main_layout.addLayout(bottom_layout)
        self.switch_btn.setToolTip('只转换现有旋转关键帧，保持关键帧姿态，不补中间帧；保留原切线类型，由 Maya 自动插值。XYZ 时间不一致时仅在已有关键帧时间补齐三轴。')
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(6)
        self.native_filter_btn = QtWidgets.QPushButton('普通欧拉过滤')
        self.native_filter_btn.setToolTip('直接调用 Maya 原生欧拉过滤菜单流程，使用图表编辑器所选曲线；没有图表曲线选择时处理所选对象。不补偿归零偏移。')
        self.native_filter_btn.setFixedHeight(26)
        self.native_filter_btn.clicked.connect(native_euler_filter_selected)
        self.filter_btn = QtWidgets.QPushButton('安全欧拉过滤')
        self.filter_btn.setFixedHeight(26)
        self.filter_btn.setToolTip('适配归零偏移。过滤全部 XYZ 曲线；保留关键帧姿态，帧间插值会改变。不要对该绑定直接使用原生欧拉过滤。')
        self.filter_btn.clicked.connect(safe_euler_filter_selected)
        filter_row.addWidget(self.native_filter_btn)
        filter_row.addWidget(self.filter_btn)
        main_layout.addLayout(filter_row)
        
    def create_connections(self):
        self.calc_btn.clicked.connect(self.calculate_euler)
        self.switch_btn.clicked.connect(self.switch_euler)

    def calculate_euler(self):
        """计算欧拉"""
        sel = cmds.ls(sl=True)
        if not sel or len(sel) != 1:
            cmds.warning('请选择单个物体')
            return
        
        obj = sel[0]
        current_ro, best_ro, results = calculate_euler_for_object(obj)
        
        # 更新显示
        self.current_euler_label.setText(current_ro)
        self.best_euler_label.setText(best_ro)
        self.result_text.setText(results)
        
        # 同步更新主界面按钮
        self.parent_slider.current_euler = current_ro
        self.parent_slider.best_euler = best_ro
        self.parent_slider.euler_current_btn.setText(current_ro)
        
        # 如果当前欧拉和推荐欧拉不同，显示红色
        if current_ro != best_ro:
            self.parent_slider.euler_current_btn.setStyleSheet("QLabel { color: #ff4444; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        else:
            self.parent_slider.euler_current_btn.setStyleSheet("QLabel { color: #ffffff; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        
        # 设置下拉框为推荐值
        idx = ROTATE_ORDERS.index(best_ro)
        self.rot_order_combo.setCurrentIndex(idx)
        
        cmds.select(sel)
    
    def switch_euler(self):
        """转换欧拉"""
        sel = cmds.ls(sl=True)
        if not sel:
            cmds.warning('请选择物体')
            return
        
        rot_order = self.rot_order_combo.currentText()
        if not switch_euler_order(sel, rot_order):
            return
        
        # 更新显示
        self.current_euler_label.setText(rot_order)
        self.parent_slider.current_euler = rot_order
        self.parent_slider.euler_current_btn.setText(rot_order)
        
        # 转换后重新检查颜色
        if rot_order != self.parent_slider.best_euler:
            self.parent_slider.euler_current_btn.setStyleSheet("QLabel { color: #ff4444; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        else:
            self.parent_slider.euler_current_btn.setStyleSheet("QLabel { color: #ffffff; } QToolTip { color: #000000; background-color: #f0f0f0; }")
        
    def contextMenuEvent(self, event):
        self.close()
        event.accept()
        
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and hasattr(self, '_drag_pos') and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()


# ============================================================================
# Trail Settings Window
# ============================================================================

class TrailSettingsWindow(QtWidgets.QWidget):
    """运动轨迹设置窗口"""
    
    STYLE = """
        QWidget {
            background-color: #3d3d3d;
            color: #cccccc;
            font-size: 11px;
        }
        QPushButton {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            border-radius: 3px;
            color: #ffffff;
            padding: 4px 8px;
        }
        QPushButton:hover {
            background-color: #5a5a5a;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:checked {
            background-color: #4a90d9;
            border-color: #4a90d9;
        }
        QPushButton:disabled {
            background-color: #2a2a2a;
            color: #666666;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #5a5a5a;
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }
        QComboBox {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            border-radius: 3px;
            color: #ffffff;
            padding: 3px 6px;
            min-height: 18px;
        }
        QComboBox:hover {
            background-color: #5a5a5a;
        }
        QComboBox::drop-down {
            border: none;
            width: 16px;
        }
        QComboBox QAbstractItemView {
            background-color: #4a4a4a;
            border: 1px solid #5a5a5a;
            color: #ffffff;
            selection-background-color: #4a90d9;
        }
        QCheckBox {
            spacing: 4px;
        }
        QCheckBox::indicator {
            width: 12px;
            height: 12px;
            border: 1px solid #4a4a4a;
            border-radius: 2px;
            background: #1a1a1a;
        }
        QCheckBox::indicator:checked {
            background: #4a90d9;
            border: 1px solid #4a90d9;
        }
    """

    def __init__(self, parent_slider):
        super(TrailSettingsWindow, self).__init__(maya_main_window())
        self.parent_slider = parent_slider
        
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        self.setFixedSize(220, 280)
        self.setStyleSheet(self.STYLE)
        
        self.create_ui()
        self.create_connections()
        self.refresh_camera_list()
        
    def create_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        
        # 追踪设置
        tracking_group = QtWidgets.QGroupBox('追踪设置')
        tracking_layout = QtWidgets.QVBoxLayout()
        tracking_layout.setContentsMargins(6, 10, 6, 6)
        tracking_layout.setSpacing(4)
        
        self.button_set_tracked = QtWidgets.QPushButton('设置追踪物体')
        self.button_set_tracked.setToolTip("手动设置当前选择的物体为追踪目标")
        
        self.button_auto_select = QtWidgets.QPushButton('自动选择')
        self.button_auto_select.setCheckable(True)
        self.button_auto_select.setChecked(self.parent_slider.auto_select_enabled)
        self.button_auto_select.setToolTip("自动追踪当前选择的物体")
        
        tracking_layout.addWidget(self.button_set_tracked)
        tracking_layout.addWidget(self.button_auto_select)
        tracking_group.setLayout(tracking_layout)
        
        # 更新设置
        update_group = QtWidgets.QGroupBox('更新方式')
        update_layout = QtWidgets.QVBoxLayout()
        update_layout.setContentsMargins(6, 10, 6, 6)
        update_layout.setSpacing(4)
        
        self.checkbox_auto_update = QtWidgets.QCheckBox('自动更新')
        self.checkbox_auto_update.setChecked(True)
        self.checkbox_auto_update.setToolTip("自动更新轨迹显示")
        
        self.button_update = QtWidgets.QPushButton('手动更新')
        self.button_update.setToolTip("手动刷新轨迹")
        
        update_layout.addWidget(self.checkbox_auto_update)
        update_layout.addWidget(self.button_update)
        update_group.setLayout(update_layout)
        
        # 显示设置
        display_group = QtWidgets.QGroupBox('显示设置')
        display_layout = QtWidgets.QFormLayout()
        display_layout.setContentsMargins(6, 10, 6, 6)
        display_layout.setSpacing(4)
        
        self.button_fade = QtWidgets.QPushButton('全部')
        self.button_fade.setFixedWidth(50)
        self.button_fade.setToolTip("点击切换淡化帧数")
        
        camera_layout = QtWidgets.QHBoxLayout()
        camera_layout.setSpacing(4)
        self.combo_camera = QtWidgets.QComboBox()
        self.combo_camera.setToolTip("选择参考相机")
        self.btn_refresh_cam = QtWidgets.QPushButton('↻')
        self.btn_refresh_cam.setFixedWidth(24)
        self.btn_refresh_cam.setToolTip("刷新相机列表")
        camera_layout.addWidget(self.combo_camera, 1)
        camera_layout.addWidget(self.btn_refresh_cam)
        
        display_layout.addRow('淡化帧数:', self.button_fade)
        display_layout.addRow('相机:', camera_layout)
        display_group.setLayout(display_layout)
        
        main_layout.addWidget(tracking_group)
        main_layout.addWidget(update_group)
        main_layout.addWidget(display_group)
        main_layout.addStretch()
        
    def create_connections(self):
        self.button_set_tracked.clicked.connect(self.set_tracked_object)
        self.button_auto_select.clicked.connect(self.toggle_auto_select)
        self.checkbox_auto_update.clicked.connect(self.validate_ui)
        self.button_update.clicked.connect(self.parent_slider.manual_process_timeline)
        self.button_fade.clicked.connect(self.toggle_fade)
        self.btn_refresh_cam.clicked.connect(self.refresh_camera_list)
        self.combo_camera.activated.connect(self.set_camera_reference)

    def refresh_camera_list(self):
        cameras = query_cameras()
        self.combo_camera.clear()
        self.combo_camera.addItem('世界空间')
        for camera in cameras:
            self.combo_camera.addItem(camera)
            
    def set_tracked_object(self):
        if self.parent_slider.trail_checkbox.isChecked():
            objects = self.parent_slider.trail.define_object()
            if objects:
                self.parent_slider.trail.create_dummy_point()
                self.parent_slider.manual_process_timeline()
                
    def toggle_auto_select(self):
        self.parent_slider.auto_select_enabled = self.button_auto_select.isChecked()
        self.button_set_tracked.setEnabled(not self.button_auto_select.isChecked())
        if self.parent_slider.auto_select_enabled and self.parent_slider.trail_checkbox.isChecked():
            self.parent_slider.auto_selection_setup()
        else:
            kill_auto_selection_job()
            
    def validate_ui(self):
        self.button_update.setEnabled(not self.checkbox_auto_update.isChecked())
        
    def toggle_fade(self):
        choices = ['3', '6', '12', '24', '48', '全部']
        current = self.button_fade.text()
        if current == '全部':
            current = 'all'
        try:
            idx = ['3', '6', '12', '24', '48', 'all'].index(current) if current != 'all' else 5
        except:
            idx = 5
        next_idx = (idx + 1) % len(choices)
        new_val = choices[next_idx]
        self.button_fade.setText(new_val)
        
        actual = 'all' if new_val == '全部' else new_val
        self.parent_slider.fade_setting = actual
        if self.parent_slider.trail:
            self.parent_slider.trail.set_faded_frames(actual)
            
    def set_camera_reference(self):
        camera = self.combo_camera.currentText()
        if camera == '世界空间':
            camera = 'world'
        if validate_camera_existance(camera) or camera == 'world':
            self.parent_slider.manual_process_timeline()
            self.parent_slider.trail.set_camera_reference(camera)
            self.set_tracked_object()
        else:
            self.combo_camera.setCurrentIndex(0)
            
    def contextMenuEvent(self, event):
        self.close()
        event.accept()
        
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and hasattr(self, '_drag_pos') and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()


# ============================================================================
# Launch Function
# ============================================================================

def start():
    global _main_window
    
    try:
        if _main_window is not None:
            try:
                kill_jobs()
                kill_auto_selection_job()
                if hasattr(_main_window, 'trail') and _main_window.trail:
                    _main_window.trail.delete_trail()
                if hasattr(_main_window, 'settings_window') and _main_window.settings_window:
                    _main_window.settings_window.close()
                if hasattr(_main_window, 'euler_window') and _main_window.euler_window:
                    _main_window.euler_window.close()
            except:
                pass
            _main_window.close()
            _main_window.deleteLater()
            _main_window = None
    except:
        _main_window = None
    
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.__class__.__name__ == 'TempoSlider':
            try:
                widget.close()
                widget.deleteLater()
            except:
                pass
    
    _main_window = TempoSlider()
    _main_window.show()

def onMayaDroppedPythonFile(*args):
    """Drag into Maya to install a persistent launcher and open this tool."""
    from pathlib import Path
    path = str(Path(__file__).resolve())
    top = mel.eval('$tmp=$gShelfTopLevel')
    shelf = 'RigEulerTools'
    if not cmds.shelfLayout(shelf, exists=True):
        cmds.shelfLayout(shelf, parent=top)
    buttons = [b for b in cmds.shelfLayout(shelf,q=True,childArray=True) or []
               if cmds.objectTypeUI(b)=='shelfButton' and cmds.shelfButton(b,q=True,label=True)=='速度轨迹欧拉']
    options = dict(label='速度轨迹欧拉', image='timeplay.png', imageOverlayLabel='欧拉修复',
                   annotation='播放速度 / 运动轨迹 / 绑定兼容欧拉工具', sourceType='python',
                   command='import runpy\nrunpy.run_path(%r, run_name="__main__")' % path)
    if buttons:
        cmds.shelfButton(buttons[0],e=True,**options)
    else:
        cmds.shelfButton(parent=shelf,**options)
    cmds.saveShelf(shelf, str(Path(cmds.internalVar(userShelfDir=True))/('shelf_'+shelf)).replace('\\','/'))
    cmds.shelfTabLayout(top,e=True,selectTab=shelf)
    start()


if __name__ == '__main__':
    start()
