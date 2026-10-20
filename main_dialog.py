# -*- coding: utf-8 -*-
# ============================================================================
# main_dialog.py — 扇区Tilt分析工具箱（多标签主界面）
#
# 把原先散落在多个独立窗口的功能整合进「1 个界面 + 多个标签」：
#   Tab 1 : 扇区Tilt分析   (VerticalAnalysisDialog，派生自 TiltMaster)
#   Tab 2 : 环向剖面分析   (RingProfileDialog，45° × 8 方向)
#
# 设计要点：
#   - MainToolDialog 维护一个全局单例 (_instance)，供 tilt_core 复用；
#     点选 / 选中要素触发的分析会自动打开工具箱并切到 Tab1。
#   - 两个子对话框都是 QDialog，去掉窗口标志后作为纯控件嵌入 QTabWidget，
#     保留它们原有的「Run Analysis」等按钮与交互。
# ============================================================================

import logging

from qgis.PyQt.QtWidgets import QDialog, QTabWidget, QVBoxLayout
from qgis.PyQt.QtCore import Qt

LOG = logging.getLogger("sector_tiltm_auto.main_dialog")


class MainToolDialog(QDialog):
    _instance = None  # 全局单例引用

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扇区Tilt分析工具箱")
        self.resize(1120, 800)
        self.setMinimumSize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

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

        MainToolDialog._instance = self
        LOG.info("[main_dialog] 工具箱已创建（含 2 个标签）")

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
        # 关闭后清空单例，下次点选/选中会重新创建
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
