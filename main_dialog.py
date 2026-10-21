# -*- coding: utf-8 -*-
# ============================================================================
# main_dialog.py — 扇区Tilt分析工具箱（多标签主界面）
#
# 把原先散落在多个独立窗口（及 4 个工具栏图标）的功能整合进
# 「1 个图标 + 1 个界面 + 多个标签」：
#   顶部操作栏：[点选扇区分析(开关)] [分析选中小区]   ← 替代原工具栏 3 个图标
#   Tab 1     : 扇区Tilt分析   (VerticalAnalysisDialog，派生自 TiltMaster)
#   Tab 2     : 环向剖面分析   (RingProfileDialog，45° × 8 方向)
#
# 设计要点：
#   - MainToolDialog 维护一个全局单例 (_instance)，供 tilt_core 复用；
#     点选 / 选中要素触发的分析会自动打开工具箱并切到 Tab1。
#   - 两个子对话框都是 QDialog，去掉窗口标志后作为纯控件嵌入 QTabWidget，
#     保留它们原有的「Run Analysis」等按钮与交互。
#   - 点选/选中回调由 plugin 实例提供（self.plugin.set_pick_mode /
#     analyze_selected），on_open_main 时注入。
# ============================================================================

import logging

from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
)
from qgis.PyQt.QtCore import Qt

LOG = logging.getLogger("sector_tiltm_auto.main_dialog")


class MainToolDialog(QDialog):
    _instance = None  # 全局单例引用

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扇区Tilt分析工具箱")
        self.plugin = None          # SectorTiltMAuto 实例，由 on_open_main 注入

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

        # ---- 顶部操作栏：替代原先 3 个独立工具栏图标 ----
        bar = QHBoxLayout()
        self.btn_pick = QPushButton("点选扇区分析")
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(
            "开关地图点选模式：\n"
            "开启后点击地图上的扇区 / 工参 / 站点要素，\n"
            "自动填参并在 Tab1 出垂直波瓣分析"
        )
        self.btn_sel = QPushButton("分析选中小区")
        self.btn_sel.setToolTip(
            "对当前激活图层中选中的 1 个要素执行分析\n"
            "（等同原「选中小区自动展现」）"
        )
        hint = QLabel("提示：点选前请把目标扇区/工参图层置于可见状态")
        hint.setStyleSheet("color: #666;")
        bar.addWidget(self.btn_pick)
        bar.addWidget(self.btn_sel)
        bar.addSpacing(12)
        bar.addWidget(hint, 1)
        layout.addLayout(bar)

        # ---- 标签页 ----
        self.tab_widget = QTabWidget(self)
        layout.addWidget(self.tab_widget)

        # ---- Tab 1 : 扇区Tilt分析 ----
        from .vendor.ui.dialogs.vertical_analysis_dialog import VerticalAnalysisDialog
        self.tilt_dialog = VerticalAnalysisDialog(parent=self)
        # 去掉窗口标志，使子 QDialog 作为纯控件嵌入 Tab（避免绘制独立标题栏）
        self.tilt_dialog.setWindowFlags(Qt.Widget)
        self.tab_widget.addTab(self.tilt_dialog, "扇区Tilt分析")

        # 关键：构造时就把 RF 引擎 controller 挂上（有 DEM 用真 DEM，无 DEM 用
        # 1×1 微型锚点）。否则 controller 为 None 时，直接点对话框自带的
        # 「Run Analysis」会弹英文框 "The RF analysis engine failed to initialize"。
        self._attach_controller()

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

        # ---- Tab 2 : 环向剖面分析 (45° × 8) ----
        from .ring_profile_dialog import RingProfileDialog
        self.ring_dialog = RingProfileDialog(parent=self)
        self.ring_dialog.setWindowFlags(Qt.Widget)
        self.tab_widget.addTab(self.ring_dialog, "环向剖面 (45°×8)")

        # ---- 信号 ----
        self.btn_pick.toggled.connect(self._on_pick_toggled)
        self.btn_sel.clicked.connect(self._on_analyze_selected)

        MainToolDialog._instance = self
        LOG.info("[main_dialog] 工具箱已创建（顶部操作栏 + 2 个标签）")

    # ------------------------------------------------------------------
    def _on_pick_toggled(self, checked):
        if self.plugin is None:
            return
        try:
            self.plugin.set_pick_mode(checked)
        except Exception as e:  # nosec
            LOG.warning(f"点选模式切换失败: {e}")

    def _on_analyze_selected(self):
        if self.plugin is None:
            return
        try:
            self.plugin.analyze_selected()
        except Exception as e:  # nosec
            LOG.warning(f"选中分析失败: {e}")

    # 点选模式结束（如用户切换到其它地图工具）时同步开关状态
    def sync_pick_button(self, checked):
        self.btn_pick.setChecked(checked)

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
        # 关闭工具箱时退出点选模式并清空单例
        try:
            if self.plugin is not None and self.btn_pick.isChecked():
                self.plugin.set_pick_mode(False)
                self.btn_pick.setChecked(False)
        except Exception:  # nosec
            pass
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
