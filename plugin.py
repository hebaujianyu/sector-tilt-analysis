# -*- coding: utf-8 -*-
# ============================================================================
# plugin.py — 扇区一键 Tilt 分析 (QGIS 插件主体)
#
# 工具栏只保留 1 个图标「Tilt分析工具箱」；点选/选中/环向剖面全部收进工具箱：
#   - 「点选扇区分析」开关 → 进入地图点选模式（PickTool）
#   - 「分析选中小区」按钮 → 对当前图层选中要素执行分析
#   - Tab1 扇区Tilt分析 / Tab2 环向剖面(45°×8)
#
# PickTool 识别方式：手写几何查找——画布点击点 → 容差矩形(10 像素) →
# 转各矢量图层 CRS → QgsFeatureRequest.setFilterRect → 取距点击点最近的要素。
# 不依赖 QgsMapToolIdentify.identify/identifyMapEvent（identifyMapEvent 在
# QGIS 3.x Python API 中并不存在，旧版调用被 except 吞掉导致永远"未找到要素"）。
#
# DEM 说明：Tab1 引擎初始化需要一个有效栅格对象作锚点（在线 Open-Meteo 模式
# 也一样）。项目里没有 DEM 栅格时，tilt_core._ensure_controller 会自动生成
# 1×1 微型 GeoTIFF 锚点（见 _create_dem_anchor），不再弹
# "RF analysis engine failed to initialize"。
# ============================================================================

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal

# 注意：QgsMapTool 属于 qgis.gui，绝不能从 qgis.core 导入
# （0.4.0 误从 qgis.core 导入导致模块加载失败、classFactory 报错）
from qgis.core import (
    QgsVectorLayer, QgsFeatureRequest, QgsRectangle,
    QgsGeometry, QgsCoordinateTransform, QgsProject
)
from qgis.gui import QgsMapTool

from .tilt_core import run_from_feature, run_from_selection


class PickTool(QgsMapTool):
    """地图点选工具：手写几何查找，命中「距点击点最近的矢量要素」。

    旧版继承 QgsMapToolIdentify 并调用 identifyMapEvent(event)——该方法在
    QGIS 3.x Python API 中不存在，AttributeError 被 except 吞掉后结果永远
    为空，表现为"该位置未找到矢量要素"。本版改为确定性几何查找：
      1. 点击点 → 画布 CRS 下 10 像素容差矩形
      2. 矩形 → 各可见矢量图层 CRS（transformBoundingBox）
      3. setFilterRect 粗筛 → 逐要素算到点击点的几何距离 → 取最近
    """
    canvasClicked = pyqtSignal(object, object, object)  # (layer, feature, button)

    TOLERANCE_PX = 10

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        layer, feat = self._find_feature(event.mapPoint())
        self.canvasClicked.emit(layer, feat, event.button())

    # ------------------------------------------------------------------
    def _find_feature(self, map_point):
        canvas = self.canvas()
        mupp = canvas.mapUnitsPerPixel()
        tol = max(mupp * self.TOLERANCE_PX, 1e-9)
        rect = QgsRectangle(
            map_point.x() - tol, map_point.y() - tol,
            map_point.x() + tol, map_point.y() + tol
        )
        crs_map = canvas.mapSettings().destinationCrs()
        project = QgsProject.instance()

        best_layer, best_feat, best_dist = None, None, None
        for layer in canvas.layers():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not self._layer_visible(layer):
                continue
            try:
                xform = QgsCoordinateTransform(crs_map, layer.crs(), project)
                lyr_rect = xform.transformBoundingBox(rect)
                pt_lyr = xform.transform(map_point)
            except Exception:  # nosec — CRS 转换失败按同 CRS 处理
                lyr_rect, pt_lyr = rect, map_point

            click_geom = QgsGeometry.fromPointXY(pt_lyr)
            req = QgsFeatureRequest().setFilterRect(lyr_rect)
            try:
                for feat in layer.getFeatures(req):
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    try:
                        d = geom.distance(click_geom)
                    except Exception:  # nosec
                        d = 0.0
                    if best_dist is None or d < best_dist:
                        best_layer, best_feat, best_dist = layer, feat, d
            except Exception:  # nosec — 空间索引/过滤异常跳过该图层
                continue

        return best_layer, best_feat

    # ------------------------------------------------------------------
    @staticmethod
    def _layer_visible(layer):
        """图层可见性要查图层树节点（QgsMapLayer 没有 isVisible 方法）。

        0.4.0 误用 layer.isVisible() → AttributeError → 点选必崩。
        正确做法：layerTreeRoot().findLayer(layer).itemVisibilityChecked()。
        节点不存在（如临时生成的锚点图层未入树）时不过滤。
        """
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer)
            if node is None:
                return True
            return bool(node.itemVisibilityChecked())
        except Exception:  # nosec
            return True


class SectorTiltMAuto:
    def __init__(self, iface):
        self.iface = iface
        self.action_main = None     # 工具栏唯一图标：Tilt分析工具箱
        self.map_tool = None
        self.plugin_dir = os.path.dirname(__file__)

    # ------------------------------------------------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action_main = QAction(icon, "Tilt分析工具箱", self.iface.mainWindow())
        self.action_main.setToolTip(
            "扇区Tilt分析工具箱：\n"
            "· Tab1 扇区Tilt分析（点选/选中小区自动填参出图）\n"
            "· Tab2 环向剖面分析(45°×8)\n"
            "· 工具箱内可开关「点选扇区分析」地图模式"
        )
        self.action_main.triggered.connect(self.on_open_main)
        self.iface.addToolBarIcon(self.action_main)

        self.map_tool = PickTool(self.iface.mapCanvas())
        self.map_tool.canvasClicked.connect(self.on_canvas_click)

    # ------------------------------------------------------------------
    # 工具箱
    # ------------------------------------------------------------------
    def on_open_main(self):
        try:
            from .main_dialog import get_or_create_main
        except Exception as e:  # nosec
            self.iface.messageBar().pushCritical(
                "扇区Tilt分析", f"工具箱加载失败:\n{e}"
            )
            return
        main = get_or_create_main(parent=self.iface.mainWindow())
        main.plugin = self          # 工具箱点选/选中按钮回调本插件
        main.activate_tilt_tab()

    # ------------------------------------------------------------------
    # 点选模式（由工具箱开关触发）
    # ------------------------------------------------------------------
    def set_pick_mode(self, enabled):
        canvas = self.iface.mapCanvas()
        if enabled:
            canvas.setMapTool(self.map_tool)
        else:
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)

    def on_canvas_click(self, layer, feat, button):
        if button != Qt.LeftButton:
            return
        if isinstance(layer, QgsVectorLayer) and feat is not None and feat.isValid():
            run_from_feature(feat, layer, auto_run=True)
            return
        self.iface.messageBar().pushWarning(
            "扇区Tilt分析",
            "该位置未找到矢量要素，请先在图层树选中扇区/工参图层并确保其可见。"
        )

    # ------------------------------------------------------------------
    # 选中小区分析（由工具箱按钮触发）
    # ------------------------------------------------------------------
    def analyze_selected(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushWarning(
                "扇区Tilt分析", "请先在图层树中激活一个矢量图层。"
            )
            return
        selected = layer.selectedFeatures()
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "扇区Tilt分析", f"请选中恰好 1 个要素（当前 {len(selected)} 个）。"
            )
            return
        run_from_feature(selected[0], layer, auto_run=True)

    # ------------------------------------------------------------------
    def unload(self):
        if self.action_main is not None:
            self.iface.removeToolBarIcon(self.action_main)
        if self.map_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
