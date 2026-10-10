"""Anatomical reference frames, independent of Maya/Max joint axis conventions.

A single aim vector cannot determine roll. Use the limb bend plane, torso
direction, or foot sole plane as a second axis. All points are Maya Y-up.
"""
import math


def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(v):
    length=math.sqrt(dot(v,v))
    if length<1e-8:raise ValueError('参考姿态存在重合关节或无法确定的方向。')
    return tuple(x/length for x in v)


def frame(aim,secondary):
    x=unit(aim)
    y=unit(sub(secondary,tuple(v*dot(x,secondary) for v in x)))
    z=cross(x,y)
    return [*x,0.,*y,0.,*z,0.,0.,0.,0.,1.]


def frames(points):
    """Return one full orientation per semantic bone; never mutate input.

    Foot forward is projected onto the reference floor, rather than the
    sloping ankle-to-ball segment. This avoids pitching a flat foot merely
    because Biped and the model have different ankle heights.
    """
    right=unit(sub(points['L Thigh'],points['R Thigh']))
    up=(0.,1.,0.)
    forward=unit(cross(right,up))
    out={}
    spine=['Pelvis','Spine','Spine1','Spine2','Neck','Head']
    for i,name in enumerate(spine):
        if name not in points:continue
        a,b=(name,spine[i+1]) if i<len(spine)-1 else (spine[i-1],name)
        if b not in points:a,b=spine[i-1],name
        out[name]=frame(sub(points[b],points[a]),right)
    for side in ('L','R'):
        clavicle=side+' Clavicle'
        if clavicle in points:
            out[clavicle]=frame(sub(points[side+' UpperArm'],points[clavicle]),up)
        for labels in [('UpperArm','Forearm','Hand'),('Thigh','Calf','Foot')]:
            names=[side+' '+n for n in labels]
            if not all(n in points for n in names):continue
            a,b,c=[points[n] for n in names]
            upper,lower=sub(b,a),sub(c,b)
            normal=cross(unit(upper),unit(lower))
            if dot(normal,normal)<1e-8:
                normal=cross(unit(upper),forward)
                if dot(normal,normal)<1e-8:normal=cross(unit(upper),up)
            out[names[0]]=frame(upper,normal)
            out[names[1]]=frame(lower,normal)
            out[names[2]]=out[names[1]][:]
        foot,toe=side+' Foot',side+' Toe0'
        if foot in points and toe in points:
            direction=sub(points[toe],points[foot])
            out[foot]=out[toe]=frame((direction[0],0.,direction[2]),up)
    return out
