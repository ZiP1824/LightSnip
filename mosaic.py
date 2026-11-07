"""Pixelation from a frozen stroke source, clipped to a rectangle or round brush."""
from PySide6.QtCore import Qt,QRect,QPointF
from PySide6.QtGui import QPainterPath,QPainterPathStroker


class MosaicEffect:
    def __init__(self,image):
        self.source=image.copy()
        self.block_size=None
        self.pixelated=None

    def draw(self,painter,start,end,stroke,style,brush_width,block_size):
        block_size=max(2,int(block_size))
        if block_size!=self.block_size:
            small=self.source.scaled(max(1,self.source.width()//block_size),max(1,self.source.height()//block_size),
                                     Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.pixelated=small.scaled(self.source.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.FastTransformation)
            self.block_size=block_size
        painter.save()
        if style=='画笔涂抹':
            points=stroke or [start]
            path=QPainterPath(QPointF(points[0]))
            for point in points[1:]:path.lineTo(QPointF(point))
            stroker=QPainterPathStroker()
            stroker.setWidth(max(1,brush_width))
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            mask=stroker.createStroke(path)
            radius=max(1,brush_width)/2
            if mask.isEmpty():mask.addEllipse(QPointF(points[0]),radius,radius)
            painter.setClipPath(mask,Qt.ClipOperation.IntersectClip)
        else:
            painter.setClipRect(QRect(start,end).normalized().intersected(self.source.rect()),Qt.ClipOperation.IntersectClip)
        painter.drawImage(0,0,self.pixelated)
        painter.restore()
