import math
from PySide6.QtCore import Qt,QPoint,QPointF,QRect,QSize,Signal,QEvent
from PySide6.QtGui import QPainter,QPen,QBrush,QColor,QPolygonF,QPixmap,QIcon,QCursor,QFont
from PySide6.QtWidgets import (QApplication,QFrame,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSlider,
    QToolButton,QMenu,QColorDialog,QPushButton,QWidgetAction,QFontComboBox,QComboBox,QListWidget)
from ui_icons import lucide
from theme import ThemedFontComboBox

ARROWS=['渐细箭头','实心箭头','双向实心箭头','开放箭头','双向开放箭头','两端端线','直线','圆点箭头']
DASHES={'实线':Qt.PenStyle.SolidLine,'虚线':Qt.PenStyle.DashLine,'点线':Qt.PenStyle.DotLine,'点划线':Qt.PenStyle.DashDotLine,'双点划线':Qt.PenStyle.DashDotDotLine}
PALETTE=['#ff535d','#d7442c','#f08a35','#f5c65a','#ffe875','#75b65d','#26a979','#49c9bc','#54b8ec','#548de1','#5461c8','#9060d5','#ca65b5','#f6a5c0','#ffffff','#b8bdc5','#727984','#151515']
BORDER_WIDTH=4


