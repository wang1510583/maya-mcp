"""Sparse camera exchange. Samples are playback data, never implicit authored keys."""
import math
import runpy
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

TR = ('translateX', 'translateY', 'translateZ', 'rotateX', 'rotateY', 'rotateZ')
TRANSFORM = TR + ('scaleX', 'scaleY', 'scaleZ', 'rotateOrder', 'inheritsTransform',
    'rotateAxisX', 'rotateAxisY', 'rotateAxisZ',
    'rotatePivotX', 'rotatePivotY', 'rotatePivotZ',
    'scalePivotX', 'scalePivotY', 'scalePivotZ',
    'rotatePivotTranslateX', 'rotatePivotTranslateY', 'rotatePivotTranslateZ',
    'scalePivotTranslateX', 'scalePivotTranslateY', 'scalePivotTranslateZ',
    'shearXY', 'shearXZ', 'shearYZ')
LENS = ('focalLength', 'horizontalFilmAperture', 'verticalFilmAperture',
    'horizontalFilmOffset', 'verticalFilmOffset', 'filmFit', 'filmFitOffset',
    'lensSqueezeRatio', 'cameraScale', 'nearClipPlane', 'farClipPlane',
    'orthographic', 'orthographicWidth', 'filmRollValue', 'filmRollOrder',
    'filmTranslateH', 'filmTranslateV', 'horizontalRollPivot', 'verticalRollPivot',
    'preScale', 'postScale', 'centerOfInterest')
DISCRETE = {'filmFit', 'filmRollOrder', 'orthographic', 'rotateOrder', 'inheritsTransform'}
IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]


def curve_io():
    return runpy.run_path(str(Path(__file__).with_name('animation_curves.py')))


def chain(shape):
    nodes = [shape]
    while True:
        parents = c.listRelatives(nodes[-1], parent=True, fullPath=True) or []
        if not parents:
            return nodes
        nodes.append(parents[0])


def capture(shape):
    io = curve_io()
    nodes, errors = [], []
    for node in chain(shape):
        curves = {}
        for attr in LENS if c.nodeType(node) == 'camera' else TRANSFORM:
            if not c.attributeQuery(attr, node=node, exists=True):
                continue
            try:
                data = io['capture'](node + '.' + attr)
                # Maya boolean attributes are numeric lens parameters.
                curves[attr] = data
            except ValueError as error:
                errors.append(str(error))
        nodes.append(dict(id=c.ls(node, uuid=True)[0], curves=curves,
                          type=c.nodeType(node)))
    return dict(version=1, nodes=nodes, errors=errors)


def lens(shape):
    return {attr: float(c.getAttr(shape + '.' + attr)) for attr in LENS
            if c.attributeQuery(attr, node=shape, exists=True)}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('相机动画含无效数值')
    return float(value)


def sparse_curve(times, values, discrete=False):
    return dict(times=times, values=values, staticValue=values[0] if values else 0.,
                inTangentType=['linear'] * len(times),
                outTangentType=['step' if discrete else 'linear'] * len(times),
                inAngle=[0.] * len(times), outAngle=[0.] * len(times),
                inWeight=[1.] * len(times), outWeight=[1.] * len(times),
                lock=[False] * len(times), weightLock=[False] * len(times),
                weightedTangents=False, breakdownTimes=[], preInfinity=0, postInfinity=0)


def same_curve(a, b):
    a, b = dict(a), dict(b)
    if a['times'] and b['times']:
        a.pop('staticValue', None)
        b.pop('staticValue', None)
    return a == b


