"""Original Maya curves travel alongside playback samples, never as sampled keys."""
import copy
import math

ATTRS = ('rotateX', 'rotateY', 'rotateZ', 'translateX', 'translateY', 'translateZ')
TANGENTS = ('inTangentType', 'outTangentType', 'inAngle', 'outAngle',
            'inWeight', 'outWeight', 'lock', 'weightLock')


def capture(plug):
    import maya.cmds as c
    drivers = c.listConnections(plug, source=True, destination=False) or []
    if any(c.nodeType(n) not in ('animCurveTA', 'animCurveTL', 'animCurveTU') for n in drivers):
        raise ValueError('不能保留非普通动画曲线: ' + plug)
    times = c.keyframe(plug, q=True, tc=True) or []
    result = dict(times=times, values=c.keyframe(plug, q=True, vc=True) or [],
                  staticValue=c.getAttr(plug))
    if times:
        result.update({f: c.keyTangent(plug, q=True, **{f: True}) for f in TANGENTS})
        result['weightedTangents'] = bool(c.keyTangent(plug, q=True, weightedTangents=True)[0])
        result['breakdownTimes'] = c.keyframe(plug, q=True, breakdown=True, tc=True) or []
        curve = drivers[0]
        for field in ('preInfinity', 'postInfinity', 'rotationInterpolation'):
            if c.attributeQuery(field, node=curve, exists=True):
                result[field] = c.getAttr(curve + '.' + field)
    validate(result)
    return result


def validate(curve):
    times, values = curve['times'], curve['values']
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise ValueError('原始曲线时间和值数量不匹配')
    def finite(v):
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
            raise ValueError('原始曲线含无效数值')
    for v in times + values + [curve['staticValue']]: finite(v)
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('原始曲线时间必须递增')
    if times:
        for field in TANGENTS:
            data = curve[field]
            if not isinstance(data, list) or len(data) != len(times):
                raise ValueError('原始曲线切线数据不完整: ' + field)
            if field in ('inAngle', 'outAngle', 'inWeight', 'outWeight'):
                for v in data: finite(v)
        if not isinstance(curve['weightedTangents'], bool): raise ValueError('无效切线权重开关')
        allowed = {'fixed', 'linear', 'flat', 'smooth', 'spline', 'step', 'slow', 'fast', 'clamped',
                   'plateau', 'stepnext', 'auto', 'autoease', 'automix', 'autocustom'}
        if any(t not in allowed for f in ('inTangentType', 'outTangentType') for t in curve[f]):
            raise ValueError('不支持的原始切线类型')
        if 'step' in curve['inTangentType']: raise ValueError('入切线不能为阶跃')
        for field in ('preInfinity', 'postInfinity'):
            if curve.get(field) not in (0, 1, 3, 4, 5): raise ValueError('无效曲线延伸模式')
        if curve.get('rotationInterpolation', 1) != 1: raise ValueError('当前仅支持独立欧拉旋转曲线，请先转换旋转插值模式')
        if any(t not in times for t in curve.get('breakdownTimes', [])): raise ValueError('无效中间关键帧')


