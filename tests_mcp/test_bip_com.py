import copy
import pytest
from maya_agent.rigs.bip_retarget import com_source


def data():
    return dict(root='Bip001',reference={'Bip001':'com_ref','Bip001 Pelvis':'pelvis_ref'},
        samples=[dict(frame=0,bones={'Bip001':'com_pose','Bip001 Pelvis':'different_pelvis_pose'})])


def test_root_is_never_substituted_with_pelvis():
    d=data();before=copy.deepcopy(d)
    assert com_source(d)=='Bip001'
    assert d==before


@pytest.mark.parametrize('missing',['root','reference','sample'])
def test_old_or_incomplete_com_capture_requires_recapture(missing):
    d=data()
    if missing=='root':del d['root']
    elif missing=='reference':del d['reference']['Bip001']
    else:del d['samples'][0]['bones']['Bip001']
    with pytest.raises(ValueError,match='Bip001 总根'):com_source(d)


def test_namespace_or_custom_biped_name():
    d=data();d['root']='HeroBip'
    d['reference']['HeroBip']=d['reference'].pop('Bip001')
    d['samples'][0]['bones']['HeroBip']=d['samples'][0]['bones'].pop('Bip001')
    assert com_source(d)=='HeroBip'
