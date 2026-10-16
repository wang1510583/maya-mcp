"""Main-thread exchange operations using the bundled, validated exporters."""
import hashlib,json,runpy,tempfile,urllib.request,urllib.error,urllib.parse
from pathlib import Path
import maya.cmds as c

BACKEND=Path(__file__).parent/'backend'
NETWORK_TIMEOUT=30

def server_filename(name, project=False):
    name=str(name or '').strip()
    if not name or any(ch in name for ch in '/\\') or any(ord(ch)<32 for ch in name):
        raise ValueError('请填写文件名，不要填写文件夹路径。')
    if not name.lower().endswith('.json'):name += '.mobile.json' if project else '.json'
    return name[:-5]+'.json'

def matching_project(row, animation):
    return (row.get('format')=='maya-mobile-project' and
            bool(row.get('sourceSnapshotSha256')) and
            all(row.get(k)==animation.get(k) for k in ('characterId','rigVersion','sourceSnapshotSha256')))

def export_to_server(root, name, base, token, project=False, start=None, end=None, progress=lambda text:None, project_name=None):
    """Temporary compilation only; exports have no user-managed local destination."""
    name=server_filename(name,project)
    rows=network_list(base,token)['files']
    with tempfile.TemporaryDirectory(prefix='maya_server_export_') as directory:
        d=Path(directory);target=d/name
        if project:
            report=export_project(root,target,False,start,end,progress)
        else:
            _,uid,meta=identity(root)
            candidates=[r for r in rows if r.get('format')=='maya-mobile-project' and r.get('characterId')==uid and str(r.get('rigVersion'))==str(meta['version'])]
            candidates.sort(key=lambda r:float(r.get('mtime',0)),reverse=True)
            chosen=next((r for r in candidates if r['name']==project_name),None)
            if chosen is None and candidates:chosen=candidates[0]
            if chosen is None:raise ValueError('服务器没有当前角色的工程，请先导出工程到服务器。')
            baseline=d/'baseline.mobile.json'
            network_download(base,token,chosen['name'],baseline)
            report=export_animation(root,str(baseline),target,progress)
        progress('正在上传服务器…')
        uploaded=network_upload(base,token,target,name)
        return dict(name=name,server=uploaded,characterId=report.get('characterId'),serverSync=True)

def module(name):return runpy.run_path(str(BACKEND/(name+'.py')))

def roots():return sorted(c.ls('*.integratedRigData',objectsOnly=True,long=True,recursive=True) or [])

def identity(root):
    found=c.ls(root,long=True) or []
    if len(found)!=1 or not c.objExists(found[0]+'.integratedRigData'):raise ValueError('请选择当前场景中的集成角色绑定。')
    return found[0],c.ls(found[0],uuid=True)[0],json.loads(c.getAttr(found[0]+'.integratedRigData'))

def read_project(path,root=None):
    p=Path(path)
    if not p.is_file():raise ValueError('请选择最初导出给手机的工程文件。')
    data=json.loads(p.read_text('utf-8-sig'))
    if data.get('format')!='maya-mobile-project':raise ValueError('原工程必须是手机工程文件（*.mobile.json），不是手机动画文件。')
    raw=data['snapshotJson'].encode('utf8');snap=json.loads(raw);graph=data['solver']
    if hashlib.sha256(raw).hexdigest()!=graph['sourceSnapshotSha256']:raise ValueError('工程快照校验失败，请重新选择原文件。')
    found,uid,meta=identity(root or snap['characterId'])
    if uid!=snap['characterId'] or str(meta['version'])!=str(snap['rigVersion']):raise ValueError('当前角色 / 绑定版本与原手机工程不一致，请选择正确角色。')
    if graph['characterId']!=uid:raise ValueError('工程求解器角色身份不匹配。')
    return data,snap,found

def write_new(source,destination):
    target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation protects an older phone project and its animation identity.
    with target.open('xb') as stream:stream.write(Path(source).read_bytes())

