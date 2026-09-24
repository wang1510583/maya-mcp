"""Actual MCP create -> separate undo -> separate redo roundtrip with owned-node cleanup."""
import asyncio
import json
from pathlib import Path
import sys
import uuid
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request

def data(response):
    assert not response.isError, response.content
    return json.loads(next(c.text for c in response.content if c.type=='text'))

async def main(count=4, height=6.0):
    ns='_CBR_MCP_'+uuid.uuid4().hex[:8]
    snapshot=request('python',{'code':'result = {"nodes": sorted(cmds.ls(long=True) or []), "dirty": cmds.file(query=True, modified=True)}'})['result']
    before=snapshot['nodes']
    rig=None
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'scripts/run_maya_mcp.py')])
    try:
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                catalog=await session.list_tools()
                assert 'create_custom_body_rig' in {t.name for t in catalog.tools}
                schema=next(t.inputSchema for t in catalog.tools if t.name=='create_custom_body_rig')
                assert {'segment_count','height'} <= schema['properties'].keys()
                response=data(await session.call_tool('create_custom_body_rig',{'namespace':ns, 'segment_count':count, 'height':height}))
                assert response['ok']
                rig=response['data']
                undone=data(await session.call_tool('undo_maya_operation',{'expected_chunk':'MayaMCP_create_custom_body_rig'}))
                assert undone['undone']=='MayaMCP_create_custom_body_rig'
                absent=request('python',{'code':'result = cmds.objExists('+repr(rig['joints'][0])+')'})['result']
                assert not absent
                redo_code='cmds.redo()\n'
                redo_code+='for name in '+repr([n for n in rig['nodes'] if n.endswith('ctrlShape')])+':\n    assert cmds.getAttr(name+".spans")==15\n'
                redo_code+='cmds.setAttr('+repr(rig['controls']['chest']+'.translateX')+',3)\n'
                expected=.999 if count==4 else 3/(count-1)
                redo_code+='assert abs(cmds.xform('+repr(rig['joints'][1])+',query=True,worldSpace=True,translation=True)[0]-'+repr(expected)+')<1e-5\n'
                redo_code+='cmds.setAttr('+repr(rig['controls']['chest']+'.translateX')+',0)\n'
                redo_code+='result = [n for n in '+repr(rig['nodes'])+' if cmds.objExists(n)]'
                restored=data(await session.call_tool('execute_maya_code',{'code':redo_code}))
                assert set(restored['result'])==set(rig['nodes']), restored
                print(json.dumps({'mcp_direct_tool':True,'created_nodes':rig['node_count'],'undo':True,'redo_all_nodes_including_layers':True},indent=2))
    finally:
        if rig:
            cleanup='for n in reversed('+repr(rig['nodes'])+'):\n    if cmds.objExists(n): cmds.delete(n)\n'
            cleanup+='if cmds.namespace(exists='+repr(ns)+'): cmds.namespace(removeNamespace='+repr(ns)+')\n'
            cleanup+='result = sorted(cmds.ls(long=True) or [])'
            after=request('python',{'code':cleanup})['result']
            assert after==before, {'added':sorted(set(after)-set(before)), 'missing':sorted(set(before)-set(after))}
            request('python',{'code':'cmds.file(modified='+repr(snapshot['dirty'])+')'})
    out=ROOT/('outputs/custom-body-tests/mcp-tests-'+str(count)+'.json')
    out.write_text(json.dumps({'mcp_direct_tool':True,'segment_count':count,'height':height,'node_count':rig['node_count'],'undo':True,'redo':True,'original_node_set_preserved':True},indent=2),encoding='utf-8')

if __name__=='__main__':
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv)>1 else 4, float(sys.argv[2]) if len(sys.argv)>2 else 6.0))
