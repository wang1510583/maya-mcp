"""UI callback -> independent MCP undo/redo, plus scene-preserving guardrail checks."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request


def py(code):
    return request('python', {'code':code})['result']


def main():
    prefix='_CBR_UI_'+uuid.uuid4().hex[:8]
    snapshot=py("result={'nodes':cmds.ls(long=True),'selection':cmds.ls(selection=True,long=True) or [],'dirty':cmds.file(query=True,modified=True),'frame':cmds.currentTime(query=True),'poses':{n:cmds.xform(n,query=True,worldSpace=True,matrix=True) for n in cmds.ls(type='transform',long=True)+cmds.ls(type='joint',long=True)}}")
    rig=None
    root=None
    try:
        fixture=py("""from maya_agent.rigs.custom_body import ui
window=ui._instance or ui.show()
root=cmds.createNode('transform',name="""+repr(prefix+'_targets')+""")
nodes=[]
for index,suffix in enumerate(['z_waist','a_middle','m_chest']):
    node=cmds.createNode('joint',name="""+repr(prefix)+"""+'_'+suffix,parent=root)
    cmds.setAttr(node+'.translate',20+index*.4,index*2.3,0,type='double3')
    nodes.append(cmds.ls(node,long=True)[0])
cmds.select(clear=True)
for node in nodes: cmds.select(node,add=True)
cmds.checkBox(window.selection_mode,edit=True,value=True)
window.toggle_selection()
assert window.targets==nodes
# Exercise list reordering, independent of alphabetical naming or DAG order.
cmds.textScrollList(window.target_list,edit=True,selectIndexedItem=2)
window.move(-1)
assert window.targets==[nodes[1],nodes[0],nodes[2]]
window.move(1)
assert window.targets==nodes
cmds.textFieldGrp(window.namespace,edit=True,text="""+repr(prefix)+""")
result={'root':root,'targets':nodes,'matrices':{n:cmds.xform(n,query=True,worldSpace=True,matrix=True) for n in nodes}}
""")
        root=fixture['root']
        rig=py("from maya_agent.rigs.custom_body import ui\nresult=ui._instance.create()")
        assert rig is not None
        assert [m['target'] for m in rig['target_mapping']]==fixture['targets']
        result=request('undo',{'expected_chunk':'MayaMCP_Python'})
        assert result['undone']=='MayaMCP_Python'
        py("assert not cmds.objExists("+repr(rig['joints'][0])+")\n"+
           "for n,m in "+repr(fixture['matrices'])+".items():\n    assert max(abs(a-b) for a,b in zip(cmds.xform(n,query=True,worldSpace=True,matrix=True),m))<1e-5\nresult=True")
        py('cmds.redo()\nresult=True')
        code="for n in "+repr(rig['nodes'])+":\n    assert cmds.objExists(n),n\n"
        code+="cmds.setAttr("+repr(rig['controls']['chest']+'.translateX')+",1.5)\n"
        code+="assert abs(cmds.xform("+repr(fixture['targets'][-1])+",query=True,worldSpace=True,translation=True)[0]-22.3)<1e-5\n"
        code+="cmds.setAttr("+repr(rig['controls']['chest']+'.translateX')+",0)\nresult=True"
        py(code)
        report={'ui_selection_order':True,'ui_reorder':True,'ui_create':True,
                'undo_restores_targets':True,'redo_restores_nodes_and_live_driving':True}
    finally:
        cleanup=""
        if rig:
            cleanup+="for n in reversed("+repr(rig['nodes'])+"):\n    if cmds.objExists(n): cmds.delete(n)\n"
            cleanup+="if cmds.namespace(exists="+repr(rig['namespace'])+"): cmds.namespace(removeNamespace="+repr(rig['namespace'])+")\n"
        if root: cleanup+="if cmds.objExists("+repr(root)+"): cmds.delete("+repr(root)+")\n"
        cleanup+="from maya_agent.rigs.custom_body import ui\nw=ui._instance\nw.targets=[]\nw.last_result=None\nw.refresh_list()\ncmds.checkBox(w.selection_mode,edit=True,value=False)\nw.toggle_selection()\ncmds.textFieldGrp(w.namespace,edit=True,text='customBody')\n"
        cleanup+='cmds.select('+repr(snapshot['selection'])+',replace=True) if '+repr(bool(snapshot['selection']))+' else cmds.select(clear=True)\n'
        cleanup+='assert set(cmds.ls(long=True))==set('+repr(snapshot['nodes'])+')\n'
        cleanup+='for n,m in '+repr(snapshot['poses'])+'.items():\n    assert max(abs(a-b) for a,b in zip(cmds.xform(n,query=True,worldSpace=True,matrix=True),m))<1e-5\n'
        cleanup+='assert cmds.currentTime(query=True)=='+repr(snapshot['frame'])+'\n'
        cleanup+='cmds.file(modified='+repr(snapshot['dirty'])+')\nresult=True'
        py(cleanup)
    report['original_scene_preserved']=True
    (ROOT/'outputs/custom-body-tests/ui-mcp-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
