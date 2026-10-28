"""Numeric exchange contract and legacy bool baselines, without editing a Maya scene.

Run with --backend <backend dir> [--fixture <project/animation.json dir>].
The Maya type registry is a test double; this is not a live scene acceptance test.
"""
import argparse,copy,hashlib,json,runpy,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser();parser.add_argument('--backend',type=Path,required=True);parser.add_argument('--fixture',type=Path)
args,extra=parser.parse_known_args()
cmds=types.ModuleType('maya.cmds');maya=types.ModuleType('maya');api=types.ModuleType('maya.api');om=types.ModuleType('maya.api.OpenMaya')
maya.cmds=cmds;maya.api=api;api.OpenMaya=om
modules={'maya':maya,'maya.cmds':cmds,'maya.api':api,'maya.api.OpenMaya':om}
with patch.dict(sys.modules,modules):
    importer=runpy.run_path(str(args.backend/'mobile_animation_io.py'))
    exporter=runpy.run_path(str(args.backend/'export_modes.py'))
curves=runpy.run_path(str(args.backend/'animation_curves.py'))
ATTRS=importer['ATTRS'];types_by_plug={}
def get_attr(plug,**kw):
    if kw.get('type'):return types_by_plug.get(plug,'double')
    raise AssertionError('Unexpected Maya call: '+plug)
cmds.getAttr=get_attr

def row(value=True):
    return {'id':'bone.visibility','name':'bone','inputOnly':True,'channels':{'translateX':{'value':value}},'inputPlugs':[None,None,None,'|rig|bone.visibility',None,None]}
def base(snapshot,bindings):return importer['snapshot_base'](snapshot,bindings)

