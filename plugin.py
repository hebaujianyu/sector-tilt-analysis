# -*- coding: utf-8 -*-
# ============================================================================
# plugin.py — 扇区一键 Tilt 分析 (QGIS 插件主体)
#
# 功能：
#   工具栏按钮（可勾选）→ 切换「点选分析」画布工具。
#   在地图上点击任意矢量要素（扇区 / 工参层 / 站点层），插件自动：
#     解析小区号(UniqueID) → 自动发现工参层 → 提取 RF 参数
#     → 弹出垂直波瓣分析对话框并填充 → 自动执行分析（DEM 在线默认）
#
# 本插件已内嵌垂直波瓣分析引擎（vendor/），
# 不再依赖任何外部插件，也不依赖联网（DEM 走 Open-Meteo 在线）。
# ============================================================================

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt

from qgis.core import (
    QgsVectorLayer, QgsFeatureRequest, QgsRectangle
)
from qgis.gui import QgsMapToolEmitPoint

from .tilt_core import run_from_feature


class ClickTool(QgsMapToolEmitPoint):
    """点击画布即发射 canvasClicked(QgsPointXY, Qt.MouseButton)。"""
    pass


class SectorTiltMAuto:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.map_tool = None
        self.plugin_dir = os.path.dirname(__file__)

    # ------------------------------------------------------------------
    def initGui(self):
        # 图标（优先 PNG，回退 SVG；找不到就用空图标）
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(
            icon, "扇区一键Tilt分析", self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.setToolTip(
            "点击扇区：自动把工参传入并启动垂直波瓣分析（DEM 在线）"
        )
        self.action.toggled.connect(self.on_toggled)
        self.iface.addToolBarIcon(self.action)

        # 画布点选工具
        self.map_tool = ClickTool(self.iface.mapCanvas())
        self.map_tool.canvasClicked.connect(self.on_canvas_click)
        # 工具被手动切换走时，同步取消按钮勾选
        self.map_tool.deactivated.connect(
            lambda: self.action.setChecked(False)
        )

    # ------------------------------------------------------------------
    def on_toggled(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            canvas.setMapTool(self.map_tool)
        else:
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)

    # ------------------------------------------------------------------
    def on_canvas_click(self, point, button):
        if button != Qt.LeftButton:
            return

        canvas = self.iface.mapCanvas()

        # 屏幕容差 → 地图单位（约 6 像素）
        r = canvas.mapSettings().mapUnitsPerPixel() * 6.0
        rect = QgsRectangle(
            point.x() - r, point.y() - r,
            point.x() + r, point.y() + r
        )

        # 按绘制顺序（顶层优先）找第一个命中的矢量要素
        for layer in canvas.layers():
            if not isinstance(layer, QgsVectorLayer):
                continue
            req = QgsFeatureRequest().setFilterRect(rect).setLimit(1)
            feat = next(layer.getFeatures(req), None)
            if feat and feat.isValid():
                run_from_feature(feat, layer, auto_run=True)
                return

        self.iface.messageBar().pushWarning(
            "扇区Tilt分析",
            "该位置未找到矢量要素，请点击扇区 / 工参 / 站点图层。"
        )

    # ------------------------------------------------------------------
    def unload(self):
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
        if self.map_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
