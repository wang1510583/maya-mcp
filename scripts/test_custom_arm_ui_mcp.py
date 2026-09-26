"""Exercise the UI and undo/redo across separate Maya bridge requests."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request


def py(code):
    return request('python',{'code':code})['result']


def main(copy_animation=False, right_side=False):
    ns='_armUI_'+uuid.uuid4().hex[:8]
    snapshot=py("result={'nodes':cmds.ls(long=True),'selection':cmds.ls(sl=True,long=True) or [],'dirty':cmds.file(q=True,modified=True)}")
    fixture=None
    rig=None
    try:
        fixture=py("""from maya_agent.rigs.soft_limb import ui
w=ui._instance or ui.show()
group=cmds.createNode('transform',name="""+repr(ns+'_fixture')+""")
targets=[]
for i,label in enumerate(['z_shoulder','a_elbow','m_wrist']):
 n=cmds.createNode('transform',name="""+repr(ns)+"""+'_'+label,parent=group)
 cmds.setAttr(n+'.translate',(-1 if """+repr(right_side)+""" else 1)*(30+i*5),3 if i==1 else 0,0)
 targets.append(cmds.ls(n,long=True)[0])
cmds.select(clear=True)
for n in targets:cmds.select(n,add=True)
w.refresh()
assert w.targets==targets,('initial order',w.targets,targets)
w.reverse()
w.refresh()
assert w.targets==list(reversed(targets)),('reverse order',w.targets,targets)
w.reverse()
cmds.textFieldGrp(w.namespace,edit=True,text="""+repr(ns)+""")
cmds.checkBox(w.copy_animation,edit=True,value="""+repr(copy_animation)+""")
cmds.checkBox(w.right_side,edit=True,value="""+repr(right_side)+""")
w.toggle_animation()
if """+repr(copy_animation)+""":
 for i,n in enumerate(targets):
  for attr,delta in [('translateZ',i+1),('rotateY',30+i*5)]:
   value=cmds.getAttr(n+'.'+attr)
   cmds.setKeyframe(n,at=attr,t=1.25,v=value)
   cmds.setKeyframe(n,at=attr,t=5.25,v=value+delta)
 cmds.floatFieldGrp(w.frame_bounds,edit=True,value1=1.25,value2=5.25)
 cmds.floatFieldGrp(w.sample_step,edit=True,value1=.5)
