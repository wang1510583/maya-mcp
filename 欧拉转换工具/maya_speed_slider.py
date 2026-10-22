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
__version__ = "0.0.10-keypose"
# Local modification: rig-aware Euler conversion preserving authored key poses.
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

def gimbal_tolerance(obj):
    """计算万向锁程度 (0-1)"""
    rotate_order = ROTATE_ORDERS[cmds.getAttr(obj + '.rotateOrder')]
    mid_value = cmds.getAttr(obj + '.r' + rotate_order[1])
    return abs(((mid_value + 90) % 180) - 90) / 90

def test_all_rotate_orders_at_frame(obj, dup):
    """在当前帧测试所有旋转顺序的万向锁程度（与原版一致）"""
    # 同步复制体的旋转值和旋转顺序
    for axis in ['rx', 'ry', 'rz']:
        cmds.setAttr(dup + '.' + axis, cmds.getAttr(obj + '.' + axis))
    cmds.setAttr(dup + '.rotateOrder', cmds.getAttr(obj + '.rotateOrder'))
    
    tolerances = []
    for roo in ROTATE_ORDERS:
        # 使用preserve=True保持世界空间旋转，自动重算欧拉角
        cmds.xform(dup, preserve=True, rotateOrder=roo)
        tolerances.append(gimbal_tolerance(dup))
    return tolerances

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

def _euler_context(obj):
    import json
    nodes = cmds.ls(obj, long=True) or []
    if len(nodes) != 1 or cmds.nodeType(nodes[0]) not in ('transform', 'joint'):
        raise ValueError('请选择唯一的控制器或变换物体：' + obj)
    obj = nodes[0]
    source, root, offsets = obj, None, [0.0] * 3
    zero_text, offset_plugs = None, []
    if cmds.objExists(obj + '.zeroChannelData'):
        zero_text = cmds.getAttr(obj + '.zeroChannelData')
        data = json.loads(zero_text)
        # Validate the actual additive graph rather than limiting body parts.
        if not all('rotate'+a in data.get('offsets', {}) for a in 'XYZ'):
            raise ValueError('此控制器未开放三轴旋转（例如膝盖方向或参数控制器）：' + obj)
        source, root = data['source'], data['root']
        if not cmds.isConnected(obj+'.rotateOrder', source+'.rotateOrder'):
            raise ValueError('此节点不是当前绑定的旋转输入控制器：' + obj)
        offsets = [data['offsets'].get('rotate' + a, 0.0) for a in 'XYZ']
        # Read the actual angle inputs, rather than assuming stored units.
        for i, axis in enumerate('XYZ'):
            edge = data['edges'].get('rotate' + axis)
            if not edge or not cmds.isConnected(edge, source + '.rotate' + axis):
                raise ValueError('零位旋转连接已改变：' + obj)
            add = edge.rsplit('.', 1)[0]
            if (cmds.nodeType(add) != 'animBlendNodeAdditiveDA'
                    or cmds.getAttr(add + '.weightA') != 1
                    or cmds.getAttr(add + '.weightB') != 1
                    or not cmds.isConnected(obj + '.rotate' + axis, add + '.inputA')):
                raise ValueError('零位旋转偏移结构不匹配：' + obj)
            offsets[i] = cmds.getAttr(add + '.inputB')
            offset_plugs.append(add + '.inputB')
    if cmds.objExists(source + '.liveInput'):
        links = cmds.listConnections(source + '.liveInput', s=True, d=False) or []
        if len(links) != 1:
            raise ValueError('找不到实际旋转输入：' + obj)
        source = links[0]
    if not cmds.objExists(source):
        raise ValueError('绑定输入不存在：' + source)
    if cmds.objExists(source + '.liveRotationData'):
        raise ValueError('请先结束旋转操作或升级旧旋转层：' + obj)
    watched = [source]
    if root and cmds.objExists(root + '.liveAlignmentData'):
        live = json.loads(cmds.getAttr(root + '.liveAlignmentData'))
        watched.extend(live['targets'].values())
        # Result joints are authoritative. Internal IK end markers can have
        # different unused orientations after an equivalent FK Euler rewrite.
        if cmds.objExists(root + '.armTargets'):
            watched.extend(json.loads(cmds.getAttr(root + '.armTargets')))
    if root:
        ancestor = root
        while ancestor:
            if cmds.objExists(ancestor + '.integratedRigData'):
                rig = json.loads(cmds.getAttr(ancestor + '.integratedRigData'))
                for part in rig['parts'].values():
                    # Chest/hips/neck can move downstream parts: validate the
                    # complete character output, not just the selected part.
                    watched.extend(part.get('joints', []))
                    watched.extend(m['target'] for m in part.get('target_mapping', []))
                    watched.extend(m['target'] for m in part.get('original_target_mapping', []))
                break
            ancestor = (cmds.listRelatives(ancestor, p=True, f=True) or [None])[0]
    return dict(obj=obj, source=source, root=root, offsets=offsets,
                zero_text=zero_text, offset_plugs=offset_plugs,
                watched=sorted(set(cmds.ls(watched, long=True) or [])))


