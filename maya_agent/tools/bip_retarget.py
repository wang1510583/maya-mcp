"""MCP entry point for Max BIP animation retargeting."""
from maya_agent.tools.registry import ToolResult, obj_schema, tool


@tool(
    name='retarget_max_bip_animation', display_name='Max BIP动画转Maya控制器', category='animation',
    description=('从 BIP 文件或当前运行的 3ds Max 读取 Biped 动画，并将身体（骨盆+3节脊柱）、头颈、肩膀、双臂和双腿的世界运动转到当前集成角色绑定控制器。'
                 '腰控制器的位移和旋转对应 Bip001 总根 COM；骨盆独立扭转保存在腰控制器的 BIP骨盆旋转 XYZ 通道。'
                 '指定 BIP 文件默认自动调用已安装的后台 Max，无需 Max MCP；不指定文件时读取当前 Max 动作，需 Max MCP。'
                 '默认使用临时 Biped 原生匹配 Maya 骨长并载入动作，不覆盖 Max 原角色动画；指定 BIP 时无需预先手动载入。'
                 'Max 必须退出 Figure Mode；首次用 Maya 创建绑定时姿态与 Max Figure Mode 参考姿态校准，后续重复导入复用校准。默认拒绝覆盖已有普通动画，明确 overwrite=True 才覆盖指定范围并创建可回溯备份。'
                 '不复制手指、动画层或非均匀缩放，不改源骨骼、蒙皮和父子关系。'),
    parameters=obj_schema({
        'root': {'type':'string','default':'customCharacter:character_rig','description':'Maya 集成绑定根'},
        'max_root': {'type':'string','default':'Bip001','description':'Max Biped 根节点'},
        'bip_path': {'type':'string','description':'可选 BIP 文件；原生适配时在临时骨架载入'},
        'backend': {'type':'string','enum':['auto','batch','live'],'default':'auto','description':'auto：指定文件用后台 Max，否则连接当前 Max；batch 无需 MCP'},
        'max_executable': {'type':'string','description':'可选 3dsmaxbatch.exe 路径；默认自动查找'},
        'max_fps': {'type':'integer','minimum':1,'maximum':4800,'default':30,'description':'后台读取源 BIP 使用的帧率，应与制作 BIP 时一致'},
        'start_frame': {'type':'number','description':'Max 起始帧，文件模式默认 BIP 实际范围，当前动作默认 Max 时间范围'},
        'end_frame': {'type':'number','description':'Max 结束帧，文件模式默认 BIP 实际范围，当前动作默认 Max 时间范围'},
        'sample_step': {'type':'number','exclusiveMinimum':0,'default':0.5,'description':'计算采样间隔；source 模式最多 0.25 源帧用于拟合切线，不增加最终关键帧'},
        'native_adaptation': {'type':'boolean','default':True,'description':'使用 Max 临时 Biped 原生适配目标身材'},
        'key_mode': {'type':'string','enum':['source','sampled'],'default':'source','description':'source 按身体、头部、左右手、左右脚独立保留本组源时间点；sampled 按间隔打帧'},
        'reference_frame': {'type':'number','description':'Maya 校准帧，默认当前帧'},
        'overwrite': {'type':'boolean','default':False,'description':'是否覆盖范围内已有普通动画；动画层始终拒绝'},
        'dry_run': {'type':'boolean','default':False,'description':'只检查采样、比例和映射，不写入动画'},
    }))
def retarget_max_bip_animation(root='customCharacter:character_rig', max_root='Bip001', bip_path=None,
                               start_frame=None, end_frame=None, sample_step=0.5,
                               reference_frame=None, overwrite=False, dry_run=False,native_adaptation=True,key_mode='source',
                               backend='auto',max_executable=None,max_fps=30):
    from maya_agent.rigs.bip_retarget import retarget_max_bip
    result=retarget_max_bip(max_root=max_root,bip_path=bip_path,start_frame=start_frame,
        end_frame=end_frame,sample_step=sample_step,root=root,reference_frame=reference_frame,
        overwrite=overwrite,dry_run=dry_run,native_adaptation=native_adaptation,key_mode=key_mode,
        backend=backend,max_executable=max_executable,max_fps=max_fps)
    return ToolResult(ok=True,data=result,message='Max BIP 动画已转移到 Maya 控制器。' if not dry_run else 'Max BIP 映射检查完成。')