def prepare(package, snapshot, time_scale=1.):
    """Resolve all destinations from trusted snapshot camera UUIDs and live DAG.

    Return complete sparse curves for the importer's common backup/undo transaction.
    Edited world poses support ordinary camera transforms under static rigid parents.
    Animated parents / pivots remain lossless for unedited roundtrips; edited writeback
    is rejected rather than baking hidden per-frame keys or changing the hierarchy.
    """
    edited = package.get('cameraTracks', {})
    rows = package.get('cameras', [])
    if not rows and not edited:
        return {}, 0
    if c.currentUnit(q=True,linear=True) != 'cm' or c.currentUnit(q=True,angle=True) != 'deg' or c.upAxis(q=True,axis=True) != 'y':
        raise ValueError('相机回传要求厘米、度和 Y 向上，请使用导出时单位')
    if not snapshot:
        raise ValueError('相机回传必须提供原工程')
    if package.get('cameraCurveVersion') != 1:
        raise ValueError('旧动画缺少相机原始曲线，请用新版 Maya 重新导出动画')
    if not isinstance(rows, list) or len(rows) > 16 or not isinstance(edited, dict):
        raise ValueError('无效相机动画')
    allowed = {r['id'] for r in snapshot.get('cameras', [])}
    if package.get('cameraTrackVersion', 1) != 1:
        raise ValueError('不支持的相机编辑轨道版本')
    sources = {}
    for row in rows:
        uid = row.get('id')
        if uid not in allowed or uid in sources:
            raise ValueError('动画相机不属于工程或重复')
        sources[uid] = row
    if set(edited) - set(sources):
        raise ValueError('已编辑相机缺少原始曲线，请重新导出匹配动画')
    result, count = {}, 0
    io = curve_io()
    for uid, row in sources.items():
        found = c.ls(uid, long=True) or []
        if len(found) != 1 or c.nodeType(found[0]) != 'camera':
            raise ValueError('源相机 UUID 未唯一匹配')
        shape = found[0]
        nodes = chain(shape)
        source = row.get('sourceCurves', {})
        if source.get('version') != 1 or source.get('errors'):
            raise ValueError('相机包含动画层、约束或不支持的曲线，不能无损回传：' + shape)
        records = source.get('nodes', [])
        if [r.get('id') for r in records] != [c.ls(n, uuid=True)[0] for n in nodes]:
            raise ValueError('相机父级关系已改变，不能回传：' + shape)
        curves = {}
        for node, record in zip(nodes, records):
            attributes = set(LENS if node == shape else TRANSFORM)
            for attr, data in record.get('curves', {}).items():
                if attr not in attributes or not c.attributeQuery(attr, node=node, exists=True):
                    raise ValueError('非法相机曲线通道')
                io['validate'](data)
                curves[node + '.' + attr] = data
        if uid in edited:
            track = edited[uid]
            markers = track.get('keyFrames')
            samples = track.get('samples')
            if not isinstance(markers, list) or not isinstance(samples, list) or not samples or len(samples) > 32000:
                raise ValueError('无效相机编辑轨道')
            times = [finite(f) for f in markers]
            if times != sorted(set(times)) or any(f < 0 or f > 100000 for f in times):
                raise ValueError('无效相机关键帧时间')
            values = {}
            for item in samples:
                t = finite(item['frame'])
                if t in values:
                    raise ValueError('相机采样帧重复')
                values[t] = item['state']
            if set(times) - set(values):
                raise ValueError('相机关键帧缺少姿态')
            camera = nodes[1]
            for attr in TRANSFORM:
                if attr in TR or attr == 'rotateOrder':
                    continue
                data = records[1]['curves'].get(attr)
                expected = 1 if attr.startswith('scale') and attr in ('scaleX', 'scaleY', 'scaleZ') or attr == 'inheritsTransform' else 0
                if data is None or data['times'] or abs(data['staticValue'] - expected) > 1e-8 or abs(c.getAttr(camera + '.' + attr) - expected) > 1e-8:
                    raise ValueError('相机含非标准轴心/缩放，暂不支持编辑回传：' + camera)
            if records[1]['curves']['rotateOrder']['times']:
                raise ValueError('不支持动画旋转顺序')
            if c.listConnections(camera + '.offsetParentMatrix', s=True, d=False) or list(c.getAttr(camera + '.offsetParentMatrix')) != IDENTITY:
                raise ValueError('相机 offsetParentMatrix 非默认，暂不支持编辑回传')
            for parent, record in zip(nodes[2:], records[2:]):
                if any(d['times'] for d in record['curves'].values()) or any(c.keyframe(parent+'.'+a,q=True,tc=True) for a in record['curves']):
                    raise ValueError('动画父级下的相机暂不支持手机编辑回传；原曲线仍可无修改往返')
                for attr, data in record['curves'].items():
                    if abs(float(c.getAttr(parent + '.' + attr)) - data['staticValue']) > 1e-8:
                        raise ValueError('相机父级已改变，请重新导出工程')
                if c.listConnections(parent + '.offsetParentMatrix', s=True, d=False) or list(c.getAttr(parent + '.offsetParentMatrix')) != IDENTITY:
                    raise ValueError('相机父级含非默认 offsetParentMatrix')
            parent = om.MMatrix(c.xform(nodes[2], q=True, ws=True, m=True)) if len(nodes) > 2 else om.MMatrix()
            order = int(records[1]['curves']['rotateOrder']['staticValue'])
            previous = om.MEulerRotation(*[math.radians(records[1]['curves']['rotate' + a]['staticValue']) for a in 'XYZ'], order)
            states = [values[t] for t in times] if times else [values[min(values)]]
            channels = {a: [] for a in TR}
            for state in states:
                world = state['world']
                if len(world) != 16:
                    raise ValueError('无效相机矩阵')
                world = [finite(v) for v in world]
                if max(abs(world[i]) for i in (3, 7, 11)) > 1e-7 or abs(world[15] - 1) > 1e-7:
                    raise ValueError('相机矩阵不是仿射变换')
                if any(abs(sum(world[i*4+k]*world[j*4+k] for k in range(3)) - (1 if i==j else 0)) > 1e-6 for i in range(3) for j in range(3)):
                    raise ValueError('相机矩阵含缩放或剪切')
                local = om.MMatrix(world) * parent.inverse()
                tm = om.MTransformationMatrix(local)
                if max(abs(a - b) for a, b in zip(tm.scale(om.MSpace.kTransform), [1, 1, 1])) > 1e-6 or max(abs(v) for v in tm.shear(om.MSpace.kTransform)) > 1e-6:
                    raise ValueError('相机父级缩放无法用稀疏 TR 关键帧表示')
                euler = tm.rotation(asQuaternion=True).asEulerRotation()
                euler.reorderIt(order)
                euler = euler.closestSolution(previous)
                previous = euler
                pose = list(tm.translation(om.MSpace.kTransform)) + [math.degrees(v) for v in euler]
                for attr, value in zip(TR, pose):
                    channels[attr].append(value)
            for attr, values_ in channels.items():
                curves[camera + '.' + attr] = sparse_curve(times, values_) if times else dict(times=[], values=[], staticValue=values_[0])
            # Lens values accompany poses, so deleted/retimed keys cannot reappear on optics.
            for attr, original in records[0]['curves'].items():
                vals = [finite(s.get('lens', {}).get(attr, original['staticValue'])) for s in states]
                if any(attr not in s.get('lens', {}) for s in states):
                    raise ValueError('旧手机相机键缺少镜头数据，请重新导出并编辑')
                keyed = times and (original['times'] or max(vals) - min(vals) > 1e-8)
                curves[shape + '.' + attr] = sparse_curve(times, vals, attr in DISCRETE) if keyed else dict(times=[], values=[], staticValue=vals[0])
        for plug, data in curves.items():
            io['validate'](data)
            current = io['capture'](plug)
            if (time_scale == 1 or not data["times"]) and same_curve(current, data):
                continue
            node = plug.rsplit('.', 1)[0]
            if c.getAttr(plug, lock=True) or c.referenceQuery(node, isNodeReferenced=True):
                raise ValueError('锁定或引用相机通道：' + plug)
            if plug in result and not same_curve(result[plug], data):
                raise ValueError('多台相机对共享父级的曲线不一致')
            result[plug] = data
        count += 1
    return result, count
