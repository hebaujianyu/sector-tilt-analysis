# -*- coding: utf-8 -*-
# ============================================================================
# plugin.py — 扇区一键 Tilt 分析 (QGIS 插件主体)
#
# 工具栏只保留 1 个图标「扇区点选分析」，且为「可勾选」状态开关：
#   勾上 → 画布进入点选模式；在地图上点击任意矢量要素（扇区/工参/站点层），
#   插件自动完成 v0.2.1 的传参链路：
#     解析小区号(CGI→gNB+CellID→小区号) → 自动发现工参层 → 查询小区
#     → 提取 RF 参数（经纬度/挂高/机械·电子下倾/波束宽度）
#     → 自动打开工具箱 Tab1 并填充 → 自动执行分析出图。
#   点空地（无要素）只在状态栏提示，不弹窗。
#
# 工具箱窗口（2 个标签）入口放在 QGIS「插件」菜单，不占工具栏图标：
#   - 扇区Tilt分析工具箱…：Tab1 手填参数 / Tab2 环向剖面
#   - 环向剖面分析 (45°×8)…：直接打开并切到 Tab2
#
# 点选查找用 tilt_core.find_feature_at_point：10 像素容差、按图层 CRS 转换、
# 只搜图层树可见图层、取几何距离最近的要素（比 v0.2.1 的矩形粗筛准）。
#
# DEM 说明：Tab1 引擎初始化需要一个有效栅格对象作锚点（在线 Open-Meteo 模式
# 也一样）。项目里没有 DEM 栅格时，tilt_core._ensure_controller 会自动生成
# 1×1 微型 GeoTIFF 锚点（见 _create_dem_anchor），不再弹
# "RF analysis engine failed to initialize"。
# ============================================================================

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt

# 注意：QgsMapTool 属于 qgis.gui，不属于 qgis.core（曾因导错导致 classFactory 失败）；
# 且 canvasClicked 信号只在 QgsMapToolEmitPoint 上，基类 QgsMapTool 没有
# （曾误继承 QgsMapTool 导致 connect 抛 AttributeError、信号从未连上）。
from qgis.gui import QgsMapToolEmitPoint


class SectorPickTool(QgsMapToolEmitPoint):
    """点选工具：单击即发射 canvasClicked(QgsPointXY, Qt.MouseButton)。

    不重写 canvasPressEvent，点击行为完全由 plugin.on_canvas_click 处理。
    """


class SectorTiltMAuto:
    def __init__(self, iface):
        self.iface = iface
        self.action_pick = None        # 工具栏唯一图标：点选分析开关（可勾选）
        self.action_menu_main = None   # 插件菜单：打开工具箱
        self.action_menu_ring = None   # 插件菜单：直接开环向剖面
        self.map_tool = None           # 画布点选工具
        self.plugin_dir = os.path.dirname(__file__)

    # ------------------------------------------------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        # ---- 工具栏唯一图标：可勾选的点选分析开关 ----
        self.action_pick = QAction(icon, "扇区点选分析", self.iface.mainWindow())
        self.action_pick.setCheckable(True)
        self.action_pick.setToolTip(
            "扇区点选分析（点击开始/结束点选）\n"
            "· 勾选后在地图上点击扇区/工参/站点要素\n"
            "· 自动解析小区号 → 查工参 → 带入经纬度/挂高/倾角 → 自动出剖面\n"
            "· 点空地不会报错，只在状态栏提示"
        )
        self.action_pick.toggled.connect(self.on_toggled)
        self.iface.addToolBarIcon(self.action_pick)

        # ---- 画布点选工具 ----
        self.map_tool = SectorPickTool(self.iface.mapCanvas())
        self.map_tool.canvasClicked.connect(self.on_canvas_click)
        # 工具被别的工具顶掉时，同步把图标取消勾选
        self.map_tool.deactivated.connect(self._on_tool_deactivated)

        # ---- 插件菜单（不占工具栏图标）：工具箱 / 环向剖面入口 ----
        self.action_menu_main = QAction(
            "扇区Tilt分析工具箱…", self.iface.mainWindow()
        )
        self.action_menu_main.triggered.connect(self.on_open_main)
        self.iface.addPluginToMenu("扇区Tilt分析", self.action_menu_main)

        self.action_menu_ring = QAction(
            "环向剖面分析 (45°×8)…", self.iface.mainWindow()
        )
        self.action_menu_ring.triggered.connect(self.on_open_ring)
        self.iface.addPluginToMenu("扇区Tilt分析", self.action_menu_ring)

    # ------------------------------------------------------------------
    # 点选模式开关
    # ------------------------------------------------------------------
    def on_toggled(self, checked):
        canvas = self.iface.mapCanvas()
        if self.map_tool is None:
            return
        if checked:
            canvas.setMapTool(self.map_tool)
        elif canvas.mapTool() == self.map_tool:
            canvas.unsetMapTool(self.map_tool)

    def _on_tool_deactivated(self):
        if self.action_pick is not None and self.action_pick.isChecked():
            self.action_pick.setChecked(False)

    # ------------------------------------------------------------------
    # 画布点击：找要素 → v0.2.1 传参链路
    # ------------------------------------------------------------------
    def on_canvas_click(self, point, button):
        if button != Qt.LeftButton:
            return

        try:
            from .tilt_core import find_feature_at_point, run_from_feature
        except Exception as e:  # nosec
            self.iface.messageBar().pushCritical(
                "扇区Tilt分析", f"模块加载失败:\n{e}"
            )
            return

        canvas = self.iface.mapCanvas()
        try:
            layer, feat = find_feature_at_point(canvas, point, 10)
        except Exception as e:  # nosec
            self.iface.messageBar().pushWarning(
                "扇区Tilt分析", f"查找要素失败:\n{e}"
            )
            return

        if layer is None or feat is None:
            self.iface.messageBar().pushWarning(
                "扇区Tilt分析",
                "该位置未找到矢量要素：请点在扇区 / 工参 / 站点图层上"
                "（图层需在图层树中可见）。"
            )
            return

        self.iface.messageBar().pushInfo(
            "扇区Tilt分析",
            f"已点选 [{layer.name()}] 要素，正在解析小区号并带入参数…"
        )
        try:
            run_from_feature(feat, layer, auto_run=True)
        except Exception as e:  # nosec
            self.iface.messageBar().pushCritical(
                "扇区Tilt分析", f"传参/分析失败:\n{e}"
            )

    # ------------------------------------------------------------------
    # 工具箱入口（插件菜单）
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

    def on_open_ring(self):
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
        canvas = self.iface.mapCanvas()

        if self.map_tool is not None and canvas.mapTool() == self.map_tool:
            canvas.unsetMapTool(self.map_tool)
        self.map_tool = None

        if self.action_pick is not None:
            self.iface.removeToolBarIcon(self.action_pick)
            self.action_pick = None

        for act in (self.action_menu_main, self.action_menu_ring):
            if act is not None:
                self.iface.removePluginMenu("扇区Tilt分析", act)
        self.action_menu_main = None
        self.action_menu_ring = None
