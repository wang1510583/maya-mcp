import copy
import pytest
from max_mcp.biped_retarget import PAIRS, validate_profile


def profile():
    names=sorted({n for pair in PAIRS for n in pair})
    return dict(version=1,points={n:[i,i*.5,100-i*2] for i,n in enumerate(names)})


def test_profile_is_read_only_and_needs_no_max():
    p=profile();before=copy.deepcopy(p)
    assert validate_profile(p)==before['points']
    assert p==before


@pytest.mark.parametrize('bad',[None,[],[0,1],[0,float('nan'),2],[float('inf'),1,2]])
def test_invalid_point_rejected(bad):
    p=profile();p['points']['L Foot']=bad
    with pytest.raises(ValueError,match='L Foot'):validate_profile(p)


def test_missing_body_part_rejected():
    p=profile();del p['points']['Neck']
    with pytest.raises(ValueError,match='Neck'):validate_profile(p)


@pytest.mark.parametrize('a,b',[('L Foot','L Toe0'),('Spine','Spine1'),('L Thigh','R Thigh')])
def test_degenerate_lengths_or_width_rejected(a,b):
    p=profile();p['points'][b]=p['points'][a][:]
    with pytest.raises(ValueError,match='Coincident'):validate_profile(p)
