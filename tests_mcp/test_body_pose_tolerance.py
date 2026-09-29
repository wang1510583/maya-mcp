import math
import pytest

from maya_agent.rigs.body_direction_match import _check_pose


def matrices():
    m=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
    return {'joint':m}, {'joint':m.copy()}


@pytest.mark.parametrize('distance', [0.0000255155, 0.019, 0.02])
def test_position_inside_tolerance(distance):
    before,after=matrices();after['joint'][12]=distance
    assert _check_pose(before,after)==distance


@pytest.mark.parametrize('xyz', [(0.02001,0,0), (0.015,0.015,0)])
def test_position_limit_uses_total_distance(xyz):
    before,after=matrices();after['joint'][12:15]=xyz
    with pytest.raises(RuntimeError):_check_pose(before,after)


def test_rotation_keeps_strict_check():
    before,after=matrices();angle=0.001
    after['joint'][0]=after['joint'][5]=math.cos(angle)
    after['joint'][1]=math.sin(angle);after['joint'][4]=-math.sin(angle)
    with pytest.raises(RuntimeError):_check_pose(before,after)


def test_meter_scene_converts_to_centimeters():
    before,after=matrices();after['joint'][12]=0.00019
    _check_pose(before,after,100)
    after['joint'][12]=0.00021
    with pytest.raises(RuntimeError):_check_pose(before,after,100)


def test_invalid_matrix_is_rejected():
    before,after=matrices();after['joint'][12]=float('nan')
    with pytest.raises(RuntimeError):_check_pose(before,after)
