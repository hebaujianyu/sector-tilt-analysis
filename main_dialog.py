# -*- coding: utf-8 -*-
# ============================================================================
# main_dialog.py — 扇区Tilt分析工具箱（多标签主界面）
#
# 结构：1 个工具栏图标 → 1 个工具箱窗口 → 2 个标签页
#   Tab 1 : 扇区Tilt分析（VerticalAnalysisDialog，派生自 TiltMaster）
#           传参方式＝原插件原生配置：纬度/经度 + 挂高 + 机械/电子下倾 +
#           垂直波束宽度，点「运行分析」出垂直波瓣剖面。
#   Tab 2 : 环向剖面分析（RingProfileDialog，45° × 8 方向）
#           左侧参数区「在地图上点选取点」+ 手动输入 → 「生成环向剖面」。
#
# 历史：
#   v0.4.13 曾移除顶部「点选扇区分析」开关与「分析选中小区」按钮（做减法）。
#   v0.4.14 按用户要求恢复 v0.2.1 的点选传参能力，形态改为「单图标可勾选」：
#     工具栏 1 个图标「扇区点选分析」勾上即进入画布点选，点中要素自动
#     解析小区号 → 查工参 → 带入经纬度/挂高/倾角 → 弹出本窗口 Tab1 并自动分析。
#     工具箱窗口自身的入口移到 QGIS「插件」菜单，不再占工具栏图标。
#     （顶部操作栏不再恢复，避免与单图标重复。）
# ============================================================================

import logging

from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout
)
from qgis.PyQt.QtCore import Qt

LOG = logging.getLogger("sector_tiltm_auto.main_dialog")


class MainToolDialog(QDialog):
    _instance = None  # 全局单例引用

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扇区Tilt分析工具箱")

        # 窗口尺寸（用户要求）：宽度 = 屏幕宽的 3/5，高度 = 与屏幕同高
        # （availableGeometry 已扣除任务栏；仅限制上限防溢出，不限制内容撑大）
        try:
            from qgis.PyQt.QtWidgets import QApplication
            screen = QApplication.desktop().availableGeometry()
            self.resize(int(screen.width() * 3 / 5), screen.height())
            self.setMaximumSize(screen.width(), screen.height())
        except Exception:  # nosec
            self.resize(1150, 900)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # ---- 标签页 ----
        self.tab_widget = QTabWidget(self)
        layout.addWidget(self.tab_widget)

        # ---- Tab 1 : 扇区Tilt分析 ----
        from .vendor.ui.dialogs.vertical_analysis_dialog import VerticalAnalysisDialog
        self.tilt_dialog = VerticalAnalysisDialog(parent=self)
        # 去掉窗口标志，使子 QDialog 作为纯控件嵌入 Tab（避免绘制独立标题栏）
        self.tilt_dialog.setWindowFlags(Qt.Widget)
        self.tab_widget.addTab(self.tilt_dialog, "扇区Tilt分析")

        # ---- Tab 2 : 环向剖面分析 (45° × 8) ----
        from .ring_profile_dialog import RingProfileDialog
        self.ring_dialog = RingProfileDialog(parent=self)
        self.ring_dialog.setWindowFlags(Qt.Widget)
        self.tab_widget.addTab(self.ring_dialog, "环向剖面 (45°×8)")

        # 关键：构造时就把 RF 引擎 controller 挂上（有 DEM 用真 DEM，无 DEM 用
        # 1×1 微型锚点）。否则 controller 为 None 时，直接点 Tab1 自带的
        # 「运行分析」会弹英文框 "The RF analysis engine failed to initialize"。
        self._attach_controller()

        MainToolDialog._instance = self
        LOG.info("[main_dialog] 工具箱已创建（2 个标签）")

    # ------------------------------------------------------------------
    def _attach_controller(self):
        """把垂直分析引擎 controller 绑定到 tilt_dialog（失败只记日志）。"""
        try:
            from .tilt_core import _ensure_controller
            _ensure_controller(self.tilt_dialog)
            ok = getattr(self.tilt_dialog, "controller", None) is not None
            LOG.info(f"[main_dialog] 引擎 controller 绑定: {'OK' if ok else 'FAILED'}")
        except Exception as e:  # nosec
            LOG.warning(f"[main_dialog] 引擎 controller 绑定失败: {e}")

    # ------------------------------------------------------------------
    def activate_tilt_tab(self):
        """切到「扇区Tilt分析」标签页。"""
        self.tab_widget.setCurrentIndex(0)

    def activate_ring_tab(self):
        """切到「环向剖面分析」标签页。"""
        self.tab_widget.setCurrentIndex(1)

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        MainToolDialog._instance = None
        super().closeEvent(event)


def get_or_create_main(parent=None):
    """返回工具箱主界面单例；不存在则创建并显示。

    供 plugin / tilt_core 调用，保证全插件只有 1 个工具箱窗口。
    """
    inst = MainToolDialog._instance
    if inst is not None and isinstance(inst, MainToolDialog):
        inst.show_and_raise()
        return inst
    if parent is None:
        from qgis.utils import iface
        parent = iface.mainWindow()
    inst = MainToolDialog(parent=parent)
    inst.show_and_raise()
    return inst
