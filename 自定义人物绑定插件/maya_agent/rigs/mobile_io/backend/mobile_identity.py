"""Stable, reference-instance-aware exchange identities; no name fallback on import."""
import maya.cmds as c


def reference_owner(node):
    if not c.referenceQuery(node, isNodeReferenced=True):
        return None
    if c.nodeType(node) == 'reference':
        return c.referenceQuery(node, parent=True, referenceNode=True)
    return c.referenceQuery(node, referenceNode=True)


def identity(node):
    uid = c.ls(node, uuid=True)[0]
    ref = reference_owner(node)
    if ref:
        # Nested reference nodes can themselves share UUIDs between instances.
        uid += '@' + identity(ref)
    return uid


def resolve(uid):
    node_id, sep, ref_id = uid.partition('@')
    nodes = c.ls(node_id, long=True) or []
    if sep:
        ref = resolve(ref_id)
        if c.nodeType(ref) != 'reference':
            raise ValueError('工程引用实例已改变，请重新导出：' + uid)
        nodes = [n for n in nodes if reference_owner(n)
                 and identity(reference_owner(n)) == ref_id]
    if len(nodes) != 1:
        raise ValueError('工程节点未唯一匹配：' + uid)
    return nodes[0]


def read(plug):
    from maya_agent.rigs import scene_data
    return scene_data.read(plug)


def registered(uid, owner):
    from maya_agent.rigs import scene_data
    return scene_data.resolve_uuid(uid, owner, '')
