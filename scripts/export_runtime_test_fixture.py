"""Export a disposable test character; preserve the artist's open scene."""
import json,runpy,uuid
from pathlib import Path
import maya.cmds as c


def run():
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import arm_ik
    output=Path(__file__).resolve().parents[1]/'outputs'/'runtime-assistant-test';output.mkdir(parents=True,exist_ok=True)
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(uuid=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    rig=None;prefix='runtimeTest_'+uuid.uuid4().hex[:7];arm_ik._busy=True;c.autoKeyframe(state=False)
    poses={n:c.xform(n,q=True,ws=True,m=True) for n in c.ls(type='transform',long=True)+c.ls(type='joint',long=True)}
    try:
        fixture,parts=suite['fixture'](prefix,True,shoulders=True)
        for key,p in parts.items():
            if key.startswith('arm'):p.update(space_wrist=True,space_upper_arm=True,live_alignment=True)
            if key.startswith('leg'):p.update(space_foot=True,space_knee=True,live_alignment=True)
        c.currentTime(1);rig=build(parts,namespace=prefix,zero_controls=True)
        nodes=[]
        for uid in set(c.ls(uuid=True))-before:nodes+=c.ls(uid,long=True) or []
        c.select(nodes,r=True,noExpand=True)
        filename=output/'character.ma'
        c.file(str(filename),force=True,options='v=0;',type='mayaAscii',exportSelected=True,preserveReferences=False)
        (output/'rig.json').write_text(json.dumps(rig),encoding='utf-8')
        return dict(file=str(filename),nodes=len(nodes))
    finally:
        if rig:suite['remove'](rig)
        for uid in set(c.ls(uuid=True))-before:
            found=c.ls(uid,long=True) or []
            if found:c.delete(found)
        c.currentTime(frame);c.select(selection,r=True) if selection else c.select(clear=True)
        c.autoKeyframe(state=auto);arm_ik._busy=busy
        assert set(c.ls(uuid=True))==before
        assert max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-8
        c.file(modified=modified)
