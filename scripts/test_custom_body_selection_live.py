"""Interactive Maya tests using owned temporary targets; preserve the user's scene."""
import math
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.custom_body import build
from maya_agent.rigs.custom_body import targets as target_tools


def run_case(count=4, joint_chain=True, rotated=True, fail=False):
    before = set(c.ls(long=True))
    poses = {n: c.xform(n, query=True, worldSpace=True, matrix=True)
             for n in c.ls(type='transform', long=True) + c.ls(type='joint', long=True)}
    selected, frame = c.ls(selection=True, long=True) or [], c.currentTime(query=True)
    dirty, ns_before = c.file(query=True, modified=True), c.namespaceInfo(currentNamespace=True)
    prefix = '_CBR_SEL_' + uuid.uuid4().hex[:8]
    rig, root, mesh, skin = None, None, None, None
    checks = []

    def near(a, b, tolerance=4e-5):
        assert len(a) == len(b) and max(abs(x-y) for x,y in zip(a,b)) < tolerance, (a,b)

    def world(node):
        return c.xform(node, query=True, worldSpace=True, matrix=True)

    try:
        root = c.createNode('transform', name=prefix+'_targets')
        c.setAttr(root+'.translate', 20, 4, -3, type='double3')
        c.setAttr(root+'.rotate', 12, -23, 8, type='double3')
        c.setAttr(root+'.scale', 1.5, 1.5, 1.5, type='double3')
        nodes = []
        for index in range(count):
            parent = nodes[-1] if joint_chain and nodes else root
            node = c.createNode('joint' if joint_chain else 'transform', name=prefix+'_target'+str(index), parent=parent)
            c.setAttr(node+'.rotateOrder', index%6)
            if joint_chain:
                c.setAttr(node+'.jointOrient', 10, 20, 5, type='double3')
            c.xform(node, worldSpace=True, translation=[20+index*.6,4+index*1.7+index*index*.08,-3+math.sin(index)*.3],
                    rotation=[index*7, 15-index*3, -10+index*8] if rotated else [0,0,0])
            nodes.append((c.ls(node,long=True) or [])[0])
        original = {node: world(node) for node in nodes}
        parents = {node: c.listRelatives(node,parent=True,fullPath=True) for node in nodes}
        if joint_chain and count == 4:
            mesh = c.polyCube(name=prefix+'_mesh',constructionHistory=False)[0]
            c.xform(mesh,worldSpace=True,translation=[21,7,-3])
            skin = c.skinCluster(nodes, mesh, toSelectedBones=True, name=prefix+'_skin')[0]
            vertices = c.xform(mesh+'.vtx[*]',query=True,worldSpace=True,translation=True)
        samples, total = target_tools.inspect(nodes)
        if fail:
            previous = target_tools.connect
            def injected(ctx, source):
                previous(ctx, source)
                raise RuntimeError('injected target rollback test')
            target_tools.connect = injected
            try:
                try:
                    build(namespace=prefix, targets=nodes)
                    raise AssertionError('expected injected failure')
                except RuntimeError as exc:
                    assert 'injected target rollback' in str(exc)
            finally:
                target_tools.connect = previous
            assert not c.namespace(exists=prefix)
            for node in nodes:
                near(world(node), original[node])
                assert not c.listConnections(node+'.translate',source=True,destination=False)
            return {'case':'rollback_after_output_constraints','passed':True}
        rig = build(namespace=prefix, targets=nodes)
        assert rig['segment_count'] == count and len(rig['target_mapping']) == count
        near([rig['height']],[total])
        controls = list(rig['controls'].values())
        for i, (node, control, joint) in enumerate(zip(nodes,controls,rig['joints'])):
            assert rig['target_mapping'][i]['target'] == node
            near(world(node), original[node])
            near(world(control)[12:15], original[node][12:15])
            near(world(joint)[12:15], original[node][12:15])
            near(list(om.MTransformationMatrix(om.MMatrix(world(control))).rotation(asQuaternion=True).asMatrix()), samples[i]['matrix'])
            assert c.listRelatives(node,parent=True,fullPath=True) == parents[node]
            near(c.getAttr(control+'.translate')[0],[0,0,0])
            near(c.getAttr(control+'.rotate')[0],[0,0,0])
        if skin:
            near(c.xform(mesh+'.vtx[*]',query=True,worldSpace=True,translation=True),vertices)
        checks.append('ordered mapping, positions/orientations, zero control channels, hierarchy and skin rest pose')
        length=0
        chest=controls[-1]
        delta=om.MVector(1.2,0,0)*om.MMatrix(samples[-1]['matrix'])
        c.setAttr(chest+'.translateX',1.2)
        for i,node in enumerate(nodes):
            if i: length += math.dist(samples[i-1]['position'],samples[i]['position'])
            fraction=length/total
            near(world(node)[12:15],[p+d*fraction for p,d in zip(samples[i]['position'],[delta.x,delta.y,delta.z])])
        c.setAttr(chest+'.translateX',0)
        checks.append('chest translation converted between rest frames and distributed by distance')
        for endpoint in (controls[0], controls[-1]):
            c.setAttr(endpoint+'.rotateZ',25)
            assert max(abs(a-b) for a,b in zip(world(nodes[-1]),original[nodes[-1]])) > .01
            for node,joint in zip(nodes,rig['joints']):
                near(world(node)[12:15],world(joint)[12:15])
            c.setAttr(endpoint+'.rotateZ',0)
        if count>2:
            c.setAttr(controls[1]+'.translateX',.5)
            assert math.dist(world(nodes[1])[12:15],samples[1]['position'])>.4
            c.setAttr(controls[1]+'.translateX',0)
        for node in nodes: near(world(node),original[node])
        if skin: near(c.xform(mesh+'.vtx[*]',query=True,worldSpace=True,translation=True),vertices)
        checks.append('endpoint rotations and middle control drive targets and return to exact rest pose')
        return {'count':count,'joint_chain':joint_chain,'rotated':rotated,'checks':checks,'passed':True}
    finally:
        if rig:
            for node in reversed(rig['nodes']):
                if c.objExists(node): c.delete(node)
            if c.namespace(exists=rig['namespace']): c.namespace(removeNamespace=rig['namespace'])
        for node in (skin,mesh,root):
            if node and c.objExists(node): c.delete(node)
        # Clean only deformer support nodes created by this test, after its owned mesh.
        extra=set(c.ls(long=True))-before
        for node in list(extra):
            if c.objExists(node):
                if c.nodeType(node) not in ('dagPose','groupId','groupParts'):
                    raise AssertionError('Unexpected leftover: '+node)
                c.delete(node)
        c.namespace(setNamespace=ns_before)
        c.select(selected,replace=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==before
        assert c.currentTime(query=True)==frame
        for node,matrix in poses.items(): near(world(node),matrix)
        c.file(modified=dirty)