def draw_arrow(p,start,end,color,width,style,dash=Qt.PenStyle.SolidLine):
    a,b=QPointF(start),QPointF(end)
    dx,dy=b.x()-a.x(),b.y()-a.y()
    length=math.hypot(dx,dy)
    if length<1:return
    ux,uy=dx/length,dy/length
    size=min(max(12,width*3.6),length*.45)
    normal=QPointF(-uy,ux)
    pen=QPen(color,width,dash,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if style=='渐细箭头':
        base=b-QPointF(ux,uy)*size
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([a,base+normal*width*.6,base+normal*size*.42,b,base-normal*size*.42,base-normal*width*.6]))
        return
    filled=style in ['实心箭头','双向实心箭头','圆点箭头']
    shaft_start=a+QPointF(ux,uy)*size*.7 if style=='双向实心箭头' else a
    shaft_end=b-QPointF(ux,uy)*size*.7 if filled else b
    p.drawLine(shaft_start,shaft_end)
    if style=='直线':return
    if style=='两端端线':
        p.setPen(QPen(color,width,Qt.PenStyle.SolidLine))
        for point in [a,b]:p.drawLine(point-normal*size*.5,point+normal*size*.5)
        return
    def head(tip,direction):
        back=tip-QPointF(ux,uy)*size*direction
        left,right=back+normal*size*.42,back-normal*size*.42
        p.setPen(QPen(color,max(1,width*.75),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        if '开放' in style:
            p.drawLine(left,tip)
            p.drawLine(tip,right)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPolygon(QPolygonF([tip,left,right]))
    head(b,1)
    if style.startswith('双向'):head(a,-1)
    if style=='圆点箭头':
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(a,max(3,width*1.4),max(3,width*1.4))


def sample_icon(kind,name):
    pix=QPixmap(96,28)
    pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind=='arrow':draw_arrow(p,QPoint(10,14),QPoint(86,14),QColor('#000000'),2,name)
    elif kind=='dash':
        p.setPen(QPen(QColor('#000000'),2,DASHES[name]))
        p.drawLine(8,14,88,14)
    elif kind=='shape':
        p.setPen(QPen(QColor('black'),2))
        if name=='椭圆':p.drawEllipse(32,4,32,20)
        elif name=='圆角矩形':p.drawRoundedRect(QRect(32,4,32,20),6,6)
        else:p.drawRect(32,4,32,20)
    elif kind=='pen':
        p.drawPixmap(36,2,lucide('highlighter' if name=='荧光笔' else 'pencil',size=24).pixmap(24,24))
    elif kind=='mosaic':
        if name=='画笔涂抹':
            p.drawPixmap(23,2,lucide('pencil',size=24).pixmap(24,24))
            p.drawPixmap(50,5,lucide('pixel-mosaic',size=18).pixmap(18,18))
        else:
            p.setPen(QPen(QColor('black'),1.5,Qt.PenStyle.DashLine))
            p.drawRect(27,3,40,22)
            p.drawPixmap(39,6,lucide('pixel-mosaic',size=16).pixmap(16,16))
    p.end()
    return QIcon(pix)


class PreviewSelector(QToolButton):
    currentTextChanged=Signal(str)

    def __init__(self,kind,names,parent=None):
        super().__init__(parent)
        self.kind=kind
        self.names=names
        self.name=names[0]
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setIconSize(QSize(78,24))
        self.setFixedSize(86,32)
        self.setStyleSheet('QToolButton {background:#f0f1f3;border:0;border-radius:6px;padding:2px;} QToolButton:hover {background:#e2ebf8;} QToolButton::menu-indicator {image:none;width:0;}')
        self.setIcon(sample_icon(kind,self.name))
        menu=QMenu(self)
        menu.setCursor(Qt.CursorShape.ArrowCursor)
        menu.setStyleSheet('QMenu {background:white;border:1px solid #d9dde3;border-radius:5px;padding:5px;}')
        for name in names:
            action=QWidgetAction(menu)
            preview=QToolButton(menu)
            preview.setIcon(sample_icon(kind,name))
            preview.setIconSize(QSize(88,24))
            preview.setFixedSize(106,34)
            preview.setToolTip(name)
            preview.setAccessibleName(name)
            preview.setStyleSheet('QToolButton {background:white;border:0;border-radius:4px;} QToolButton:hover {background:#deebfc;}')
            def choose(_,value=name):
                self.setCurrentText(value)
                menu.close()
            preview.clicked.connect(choose)
            action.setDefaultWidget(preview)
            menu.addAction(action)
        self.setMenu(menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def setIcon(self,icon):
        pix=QPixmap(78,24)
        pix.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pix)
        painter.drawPixmap(0,2,icon.pixmap(58,20))
        painter.drawPixmap(64,7,lucide('chevron-down',size=10).pixmap(10,10))
        painter.end()
        super().setIcon(QIcon(pix))

    def currentText(self):return self.name

    def setCurrentText(self,name):
        if name not in self.names or name==self.name:return
        self.name=name
        self.setToolTip(name)
        self.setIcon(sample_icon(self.kind,name))
        self.currentTextChanged.emit(name)


def tool_cursor(mode,color):
    return QCursor(Qt.CursorShape.ArrowCursor)


def badge_icon(mode,color):
    names={'矩形':'square','圆角矩形':'square','椭圆':'circle','箭头':'annotation-arrow','画笔':'pencil','荧光笔':'highlighter','马赛克':'pixel-mosaic','序号':'list-ordered'}
    return lucide('type' if mode=='文字' else names.get(mode,'pencil'),color.name(),16).pixmap(16,16)


class SelectionBorder(QWidget):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def paintEvent(self,event):
        r=self.owner.rect_selected
        if r is None:return
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor('#3286ff'),BORDER_WIDTH))
            p.drawRect(r)
            p.setPen(QPen(QColor('white'),1.5))
            p.setBrush(QColor('#3286ff'))
            for pt in self.owner.handles(r):p.drawEllipse(pt,4.5,4.5)