def prepare(package, base):
    """Build sparse import rows. Curves use absolute local values; samples use deltas.

    Unedited original inputs are restored exactly, including independent axis times
    and static channels. Edited controls use their mobile keys, including empty
    tracks after deleting the last key. Old files retain their legacy behavior.
    """
    if 'curvePayloadVersion' not in package:
        return package.get('keys', []), {}, set()
    if type(package['curvePayloadVersion']) is not int or package['curvePayloadVersion'] != 1:
        raise ValueError('不支持的原始曲线版本，请更新两端软件')
    original = package.get('sourceCurves')
    if not isinstance(original, dict): raise ValueError('缺少原始曲线')
    edited = set(package.get('autoEaseControls', []))
    if edited and (package.get('interpolation') != 'maya-auto-ease' or package.get('curvePolicy') != 'replace-auto-ease-tracks'):
        raise ValueError('已编辑轨道必须使用手机曲线替换策略')
    channels = package.get('editedChannels', {})
    rows, specs, present = {}, {}, set()
    def put(frame, uid, attr, value):
        rows.setdefault(frame, {}).setdefault(uid, {})[attr] = value
    for row in package.get('keys', []):
        for uid, pose in row.get('values', {}).items():
            if uid not in original and uid not in edited:
                raise ValueError('播放采样缺少对应的原始曲线: ' + uid)
            if uid in edited:
                # The phone stores already-pruned authored tracks for these IDs.
                if (uid, row['frame']) in present: raise ValueError('同一控制器关键帧重复')
                present.add((uid, row['frame']))
                rows.setdefault(row['frame'], {})[uid] = copy.deepcopy(pose)
    static = set()
    for uid, tracks in original.items():
        if not isinstance(tracks, dict): raise ValueError('无效原始曲线表')
        if uid in edited: continue
        for attr, curve in tracks.items():
            if attr not in ATTRS: raise ValueError('非法原始曲线通道')
            validate(curve)
            specs[uid, attr] = curve
            offset = base[uid][attr] if package.get('valueSpace') == 'snapshot-local-delta' else 0
            if curve['times']:
                for time, value in zip(curve['times'], curve['values']): put(time, uid, attr, value - offset)
            else:
                put(package.get('frame', 0), uid, attr, curve['staticValue'] - offset)
                static.add((uid, attr))
    for uid in edited:
        if not any(key[0] == uid for key in present):
            attrs = channels.get(uid, list(original.get(uid, {})))
            if not attrs: raise ValueError('已清空轨道缺少通道表: ' + uid)
            for attr in attrs:
                if attr not in ATTRS: raise ValueError('非法已编辑通道')
                put(package.get('frame', 0), uid, attr, 0 if package.get('valueSpace') == 'snapshot-local-delta' else base.get(uid, {}).get(attr, 0))
                static.add((uid, attr))
    return [dict(frame=t, values=v) for t, v in sorted(rows.items())], specs, static


def restore_tangents(plug, data, time_scale):
    import maya.cmds as c
    if not data['times']: return
    c.keyTangent(plug, e=True, weightedTangents=data['weightedTangents'])
    # Unlock both handles while restoring asymmetric fixed tangents.
    c.keyTangent(plug, e=True, lock=False)
    if data['weightedTangents']: c.keyTangent(plug, e=True, weightLock=False)
    for i, time in enumerate(data['times']):
        span = (time * time_scale, time * time_scale)
        flags = {field: data[field][i] for field in ('inAngle', 'outAngle', 'inWeight', 'outWeight')}
        if time_scale != 1:
            for side in ('in', 'out'):
                angle = math.radians(flags[side + 'Angle'])
                x, y = math.cos(angle) * time_scale, math.sin(angle)
                flags[side + 'Angle'] = math.degrees(math.atan2(y, x))
                flags[side + 'Weight'] *= math.hypot(x, y)
        if not data['weightedTangents']:
            flags.pop('inWeight'); flags.pop('outWeight')
        c.keyTangent(plug, e=True, time=span, **flags)
        c.keyTangent(plug, e=True, time=span, inTangentType=data['inTangentType'][i], outTangentType=data['outTangentType'][i])
        c.keyTangent(plug, e=True, time=span, lock=data['lock'][i])
        if data['weightedTangents']: c.keyTangent(plug, e=True, time=span, weightLock=data['weightLock'][i])
        c.keyframe(plug, e=True, time=span, breakdown=time in data.get('breakdownTimes', []))
    curve = c.listConnections(plug, source=True, destination=False, type='animCurve')[0]
    for field in ('preInfinity', 'postInfinity'):
        if field in data and c.attributeQuery(field, node=curve, exists=True):
            c.setAttr(curve + '.' + field, data[field])