def _euler_angles(context):
    import maya.api.OpenMaya as om
    unit = om.MAngle.uiUnit()
    source = context['source']
    return om.MEulerRotation(*[om.MAngle(v, unit).asRadians()
                              for v in cmds.getAttr(source + '.rotate')[0]],
                            cmds.getAttr(source + '.rotateOrder'))


def _euler_reorder(rotation, order, previous=None):
    """Keep matrix equivalence even at singularities / distant Euler branches."""
    import math
    import maya.api.OpenMaya as om
    result = rotation.reorder(order)
    if previous is not None:
        candidate = result.closestSolution(previous)
        error = max(abs(a-b) for a, b in zip(rotation.asMatrix(), candidate.asMatrix()))
        if error < 1e-10:
            result = candidate
        else:
            result = om.MEulerRotation(*[v + round((p-v)/(2*math.pi))*2*math.pi
                                        for v, p in zip(result, previous)], order)
    # q and -q have the same rigid transform, but the spine's continuous
    # weighted-quaternion graph uses the authored lift/sign. Preserve it too.
    if sum(a*b for a,b in zip(rotation.asQuaternion(),result.asQuaternion())) < 0:
        reference = list(previous) if previous is not None else list(result)
        candidates = []
        for axis in range(3):
            for turn in (-2*math.pi, 2*math.pi):
                values = list(result)
                values[axis] += turn
                candidates.append(values)
        values = min(candidates, key=lambda values:sum((a-b)**2 for a,b in zip(values,reference)))
        result = om.MEulerRotation(*values,order)
    return result


def calculate_euler_for_object(obj):
    """Analyze actual rotations; do not duplicate a result-following control."""
    context = _euler_context(obj)
    old_time = cmds.currentTime(q=True)
    current = ROTATE_ORDERS[cmds.getAttr(context['obj'] + '.rotateOrder')]
    times = get_euler_keyframes(context['obj']) or [old_time]
    totals = [0.0] * 6
    def tolerances():
        import math
        rotation = _euler_angles(context)
        return [abs(((math.degrees(list(rotation.reorder(i))['xyz'.index(order[1])])
                       + 90) % 180) - 90) / 90 for i, order in enumerate(ROTATE_ORDERS)]
    try:
        for frame in times:
            cmds.currentTime(frame)
            totals = [a+b for a, b in zip(totals, tolerances())]
        cmds.currentTime(old_time)
        current_values = tolerances()
    finally:
        cmds.currentTime(old_time)
    averages = [v / len(times) for v in totals]
    best = ROTATE_ORDERS[averages.index(min(averages))]
    lines = ['分析了 %d 个关键帧（实际旋转输入）' % len(times)]
    for avg, cur, order in zip(averages, current_values, ROTATE_ORDERS):
        lines.append('%s: 平均%d%% 当前帧%d%%%s' %
                     (order, avg*100, cur*100, ' [推荐]' if order == best else ''))
    lines.append('\n综合推荐: ' + best)
    return current, best, '\n'.join(lines)


def _euler_validate(expected, tolerance=1e-5):
    maximum = 0.0
    for frame, poses in expected.items():
        cmds.currentTime(frame)
        for node, matrix in poses.items():
            actual = cmds.xform(node, q=True, ws=True, matrix=True)
            error = max(abs(a-b) for a, b in zip(matrix, actual))
            maximum = max(maximum, error)
            if error > tolerance:
                raise RuntimeError('关键帧姿态核对失败：%s，帧 %g，矩阵误差 %.8g' %
                                   (node, frame, error))
    return maximum


