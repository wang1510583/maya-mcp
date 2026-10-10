import copy
import pytest
from maya_agent.rigs.bip_retarget import read_data


def data():
    return dict(up_axis='Z',fps=30,reference={'Bip001 Pelvis':[]},
                samples=[dict(frame=0,bones={}),dict(frame=.5,bones={}),dict(frame=1,bones={})])


def test_fractional_samples_are_retained():
    source=data();before=copy.deepcopy(source)
    assert read_data(source)==before
    assert source==before


@pytest.mark.parametrize('fps',[0,-1,float('nan'),float('inf')])
def test_invalid_fps_rejected(fps):
    source=data();source['fps']=fps
    with pytest.raises(ValueError):read_data(source)


@pytest.mark.parametrize('frames',[[1,0],[0,0],[0,float('nan')],[0,float('inf')]])
def test_nonmonotonic_or_nonfinite_time_rejected(frames):
    source=data();source['samples']=[dict(frame=f,bones={}) for f in frames]
    with pytest.raises(ValueError):read_data(source)


def test_missing_figure_reference_rejected():
    source=data();del source['reference']
    with pytest.raises(ValueError,match='Figure'):read_data(source)


def test_empty_motion_rejected():
    source=data();source['samples']=[]
    with pytest.raises(ValueError):read_data(source)