frame=cmds.currentTime(q=True)
cmds.currentTime(frame+.001);cmds.currentTime(frame)
result={'root':group,'targets':targets,'matrices':{n:cmds.xform(n,q=True,ws=True,m=True) for n in targets}}
result['edges']={n+'.'+a:cmds.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in targets for a in ['translateZ','rotateY']}
""")
        motion=py('old=cmds.currentTime(q=True)\nresult={}\nfor f in [1.25,2.75,5.25]:\n cmds.currentTime(f)\n result[str(f)]={n:cmds.xform(n,q=True,ws=True,m=True) for n in '+repr(fixture['targets'])+'}\ncmds.currentTime(old)') if copy_animation else {}
        rig=py('from maya_agent.rigs.soft_limb import ui\nresult=ui._instance.create()')
        assert rig is not None,py('from maya_agent.rigs.soft_limb import ui\nresult=cmds.scrollField(ui._instance.status,q=True,text=True)')
        assert [m['target'] for m in rig['target_mapping']]==fixture['targets']
        side='R' if right_side else 'L'
        assert rig['side']==side
        assert rig['controls']['middle_fk']==ns+':armFK_'+side+'1'
        py('assert cmds.getAttr('+repr(rig['root']+'.armSide')+')=='+repr(side)+'\nresult=True')
        if copy_animation:assert rig['animation_transfer']['sample_count']==9
        assert request('undo',{'expected_chunk':'MayaMCP_Python'})['undone']=='MayaMCP_Python'
        py('assert not cmds.objExists('+repr(rig['root'])+')\n'+
           'for n,m in '+repr(fixture['matrices'])+'.items():\n'+
           ' assert cmds.objExists(n)\n assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-5\nresult=True')
        py('assert all(cmds.connectionInfo(dst,sourceFromDestination=True)==src for dst,src in '+repr(fixture['edges'])+'.items())\nresult=True')
        redo_response=request('python',{'code':'cmds.redo()\nresult=True'})
        if redo_response.get('stderr') or redo_response.get('stdout'):print(json.dumps(redo_response,ensure_ascii=True))
        check=py('result={"missing":[n for n in '+repr(rig['nodes'])+' if not cmds.objExists(n)],"expressions":cmds.ls(type="expression"),"metadata":cmds.ls(type="blindDataTemplate"),"redo_name":cmds.undoInfo(q=True,redoName=True)}')
        assert not check['missing'],check
        if copy_animation:
            py('old=cmds.currentTime(q=True)\nfor f,poses in '+repr(motion)+'.items():\n cmds.currentTime(float(f))\n for n,m in poses.items():\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-4\ncmds.currentTime(old)\nresult=True')
        py('import maya.mel as mel\nns='+repr(ns+':')+'\n'+
           'cmds.select('+repr(rig['controls']['middle_fk'])+',replace=True)\n'+
           'assert mel.eval(\'EasyGameRig4_0_e8f0c3b3e6300189aca31ae83320ec92("*recalculate_node*")\')==ns+"recalculate_node"\n'+
           'before=cmds.xform('+repr(fixture['targets'][2])+',q=True,ws=True,t=True)\n'+
           'cmds.setAttr('+repr(rig['controls']['end_locator']+'.translateY')+',.5)\n'+
           'after=cmds.xform('+repr(fixture['targets'][2])+',q=True,ws=True,t=True)\n'+
           'assert sum((a-b)**2 for a,b in zip(before,after))>.01\n'+
           'assert max(abs(a-b) for a,b in zip(after,cmds.xform(ns+"joint3",q=True,ws=True,t=True)))<1e-5\nresult=True')
        report={'ui_order_and_reverse':True,'ui_create':True,'undo_targets_preserved':True,
                'redo_nodes_restored':True,'redo_live_solver_and_easy_rig_discovery':True,
                'copy_animation':copy_animation,'side':side,'undo_original_connections_restored':True}
    finally:
        cleanup=''
        if rig:
            cleanup+='for n in cmds.ls('+repr(ns+':*')+',type="constraint",long=True) or []:\n if cmds.objExists(n):cmds.delete(n)\n'
            cleanup+='for n in sorted(cmds.ls('+repr(ns+':*')+',long=True) or [],key=lambda n:n.count("|"),reverse=True):\n if cmds.objExists(n):cmds.delete(n)\n'
            cleanup+='if cmds.namespace(exists='+repr(ns)+'):cmds.namespace(removeNamespace='+repr(ns)+')\n'
        fixture_root=fixture['root'] if fixture else ns+'_fixture'
        cleanup+='if cmds.objExists('+repr(fixture_root)+'):cmds.delete('+repr(fixture_root)+')\n'
        cleanup+='cmds.select('+repr(snapshot['selection'])+',replace=True) if '+repr(bool(snapshot['selection']))+' else cmds.select(clear=True)\n'
        cleanup+='assert set(cmds.ls(long=True))==set('+repr(snapshot['nodes'])+')\n'
        cleanup+='from maya_agent.rigs.soft_limb import ui\nw=ui._instance\nw.last_result=None\nw.refresh()\n'
        cleanup+='cmds.textFieldGrp(w.namespace,edit=True,text="customArm")\n'
        cleanup+='cmds.checkBox(w.copy_animation,edit=True,value=False)\nw.toggle_animation()\n'
        cleanup+='cmds.checkBox(w.right_side,edit=True,value=False)\n'
        cleanup+='cmds.scrollField(w.status,edit=True,text="就绪。请按肩、肘、腕依次选择三个目标，再点击创建。")\n'
        cleanup+='cmds.file(modified='+repr(snapshot['dirty'])+')\nresult=True'
        py(cleanup)
    report['original_node_set_preserved']=True
    out=ROOT/('outputs/custom-arm-tests/'+('right-' if right_side else '')+('animation-' if copy_animation else '')+'ui-mcp.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main('--animation' in sys.argv,'--right' in sys.argv)
