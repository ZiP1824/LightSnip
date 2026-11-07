import json
import startup
from pathlib import Path
from PySide6.QtCore import Qt, QSettings,QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLabel,QPushButton,QListWidget,QStackedWidget,QScrollArea,QFrame,QKeySequenceEdit,
    QCheckBox,QSpinBox,QComboBox,QLineEdit,QFileDialog,QMessageBox,QSlider,QListWidgetItem)
from theme import LIGHT_STYLE,ThemedComboBox
from ui_icons import lucide

DEFAULT_KEYS={1:'Ctrl+Shift+1',2:'Ctrl+Shift+2',3:'Ctrl+Shift+3',4:'',5:'',6:'',7:'',8:'F8'}
ACTION_NAMES={1:'截图',2:'贴图',3:'文字翻译',4:'恢复上次关闭的贴图',5:'关闭所有贴图窗口',6:'隐藏/显示所有贴图窗口',7:'自定义/延时截图',8:'切换窗口边界识别（截图中）'}
CAPTURE_ONLY_ACTIONS={8}


def preferences():
    return QSettings('LightSnip','LightSnip')


def keys():
    cfg=preferences()
    return {n:str(cfg.value(f'keys/{n}',default)) for n,default in DEFAULT_KEYS.items()}


def flag(name,default=False):
    return preferences().value(name,default,type=bool)


NAV_ICONS={'系统':'sliders-horizontal','截图':'scan-line','贴图':'pin','保存':'download','标注':'pencil','快捷键/动作':'command','内置快捷键':'keyboard','关于':'info'}


