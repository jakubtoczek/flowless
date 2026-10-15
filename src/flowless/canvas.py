"""Plots on screen. PlotCanvas: one matplotlib figure, focusable, Ctrl+C copies it.
FigureView: the figure to export, as a vector picture: wheel zoom, drag to pan, a click
picks the panel under it, a checker shows a transparent background.
"""

from __future__ import annotations

import io

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QByteArray, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsScene, QGraphicsView

FOCUS = QColor("#3d6ea5")


def copy_figure(fig, dpi=200, transparent=False) -> None:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=dpi, transparent=transparent,
                facecolor="none" if transparent else "white")
    QApplication.clipboard().setImage(QImage.fromData(b.getvalue()))


class PlotCanvas(FigureCanvasQTAgg):
    """A plot in the window: click it to give it the focus (a blue frame), Ctrl+C copies
    it. Keys it doesn't use go to *keyPressed* (Delete, Esc, Enter for the gate editor)."""

    keyPressed = Signal(object)

    def __init__(self, fig: Figure | None = None, on_copy=None):
        super().__init__(fig or Figure(layout="tight"))
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background: white")
        self.on_copy = on_copy

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            copy_figure(self.figure)
            if self.on_copy:
                self.on_copy()
            return
        self.keyPressed.emit(e)
        super().keyPressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.hasFocus():
            p = QPainter(self)
            p.setPen(QPen(FOCUS, 2))
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))
            p.end()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


class FigureView(QGraphicsView):
    """The figure as SVG: crisp at any zoom. Wheel zooms on the cursor, drag pans,
    double-click fits; a click (no drag) gives its place as figure fractions (*clicked*).
    Behind the figure a checker (a transparent background shows) or grey."""

    clicked = Signal(float, float)
    zoomed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = None
        self._renderer = None                    # must outlive the item
        self._sel = None
        self._size = (0.0, 0.0)
        self.checker = True
        self._fit_mode = True
        self._press = None
        self._tile = None
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_figure(self, fig) -> None:
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", facecolor=fig.get_facecolor(), edgecolor="none")
        self._renderer = QSvgRenderer(QByteArray(buf.getvalue()))
        s = self._renderer.defaultSize()
        w, h = float(s.width()), float(s.height())
        if self._item is not None:
            self._scene.removeItem(self._item)
        self._item = QGraphicsSvgItem()
        self._item.setSharedRenderer(self._renderer)
        self._item.setCacheMode(QGraphicsItem.NoCache)
        self._scene.addItem(self._item)
        self._scene.setSceneRect(QRectF(-w, -h, 3 * w, 3 * h))
        if self._sel is not None:
            self._sel.setZValue(10)
        changed = (w, h) != self._size
        self._size = (w, h)
        if self._fit_mode or changed and not self.transform().isScaling():
            self.fit()
        self.viewport().update()

    def select(self, rect) -> None:
        """Frame (x0, y0, x1, y1) in figure fractions; None: none."""
        if self._sel is not None:
            self._scene.removeItem(self._sel)
            self._sel = None
        if rect is None or not self._size[0]:
            return
        w, h = self._size
        x0, y0, x1, y1 = rect
        r = QRectF(x0 * w, (1 - y1) * h, (x1 - x0) * w, (y1 - y0) * h)
        pen = QPen(FOCUS, 0)
        pen.setStyle(Qt.DashLine)
        self._sel = self._scene.addRect(r, pen)
        self._sel.setZValue(10)

    def fit(self) -> None:
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self._fit_mode = True
            self.zoomed.emit(self.transform().m11())

    def actual_size(self) -> None:
        """1 mm of the figure = 1 mm on the screen (as the screen reports its dpi)."""
        s = self.logicalDpiX() / 72.0
        self.setTransform(QTransform.fromScale(s, s))
        if self._item is not None:
            self.centerOn(self._item)
        self._fit_mode = False
        self.zoomed.emit(1.0)

    def zoom_percent(self) -> float:
        return 100 * self.transform().m11() / (self.logicalDpiX() / 72.0)

    def drawBackground(self, painter, rect):
        painter.save()
        painter.resetTransform()
        vp = self.viewport().rect()
        painter.fillRect(vp, QColor("#3a3a3a"))
        if self._item is not None:
            r = self.mapFromScene(self._item.boundingRect()).boundingRect()
            if self.checker:
                if self._tile is None:
                    t = QPixmap(16, 16)
                    t.fill(QColor("#e8e8e8"))
                    q = QPainter(t)
                    q.fillRect(0, 0, 8, 8, QColor("#c8c8c8"))
                    q.fillRect(8, 8, 8, 8, QColor("#c8c8c8"))
                    q.end()
                    self._tile = t
                painter.fillRect(r, QBrush(self._tile))
            else:
                painter.fillRect(r, QColor("white"))
        painter.restore()

    def wheelEvent(self, e):
        if self._item is None:
            return
        step = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        pos = e.position().toPoint()
        before = self.mapToScene(pos)
        self.scale(step, step)
        d = self.mapToScene(pos) - before
        self.translate(d.x(), d.y())
        self._fit_mode = False
        self.zoomed.emit(self.transform().m11())

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def mousePressEvent(self, e):
        self.setFocus()
        self._press = (e.position(), e.position())
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        d = e.position() - self._press[1]
        self._press = (self._press[0], e.position())
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setValue(hb.value() - int(d.x()))
        vb.setValue(vb.value() - int(d.y()))
        if (e.position() - self._press[0]).manhattanLength() > 4:
            self._fit_mode = False

    def mouseReleaseEvent(self, e):
        self.unsetCursor()
        if self._press is not None and \
                (e.position() - self._press[0]).manhattanLength() <= 4 and self._size[0]:
            p = self.mapToScene(e.position().toPoint())
            w, h = self._size
            self.clicked.emit(p.x() / w, 1 - p.y() / h)
        self._press = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit_mode:
            self.fit()