def find_matching_project(root):
    """Find the newest local mobile project for the currently open role."""
    found,uid,meta=identity(root)
    scene=c.file(q=True,sn=True)
    folder=Path(scene).parent/'mobile_exports' if scene else Path(c.internalVar(userWorkspaceDir=True))/'mobile_exports'
    candidates=[]
    if folder.is_dir():
        for path in folder.glob('*.mobile.json'):
            try:
                data=json.loads(path.read_text('utf8-sig'));snap=json.loads(data.get('snapshotJson','{}'))
                if data.get('format')=='maya-mobile-project' and snap.get('characterId')==uid and str(snap.get('rigVersion'))==str(meta.get('version')):
                    candidates.append(path)
            except Exception:continue
    return max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None

def export_project(root,destination,include_animation=True,start=None,end=None,progress=lambda text:None):
    root,uid,meta=identity(root);target=Path(destination)
    if target.exists():raise ValueError('文件已存在，请更换文件名，保留原工程用于动画回传。')
    if not str(destination).strip():raise ValueError('请选择导出文件位置。')
    if c.currentUnit(q=True,linear=True)!='cm' or c.upAxis(q=True,axis=True)!='y':raise ValueError('手机求解器目前要求厘米单位、Y 向上，请使用对应工程。')
    start=c.playbackOptions(q=True,minTime=True) if start is None else start
    end=c.playbackOptions(q=True,maxTime=True) if end is None else end
    if int(start)!=start or int(end)!=end or not 0<=start<=end<=100000:raise ValueError('动画范围需为 0–100000 内的整数，结束帧不能小于开始帧。')
    with tempfile.TemporaryDirectory(prefix='maya_mobile_') as directory:
        d=Path(directory);snapshot=d/'snapshot.json';debug=d/'graph-debug.json';graph=d/'graph.json';animation=d/'animation.json'
        progress('1/4 读取角色、手指、通用物件和蒙皮…');report=module('export_snapshot')['export'](root,str(snapshot))
        snap=json.loads(snapshot.read_text('utf8'));snap['frameRange']=[int(start),int(end)]
        snapshot.write_text(json.dumps(snap,ensure_ascii=False,separators=(',',':'),allow_nan=False),'utf8')
        progress('2/4 编译手机离线求解与模式切换…');compiler=module('export_portable_graph');compiler['export'](str(snapshot),str(debug));compiler['compact'](str(debug),str(graph))
        if include_animation:
            progress('3/4 采样动画，完成后恢复 Maya 当前帧…');animation_report=module('export_animation')['export'](str(snapshot),str(graph),str(animation),str(d/'reference.json'))
        else:animation_report=None
        progress('4/4 生成手机工程文件…');compiler['package_snapshot'](str(snapshot),str(graph),str(d/'package.json'),str(animation) if include_animation else None)
        write_new(d/'package.json',target)
        return dict(path=str(target),characterId=uid,rigVersion=meta['version'],controls=report['visibleControls'],meshes=report['meshes'],frameRange=[start,end],animation=animation_report,bytes=target.stat().st_size)

def export_animation(root,project_path,destination,progress=lambda text:None):
    if Path(destination).exists():raise ValueError('动画文件已存在，请更换文件名。')
    with tempfile.TemporaryDirectory(prefix='maya_mobile_anim_') as directory:
        d=Path(directory)
        if not project_path or not str(project_path).strip():
            auto_project=find_matching_project(root)
            if auto_project:
                project_path=str(auto_project)
        if project_path and str(project_path).strip():
            project,snap,root=read_project(project_path,root)
            (d/'snapshot.json').write_text(project['snapshotJson'],'utf8');(d/'graph.json').write_text(json.dumps(project['solver']),'utf8')
        else:
            # The open Maya character is the source of truth; no project file is
            # needed just to export its animation identity.
            root,uid,meta=identity(root)
            if c.currentUnit(q=True,linear=True)!='cm' or c.upAxis(q=True,axis=True)!='y':raise ValueError('手机求解器目前要求厘米单位、Y 向上，请使用对应工程。')
            start=int(c.playbackOptions(q=True,minTime=True));end=int(c.playbackOptions(q=True,maxTime=True))
            snapshot=d/'snapshot.json';debug=d/'graph-debug.json';graph=d/'graph.json'
            progress('读取当前角色工程身份并编译手机求解…');module('export_snapshot')['export'](root,str(snapshot))
            snap=json.loads(snapshot.read_text('utf8'));snap['frameRange']=[start,end];snapshot.write_text(json.dumps(snap,ensure_ascii=False,separators=(',',':'),allow_nan=False),'utf8')
            compiler=module('export_portable_graph');compiler['export'](str(snapshot),str(debug));compiler['compact'](str(debug),str(graph))
        progress('按当前工程身份采样 Maya 动画…')
        report=module('export_animation')['export'](str(d/'snapshot.json'),str(d/'graph.json'),str(d/'animation.json'),str(d/'reference.json'))
        write_new(d/'animation.json',destination)
        return dict(path=str(destination),**report)

