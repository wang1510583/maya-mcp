"""Reversible, same-frame audit; retains existing keys and unkeyed user poses."""
import json,math
import maya.cmds as c
from maya_agent.rigs import live_edit


def verify_character(root):
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();selection=c.ls(sl=True,long=True) or []
    reports=[]
    try:
        c.autoKeyframe(state=False)
        for key,p in rig['parts'].items():
            if not key.startswith('arm') or not c.objExists(p['root']+'.liveAlignmentData'):continue
            data=json.loads(c.getAttr(p['root']+'.liveAlignmentData'));ctrl=data['controls']
            plugs=[n+'.'+a for n in ctrl.values() for a in live_edit.TR]
            snapshot=live_edit._snapshot(plugs)
            pose={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
            try:
                fixed={n:c.getAttr(n+'.translate')[0] for r,n in ctrl.items() if r!='shoulder_fk'}
                hand=ctrl['end_fk'];c.select(hand)
                global_locked=c.objExists(hand+'.global') and c.getAttr(hand+'.global')>.001
                movement=None
                if not global_locked:
                    c.setToolTo('moveSuperContext')
                    start=c.xform(hand,q=True,ws=True,t=True)
                    shoulder=c.xform(ctrl['shoulder_fk'],q=True,ws=True,t=True)
                    delta=[(a-b)*.02 for a,b in zip(shoulder,start)]
                    target=[a+b for a,b in zip(start,delta)]
                    live_edit.before_drag('verify');c.move(*delta,hand,r=True,ws=True);live_edit.update_drag();live_edit.after_drag('verify')
                    movement=math.dist(target,c.xform(p['joints'][2],q=True,ws=True,t=True))
                    assert movement<1e-4,(key,movement)
                elbow=c.xform(p['joints'][1],q=True,ws=True,t=True)
                c.setToolTo('RotateSuperContext')
                live_edit.before_drag('verify');c.rotate(0,0,7,hand,r=True,os=True);live_edit.after_drag('verify')
                hold=math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True))
                assert hold<1e-5,(key,hold)
                translation=max(abs(a-b) for n,t in fixed.items() for a,b in zip(t,c.getAttr(n+'.translate')[0]))
                assert translation<1e-8,(key,translation)
                assert snapshot[1]==live_edit._snapshot(plugs)[1],'User keys changed'
            finally:
                if live_edit._gesture:live_edit.after_drag('cleanup')
                live_edit._restore(snapshot)
            error=max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
            assert error<1e-5,(key,'restore',error)
            reports.append(dict(part=key,move_error=movement,global_locked=bool(global_locked),
                                wrist_rotation_elbow_error=hold,child_translation_change=translation,restored_pose_error=error))
        return reports
    finally:
        c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(selection,r=True) if selection else c.select(cl=True)