class AnnotationOptions(QFrame):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.arrow_style='渐细箭头'
        self.dash_name='实线'
        from settings_ui import preferences
        self.line_width=preferences().value('annotation/width',4,type=int)
        self.width_mode='line'
        self.widths={'line':self.line_width,'arrow':preferences().value('annotation/arrow_width',8,type=int)}
        self.font_size=preferences().value('annotation/font',20,type=int)
        self.opacity=255
        self.block_size=14
        self.mosaic_style='矩形框选'
        self.mosaic_width=32
        self.color=QColor(str(preferences().value('annotation/color','#ff535d')))
        self.fill_shape=False
        self.font_family='Microsoft YaHei UI'
        self.text_bold=False
        self.text_italic=False
        self.setStyleSheet('QFrame {background:#fafafa;border:1px solid #d9dde3;border-radius:7px;} QLabel {border:0;background:transparent;font-size:12px;} QToolButton {border:0;border-radius:6px;background:#f0f1f3;padding:3px;} QToolButton:hover {background:#e0ebfa;} QSlider {border:0;} QSlider::groove:horizontal {height:4px;background:#dfe4eb;border-radius:2px;} QSlider::sub-page:horizontal {background:#3286ff;border-radius:2px;} QSlider::handle:horizontal {background:white;border:2px solid #3286ff;width:10px;margin:-5px 0;border-radius:6px;}')
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,6,8,6)
        layout.setSpacing(6)
        row=QHBoxLayout()
        row.setSpacing(9)
        self.shape_choice=PreviewSelector('shape',['矩形','圆角矩形','椭圆'],self)
        self.shape_choice.currentTextChanged.connect(self.owner.tool)
        row.addWidget(self.shape_choice)
        self.pen_choice=PreviewSelector('pen',['画笔','荧光笔'],self)
        self.pen_choice.currentTextChanged.connect(self.owner.tool)
        row.addWidget(self.pen_choice)
        self.arrow_button=self.choice(row,'arrow',ARROWS,self.choose_arrow)
        self.dash_button=self.choice(row,'dash',list(DASHES),self.choose_dash)
        self.mosaic_choice=PreviewSelector('mosaic',['矩形框选','画笔涂抹'],self)
        self.mosaic_choice.setToolTip('马赛克方式：矩形框选 / 画笔涂抹')
        self.mosaic_choice.currentTextChanged.connect(self.choose_mosaic)
        row.addWidget(self.mosaic_choice)
        self.fill_button=QToolButton()
        self.fill_button.setText('空心')
        self.fill_button.setCheckable(True)
        self.fill_button.toggled.connect(self.fill_changed)
        row.addWidget(self.fill_button)
        self.width_widget=self.slider(row,'粗细',1,32,self.line_width,self.set_width)
        self.font_widget=self.slider(row,'字号',10,96,self.font_size,lambda v:self.set_value('font_size',v))
        self.delete_number_button=QToolButton()
        self.delete_number_button.setText('删除序号')
        self.delete_number_button.setToolTip('点击序号选中后删除，也可按 Delete')
        self.delete_number_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_number_button.clicked.connect(self.delete_number)
        row.addWidget(self.delete_number_button)
        self.font_controls=QWidget()
        fonts=QHBoxLayout(self.font_controls)
        fonts.setContentsMargins(0,0,0,0)
        self.edit_text_button=QToolButton()
        self.edit_text_button.setText('编辑文字 ▾')
        self.edit_text_button.setToolTip('从已添加的文字中选择一条进行修改')
        self.text_list=QListWidget(owner)
        self.text_list.setStyleSheet('QListWidget {background:white;border:1px solid #cbd5e1;border-radius:6px;padding:4px;color:#243449;} QListWidget::item {padding:7px;} QListWidget::item:hover,QListWidget::item:selected {background:#e6f0ff;color:#172b4d;}')
        self.text_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_list.setCursor(Qt.CursorShape.ArrowCursor)
        self.text_list.itemClicked.connect(self.open_text_item)
        self.text_list.itemActivated.connect(self.open_text_item)
        self.text_list.hide()
        self.edit_text_button.clicked.connect(self.toggle_text_list)
        fonts.addWidget(self.edit_text_button)
        self.font_picker=ThemedFontComboBox()
        self.font_picker.setFixedWidth(145)
        self.font_picker.setCurrentFont(QFont(self.font_family))
        self.font_picker.currentFontChanged.connect(lambda font:self.set_value('font_family',font.family()))
        fonts.addWidget(self.font_picker)
        self.text_style_buttons={}
        for label,name in [('B','text_bold'),('I','text_italic')]:
            button=QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip('粗体' if label=='B' else '斜体')
            button.toggled.connect(lambda on,n=name:self.set_value(n,on))
            self.text_style_buttons[name]=button
            fonts.addWidget(button)
        row.addWidget(self.font_controls)
        self.mosaic_widget=self.slider(row,'颗粒',4,40,self.block_size,lambda v:self.set_value('block_size',v))
        self.mosaic_brush_widget=self.slider(row,'笔刷',4,160,self.mosaic_width,lambda v:self.set_value('mosaic_width',v))
        self.opacity_widget=self.slider(row,'不透明度%',10,100,100,lambda v:self.set_value('opacity',round(v*255/100)))
        layout.addLayout(row)
        self.colors_widget=QWidget()
        colors=QHBoxLayout(self.colors_widget)
        colors.setContentsMargins(0,0,0,0)
        colors.setSpacing(5)
        self.swatches=[]
        for color in PALETTE:
            b=QToolButton()
            b.setFixedSize(22,22)
            b.setToolTip(color)
            b.clicked.connect(lambda _,c=color:self.set_color(QColor(c)))
            colors.addWidget(b)
            self.swatches.append((b,color))
        custom=QToolButton()
        custom.setIcon(lucide('pencil',size=16))
        custom.setToolTip('自定义颜色')
        custom.clicked.connect(self.custom_color)
        colors.addWidget(custom)
        colors.addStretch()
        layout.addWidget(self.colors_widget)
        self.refresh_swatches()
        self.hide()

    def choice(self,row,kind,names,callback):
        button=PreviewSelector(kind,names,self)
        button.setToolTip('箭头样式' if kind=='arrow' else '线条样式')
        button.currentTextChanged.connect(callback)
        row.addWidget(button)
        return button

    def slider(self,row,label,lo,hi,value,callback):
        widget=QWidget()
        box=QHBoxLayout(widget)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(4)
        box.addWidget(QLabel(label))
        control=QSlider(Qt.Orientation.Horizontal)
        control.setRange(lo,hi)
        control.setValue(value)
        control.setFixedWidth(78)
        number=QLabel(str(value))
        number.setFixedWidth(23)
        control.valueChanged.connect(lambda v:number.setText(str(v)))
        control.valueChanged.connect(callback)
        box.addWidget(control)
        box.addWidget(number)
        widget.control=control
        widget.number=number
        row.addWidget(widget)
        return widget

    def set_value(self,name,value):
        setattr(self,name,value)
        self.apply()

    def set_width(self,value):
        self.line_width=value
        self.widths[self.width_mode]=value
        self.width_widget.control.blockSignals(True)
        self.width_widget.control.setValue(value)
        self.width_widget.control.blockSignals(False)
        self.width_widget.number.setText(str(value))
        self.apply()

    def choose_arrow(self,name):
        self.arrow_style=name
        self.arrow_button.setIcon(sample_icon('arrow',name))
        self.owner.tool('箭头')

    def choose_dash(self,name):
        self.dash_name=name
        self.dash_button.setIcon(sample_icon('dash',name))
        self.apply()

    def choose_mosaic(self,name):
        self.mosaic_style=name
        self.owner.tool('马赛克')

    def fill_changed(self,on):
        self.fill_shape=on
        self.fill_button.setText('实心' if on else '空心')
        self.apply()

    def set_color(self,color):
        self.color=color
        self.refresh_swatches()
        self.apply()

    def custom_color(self):
        dialog=QColorDialog(self.color,self.window())
        dialog.setWindowTitle('选择标注颜色')
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog,True)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.colorSelected.connect(self.set_color)
        self.color_dialog=dialog
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def refresh_swatches(self):
        for button,color in self.swatches:
            selected=QColor(color)==self.color
            button.setStyleSheet(f'background:{color};border:{2 if selected else 1}px solid {"#3286ff" if selected else "#abb1ba"};border-radius:6px;')

    def toggle_text_list(self):
        if self.text_list.isVisible():
            self.close_text_list()
            return
        self.text_list.clear()
        canvas=self.owner.canvas
        if canvas is not None:
            canvas.commit_text()
            for index,mark in enumerate(canvas.text_marks):
                preview=' '.join(mark.text.split())
                label=preview[:28]+('…' if len(preview)>28 else '')
                self.text_list.addItem(f'{index+1}. {label}')
        if not self.text_list.count():
            self.text_list.addItem('暂无已添加的文字')
            self.text_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.text_list_canvas=canvas
        button=self.edit_text_button
        anchor=QRect(button.mapTo(self.owner,QPoint()),button.size())
        bounds=self.owner.rect().adjusted(4,4,-4,-4)
        width=min(300,bounds.width())
        height=min(220,bounds.height(),self.text_list.sizeHintForRow(0)*self.text_list.count()+12)
        x=max(bounds.left(),min(anchor.left(),bounds.right()-width+1))
        y=anchor.bottom()+5
        if y+height>bounds.bottom()+1:y=max(bounds.top(),anchor.top()-height-4)
        self.text_list.setGeometry(x,y,width,height)
        self.text_list.show()
        self.text_list.raise_()
        self.text_list.setFocus()
        QApplication.instance().installEventFilter(self)

    def close_text_list(self):
        QApplication.instance().removeEventFilter(self)
        self.text_list.hide()
        self.text_list_canvas=None

    def open_text_item(self,item):
        canvas=self.text_list_canvas
        index=self.text_list.row(item)
        self.close_text_list()
        if canvas is not None and self.owner.canvas is canvas and canvas.mode=='文字':
            canvas.edit_text(index)

    def eventFilter(self,watched,event):
        if self.text_list.isVisible():
            if event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape:
                self.close_text_list()
                return True
            if event.type()==QEvent.Type.MouseButtonPress and isinstance(watched,QWidget):
                inside=watched is self.text_list or isinstance(watched,QWidget) and self.text_list.isAncestorOf(watched)
                if not inside and watched is not self.edit_text_button:self.close_text_list()
        return super().eventFilter(watched,event)

    def load_text_style(self,style):
        from PySide6.QtCore import QSignalBlocker
        self.font_size,self.font_family,self.text_bold,self.text_italic,color=style
        self.color=QColor(color)
        self.opacity=self.color.alpha()
        self.color.setAlpha(255)
        for widget,value in [(self.font_widget,self.font_size),(self.opacity_widget,round(self.opacity*100/255))]:
            with QSignalBlocker(widget.control):
                widget.control.setValue(value)
            widget.number.setText(str(value))
        with QSignalBlocker(self.font_picker):
            self.font_picker.setCurrentFont(QFont(self.font_family))
        for name,button in self.text_style_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(getattr(self,name))
        self.refresh_swatches()

    def apply(self):
        c=self.owner.canvas
        if c is None:return
        c.arrow_style=self.arrow_style
        c.line_style=DASHES[self.dash_name]
        c.pen_width=self.line_width
        c.font_size=self.font_size
        c.block_size=self.block_size
        c.mosaic_style=self.mosaic_style
        c.mosaic_width=self.mosaic_width
        c.color=QColor(self.color)
        c.color.setAlpha(self.opacity)
        c.fill_shape=self.fill_shape
        c.font_family=self.font_family
        c.text_bold=self.text_bold
        c.text_italic=self.text_italic
        c.update_text_editor_style()
        c.setCursor(tool_cursor(c.mode,c.color))
        c.update()

    def set_mode(self,mode):
        self.close_text_list()
        width_mode='arrow' if mode=='箭头' else 'line'
        self.width_mode=width_mode
        self.set_width(self.widths[width_mode])
        shapes=['矩形','圆角矩形','椭圆']
        self.shape_choice.setVisible(mode in shapes)
        self.pen_choice.setVisible(mode in ['画笔','荧光笔'])
        for widget,modes in [(self.shape_choice,shapes),(self.pen_choice,['画笔','荧光笔'])]:
            if mode in modes:
                widget.blockSignals(True)
                widget.setCurrentText(mode)
                widget.blockSignals(False)
        self.arrow_button.setVisible(mode=='箭头')
        self.dash_button.setVisible(mode in ['箭头','矩形','圆角矩形','椭圆'])
        self.fill_button.setVisible(mode in ['矩形','圆角矩形','椭圆'])
        self.font_widget.setVisible(mode in ['文字','序号'])
        self.delete_number_button.setVisible(mode=='序号')
        self.font_controls.setVisible(mode=='文字')
        self.mosaic_widget.setVisible(mode=='马赛克')
        self.mosaic_choice.setVisible(mode=='马赛克')
        self.mosaic_brush_widget.setVisible(mode=='马赛克' and self.mosaic_style=='画笔涂抹')
        self.width_widget.setVisible(mode not in ['马赛克','文字'])
        self.opacity_widget.setVisible(mode!='马赛克')
        self.colors_widget.setVisible(mode!='马赛克')
        self.apply()

    def delete_number(self):
        canvas=self.owner.canvas
        if canvas is not None and canvas.mode=='序号':
            canvas.delete_number()
