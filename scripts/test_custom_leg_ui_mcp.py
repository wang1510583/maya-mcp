"""UI create, setup, animation and undo/redo across independent bridge requests."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request


def py(code):return request('python',{'code':code})['result']


def main(animation=False):
    ns='_legUI_'+uuid.uuid4().hex[:8]
    snapshot=py("result={'nodes':cmds.ls(long=True),'selection':cmds.ls(sl=True,long=True) or [],'frame':cmds.currentTime(q=True),'auto':cmds.autoKeyframe(q=True,state=True)}")
    rig=None
    fixture=None
    try:
        fixture=py('ns='+repr(ns)+'''
from maya_agent.rigs.soft_leg import ui
w=ui._instance or ui.show()
cmds.autoKeyframe(state=False)
root=cmds.createNode('transform',name=ns+'_fixture')
targets=[]
for i,p in enumerate([(-25,12,0),(-25,7,1),(-25,2,0),(-25,.4,3)]):
 n=cmds.createNode('transform',name=ns+'_target'+str(i),parent=root)
 cmds.setAttr(n+'.translate',*p);targets.append(cmds.ls(n,long=True)[0])
cmds.select(clear=True)
for n in targets:cmds.select(n,add=True)
w.refresh();assert w.targets==targets
w.reverse();assert w.targets==list(reversed(targets))
w.reverse();assert w.targets==targets
cmds.textFieldGrp(w.namespace,e=True,text=ns)
cmds.checkBox(w.right_side,e=True,value=True)
cmds.checkBox(w.copy_animation,e=True,value='''+repr(animation)+''')
w.toggle_animation()
if '''+repr(animation)+''':
 for i,n in enumerate(targets):
  for a,d in [('translateX',.5+i*.2),('rotateY',20+i*5)]:
   value=cmds.getAttr(n+'.'+a)
   cmds.setKeyframe(n,at=a,t=1.25,v=value);cmds.setKeyframe(n,at=a,t=5.25,v=value+d)
cmds.floatFieldGrp(w.frame_bounds,e=True,value1=1.25,value2=5.25)
cmds.floatFieldGrp(w.sample_step,e=True,value1=.5)
frame=cmds.currentTime(q=True)
cmds.currentTime(frame+.001);cmds.currentTime(frame)
result={'root':root,'targets':targets,'matrices':{n:cmds.xform(n,q=True,ws=True,m=True) for n in targets},
        'edges':{n+'.'+a:cmds.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in targets for a in ['translateX','rotateY']}}
''')
        motion=py('old=cmds.currentTime(q=True)\nresult={}\nfor f in [1.25,2.75,5.25]:\n cmds.currentTime(f)\n result[str(f)]={n:cmds.xform(n,q=True,ws=True,m=True) for n in '+repr(fixture['targets'])+'}\ncmds.currentTime(old)') if animation else {}
        rig=py('from maya_agent.rigs.soft_leg import ui\nresult=ui._instance.create()')
        assert rig is not None,py('result=cmds.scrollField(ui._instance.status,q=True,text=True)')
        assert rig['side']=='R' and rig['controls']['heel']==ns+':heel_R1'
        assert request('undo',{'expected_chunk':'MayaMCP_Python'})['undone']=='MayaMCP_Python'
        py('assert not cmds.objExists('+repr(rig['root'])+'),"root survived undo"\n'+
           'for n,m in '+repr(fixture['matrices'])+'.items():\n assert cmds.objExists(n),("target removed",n)\n assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-5,("pose changed",n)\n'+
           'assert all(cmds.connectionInfo(dst,sourceFromDestination=True)==src for dst,src in '+repr(fixture['edges'])+'.items()),"curve connection changed"\nresult=True')
        py('cmds.redo()\nresult=True')
        py('assert all(cmds.objExists(n) for n in '+repr(rig['nodes'])+')\nresult=True')
        if animation:
            assert rig['animation_transfer']['sample_count']==9
            py('old=cmds.currentTime(q=True)\nfor f,poses in '+repr(motion)+'.items():\n cmds.currentTime(float(f))\n for n,m in poses.items():\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-4,(n,f)\ncmds.currentTime(old)\nresult=True')
        if rig:
            pivot_key='toe' if animation else 'heel'
            py('from maya_agent.rigs.soft_leg import ui\nw=ui._instance\nw.refresh_rigs('+repr(ns)+')\nw.toggle_mode(True)\nw.refresh_mode()\nw.pick('+repr(pivot_key)+')\n'+
               'assert cmds.checkBox(w.mode,q=True,value=True)\ncmds.move(0,0,-.7,r=True,ws=True)\nresult=True')
            before=py('result={n:cmds.xform(n,q=True,ws=True,m=True) for n in '+repr(rig['joints'])+'}')
            old_pivot=py('result=cmds.xform('+repr(rig['controls'][pivot_key])+',q=True,ws=True,rp=True)')
            py('from maya_agent.rigs.soft_leg import ui\nresult=ui._instance.toggle_mode(False)')
            committed=py('result=cmds.xform('+repr(rig['controls'][pivot_key])+',q=True,ws=True,rp=True)')
            assert abs(committed[2]-old_pivot[2]+.7)<1e-5
            assert request('undo',{'expected_chunk':'MayaMCP_Python'})['undone']=='MayaMCP_Python'
            py('assert cmds.getAttr('+repr(rig['root']+'.adjustmentMode')+')\nresult=True')
            py('cmds.redo()\nresult=True')
            py('assert not cmds.getAttr('+repr(rig['root']+'.adjustmentMode')+')\n'+
               'for n,m in '+repr(before)+'.items():\n assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-5\n'+
               'from maya_agent.rigs.soft_leg import ui\nw=ui.show();w.refresh_rigs('+repr(ns)+')\nassert not cmds.checkBox(w.mode,q=True,value=True)\nresult=True')
        if animation:
            py('old=cmds.currentTime(q=True)\nfor f,poses in '+repr(motion)+'.items():\n cmds.currentTime(float(f))\n for n,m in poses.items():\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-4,(n,f)\ncmds.currentTime(old)\nresult=True')
        result=dict(passed=True,side='R',ui_selection_order=True,undo_targets_and_curves_preserved=True,
                    redo_nodes=True,animation=animation,adjustment_undo_redo_and_ui_reopen=True)
    finally:
        code='from maya_agent.rigs.soft_leg import cleanup\n'
        if rig and animation:
            code+='backup='+repr(rig['animation_transfer']['source_animation_backup'])+'\n'
            code+='if cmds.objExists(backup):\n pairs=cmds.listConnections(backup+".sourceCurves",s=True,d=False,p=True,c=True) or []\n for dst,src in zip(pairs[::2],pairs[1::2]):cmds.disconnectAttr(src,dst)\n'
        code+='if cmds.namespace(exists='+repr(ns)+'):cleanup('+repr(ns)+')\n'
        code+='if cmds.objExists('+repr(ns+'_fixture')+'):cmds.delete('+repr(ns+'_fixture')+')\n'
        if fixture:
            code+='for n in '+repr(list({src.split('.')[0] for src in fixture['edges'].values() if src}))+':\n if cmds.objExists(n):cmds.delete(n)\n'
        code+='cmds.currentTime('+repr(snapshot['frame'])+')\ncmds.autoKeyframe(state='+repr(snapshot['auto'])+')\n'
        code+='cmds.select('+repr(snapshot['selection'])+',r=True) if '+repr(bool(snapshot['selection']))+' else cmds.select(clear=True)\n'
        code+='expected=set('+repr(snapshot['nodes'])+')\nassert set(cmds.ls(long=True))==expected,(list(set(cmds.ls(long=True))-expected),list(expected-set(cmds.ls(long=True))))\n'
        code+='from maya_agent.rigs.soft_leg import ui\nw=ui.show()\nresult=True'
        py(code)
    out=ROOT/'outputs/leg-study'/('animation-ui-tests.json' if animation else 'static-ui-tests.json')
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main('--animation' in sys.argv)
