"""Run inside Maya after importing a BIP; pass a capture JSON explicitly.

run(path, root) checks driven target matrices in DG and parallel evaluation.
Use a half-frame capture to measure interpolation between baked whole frames.
This test reads animation and restores time, selection and evaluation mode.
"""
import math


def run(path,root):
    import maya.cmds as c
    from maya_agent.rigs import bip_retarget as br
    job=br.plan(path,root=root)
    current=c.currentTime(q=True);mode=c.evaluationManager(q=True,mode=True)[0]
    report={}
    try:
        for evaluation in ('off','parallel'):
            c.evaluationManager(mode=evaluation)
            matrix_error=position_error=0.0
            for frame,world in job['frames']:
                c.currentTime(frame)
                for node,expected in world.items():
                    actual=c.xform(node,q=True,ws=True,m=True)
                    matrix_error=max(matrix_error,max(abs(a-b) for a,b in zip(actual,list(expected))))
                    position_error=max(position_error,math.dist(actual[12:15],list(expected)[12:15]))
            report[evaluation]=dict(max_matrix_error=matrix_error,max_position_error_cm=position_error)
        report['target_key_count']=sum(c.keyframe(n,q=True,kc=True) or 0 for n in job['rest'])
        report['mapped_bones']=len(job['rest'])
        return report
    finally:
        c.currentTime(current);c.evaluationManager(mode=mode)