def switch_euler_order(objects, rot_order):
    """Preserve authored key poses without constraining result-following handles.

    Rotation order is global, so convert ALL authored times (including fractional
    keys), not just a highlighted range. Interpolation between keys may change.
    Old curves remain untouched until validation passes. One undo restores them.
    """
    import json
    import maya.api.OpenMaya as om
    if not objects:
        cmds.warning('请选择物体')
        return False
    order = ROTATE_ORDERS.index(rot_order)
    contexts = [_euler_context(obj) for obj in dict.fromkeys(objects)]
    key_objects = [ctx['obj'] for ctx in contexts]
    contexts = [ctx for ctx in contexts if cmds.getAttr(ctx['obj']+'.rotateOrder') != order]
    if not contexts:
        return dict(changed=0, max_error=0.0)
    if not cmds.undoInfo(q=True, state=True):
        raise ValueError('请先开启 Maya 撤销，再转换欧拉顺序。')
    for ctx in contexts:
        obj = ctx['obj']
        if cmds.referenceQuery(obj, isNodeReferenced=True):
            raise ValueError('请在绑定源文件中转换，当前控制器来自引用：' + obj)
        order_plug = obj + '.rotateOrder'
        if cmds.getAttr(order_plug, lock=True) or cmds.connectionInfo(order_plug, sfd=True):
            raise ValueError('旋转顺序已锁定或受驱动：' + obj)
        ctx['old_order'] = cmds.getAttr(order_plug)
        rest = _euler_reorder(om.MEulerRotation(*[om.MAngle(v, om.MAngle.uiUnit()).asRadians()
                                   for v in ctx['offsets']], ctx['old_order']), order)
        ctx['new_offsets'] = [om.MAngle(v).asUnits(om.MAngle.uiUnit()) for v in rest]
        for plug in ctx['offset_plugs']:
            if cmds.getAttr(plug, lock=True) or cmds.connectionInfo(plug, sfd=True):
                raise ValueError('零位偏移已锁定或受驱动：' + plug)
        ctx['channels'] = []
        for axis in 'XYZ':
            plug = obj + '.rotate' + axis
            incoming = cmds.connectionInfo(plug, sfd=True)
            if cmds.getAttr(plug, lock=True) or (incoming and
                    cmds.nodeType(incoming.rsplit('.', 1)[0]) != 'animCurveTA'):
                raise ValueError('旋转通道锁定、约束或存在动画层，未作修改：' + plug)
            ctx['channels'].append(dict(plug=plug, incoming=incoming,
                                        value=cmds.getAttr(plug), copy=None))
    old_time = cmds.currentTime(q=True)
    selection = cmds.ls(sl=True, long=True) or []
    auto = cmds.autoKeyframe(q=True, state=True)
    modified = cmds.file(q=True, modified=True)
    times = sorted(set(cmds.keyframe(key_objects, q=True, tc=True) or []))
    animated = bool(times)
    times = times or [old_time]
    watched = sorted({n for ctx in contexts for n in ctx['watched']})
    expected, replacements = {}, []
    committed = False
    cmds.undoInfo(openChunk=True, chunkName='EulerOrderPreserveKeyPoses')
    try:
        cmds.autoKeyframe(state=False)
        for ctx in contexts:
            ctx['converted'] = []
        # Capture every object before touching any parent or child curve.
        for frame in times:
            cmds.currentTime(frame)
            expected[frame] = {n: cmds.xform(n, q=True, ws=True, matrix=True) for n in watched}
            for ctx in contexts:
                previous = ctx.get('previous')
                rotation = _euler_reorder(_euler_angles(ctx), order, previous)
                ctx['previous'] = rotation
                ctx['converted'].append([om.MAngle(v).asUnits(om.MAngle.uiUnit())-offset
                                         for v, offset in zip(rotation, ctx['new_offsets'])])
        for ctx in contexts:
            cmds.setAttr(ctx['obj']+'.rotateOrder', order)
            if ctx['zero_text']:
                data = json.loads(ctx['zero_text'])
                for axis, plug, value in zip('XYZ', ctx['offset_plugs'], ctx['new_offsets']):
                    cmds.setAttr(plug, value)
                    data['offsets']['rotate'+axis] = value
                plug = ctx['obj']+'.zeroChannelData'
                cmds.setAttr(plug, lock=False)
                cmds.setAttr(plug, json.dumps(data), type='string', lock=True)
            for i, channel in enumerate(ctx['channels']):
                plug, incoming = channel['plug'], channel['incoming']
                if animated:
                    if incoming:
                        curve = cmds.duplicate(incoming.rsplit('.', 1)[0],
                                               inputConnections=True, name='eulerConverted#')[0]
                    else:
                        curve = cmds.createNode('animCurveTA', name='eulerConverted#', skipSelect=True)
                        cmds.connectAttr((cmds.ls(type='time') or ['time1'])[0]+'.outTime', curve+'.input')
                    channel['copy'] = curve
                    replacements.append(curve)
                    cmds.connectAttr(curve+'.output', plug, force=True)
                    for frame, angles in zip(times, ctx['converted']):
                        cmds.setKeyframe(curve, t=frame, v=angles[i])
                else:
                    cmds.setAttr(plug, ctx['converted'][0][i])
        maximum = _euler_validate(expected)
        # Keep shared curves; delete only originals no longer driving anything.
        originals = {ch['incoming'].rsplit('.', 1)[0] for ctx in contexts
                     for ch in ctx['channels'] if ch['incoming']}
        for curve in originals:
            if not cmds.listConnections(curve, s=False, d=True):
                cmds.delete(curve)
        committed = True
        return dict(changed=len(contexts), key_times=times, max_error=maximum)
    except Exception:
        # Originals have not been edited. Restore edges / constants explicitly;
        # do not undo an outer caller's transaction or the user's previous edit.
        for ctx in contexts:
            cmds.setAttr(ctx['obj']+'.rotateOrder', ctx['old_order'])
            if ctx['zero_text']:
                for plug, value in zip(ctx['offset_plugs'], ctx['offsets']):
                    cmds.setAttr(plug, value)
                plug = ctx['obj']+'.zeroChannelData'
                cmds.setAttr(plug, lock=False)
                cmds.setAttr(plug, ctx['zero_text'], type='string', lock=True)
            for ch in ctx['channels']:
                if ch['incoming']:
                    cmds.connectAttr(ch['incoming'], ch['plug'], force=True)
                else:
                    edge = cmds.connectionInfo(ch['plug'], sfd=True)
                    if edge:
                        cmds.disconnectAttr(edge, ch['plug'])
                    cmds.setAttr(ch['plug'], ch['value'])
        for curve in replacements:
            if cmds.objExists(curve):
                cmds.delete(curve)
        raise
    finally:
        cmds.currentTime(old_time)
        cmds.select(selection, r=True) if selection else cmds.select(clear=True)
        cmds.autoKeyframe(state=auto)
        if not committed:
            cmds.file(modified=modified)
        cmds.undoInfo(closeChunk=True)



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
        if self.best_euler == '---':
            if len(sel) == 1:
                try:
                    _, self.best_euler, _ = calculate_euler_for_object(sel[0])
                except Exception as exc:
                    cmds.warning("欧拉分析未完成：" + str(exc))
                    return
            else:
                cmds.warning('请先左键点击计算推荐欧拉')
                return
        
        # 转换到推荐欧拉
        try:
            switch_euler_order(sel, self.best_euler)
        except Exception as exc:
            cmds.warning("欧拉转换未完成：" + str(exc))
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
        try:
            current_ro, best_ro, _ = calculate_euler_for_object(obj)
        except Exception as exc:
            cmds.warning("欧拉分析未完成：" + str(exc))
            return
        
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
        self.setFixedSize(220, 320)
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
        self.switch_btn.setToolTip("保留全部原关键帧姿态（含小数帧）；帧间插值可能变化。支持一次撤销。")
        self.switch_btn.setFixedHeight(24)
        
        bottom_layout.addWidget(self.rot_order_combo)
        bottom_layout.addWidget(self.calc_btn)
        bottom_layout.addWidget(self.switch_btn)
        
        main_layout.addWidget(display_group)
        main_layout.addWidget(result_group)
        main_layout.addLayout(bottom_layout)
        
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
        try:
            current_ro, best_ro, results = calculate_euler_for_object(obj)
        except Exception as exc:
            cmds.warning("欧拉分析未完成：" + str(exc))
            return
        
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
        try:
            switch_euler_order(sel, rot_order)
        except Exception as exc:
            cmds.warning("欧拉转换未完成：" + str(exc))
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

def onMayaDroppedPythonFile(*_):
    start()


if __name__ == "__main__":
    start()
