# -*- coding: utf-8 -*-
# ============================================================================
# plugin.py — 扇区一键 Tilt 分析 (QGIS 插件主体)
#
# 功能入口：
#   1) 工具栏按钮（可勾选）→ 切换「点选分析」画布工具：
#      在地图上点击任意矢量要素（扇区 / 工参层 / 站点层），插件自动解析
#      小区号 → 发现工参层 → 提取 RF 参数 → 弹垂直波瓣分析对话框并自动跑。
#   2) 工具栏按钮（可勾选）→ 「选中小区自动展现」：
#      选中图层中 1 个要素即自动取经纬度 + RF 参数并展现（无需点选/小区号）。
#   3) 工具栏按钮 → 「环向剖面分析(45°×8)」：
#      给定经纬度，生成 8 个方向(每 45°)的地形剖面与阻挡玫瑰图。
#
# 本插件已内嵌垂直波瓣分析引擎（vendor/），
# 不再依赖任何外部插件，也不依赖联网（DEM 走 Open-Meteo 在线）。
# ============================================================================

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal

from qgis.core import QgsVectorLayer
from qgis.gui import QgsMapToolIdentify

from .tilt_core import run_from_feature, run_from_selection


class ClickTool(QgsMapToolIdentify):
    """点击画布即发射 canvasClicked(QgsPointXY, Qt.MouseButton)。

    继承 QgsMapToolIdentify：on_canvas_click 里用官方 identify() 找要素，
    自动处理「画布坐标系 → 图层坐标系」转换、点击容差与多图层遍历
    （原手写 setFilterRect 未做 CRS 转换，投影坐标系下永远找不到要素）。
    """
    canvasClicked = pyqtSignal(object, object)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.canvasClicked.emit(event.mapPoint(), event.button())


class SectorTiltMAuto:
    def __init__(self, iface):
        self.iface = iface
        self.action = None          # 点选分析
        self.action_sel = None      # 选中小区自动展现
        self.action_ring = None     # 环向剖面分析（工具箱 Tab2）
        self.action_main = None     # 工具箱主界面（多标签）
        self.map_tool = None
        self.plugin_dir = os.path.dirname(__file__)

        # 选中自动展现状态
        self.sel_enabled = False
        self._sel_layer = None

    # ------------------------------------------------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        # 1) 点选分析（可勾选）
        self.action = QAction(
            icon, "扇区一键Tilt分析", self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.setToolTip(
            "点击扇区：自动把工参传入并启动垂直波瓣分析（DEM 在线）"
        )
        self.action.toggled.connect(self.on_toggled)
        self.iface.addToolBarIcon(self.action)

        self.map_tool = ClickTool(self.iface.mapCanvas())
        self.map_tool.canvasClicked.connect(self.on_canvas_click)
        self.map_tool.deactivated.connect(
            lambda: self.action.setChecked(False)
        )

        # 2) 选中小区自动展现（可勾选）
        self.action_sel = QAction(
            icon, "选中小区自动展现", self.iface.mainWindow()
        )
        self.action_sel.setCheckable(True)
        self.action_sel.setToolTip(
            "选中矢量图层中 1 个要素即自动取经纬度与 RF 参数并展现剖面"
        )
        self.action_sel.toggled.connect(self.on_sel_toggled)
        self.iface.addToolBarIcon(self.action_sel)

        # 当前图层切换时，若开启选中模式则重新绑定 selectionChanged
        try:
            self.iface.currentLayerChanged.connect(self._on_current_layer_changed)
        except Exception:  # nosec
            pass

        # 3) 环向剖面分析（45°×8）
        self.action_ring = QAction(
            icon, "环向剖面分析(45°×8)", self.iface.mainWindow()
        )
        self.action_ring.setToolTip(
            "给定经纬度，生成 8 个方向(每 45°)的地形剖面与阻挡玫瑰图"
        )
        self.action_ring.triggered.connect(self.on_ring)
        self.iface.addToolBarIcon(self.action_ring)

        # 4) 工具箱主界面（多标签）—— 一键打开扇区Tilt分析 + 环向剖面
        self.action_main = QAction(
            icon, "Tilt分析工具箱", self.iface.mainWindow()
        )
        self.action_main.setToolTip(
            "打开扇区Tilt分析工具箱：扇区Tilt分析 / 环向剖面分析（45°×8）多标签界面"
        )
        self.action_main.triggered.connect(self.on_open_main)
        self.iface.addToolBarIcon(self.action_main)

    # ------------------------------------------------------------------
    # 工具箱主界面（多标签）
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
        main.activate_tilt_tab()

    # ------------------------------------------------------------------
    # 点选分析
    # ------------------------------------------------------------------
    def on_toggled(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            canvas.setMapTool(self.map_tool)
        else:
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)

    def on_canvas_click(self, point, button):
        if button != Qt.LeftButton:
            return

        # 官方 identify：自动处理 CRS 转换 + 容差，遍历所有可见图层
        try:
            results = self.map_tool.identify(
                point, QgsMapToolIdentify.IdentifyMode.TopDownAll
            )
        except Exception:  # nosec
            results = []

        for res in results:
            try:
                layer = res.mLayer
                feat = res.mFeature
            except AttributeError:  # nosec
                continue
            if isinstance(layer, QgsVectorLayer) and feat.isValid():
                run_from_feature(feat, layer, auto_run=True)
                return

        self.iface.messageBar().pushWarning(
            "扇区Tilt分析",
            "该位置未找到矢量要素，请点击扇区 / 工参 / 站点图层。"
        )

    # ------------------------------------------------------------------
    # 选中小区自动展现
    # ------------------------------------------------------------------
    def on_sel_toggled(self, checked):
        self.sel_enabled = checked
        self._connect_selection(checked)

    def _connect_selection(self, enabled):
        # 先断开旧绑定
        if self._sel_layer is not None:
            try:
                self._sel_layer.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:  # nosec
                pass
            self._sel_layer = None

        if not enabled:
            return

        layer = self.iface.activeLayer()
        if isinstance(layer, QgsVectorLayer):
            layer.selectionChanged.connect(self._on_selection_changed)
            self._sel_layer = layer

    def _on_current_layer_changed(self, layer):
        if self.sel_enabled:
            self._connect_selection(True)

    def _on_selection_changed(self):
        if not self.sel_enabled:
            return
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return
        selected = layer.selectedFeatures()
        if len(selected) == 1:
            run_from_selection(selected[0], layer, auto_run=True)

    # ------------------------------------------------------------------
    # 环向剖面分析
    # ------------------------------------------------------------------
    def on_ring(self):
        # 改为打开「工具箱主界面」并切到「环向剖面」标签页（多标签整合）
        try:
            from .main_dialog import get_or_create_main
        except Exception as e:  # nosec
            self.iface.messageBar().pushCritical(
                "扇区Tilt分析", f"工具箱加载失败:\n{e}"
            )
            return
        main = get_or_create_main(parent=self.iface.mainWindow())
        main.activate_ring_tab()

    # ------------------------------------------------------------------
    def unload(self):
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
        if self.action_sel is not None:
            self.iface.removeToolBarIcon(self.action_sel)
        if self.action_ring is not None:
            self.iface.removeToolBarIcon(self.action_ring)
        if self.action_main is not None:
            self.iface.removeToolBarIcon(self.action_main)

        # 断开选中模式绑定
        self.sel_enabled = False
        if self._sel_layer is not None:
            try:
                self._sel_layer.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:  # nosec
                pass
            self._sel_layer = None
        try:
            self.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
        except Exception:  # nosec
            pass

        if self.map_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
