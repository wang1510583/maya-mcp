"""Read rig metadata in its owning reference, without editing saved JSON.

Maya remaps DG connections when referencing a file, but not node names inside
string attributes. Never resolve against another copy or a global short name.
"""
import json
import re

_NAME = re.compile(r'^[\w:|.\[\]]+$', re.UNICODE)


def resolve_uuid(identity, owner, fallback):
    """UUIDs from the same referenced source are not globally unique."""
    import maya.cmds as c
    def reference(node):
        return c.referenceQuery(node, referenceNode=True) if c.referenceQuery(node, isNodeReferenced=True) else None
    ref = reference(owner)
    matches = [n for n in c.ls(identity, long=True) or [] if reference(n) == ref]
    if len(matches) == 1:
        return matches[0]
    if c.objExists(fallback) and reference(fallback) == ref:
        return fallback
    raise ValueError('无法在当前角色内唯一定位控制器：' + fallback)


def read(plug):
    import maya.cmds as c
    return contextualize(json.loads(c.getAttr(plug)), plug.split('.', 1)[0])


def contextualize(data, owner):
    import maya.cmds as c
    if not c.referenceQuery(owner, isNodeReferenced=True):
        return data
    prefix = c.referenceQuery(owner, namespace=True).strip(':')
    if not prefix:
        return data
    prefix += ':'
    mapped = {}

    def name(value, namespace=False):
        if not value or not _NAME.fullmatch(value):
            return value
        if (value, namespace) in mapped:
            return mapped[value, namespace]
        node, dot, attr = value.partition('.')
        parts = node.split('|')
        # Runtime metadata written after reference edits is already qualified.
        candidate = '|'.join(p if not p or p.startswith(prefix) else prefix + p.lstrip(':') for p in parts)
        candidate += dot + attr
        qualified = ':' in node or '|' in node or namespace
        if not qualified and not c.objExists(candidate):
            result = value  # role names, enum labels, versions, etc.
        else:
            result = candidate
            if '|' in node and not c.objExists(candidate):
                # A file may have been grouped/reparented after JSON creation.
                # Only use the fully namespaced leaf within this reference.
                leaf = candidate.rsplit('|', 1)[-1]
                matches = c.ls(leaf.split('.', 1)[0], long=True) or []
                if len(matches) == 1 and c.objExists(leaf):
                    result = leaf
        mapped[value, namespace] = result
        return result

    def walk(value, field=None):
        if isinstance(value, dict):
            return {name(k) if ':' in k or '|' in k else k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, field) for v in value]
        if isinstance(value, str):
            if field in ('role', 'part', 'side', 'kind', 'version', 'type', 'mode', 'missing', 'column_order'):
                return value
            return name(value, field == 'namespace')
        return value

    return walk(data)
