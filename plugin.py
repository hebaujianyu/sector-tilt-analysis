# -*- coding: utf-8 -*-
# ============================================================================
# plugin.py — 扇区一键 Tilt 分析 (QGIS 插件主体)
#
# 工具栏只保留 1 个图标「Tilt分析工具箱」，点开即得 2 个标签：
#   - Tab1 扇区Tilt分析：原生参数面板（经纬度/挂高/机械·电子下倾/波束宽度）
#   - Tab2 环向剖面(45°×8)：在地图上点选取点 + 生成立体阻挡剖面
#
# v0.4.13：移除「点选扇区分析」开关与「分析选中小区」按钮（用户要求做减法）。
# 原先的 PickTool（全图层手写几何查找 + 工参表反查传参）随之删除，传参回到
# 原插件的手填配置；Tab2 的点选由 ring_profile_dialog.RingPickTool 独立提供。
#
# DEM 说明：Tab1 引擎初始化需要一个有效栅格对象作锚点（在线 Open-Meteo 模式
# 也一样）。项目里没有 DEM 栅格时，tilt_core._ensure_controller 会自动生成
# 1×1 微型 GeoTIFF 锚点（见 _create_dem_anchor），不再弹
# "RF analysis engine failed to initialize"。
# ============================================================================

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class SectorTiltMAuto:
    def __init__(self, iface):
        self.iface = iface
        self.action_main = None     # 工具栏唯一图标：Tilt分析工具箱
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
            "· Tab1 扇区Tilt分析（填经纬度/挂高/下倾/波束宽度 → 运行分析）\n"
            "· Tab2 环向剖面分析(45°×8)（地图点选取点 → 生成环向剖面）"
        )
        self.action_main.triggered.connect(self.on_open_main)
        self.iface.addToolBarIcon(self.action_main)

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
        main.activate_tilt_tab()

    # ------------------------------------------------------------------
    def unload(self):
        if self.action_main is not None:
            self.iface.removeToolBarIcon(self.action_main)
