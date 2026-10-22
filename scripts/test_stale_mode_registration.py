"""Live regression for copied/deleted control metadata and empty exceptions."""
import contextlib
import io
import json
import types
import uuid
from unittest.mock import patch
import maya.cmds as c


def run():
    from maya_agent.rigs import arm_ik
    from maya_agent.rigs.custom_body.rotation_reference import Reference, CONTROL_REGISTRATIONS
    from maya_agent.rigs.integrated import ui
    before=set(c.ls(uuid=True));selection=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True)
    ns='_staleMode_'+uuid.uuid4().hex[:8];created=[]
    c.namespace(addNamespace=ns)
    try:
        control=c.createNode('transform',name=ns+':hips');created.append(control)
        c.addAttr(control,ln='bodyDrive',at='double',defaultValue=0)
        c.addAttr(control,ln='bodyDriveData',dt='string')
        data=json.dumps(dict(global_plug=control+'.bodyDrive'))
        c.setAttr(control+'.bodyDriveData',data,type='string',lock=True)
        copied=c.createNode('transform',name=ns+':oldReference');created.append(copied)
        c.addAttr(copied,ln='bodyDriveData',dt='string')
        c.setAttr(copied+'.bodyDriveData',data,type='string')
        stale=c.createNode('transform',name=ns+':staleReference');created.append(stale)
        c.addAttr(stale,ln='chestSpaceData',dt='string')
        c.setAttr(stale+'.chestSpaceData',json.dumps(dict(global_plug=ns+':deleted.global')),type='string')
        for _ in range(3):
            arm_ik.install()
            assert control in arm_ik._callbacks
            assert copied not in arm_ik._callbacks and stale not in arm_ik._callbacks
        reference=Reference(ns,created)
        clone=reference.source(control+'.rotateX').split('.')[0]
        assert not any(c.objExists(clone+'.'+attr) for attr in CONTROL_REGISTRATIONS)
        assert c.getAttr(control+'.bodyDriveData')==data
        c.delete(control);arm_ik.install()
        assert control not in arm_ik._callbacks
        messages=[];dummy=types.SimpleNamespace(message=messages.append)
        def fail():raise RuntimeError()
        with patch.object(ui.c,'warning') as warning, contextlib.redirect_stderr(io.StringIO()) as stderr:
            ui.IntegratedWindow.safe(dummy,fail)
        assert messages and 'RuntimeError' in messages[0]
        assert warning.call_args[0][0]==messages[0]
        assert 'fail' in dummy.last_error['traceback'] and 'RuntimeError' in stderr.getvalue()
        return dict(passed=True,stale_skipped=True,copied_valid_control_skipped=True,
                    new_reference_clean=True,deleted_control_unregistered=True,empty_error_described=True)
    finally:
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        arm_ik.install()
        c.namespace(removeNamespace=ns)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(uuid=True))==before
        c.file(modified=modified)
