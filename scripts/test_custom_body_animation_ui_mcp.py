"""UI animation transfer and separate-request undo/redo on an owned fixture."""
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request


def py(code):
    return request('python',{'code':code})['result']


def main():
    prefix='_CBR_ANIM_UI_'+uuid.uuid4().hex[:8]
    snapshot=py("result={'nodes':cmds.ls(long=True),'selection':cmds.ls(sl=True,long=True) or [],'dirty':cmds.file(q=True,modified=True),'time':cmds.currentTime(q=True),'poses':{n:cmds.xform(n,q=True,ws=True,m=True) for n in cmds.ls(type='transform',long=True)+cmds.ls(type='joint',long=True)}}")
    fixture=None
    try:
        fixture=py("""from maya_agent.rigs.custom_body import ui
w=ui.show()
nodes=[]
for i in range(4):
 n=cmds.createNode('transform',name="""+repr(prefix)+"""+'_target'+str(i))
 cmds.setAttr(n+'.translateY',i*2)
 for f in (1,5,10):
  cmds.setKeyframe(n,at='translateX',t=f,v=(f-1)*(.1+i*.03))
  cmds.setKeyframe(n,at='rotateZ',t=f,v=(f-1)*(3+i))
 nodes.append(cmds.ls(n,long=True)[0])
cmds.select(nodes,r=True)
cmds.checkBox(w.selection_mode,e=True,v=True)
w.toggle_selection()
cmds.checkBox(w.copy_animation,e=True,v=True)
w.toggle_animation()
assert cmds.columnLayout(w.animation_fields,q=True,enable=True)
cmds.floatFieldGrp(w.frame_bounds,e=True,value1=1,value2=10)
cmds.floatFieldGrp(w.sample_step,e=True,value1=1)
cmds.textFieldGrp(w.namespace,e=True,text="""+repr(prefix)+""")
edges={n+'.'+a:cmds.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in nodes for a in ('translateX','rotateZ')}
motion=[]
for f in (1,4,7,10):
 cmds.currentTime(f)
 motion.append([cmds.xform(n,q=True,ws=True,m=True) for n in nodes])
cmds.currentTime("""+repr(snapshot['time'])+""")
result={'targets':nodes,'motion':motion,'edges':edges}
""")
        rig=py('from maya_agent.rigs.custom_body import ui\nresult=ui._instance.create()')
        assert rig and rig['animation_transfer']['sample_count']==10
        assert request('undo',{'expected_chunk':'MayaMCP_Python'})['undone']=='MayaMCP_Python'
        py('assert not cmds.namespace(exists='+repr(prefix)+')\nfor dst,src in '+repr(fixture['edges'])+'.items():\n assert cmds.isConnected(src,dst)\nresult=True')
        py('cmds.redo()\nresult=True')
        verify='for n in '+repr(rig['nodes'])+':\n assert cmds.objExists(n),n\n'
        verify+='for dst,src in '+repr(fixture['edges'])+'.items():\n assert cmds.objExists(src) and not cmds.isConnected(src,dst)\n'
        verify+='for f,matrices in zip((1,4,7,10),'+repr(fixture['motion'])+'):\n cmds.currentTime(f)\n for n,expected in zip('+repr(fixture['targets'])+',matrices):\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),expected))<1e-4\nresult=True'
        py(verify)
        report={'ui_checkbox_and_range':True,'ui_transfer':True,'undo_restores_exact_connections':True,
                'redo_restores_animation_and_backups':True,'passed':True}
    finally:
        py('before=set('+repr(snapshot['nodes'])+')\nfor n in reversed(cmds.ls(long=True)):\n if n not in before and cmds.objExists(n): cmds.delete(n)\n'+
           'if cmds.namespace(exists='+repr(prefix)+'): cmds.namespace(removeNamespace='+repr(prefix)+')\n'+
           'cmds.currentTime('+repr(snapshot['time'])+')\ncmds.select('+repr(snapshot['selection'])+',r=True)\n'+
           'assert set(cmds.ls(long=True))==before\nfor n,expected in '+repr(snapshot['poses'])+'.items():\n assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),expected))<1e-5\n'+
           'cmds.file(modified='+repr(snapshot['dirty'])+')\nfrom maya_agent.rigs.custom_body import ui\nui.show()\nresult=True')
    output=ROOT/'outputs/custom-body-tests/animation-ui-mcp-tests.json'
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__': main()
