import math
import pytest
from maya_agent.rigs.bip_sparse import fit_slopes,key_schedule,group_schedules,group_for_part


def test_linear_and_constant_fit():
    assert fit_slopes([(x,2*x+4) for x in range(11)],0,10,4,24)==pytest.approx((2,2))
    assert fit_slopes([(x,3) for x in range(11)],0,10,3,3)==pytest.approx((0,0))


def test_cubic_fit_recovers_end_derivatives():
    # y = x^3 on [0,2] has independently known endpoint derivatives 0 and 12.
    samples=[(x/10,(x/10)**3) for x in range(21)]
    assert fit_slopes(samples,0,2,0,8)==pytest.approx((0,12),abs=1e-6)


def test_no_interior_data_falls_back_to_linear():
    assert fit_slopes([],0,10,3,13)==pytest.approx((1,1))


def motion():
    return dict(fps=30,source_keys=dict(times=[0,9,10,19,22,28,33]),
                samples=[dict(frame=x*.5) for x in range(147)])


def test_preserve_exact_source_time_union_no_end_key():
    d=motion()
    assert key_schedule(d,30,0)==[0,9,10,19,22,28,33]


def test_fps_conversion_and_output_offset():
    assert key_schedule(motion(),24,10)==pytest.approx([10,17.2,18,25.2,27.6,32.4,36.4])


def test_missing_metadata_requires_recapture():
    d=motion();del d['source_keys']
    with pytest.raises(ValueError,match='原始关键帧'):key_schedule(d,30,0)


def test_fractional_key_requires_exact_sample():
    d=motion();d['source_keys']['times']=[0,1.25,10]
    with pytest.raises(ValueError,match='缺少'):key_schedule(d,30,0)
    d['samples'].append(dict(frame=1.25));d['samples'].sort(key=lambda s:s['frame'])
    assert key_schedule(d,30,0)==[0,1.25,10]


def test_empty_or_invalid_key_times_rejected():
    for times in ([],[float('nan')],[float('inf')]):
        d=motion();d['source_keys']['times']=times
        with pytest.raises(ValueError):key_schedule(d,30,0)


def grouped_motion():
    d=motion();d['root']='Bip001'
    tracks={'Pelvis':[0,10],'Spine':[0,10,19],'Spine1':[0,10,19],'Spine2':[0,10,19],
            'COM Vertical':[0,9],'COM Horizontal':[9],'COM Turn':[],
            'Neck':[0,10,28],'Head':[0,10,28]}
    for side in ('L','R'):
        for name in ('Clavicle','UpperArm','Forearm','Hand'):tracks[side+' '+name]=[0,10]
        for name in ('Thigh','Calf','Foot','Toe0'):tracks[side+' '+name]=[0,10,22,33] if side=='L' else [0,10]
    d['source_keys']['tracks']={'Bip001 '+name:frames for name,frames in tracks.items()}
    return d


def test_six_groups_do_not_share_body_head_or_opposite_leg_keys():
    groups=group_schedules(grouped_motion(),30,0,
        ['body','head','shoulder_L','shoulder_R','arm_L','arm_R','leg_L','leg_R'])
    assert groups==dict(body=[0,9,10,19],head=[0,10,28],arm_L=[0,10],arm_R=[0,10],
                        leg_L=[0,10,22,33],leg_R=[0,10])


def test_shoulder_keys_stay_on_their_own_arm():
    d=grouped_motion();d['source_keys']['tracks']['Bip001 L Clavicle']=[0,3,10]
    g=group_schedules(d,30,0,['shoulder_L','arm_L','arm_R'])
    assert g==dict(arm_L=[0,3,10],arm_R=[0,10])
    assert group_for_part('shoulder_R')=='arm_R'


def test_no_keys_in_group_does_not_borrow_root_keys():
    d=grouped_motion()
    for n in ('Neck','Head'):d['source_keys']['tracks']['Bip001 '+n]=[]
    assert group_schedules(d,30,0,['head'])=={'head':[]}


def test_groups_require_track_metadata_not_just_union():
    with pytest.raises(ValueError,match='分部位'):group_schedules(motion(),30,0,['body'])
