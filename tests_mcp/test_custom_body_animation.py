import pytest
from maya_agent.rigs.custom_body.animation import frame_range


def test_fractional_endpoint_and_single_frame():
    assert frame_range(1.25, 3.5) == [1.25, 2.25, 3.25, 3.5]
    assert frame_range(-2, -2) == [-2]
    assert len(frame_range(0, 10000)) == 10001


@pytest.mark.parametrize('args', [(2,1,1),(0,1,0),(0,1,-1),(0,float('inf'),1),
                                  (True,2,1),(0,10001,1),(0,10000.5,1),('0',2,1)])
def test_invalid_ranges(args):
    with pytest.raises(ValueError): frame_range(*args)
