"""Chinese file workflow for the offline Android editor (Maya 2024 / PySide2)."""
import json,traceback,tempfile
from pathlib import Path
from datetime import datetime
from PySide2 import QtCore,QtWidgets
import maya.cmds as c
from . import service,VERSION

_instance=globals().get('_instance')

class ExchangeWindow(QtWidgets.QDialog):
    def __init__(self):
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
        super().__init__(wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()),QtWidgets.QWidget))
        self.setObjectName('MayaMobileExchangeWindow');self.setWindowTitle('Maya ↔ 安卓 · 工程与动画互通 '+VERSION)
        self.setWindowFlags(self.windowFlags()|QtCore.Qt.Window);self.resize(640,590);self.busy=False;self.last_report=None
        self.setStyleSheet('QDialog{background:#353940;color:#eee} QLabel,QGroupBox{color:#eee} QLineEdit,QComboBox,QSpinBox,QPlainTextEdit{background:#25292f;color:#eee;padding:5px;border:1px solid #59616b} QPushButton{padding:8px} QTabWidget::pane{border:1px solid #59616b}')
        layout=QtWidgets.QVBoxLayout(self);layout.setSpacing(10)
        title=QtWidgets.QLabel('手机工程 / 动画互通');title.setStyleSheet('font-size:20px;font-weight:600');layout.addWidget(title)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('当前角色'));self.characters=QtWidgets.QComboBox();self.characters.setMinimumWidth(300);row.addWidget(self.characters,1)
        self.refresh_button=QtWidgets.QPushButton('刷新 / 识别选择');self.refresh_button.clicked.connect(lambda:self.run(self.refresh));row.addWidget(self.refresh_button);layout.addLayout(row)
        self.character_info=QtWidgets.QLabel();self.character_info.setWordWrap(True);layout.addWidget(self.character_info);self.characters.currentIndexChanged.connect(self.update_info)
        self.tabs=QtWidgets.QTabWidget();layout.addWidget(self.tabs)
        # Page 1: only the two export operations. The current role is already
        # selected above, so no project file is needed for animation export.
        page=QtWidgets.QWidget();form=QtWidgets.QVBoxLayout(page);self.tabs.addTab(page,'导出')
        note=QtWidgets.QLabel('当前角色：导出工程文件或动画文件。动画会自动记录当前工程身份。');note.setWordWrap(True);form.addWidget(note)
        self.project_out=QtWidgets.QLineEdit();form.addWidget(self.labeled('工程文件名',self.project_out))
        self.export_button=QtWidgets.QPushButton('导出工程');self.export_button.setStyleSheet('background:#327d81;color:white;font-weight:600;padding:11px');self.export_button.clicked.connect(lambda:self.run(self.perform_export));form.addWidget(self.export_button)
        self.animation_out=QtWidgets.QLineEdit();form.addWidget(self.labeled('动画文件名',self.animation_out))
        self.animation_export_button=QtWidgets.QPushButton('导出动画文件');self.animation_export_button.clicked.connect(lambda:self.run(self.perform_animation_export));form.addWidget(self.animation_export_button)
        range_row=QtWidgets.QHBoxLayout();range_row.addWidget(QtWidgets.QLabel('工程动画范围'));self.start=QtWidgets.QSpinBox();self.start.setRange(0,100000);range_row.addWidget(self.start);range_row.addWidget(QtWidgets.QLabel('到'));self.end=QtWidgets.QSpinBox();self.end.setRange(0,100000);range_row.addWidget(self.end);use_range=QtWidgets.QPushButton('读取播放范围');use_range.clicked.connect(self.timeline_range);range_row.addWidget(use_range);form.addLayout(range_row)
        tip=QtWidgets.QLabel('导出工程不附带动画；动画文件单独保存，一个工程可对应多个动画。');tip.setWordWrap(True);form.addWidget(tip);form.addStretch()
        # Hidden compatibility fields are populated when a network animation
        # is downloaded and applied; they are no longer user-facing selectors.
        self.source_project=QtWidgets.QLineEdit();self.source_project.setVisible(False);self.animation_file=QtWidgets.QLineEdit();self.animation_file.setVisible(False);self.import_button=QtWidgets.QPushButton();self.import_button.setEnabled(False)
        # Page 2: network animation discovery and direct application.
        page=QtWidgets.QWidget();form=QtWidgets.QVBoxLayout(page);self.tabs.addTab(page,'联网下载')
        note=QtWidgets.QLabel('打开当前角色后，列表会自动匹配对应工程，并显示服务器上的动画和保存时间。选择动画后直接下载并应用。');note.setWordWrap(True);form.addWidget(note)
        settings=QtCore.QSettings('MayaAgent','MobileExchange');saved_url=str(settings.value('url','') or '').strip()
        if not saved_url or 'fd7a:115c:a1e0::ab3b:8149' in saved_url or '100.114.129.72' in saved_url or 'lempet.top' in saved_url:saved_url='http://wang.tail26a65a.ts.net:8765'
        self.remote_url=QtWidgets.QLineEdit();self.remote_url.setPlaceholderText('http://wang.tail26a65a.ts.net:8765');self.remote_url.setText(saved_url);form.addWidget(self.labeled('Tailscale 地址',self.remote_url))
        self.remote_token=QtWidgets.QLineEdit();self.remote_token.setEchoMode(QtWidgets.QLineEdit.Password);self.remote_token.setPlaceholderText('访问令牌');self.remote_token.setText(str(settings.value('token','') or ''));form.addWidget(self.labeled('访问令牌',self.remote_token))
        actions=QtWidgets.QHBoxLayout();test=QtWidgets.QPushButton('测试连接');test.clicked.connect(lambda:self.run(self.perform_remote_health));refresh=QtWidgets.QPushButton('刷新动画');refresh.clicked.connect(lambda:self.run(self.perform_remote_list));actions.addWidget(test);actions.addWidget(refresh);form.addLayout(actions)
        self.remote_files=QtWidgets.QComboBox();self.remote_files.setMinimumHeight(38);form.addWidget(self.labeled('服务器工程',self.remote_files));self.remote_files.currentIndexChanged.connect(self.filter_remote_animations);self.remote_animations=QtWidgets.QComboBox();self.remote_animations.setMinimumHeight(38);form.addWidget(self.labeled('匹配动画',self.remote_animations))
        actions=QtWidgets.QHBoxLayout();apply_anim=QtWidgets.QPushButton('下载并应用动画');apply_anim.clicked.connect(lambda:self.run(self.perform_remote_apply_animation));actions.addWidget(apply_anim);form.addLayout(actions)
        tip=QtWidgets.QLabel('工程和动画按文件内身份自动匹配，不需要手动指定工程文件。导出只需命名并上传服务器；无需选择本地路径。同名上传会更新服务器文件。');tip.setWordWrap(True);form.addWidget(tip);form.addStretch()
        self.status=QtWidgets.QLabel('就绪');self.status.setWordWrap(True);self.status.setMinimumHeight(44);layout.addWidget(self.status)
        self.log=QtWidgets.QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(130);layout.addWidget(self.log)
        self.remote_rows={};self.remote_animation_rows={}
        self.refresh();self.timeline_range();QtCore.QTimer.singleShot(0,self.auto_remote_list)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S');self.project_out.setText('character_'+stamp);self.animation_out.setText('animation_'+stamp)
        for edit in (self.project_out,self.animation_out):
            edit.editingFinished.connect(lambda field=edit:field.setText(self.bare_name(field.text())))

    @staticmethod
    def bare_name(value):
        value=value.strip()
        for suffix in ('.mobile.json','.json'):
            if value.lower().endswith(suffix):return value[:-len(suffix)]
        return value
    def labeled(self,label,widget):
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel(label));row.addWidget(widget,1);box=QtWidgets.QWidget();box.setLayout(row);return box

    def root(self):
        value=self.characters.currentData()
        if not value:raise ValueError('当前场景没有集成角色绑定，请先创建或打开对应 Maya 场景。')
        return service.identity(value)[0]

    def refresh(self):
        previous=self.characters.currentData();selected=c.ls(sl=True,long=True) or [];available=service.roots();self.characters.blockSignals(True);self.characters.clear();chosen=0
        for i,root in enumerate(available):
            _,uid,_=service.identity(root);self.characters.addItem(root.rsplit('|',1)[-1],uid)
            if uid==previous:chosen=i
            if any(n==root or n.startswith(root+'|') for n in selected):chosen=i
        self.characters.setCurrentIndex(chosen);self.characters.blockSignals(False);self.update_info();self.invalidate_check()

    def update_info(self,*_):
        try:
            root,uid,meta=service.identity(self.characters.currentData());self.character_info.setText('绑定版本 '+str(meta['version'])+'  ·  当前帧 '+str(c.currentTime(q=True))+'\n'+root)
        except Exception:self.character_info.setText('未找到集成角色绑定。')

    def timeline_range(self):self.start.setValue(int(c.playbackOptions(q=True,minTime=True)));self.end.setValue(int(c.playbackOptions(q=True,maxTime=True)))
    def invalidate_check(self,*_):
        if hasattr(self,'import_button'):self.import_button.setEnabled(False)
    def progress(self,text):self.status.setText(text);QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
    def run(self,callback,notify=True):
        if self.busy:return
        self.busy=True;self.tabs.setEnabled(False);self.refresh_button.setEnabled(False);self.characters.setEnabled(False)
        try:
            self.last_report=callback()
            if self.last_report is not None:self.log.setPlainText(json.dumps(self.last_report,ensure_ascii=False,indent=2))
            if notify:self.notice(True,self.status.text() if self.last_report is not None else '刷新完成')
            return self.last_report
        except Exception as error:
            self.invalidate_check();self.status.setText('未完成：'+str(error));self.log.setPlainText(traceback.format_exc());c.warning(str(error));self.notice(False,str(error))
        finally:self.busy=False;self.tabs.setEnabled(True);self.refresh_button.setEnabled(True);self.characters.setEnabled(True);self.update_info()
    def notice(self,ok,text):
        box=QtWidgets.QMessageBox(self);box.setWindowTitle('操作成功' if ok else '操作失败');box.setIcon(QtWidgets.QMessageBox.Information if ok else QtWidgets.QMessageBox.Critical);box.setText(text);box.setAttribute(QtCore.Qt.WA_DeleteOnClose);box.open();self._notice=box
    def perform_export(self):
        url,token=self.remote_args()
        report=service.export_to_server(self.root(),self.project_out.text(),url,token,True,self.start.value(),self.end.value(),self.progress)
        self.perform_remote_list(preferred=report['name']);self.status.setText('工程已上传服务器：'+report['name']);return report
    def perform_animation_export(self):
        url,token=self.remote_args()
        report=service.export_to_server(self.root(),self.animation_out.text(),url,token,progress=self.progress,project_name=self.remote_files.currentData())
        self.perform_remote_list();self.status.setText('动画已上传服务器：'+report['name']);return report
    def perform_check(self):
        report=service.import_animation(self.root(),self.source_project.text().strip(),self.animation_file.text().strip(),True);self.import_button.setEnabled(True);self.status.setText('检查通过：'+str(report['keys'])+' 条控制器帧，'+str(report['channelKeys'])+' 个通道键。可点击“导入动画到 Maya”。');return report
    def perform_import(self):
        # Always recheck live identity and channels immediately before writing.
        service.import_animation(self.root(),self.source_project.text().strip(),self.animation_file.text().strip(),True)
        report=service.import_animation(self.root(),self.source_project.text().strip(),self.animation_file.text().strip(),False);self.invalidate_check();self.status.setText('动画已导入，可 Ctrl+Z 撤销。原曲线备份路径见下方结果。');return report
    def remote_args(self):
        url=self.remote_url.text().strip();token=self.remote_token.text();
        settings=QtCore.QSettings('MayaAgent','MobileExchange');settings.setValue('url',url);settings.setValue('token',token)
        if not url or not token: raise ValueError('请填写服务器地址和访问令牌。')
        return url,token
    def perform_remote_health(self):
        url,token=self.remote_args();report=service.network_health(url,token);self.status.setText('连接成功：'+str(report.get('root','')));return report
    def auto_remote_list(self):
        if self.remote_url.text().strip() and self.remote_token.text().strip():
            self.run(self.perform_remote_list,notify=False)
    def _saved_time(self,row):
        try:return datetime.fromtimestamp(float(row.get('mtime',0))).strftime('%Y-%m-%d %H:%M')
        except Exception:return '时间未知'
    def perform_remote_list(self,preferred=None):
        url,token=self.remote_args();report=service.network_list(url,token)
        previous=preferred or self.remote_files.currentData()
        uid=self.characters.currentData();version=str(service.identity(uid)[2]['version'])
        rows=[r for r in report.get('files',[]) if r.get('characterId')==uid and str(r.get('rigVersion',''))==version]
        rows.sort(key=lambda r:float(r.get('mtime',0)),reverse=True)
        self.remote_rows={r['name']:r for r in rows};self.remote_files.blockSignals(True);self.remote_files.clear()
        for r in rows:
            if r.get('format')=='maya-mobile-project':self.remote_files.addItem('%s  · 保存 %s'%(r['name'],self._saved_time(r)),r['name'])
        index=self.remote_files.findData(previous)
        if index>=0:self.remote_files.setCurrentIndex(index)
        self.remote_files.blockSignals(False);self.filter_remote_animations()
        self.status.setText('刷新完成：%d 个工程，所选工程 %d 个动画'%(self.remote_files.count(),self.remote_animations.count()))
        return {'projects':self.remote_files.count(),'animations':self.remote_animations.count()}
    def filter_remote_animations(self,*_):
        if not hasattr(self,'remote_rows'):return
        project=self.remote_rows.get(self.remote_files.currentData(),{})
        previous=self.remote_animations.currentData();self.remote_animations.clear();self.remote_animation_rows={}
        for name,row in self.remote_rows.items():
            if row.get('format')=='maya-mobile-animation' and service.matching_project(project,row):
                self.remote_animation_rows[name]=row;self.remote_animations.addItem('%s  · 保存 %s'%(name,self._saved_time(row)),name)
        index=self.remote_animations.findData(previous)
        if index>=0:self.remote_animations.setCurrentIndex(index)
    def perform_remote_apply_animation(self):
        url,token=self.remote_args();name=self.remote_animations.currentData();row=self.remote_animation_rows.get(name or '')
        if not row:raise ValueError('请先刷新并选择当前角色动画。')
        projects=[r for r in self.remote_rows.values() if service.matching_project(r,row)]
        if not projects:raise ValueError('未找到与该动画快照匹配的工程文件。请先上传对应工程。')
        with tempfile.TemporaryDirectory(prefix='maya_server_import_') as directory:
            project_target=Path(directory)/'project.mobile.json';animation_target=Path(directory)/'animation.json'
            service.network_download(url,token,projects[0]['name'],project_target);service.network_download(url,token,name,animation_target)
            service.import_animation(self.root(),str(project_target),str(animation_target),True)
            report=service.import_animation(self.root(),str(project_target),str(animation_target),False)
        self.status.setText('已下载匹配工程并应用动画：'+name);return report



def show():
    global _instance
    if _instance is not None:
        try:_instance.show();_instance.raise_();_instance.activateWindow();return _instance
        except RuntimeError:pass
    _instance=ExchangeWindow();_instance.show();return _instance
