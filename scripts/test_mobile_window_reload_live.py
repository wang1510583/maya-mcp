"""Regression for stale Qt callbacks after reloading the mobile exporter UI.

Uses the existing window, retaining its inputs; all network writes are mocked.
"""
import importlib,json
import maya.cmds as c
from maya_agent.rigs.mobile_io import service,ui


def run():
    old=ui._instance
    if old is None or old.busy:raise RuntimeError('Open an idle mobile exchange window first')
    def inputs(w):return (w.project_out.text(),w.animation_out.text(),w.start.value(),w.end.value(),w.characters.currentData())
    expected=inputs(old);selection=c.ls(sl=True,long=True) or []
    importlib.reload(ui);w=ui.show()
    assert w is not old and type(w) is ui.ExchangeWindow and inputs(w)==expected
    captured={};original=service.export_to_server
    remote_args=w.remote_args;listing=w.perform_remote_list;root=w.root;status=w.status.text()
    try:
        def intercept(*args,**kwargs):
            captured.update(kwargs)
            return dict(name='test',appearance=None)
        service.export_to_server=intercept
        w.remote_args=lambda:('unused','unused');w.root=lambda:'test-root';w.perform_remote_list=lambda **kwargs:None
        w.perform_export()
        assert captured['selection']==selection
    finally:
        service.export_to_server=original;w.remote_args=remote_args;w.root=root;w.perform_remote_list=listing;w.status.setText(status)
    saved={k:getattr(service,k) for k in ('network_list','export_project','network_upload')}
    try:
        def project(root,target,*args,**kwargs):
            captured.clear();captured.update(kwargs);target.write_text('{}','utf8')
            return dict(characterId='fixture',meshes=4,cameras=1,selection=kwargs['selection'])
        service.network_list=lambda *args:dict(files=[])
        service.export_project=project;service.network_upload=lambda *args:dict(ok=True)
        report=service.export_to_server('fixture','test','unused','unused',project=True)
        assert captured['selection']==selection and report['meshes']==4 and report['cameras']==1
        service.export_to_server('fixture','test','unused','unused',project=True,selection=[])
        assert captured['selection']==[]
    finally:
        for k,v in saved.items():setattr(service,k,v)
    assert c.ls(sl=True,long=True)==selection
    print(json.dumps(dict(passReload=True,inputFieldsPreserved=True,newCallbackPassesSelection=True,oldCallbackFallback=True,explicitEmptySelection=True,networkWrites=0)))

if __name__=='__main__':run()