class SettingsWindow(QDialog):
    def __init__(self,controller):
        super().__init__(None)
        self.controller=controller
        self.setStyleSheet(LIGHT_STYLE)
        self.setWindowTitle('轻截 配置')
        from app import icon
        self.setWindowIcon(icon())
        self.resize(820,680)
        root=QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        left=QWidget()
        left.setObjectName('settingsSidebar')
        left.setFixedWidth(172)
        ll=QVBoxLayout(left)
        ll.setContentsMargins(8,0,8,16)
        self.nav=QListWidget()
        self.nav.setIconSize(QSize(18,18))
        ll.addWidget(self.nav)
        reset=QPushButton('恢复当前页默认设置')
        reset.clicked.connect(self.defaults)
        ll.addWidget(reset)
        root.addWidget(left)
        right=QVBoxLayout()
        right.setContentsMargins(16,16,20,16)
        right.setSpacing(0)
        self.stack=QStackedWidget()
        right.addWidget(self.stack,1)
        right.addSpacing(20)
        self.footer=QWidget()
        bottom=QHBoxLayout(self.footer)
        bottom.setContentsMargins(0,0,0,0)
        bottom.setSpacing(8)
        self.message=QLabel('修改后点击应用，立即生效并保存。')
        self.message.setWordWrap(True)
        self.message.setObjectName('muted')
        bottom.addWidget(self.message,1)
        apply=QPushButton('应用')
        apply.setObjectName('primary')
        apply.setMinimumWidth(76)
        apply.clicked.connect(self.apply)
        bottom.addWidget(apply)
        close=QPushButton('关闭')
        close.setMinimumWidth(76)
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        right.addWidget(self.footer)
        root.addLayout(right,1)
        self.bindings={}
        self.page('系统',self.system_page())
        self.page('截图',self.capture_page())
        self.page('贴图',self.pin_page())
        self.page('保存',self.save_page())
        self.page('标注',self.annotation_page())
        self.page('快捷键/动作',self.hotkey_page())
        self.page('内置快捷键',self.builtin_page())
        self.page('关于',self.about_page())
        self.nav.currentRowChanged.connect(self.change_page)
        self.nav.setCurrentRow(5)

    def page(self,name,widget):
        item=QListWidgetItem(lucide(NAV_ICONS[name],'#64748b',18),name)
        self.nav.addItem(item)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)

    def card(self):
        frame=QFrame()
        frame.setObjectName('card')
        layout=QVBoxLayout(frame)
        layout.setContentsMargins(22,22,22,22)
        layout.setSpacing(16)
        return frame,layout

    def checkbox(self,layout,label,key,default):
        w=QCheckBox(label)
        w.setChecked(flag(key,default))
        layout.addWidget(w)
        self.bindings[key]=(w,default)
        return w

    def spin(self,layout,label,key,default,lo,hi):
        row=QHBoxLayout()
        row.addWidget(QLabel(label),1)
        w=QSlider(Qt.Orientation.Horizontal) if key.startswith('annotation/') else QSpinBox()
        w.setRange(lo,hi)
        w.setValue(preferences().value(key,default,type=int))
        if isinstance(w,QSlider):
            w.setFixedWidth(180)
            number=QLabel(str(w.value()))
            w.valueChanged.connect(lambda value:number.setText(str(value)))
            row.addWidget(number)
        else:w.setFixedWidth(124)
        row.addWidget(w)
        layout.addLayout(row)
        self.bindings[key]=(w,default)
        return w

    def combo(self,layout,label,key,default,items):
        row=QHBoxLayout()
        row.addWidget(QLabel(label),1)
        w=ThemedComboBox()
        w.setFixedWidth(172)
        w.addItems(items)
        w.setCurrentText(str(preferences().value(key,default)))
        row.addWidget(w)
        layout.addLayout(row)
        self.bindings[key]=(w,default)

    def system_page(self):
        f,l=self.card()
        l.addWidget(QLabel('常规'))
        self.autostart=self.checkbox(l,'开机自动启动','system/autostart',False)
        try:
            self.autostart.setChecked(startup.is_enabled())
        except OSError as exc:
            self.message.setText(f'无法读取开机启动设置：{exc}')
        note=QLabel('登录 Windows 后自动驻留托盘。绿色版移动文件夹后，请重新开启此项并应用。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        l.addWidget(note)
        self.checkbox(l,'启动后显示配置窗口','system/show_settings',True)
        self.checkbox(l,'关闭配置窗口后驻留托盘','system/tray',True)
        l.addWidget(QLabel('托盘左键双击：开始截图；右键：动作菜单与配置。'))
        l.addStretch()
        return f

    def capture_page(self):
        f,l=self.card()
        self.checkbox(l,'显示信息栏','capture/info',True)
        self.checkbox(l,'显示放大镜','capture/magnifier',True)
        self.checkbox(l,'显示快捷键提示','capture/hints',True)
        self.checkbox(l,'自动识别窗口边界','capture/window_detection',True)
        note=QLabel('悬停识别窗口、控件与文字行；滚轮切换上层/下层范围，Tab 切换整窗。\n单击确定，拖动可手动框选。文字区域在本机识别，无需联网。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        l.addWidget(note)
        self.checkbox(l,'显示选区中心辅助线','capture/guides',False)
        self.combo(l,'左键双击动作','capture/double','复制',['复制','贴图','保存'])
        self.spin(l,'延时截图秒数','capture/delay',3,0,60)
        l.addWidget(QLabel('选区边缘拖动调整大小；内部拖动移动；工具栏原位标注。'))
        l.addStretch()
        return f

    def pin_page(self):
        f,l=self.card()
        self.spin(l,'默认不透明度（%）','pin/opacity',100,20,100)
        self.checkbox(l,'贴图时同时复制到剪贴板','pin/copy',False)
        self.combo(l,'左键双击动作','pin/double','关闭',['关闭','恢复原始大小'])
        l.addWidget(QLabel('滚轮缩放，右键可翻转、OCR、翻译、调节透明度。'))
        l.addStretch()
        return f

    def save_page(self):
        from file_names import save_directory,save_location_events
        f,l=self.card()
        l.addWidget(QLabel('截图保存文件夹'))
        self.save_dir=QLineEdit(str(save_directory()))
        self.save_dir.textChanged.connect(lambda:self.save_dir.setModified(True))
        save_location_events().changed.connect(self.saved_directory_changed)
        l.addWidget(self.save_dir)
        b=QPushButton('选择文件夹')
        def browse():
            path=QFileDialog.getExistingDirectory(self,'截图保存文件夹',self.save_dir.text())
            if path:self.save_dir.setText(path)
        b.clicked.connect(browse)
        l.addWidget(b)
        note=QLabel('保存窗口会记住上次成功保存的位置。也可在这里指定文件夹并点击应用；Ctrl+S 会直接保存到此文件夹。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        l.addWidget(note)
        l.addWidget(QLabel('文件名示例：轻截-20261106-153012-123456.png\n名称后附日期、时间和微秒，同一秒内连续截图也不会重名。\n截图选区按 Ctrl+S 快速保存；工具栏保存按钮可另存。'))
        l.addStretch()
        return f

    def annotation_page(self):
        f,l=self.card()
        self.spin(l,'默认线条粗细','annotation/width',4,1,32)
        self.spin(l,'默认箭头粗细','annotation/arrow_width',8,1,32)
        self.spin(l,'默认文字字号','annotation/font',20,10,96)
        self.combo(l,'默认标注颜色','annotation/color','#ff535d',['#ff535d','#3286f5','#35b66a','#ffcc33','#ffffff','#151515'])
        l.addWidget(QLabel('矩形、椭圆、箭头、画笔、荧光笔、马赛克、文字、序号。'))
        l.addStretch()
        return f

    def hotkey_page(self):
        f,l=self.card()
        self.key_edits={}
        for n,name in ACTION_NAMES.items():
            row=QHBoxLayout()
            row.addWidget(QLabel(name),1)
            edit=QKeySequenceEdit(QKeySequence(keys()[n]))
            if edit.layout():edit.layout().setContentsMargins(0,0,0,0)
            edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(190)
            edit.setToolTip('点击后直接按下新的组合键；退格或清除按钮可取消绑定。')
            edit.findChild(QLineEdit).setPlaceholderText('按下快捷键')
            row.addWidget(edit)
            clear=QPushButton('×')
            clear.setFixedWidth(32)
            clear.clicked.connect(edit.clear)
            row.addWidget(clear)
            self.key_edits[n]=edit
            l.addLayout(row)
        tip=QLabel('点击快捷键框录入组合键，然后点击应用。\n窗口边界识别快捷键仅在截图期间生效。\n与其他程序冲突时会提示，原有绑定会恢复。')
        tip.setWordWrap(True)
        tip.setObjectName('muted')
        l.addWidget(tip)
        l.addStretch()
        return f

    def builtin_page(self):
        f,l=self.card()
        row=QHBoxLayout()
        row.addWidget(QLabel('开关窗口边界识别'),1)
        self.detection_shortcut_label=QLabel(keys()[8] or '未设置')
        row.addWidget(self.detection_shortcut_label)
        l.addLayout(row)
        for name,key in [('选择上层 / 下层元素','鼠标滚轮'),('切换整窗 / 内部元素','Tab'),('取消截图','Esc / 右键'),('复制并结束截图','Enter / Ctrl+C'),('快速保存','Ctrl+S'),('贴图','Ctrl+T'),('识别选区文字','Shift+C'),('选择/移动选区','V'),('矩形 / 椭圆 / 箭头','R / O / A'),('画笔 / 荧光笔 / 马赛克','P / H / M'),('文字 / 序号','T / N'),('撤销 / 重做','Ctrl+Z / Ctrl+Y'),('微调选区位置','方向键'),('调整选区右下角','Shift+方向键')]:
            row=QHBoxLayout()
            row.addWidget(QLabel(name),1)
            row.addWidget(QLabel(key))
            l.addLayout(row)
        l.addStretch()
        return f

    def about_page(self):
        f,l=self.card()
        l.addWidget(QLabel('轻截 LightSnip 0.27'))
        developer=QLabel('开发者：ZiP1824')
        developer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        l.addWidget(developer)
        email=QLabel('邮箱：<a href="mailto:zhangxh1994@gmail.com">zhangxh1994@gmail.com</a>')
        email.setOpenExternalLinks(True)
        email.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        l.addWidget(email)
        label=QLabel('轻巧易用的截图与翻译工具。\n截图、标注、置顶贴图、本地文字识别、免费联网翻译。\n\n公式/表格识别、图片覆盖翻译暂未提供。')
        label.setWordWrap(True)
        l.addWidget(label)
        b=QPushButton('开始截图')
        b.clicked.connect(self.controller.capture)
        l.addWidget(b)
        l.addStretch()
        return f

    def change_page(self,n):
        if n==3:self.refresh_save_directory()
        self.stack.setCurrentIndex(n)
        for index in range(self.nav.count()):
            item=self.nav.item(index)
            item.setIcon(lucide(NAV_ICONS[item.text()],'#ffffff' if index==n else '#64748b',18))

    def defaults(self):
        if self.nav.currentRow()==5:
            for n,w in self.key_edits.items():w.setKeySequence(QKeySequence(DEFAULT_KEYS[n]))
        elif self.nav.currentRow()==3:
            from file_names import default_save_directory
            self.save_dir.setText(str(default_save_directory()))
        else:
            page=self.stack.currentWidget().widget()
            for w,value in self.bindings.values():
                if page.isAncestorOf(w):
                    if isinstance(w,QCheckBox):w.setChecked(value)
                    elif isinstance(w,(QSpinBox,QSlider)):w.setValue(value)
                    elif isinstance(w,QComboBox):w.setCurrentText(value)
        self.message.setText('已填入默认值，点击应用保存。')

    def apply(self):
        directory=None
        if self.save_dir.isModified():
            directory=Path(self.save_dir.text().strip()).expanduser()
            if not self.save_dir.text().strip() or not directory.is_absolute():
                self.message.setText('请输入完整的保存文件夹路径。')
                return
            try:directory.mkdir(parents=True,exist_ok=True)
            except OSError as exc:
                self.message.setText(f'保存文件夹不可用：{exc}')
                return
        new={n:w.keySequence().toString(QKeySequence.SequenceFormat.PortableText) for n,w in self.key_edits.items()}
        ok,message=self.controller.hotkeys.rebind(new)
        if not ok:
            self.message.setText(message)
            return
        try:
            startup.set_enabled(self.autostart.isChecked())
        except OSError as exc:
            self.controller.hotkeys.rebind(keys())
            self.message.setText(f'开机自动启动设置失败：{exc}')
            return
        cfg=preferences()
        for n,value in new.items():cfg.setValue(f'keys/{n}',value)
        for key,(w,_) in self.bindings.items():
            value=w.isChecked() if isinstance(w,QCheckBox) else w.value() if isinstance(w,(QSpinBox,QSlider)) else w.currentText()
            cfg.setValue(key,value)
        cfg.sync()
        self.detection_shortcut_label.setText(new.get(8,'') or '未设置')
        callback=getattr(self.controller,'set_window_detection',None)
        if callable(callback):callback(flag('capture/window_detection',True))
        if directory is not None:
            from file_names import set_save_directory
            set_save_directory(directory)
        self.save_dir.setModified(False)
        self.refresh_save_directory()
        self.controller.rebuild_tray()
        self.message.setText('已保存并生效。')

    def refresh_save_directory(self):
        if hasattr(self,'save_dir') and not self.save_dir.isModified():
            from file_names import save_directory
            self.save_dir.setText(str(save_directory()))
            self.save_dir.setModified(False)

    def saved_directory_changed(self,directory):
        # A completed save is the latest authoritative choice, including when
        # this window still contains an older un-applied folder edit.
        self.save_dir.setText(directory)
        self.save_dir.setModified(False)

    def showEvent(self,event):
        self.refresh_save_directory()
        super().showEvent(event)

    def closeEvent(self,e):
        if not flag('system/tray',True):
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()
        e.accept()