def import_animation(root,project_path,animation_path,dry_run=True):
    read_project(project_path,root)
    backup=Path(c.internalVar(userAppDir=True))/'maya-animation-backups'
    result=module('mobile_animation_io')['apply'](str(animation_path),dry_run=dry_run,snapshot_path=str(project_path),backup_directory=str(backup))
    return {key:value for key,value in result.items() if key!='controls'}

def network_url(value):
    value=str(value or '').strip().rstrip('/')
    if not value: raise ValueError('请输入服务器地址，例如 http://[IPv6]:8765')
    if '://' not in value: value='http://'+value
    if not (value.startswith('http://') or value.startswith('https://')): raise ValueError('服务器地址必须以 http:// 或 https:// 开头')
    return value

def _request(base, token, method, path, data=None):
    if not token: raise ValueError('请输入文件服务令牌。')
    url=network_url(base)+path
    req=urllib.request.Request(url,data=data,method=method,headers={'X-Exchange-Token':str(token),'Accept':'application/json'})
    if data is not None: req.add_header('Content-Type','application/json')
    try:
        # Do not inherit a desktop HTTP proxy: Tailscale/IPv6 addresses must be reached directly.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req,timeout=NETWORK_TIMEOUT) as response:
            body=response.read()
            return response,body
    except urllib.error.HTTPError as e:
        try: detail=json.loads(e.read().decode('utf8')).get('error',e.reason)
        except Exception: detail=str(e.reason)
        raise ValueError('服务器返回 %s：%s'%(e.code,detail))
    except Exception as e: raise ValueError('连接服务器失败：%s'%e)

def network_health(base,token):
    _,body=_request(base,token,'GET','/api/health');return json.loads(body.decode('utf8'))

def network_list(base,token):
    _,body=_request(base,token,'GET','/api/files');return json.loads(body.decode('utf8'))

def network_upload(base,token,path,remote_name=None):
    p=Path(path)
    if not p.is_file(): raise ValueError('本地文件不存在：%s'%p)
    name=remote_name or p.name
    if '/' in name or '\\' in name or not name.lower().endswith('.json'): raise ValueError('远端文件名必须是 JSON 文件名')
    data=p.read_bytes();response,body=_request(base,token,'PUT','/api/files/'+urllib.parse.quote(name,safe='.-_'),data)
    return json.loads(body.decode('utf8'))

def network_download(base,token,name,destination):
    if '/' in name or '\\' in name or not name.lower().endswith('.json'): raise ValueError('远端文件名无效')
    response,body=_request(base,token,'GET','/api/files/'+urllib.parse.quote(name,safe='.-_'))
    target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name('.'+target.name+'.download')
    temp.write_bytes(body)
    digest=hashlib.sha256(body).hexdigest();expected=response.headers.get('X-File-Sha256')
    if expected and expected!=digest:
        temp.unlink(missing_ok=True);raise ValueError('下载校验失败，远端文件可能已变化')
    temp.replace(target)
    return {'path':str(target),'name':name,'bytes':len(body),'sha256':digest}
