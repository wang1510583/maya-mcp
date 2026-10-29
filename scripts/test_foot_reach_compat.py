def run(out):
    import runpy,pathlib
    import maya.cmds as c
    c.file(new=True,force=True)
    root=pathlib.Path(__file__).resolve().parents[1]
    # Runtime-only packages intentionally omit rig-construction templates.
    # Use the canonical template directory for fixture creation in this test.
    from maya_agent.rigs import soft_leg
    original_data=soft_leg.DATA
    soft_leg.DATA=root/'自定义人物绑定插件'/'maya_agent'/'rigs'/'soft_leg'/'data'
    suite=runpy.run_path(str(root/'scripts'/'test_foot_translation_live.py'))
    results=[]
    for animated,extra in ((False,None),(True,None),(True,'layer'),(True,'constraint')):
        report=suite['run'](animated=animated,extra=extra)
        assert report['passed'],report.get('traceback')
        assert report['original_nodes_preserved'] and report['original_curves_preserved'],report
        results.append(dict(animated=animated,extra=extra,cases=len(report['cases'])))
    soft_leg.DATA=original_data
    return dict(passed=True,suites=results)
