import copy
import math
import pytest
from maya_agent.rigs.bip_reference import frames, frame, dot, cross


def points():
    p={'Pelvis':[0,100,0],'Spine':[0,110,0],'Spine1':[0,125,0],
       'Spine2':[0,140,0],'Neck':[0,155,0],'Head':[0,165,0]}
    for side,sign in [('L',1),('R',-1)]:
        for label,v in {'Clavicle':[3,150,0],'UpperArm':[16,148,-3],
                'Forearm':[36,132,-5],'Hand':[55,120,5],
                'Thigh':[9,98,0],'Calf':[11,54,2],'Foot':[13,12,0],
                'Toe0':[13,3,17]}.items():
            p[side+' '+label]=[v[0]*sign,v[1],v[2]]
    return p


def test_full_frames_orthonormal_and_right_handed_for_both_sides():
    p=points();old=copy.deepcopy(p);out=frames(p)
    assert p==old and set(out)==set(p)
    for m in out.values():
        x,y,z=m[:3],m[4:7],m[8:11]
        assert dot(x,x)==pytest.approx(1)
        assert dot(y,y)==pytest.approx(1)
        assert dot(z,z)==pytest.approx(1)
        assert dot(x,y)==pytest.approx(0,abs=1e-12)
        assert cross(x,y)==pytest.approx(z)


def test_different_ankle_heights_do_not_pitch_the_sole():
    p=points();a=frames(p)
    p['L Foot'][1]=22;p['R Toe0'][1]=1
    b=frames(p)
    for side in ('L','R'):
        assert a[side+' Foot']==pytest.approx(b[side+' Foot'])
        assert b[side+' Foot'][4:7]==pytest.approx([0,1,0])


def test_elbow_plane_determines_roll_even_with_unchanged_upper_arm_aim():
    p=points();p['L UpperArm']=[10,150,0];p['L Forearm']=[30,150,0]
    p['L Hand']=[45,150,10];a=frames(p)['L UpperArm']
    p['L Hand']=[45,140,0];b=frames(p)['L UpperArm']
    assert a[:3]==b[:3]
    assert abs(dot(a[4:7],b[4:7]))<1e-12


def test_translation_scale_and_heading_do_not_change_anatomical_alignment():
    p=points();a=frames(p);angle=.74
    def yaw(v):return [v[0]*math.cos(angle)+v[2]*math.sin(angle),v[1],-v[0]*math.sin(angle)+v[2]*math.cos(angle)]
    q={n:[2*x+b for x,b in zip(yaw(v),[38,4,-12])] for n,v in p.items()}
    for n,m in frames(q).items():
        for offset in [0,4,8]:assert m[offset:offset+3]==pytest.approx(yaw(a[n][offset:offset+3]),abs=1e-12)


def test_straight_limb_has_deterministic_fallback():
    p=points();p['L UpperArm']=[10,150,0];p['L Forearm']=[30,150,0];p['L Hand']=[50,150,0]
    assert all(math.isfinite(v) for v in frames(p)['L UpperArm'])


def test_degenerate_reference_rejected():
    with pytest.raises(ValueError):frame([0,0,0],[0,1,0])
    with pytest.raises(ValueError):frame([0,1,0],[0,2,0])