class ExchangeTests(unittest.TestCase):
    def setUp(self):types_by_plug.clear();types_by_plug['|rig|bone.visibility']='bool'
    def test_export_discovery_writes_numeric_bool_baseline(self):
        class Selection:
            def add(self,plug):self.plug=plug
            def getPlug(self,index):return types.SimpleNamespace(name=lambda:self.plug)
        agent=types.ModuleType('maya_agent');rigs=types.ModuleType('maya_agent.rigs')
        agent.rigs=rigs;rigs.switch_panel=types.SimpleNamespace(targets=lambda metadata:{})
        rigs.arm_ik=types.SimpleNamespace()
        for state in (True,False):
            def attr(plug,**kw):
                if kw.get('type'):return 'bool' if plug.endswith('.visibility') else 'double'
                if kw.get('lock'):return False
                return state if plug.endswith('.visibility') else 0
            with patch.dict(sys.modules,{**modules,'maya_agent':agent,'maya_agent.rigs':rigs}),patch.object(om,'MSelectionList',Selection,create=True),patch.multiple(cmds,create=True,getAttr=attr,ls=lambda node,**kw:['bone-uuid' if kw.get('uuid') else node],listRelatives=lambda *a,**kw:[],listHistory=lambda *a,**kw:[],nodeType=lambda node:'animCurveTU' if node=='visibilityCurve' else 'transform',listAttr=lambda *a,**kw:['visibility'],connectionInfo=lambda plug,**kw:'visibilityCurve.output' if plug.endswith('.visibility') else '',xform=lambda *a,**kw:[0,0,0] if kw.get('t') else [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]):
                snapshot={'rigMetadata':{'parts':{}},'controls':[],'joints':[{'path':'|rig|bone'}]}
                exporter['extend_snapshot'](snapshot)
                self.assertEqual(len(snapshot['controls']),1)
                exported=snapshot['controls'][0];value=exported['channels']['translateX']['value']
                self.assertTrue(exported['sourceAnimation']);self.assertEqual(exported['role'],'sourceAnimation_visibility')
                self.assertIs(type(value),float);self.assertEqual(value,float(state))
                self.assertEqual(base(snapshot,{exported['id']:exported})[exported['id']]['translateX'],float(state))
    def test_new_export_numeric(self):
        for value in (True,False,1,0,-2.25):
            actual=exporter['channel_number'](value,'|rig|bone.visibility')
            self.assertIs(type(actual),float);self.assertEqual(actual,float(value))
            self.assertNotIn(json.dumps(actual),('true','false'))
        for value in (None,'1',[],float('nan'),float('inf')):
            with self.assertRaisesRegex(ValueError,'bone.visibility'):exporter['channel_number'](value,'|rig|bone.visibility')
    def test_legacy_true_false_and_original_bytes(self):
        for value in (True,False):
            r=row(value);snapshot={'controls':[r]};before=json.dumps(snapshot)
            self.assertEqual(base(snapshot,{r['id']:r})[r['id']]['translateX'],float(value))
            self.assertEqual(json.dumps(snapshot),before)
    def test_bool_only_on_trusted_bool_input(self):
        r=row();s={'controls':[r]}
        with self.assertRaisesRegex(ValueError,'bone.*translateX'):base(s,{})
        types_by_plug['|rig|bone.visibility']='double'
        with self.assertRaises(ValueError):base(s,{r['id']:r})
        types_by_plug['|rig|bone.visibility']='bool';r['inputOnly']=False
        with self.assertRaises(ValueError):base(s,{r['id']:r})
        for value in (True,False,None,'1',float('nan'),float('inf')):
            with self.assertRaises(ValueError):importer['number'](value,'pose/fps')
    def test_original_and_edited_boolean_curves(self):
        r=row();baseline=base({'controls':[r]},{r['id']:r})
        # A static bool curve from Maya has a numeric staticValue already.
        package={'curvePayloadVersion':1,'valueSpace':'snapshot-local-delta','frame':0,'sourceCurves':{r['id']:{'translateX':{'times':[],'values':[],'staticValue':0.0}}},'keys':[]}
        rows,specs,static=curves['prepare'](package,baseline)
        self.assertEqual(rows[0]['values'][r['id']]['translateX']+baseline[r['id']]['translateX'],0.0)
        package.update(autoEaseControls=[r['id']],interpolation='maya-auto-ease',curvePolicy='replace-auto-ease-tracks',keys=[{'frame':3,'values':{r['id']:{'translateX':-1.0}}},{'frame':8,'values':{r['id']:{'translateX':0.0}}}])
        rows,_,_=curves['prepare'](package,baseline)
        self.assertEqual([row['values'][r['id']]['translateX']+1 for row in rows],[0,1])
    def test_import_preflight_and_hash_protection(self):
        r=row();r.update(nodeId='bone',sourceAnimation=True)
        snapshot={'characterId':'root','rigVersion':'v','controls':[r]};raw=json.dumps(snapshot).encode()
        package={'format':'maya-mobile-animation','schemaVersion':1,'characterId':'root','rigVersion':'v','fps':30,'valueSpace':'snapshot-local-delta','sourceSnapshotSha256':hashlib.sha256(raw).hexdigest(),'keys':[{'frame':3,'values':{r['id']:{'translateX':-1.0}}}]}
        def attr(plug,**kw):
            if kw.get('lock'):return False
            if plug=='|rig.integratedRigData':return json.dumps({'version':'v','parts':{}})
            return get_attr(plug,**kw)
        def run(path,*a,**kw):
            if Path(path).name=='export_modes.py':return {'extend_snapshot':lambda s:s.update(controls=[r],modePanel={})}
            return real_run(path,*a,**kw)
        real_run=runpy.run_path
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules,modules),patch.object(runpy,'run_path',run),patch.multiple(cmds,create=True,getAttr=attr,ls=lambda uid,**kw:['|rig' if uid=='root' else '|rig|bone'],attributeQuery=lambda *a,**kw:True,currentUnit=lambda **kw:'ntsc',referenceQuery=lambda *a,**kw:False,listConnections=lambda *a,**kw:[]):
            p=Path(tmp);(p/'project.json').write_bytes(raw);(p/'anim.json').write_text(json.dumps(package))
            result=importer['apply'](p/'anim.json',dry_run=True,snapshot_path=p/'project.json')
            self.assertEqual(result['channelKeys'],1);self.assertTrue(result['dryRun'])
            package['sourceSnapshotSha256']='wrong';(p/'anim.json').write_text(json.dumps(package))
            with self.assertRaisesRegex(ValueError,'SHA256'):importer['apply'](p/'anim.json',dry_run=True,snapshot_path=p/'project.json')
    @unittest.skipUnless(args.fixture,'actual fixture not supplied')
    def test_actual_111122_and_android_roundtrip(self):
        raw=(args.fixture/'project.json').read_bytes();project=json.loads(raw);snap=json.loads(project['snapshotJson'])
        bindings={r['id']:r for r in snap['controls'] if r.get('inputOnly')}
        bools=[r for r in snap['controls'] if any(type(d['value']) is bool for a,d in r.get('channels',{}).items() if a in ATTRS)]
        self.assertEqual(len(bools),168)
        # Fixture metadata supplies test-double types; production queries live Maya.
        for r in bools:
            self.assertEqual(r['role'],'sourceAnimation_visibility')
            types_by_plug[r['inputPlugs'][3]]='bool'
        baseline=base(snap,bindings);reports=[]
        for name in ('animation.json','android-roundtrip.json'):
            path=args.fixture/name
            if not path.exists():continue
            animation=json.loads(path.read_bytes());self.assertEqual(hashlib.sha256(project['snapshotJson'].encode()).hexdigest(),animation['sourceSnapshotSha256'])
            rows,specs,static=curves['prepare'](animation,baseline);count=0
            for entry in rows:
                importer['number'](entry['frame'])
                for uid,pose in entry['values'].items():
                    for attr,value in pose.items():
                        if attr in ATTRS:importer['number'](value);count+=1
            for r in bools:
                if r['id'] in animation['sourceCurves']:
                    self.assertEqual(specs[(r['id'],'translateX')],animation['sourceCurves'][r['id']]['translateX'])
                else:
                    self.assertNotIn((r['id'],'translateX'),specs)
                    self.assertTrue(all(r['id'] not in entry['values'] for entry in rows))
            reports.append((name,len(rows),count))
        self.assertEqual((args.fixture/'project.json').read_bytes(),raw)
        print('Actual fixture numeric checks:',reports)

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+extra)
