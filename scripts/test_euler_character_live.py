"""Verify all additive zero-control parts without editing the user's rig."""
import json
import runpy
import traceback
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

BASE=Path(__file__).resolve().parents[1]


def run(extra_modes=False):
    from maya_agent.rigs.integrated import build
    core=runpy.run_path(str(BASE/'scripts'/'test_euler_tool_live.py'))
    suite=runpy.run_path(str(BASE/'scripts'/'test_integrated_rig_live.py'))
    curves=runpy.run_path(str(BASE/'scripts'/'test_external_constraints_live.py'))['_curves']
    api=core['load_tool']()
    before=set(c.ls(uuid=True));original=curves(c.ls(type='animCurve') or [])
    sel=c.ls(sl=True,l=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    report={'cases':[],'warnings':[]};rig=fixture=None
    def output(message,kind,*_):
        if kind in (om.MCommandMessage.kWarning,om.MCommandMessage.kError) and len(report['warnings'])<12:
            report['warnings'].append(message)
    cb=om.MCommandMessage.addCommandOutputCallback(output)
    c.autoKeyframe(state=False)
    try:
        prefix='_eulerCharacter_'+uuid.uuid4().hex[:8]
        fixture,parts=suite['fixture'](prefix,True,shoulders=True)
        original_targets=[n for p in parts.values() for n in p['targets']]
        for key,p in parts.items():
            p.update(space_head=True,space_chest=True,space_upper_arm=True,space_wrist=True,space_foot=True,space_knee=True)
            if key.startswith(('arm','leg')):p['live_alignment']=True
        c.currentTime(1)
        rig=build(parts,namespace=prefix,zero_controls=True)
        groups={}
        for key,p in rig['parts'].items():
            groups[key]=[n for n in dict.fromkeys(p['zero_controls'].values())
                         if all('rotate'+a in json.loads(c.getAttr(n+'.zeroChannelData'))['offsets'] for a in 'XYZ')]
        watched=original_targets+[n for p in rig['parts'].values() for n in p.get('joints',[])]
        for key,nodes in groups.items():
            for i,n in enumerate(nodes):
                c.currentTime(2.25)
                for axis,delta in zip('XYZ',(11,-8,6)):
                    c.setKeyframe(n,at='rotate'+axis,t=2.25,v=c.getAttr(n+'.rotate'+axis)+delta+i)
        # A full turn must retain the quaternion sign used by spine blending.
        hips=rig['parts']['body']['zero_controls']['hips']
        c.currentTime(2.25)
        c.setKeyframe(hips,at='rx',t=2.25,v=c.getAttr(hips+'.rx')+360)
        all_controls=[n for group in groups.values() for n in group]
        times=sorted(set(c.keyframe(all_controls,q=True,tc=True) or []))
        baseline=core['poses'](watched,times)
        report['controls']={key:len(nodes) for key,nodes in groups.items()}
        report['continuous_body']=c.objExists(rig['parts']['body']['controls']['hips']+'.continuousBodyRotationData')
        scenarios=[(key,nodes,None) for key,nodes in groups.items()]
        if extra_modes:
            body=rig['parts']['body']['zero_controls']
            scenarios=[('body_%d_%d'%(drive,follow),groups['body'],
                        {body['hips']+'.bodyDrive':drive,body['chest']+'.global':follow})
                       for drive,follow in ((0,1),(1,0),(1,1))]
            scenarios.extend((key+'_global',groups[key],
                              {rig['parts'][key]['zero_controls'][role]+'.global':1})
                             for key,role in (('head','head'),('leg_L','foot'),('leg_R','foot')))
            scenarios.append(('mixed',all_controls,{}))
        for key,nodes,modes in scenarios:
            if modes is not None:
                for plug,value in modes.items():c.setAttr(plug,value)
                baseline=core['poses'](watched,times)
            for order in (('zxy','zyx','xyz') if extra_modes else api['ROTATE_ORDERS']):
                row={'part':key,'order':order}
                saved=curves(c.ls(type='animCurve') or [])
                data={n:c.getAttr(n+'.zeroChannelData') for n in nodes}
                try:
                    result=api['switch_euler_order'](nodes,order)
                    row['error']=core['error'](baseline)
                    assert row['error']<1e-5,row
                    if result['changed']:
                        c.undo()
                        assert curves(saved)==saved,'undo curves'
                        assert {n:c.getAttr(n+'.zeroChannelData') for n in nodes}==data
                        assert core['error'](baseline)<1e-5
                        c.redo();assert core['error'](baseline)<1e-5;c.undo()
                    row['passed']=True
                except Exception as exc:
                    row['passed']=False;row['error_text']=str(exc)
                    if core['error'](baseline)>1e-5:raise
                report['cases'].append(row)
                (BASE/'outputs'/'euler-character-progress.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        report['passed']=all(row['passed'] for row in report['cases'])
    except Exception:
        report['passed']=False;report['traceback']=traceback.format_exc()
    finally:
        om.MMessage.removeCallback(cb)
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        for uid in set(c.ls(uuid=True))-before:
            nodes=c.ls(uid,l=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):c.delete(nodes[0])
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        report['original_nodes_preserved']=set(c.ls(uuid=True))==before
        report['original_curves_preserved']=curves(original)==original
        c.file(modified=modified)
        (BASE/'outputs'/('euler-character-modes.json' if extra_modes else 'euler-character-regression.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
