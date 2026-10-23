# -*- coding: utf-8 -*-
# ============================================================================
# ring_profile_dialog.py — 环向剖面分析 (45° × 8 方向, 方案C 布局)
#
# 给定经纬度(天线挂高 + 机械/电子下倾 + 垂直波束宽度)，对 8 个方向(每 45°)
# 采样地形剖面，计算「首次地形遮挡距离」与「最大山体高度」。
#
# 界面布局（方案C，窗口自适应屏幕、不跳变）：
#   左列（固定宽）：参数区（上）+ 8 方向汇总表（下）
#   右侧：3×3 九宫格 —— 8 张分方向剖面图按罗盘方位排布，中心放阻挡玫瑰图
#     NW | N  | NE
#     W  |玫瑰| E
#     SW | S  | SE
#
# 剖面图画法 = Tab1 同款（对齐其波束图例）：
#   棕色地形底线 + 分段着色：绿=强(低于波束5m以上) / 橙=弱(贴近±5m) / 红=阴影；
#   主波束=绿实线；上波束=蓝虚线；下波束=红虚线（上/下边缘由
#   总下倾 ± 垂直波束宽度/2 求得，垂直波束宽度优先取要素字段，否则默认 7°）；
#   黑竖线=塔桅+天线挂高；红点=首次遮挡点。
#
# 设计要点：
#   * 方向标签一律按 result["az"]（方位角）映射，不按下标。
#   * 单方向采样失败只记入 failures，不中断整轮；进度实时回传状态栏。
#   * 「被遮挡」判定 = 首次遮挡距离 < 用户设定的最大距离。
#
# 复用内嵌 TerrainSampler（本地 DEM / Open-Meteo 在线），无需额外依赖。
# ============================================================================

import math

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QGridLayout, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QHeaderView,
    QWidget, QScrollArea, QApplication, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

try:
    import pyqtgraph as pg
except ImportError:  # nosec
    pg = None

from qgis.core import (
    QgsPointXY, QgsCoordinateTransform, QgsProject, QgsVectorLayer
)
# 注意：QgsMapTool 属于 qgis.gui，不可从 qgis.core 导入
from qgis.gui import QgsMapTool
from qgis.utils import iface

from .tilt_core import (
    _find_dem_layer, _match_field, FIELD_CANDIDATES, extract_site_values,
    find_feature_at_point,
)

# 8 个方向标签与固定配色（必须按方位角映射，禁止按结果下标取）
DIRECTION_LABELS = ["N (0°)", "NE (45°)", "E (90°)", "SE (135°)",
                    "S (180°)", "SW (225°)", "W (270°)", "NW (315°)"]
DIRECTION_COLORS = [
    "#d62728", "#ff7f0e", "#bcbd22", "#2ca02c",
    "#1f77b4", "#9467bd", "#8c564b", "#17becf",
]
AZ_TO_LABEL = {i * 45: DIRECTION_LABELS[i] for i in range(8)}
AZ_TO_COLOR = {i * 45: DIRECTION_COLORS[i] for i in range(8)}


def compute_ring(sampler, site, azimuths, max_d, step, source,
                 height, total_tilt, progress_cb=None):
    """核心：对 8 个方向采样地形剖面并计算遮挡/山体指标。

    返回 (results, failures)：
      results  — 采样成功方向的结果列表（每项含 az/dists/elevs/beam/
                 site_ground/first_occ/max_hill）
      failures — [(az, 失败原因), ...]
    progress_cb(az, ok, msg) 每完成一个方向回调一次（可为主线程更新 UI）。
    """
    tilt_rad = math.radians(total_tilt)
    results = []
    failures = []
    for az in azimuths:
        label = AZ_TO_LABEL.get(az, f"{az}°")
        try:
            prof = sampler.sample_profile(
                site, az, max_d, step, source=source, timeout=60
            )
            dists = prof.get("distances", [])
            elevs = prof.get("elevations", [])
        except Exception as e:  # nosec — 单方向失败不拖垮整轮
            dists, elevs = [], []
            failures.append((az, f"采样异常: {e}"))
            if progress_cb:
                progress_cb(az, False, f"采样异常: {e}")
            continue
        if not dists or elevs is None or not elevs:
            failures.append((az, "无采样数据（网络/DEM 覆盖问题）"))
            if progress_cb:
                progress_cb(az, False, "无采样数据")
            continue
        site_ground = elevs[0]
        beam = [site_ground + height - d * math.tan(tilt_rad)
                for d in dists]
        # 首次遮挡：地形高于主波束中心线的第一个距离
        first_occ = max_d
        for d, e, b in zip(dists, elevs, beam):
            if d > 1 and e > b:
                first_occ = d
                break
        max_hill = max((e - site_ground for e in elevs), default=0)
        if max_hill < 0:
            max_hill = 0
        results.append({
            "az": az,
            "dists": dists,
            "elevs": elevs,
            "beam": beam,
            "site_ground": site_ground,
            "first_occ": first_occ,
            "max_hill": max_hill,
            "tilt": total_tilt,
        })
        if progress_cb:
            if first_occ >= max_d:
                progress_cb(az, True, "全程畅通")
            else:
                progress_cb(az, True, f"{first_occ:.0f} m 处遮挡")
    return results, failures


class _RingWorker(QThread):
    """后台采样 8 个方向地形剖面（避免在线请求时界面卡死）。"""
    result_ready = pyqtSignal(list, list)   # (results, failures)
    progress = pyqtSignal(int, bool, str)   # (az, ok, msg)
    error_occured = pyqtSignal(str)

    def __init__(self, sampler, site, azimuths, max_d, step, source,
                 height, total_tilt):
        super().__init__()
        self.sampler = sampler
        self.site = site
        self.azimuths = azimuths
        self.max_d = max_d
        self.step = step
        self.source = source
        self.height = height
        self.total_tilt = total_tilt

    def _emit_progress(self, az, ok, msg):
        try:
            self.progress.emit(int(az), bool(ok), str(msg))
        except Exception:  # nosec
            pass

    def run(self):
        try:
            results, failures = compute_ring(
                self.sampler, self.site, self.azimuths, self.max_d,
                self.step, self.source, self.height, self.total_tilt,
                progress_cb=self._emit_progress
            )
            self.result_ready.emit(results, failures)
        except Exception as e:  # nosec
            self.error_occured.emit(str(e))


class RingPickTool(QgsMapTool):
    """一次性地图点选工具：取回经纬度，命中要素时连带返回该要素。

    点完自动恢复上一个地图工具，避免把用户困在点选模式里导致无法平移/缩放。
    """
    picked = pyqtSignal(object, object, object, object)  # (lon, lat, layer, feature)

    TOLERANCE_PX = 10

    def __init__(self, canvas, prev_tool=None):
        super().__init__(canvas)
        self.setCursor(Qt.CrossCursor)
        self._prev_tool = prev_tool

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        canvas = self.canvas()
        map_pt = event.mapPoint()
        lon, lat = self._to_wgs84(map_pt, canvas)
        layer, feat = find_feature_at_point(canvas, map_pt, self.TOLERANCE_PX)
        self._restore(canvas)
        self.picked.emit(lon, lat, layer, feat)

    @staticmethod
    def _to_wgs84(map_pt, canvas):
        crs = canvas.mapSettings().destinationCrs()
        if crs is not None and crs.authid() != "EPSG:4326":
            xform = QgsCoordinateTransform(
                crs, QgsProject.instance().crsFromAuthId("EPSG:4326"),
                QgsProject.instance()
            )
            pt = xform.transform(map_pt)
        else:
            pt = map_pt
        return pt.x(), pt.y()

    def _restore(self, canvas):
        try:
            if self._prev_tool is not None:
                canvas.setMapTool(self._prev_tool)
            else:
                canvas.unsetMapTool(self)
        except Exception:  # nosec — 恢复失败不阻塞后续出图
            pass


class RingProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("环向剖面分析 (45° × 8 方向)")
        # 初始尺寸参考屏幕；不设 setMaximumSize——嵌入 Tab 页时它会卡死页面
        # 尺寸（离屏复现实锤），父窗口/布局天然约束足够
        screen = QApplication.desktop().availableGeometry()
        self.resize(min(1150, int(screen.width() * 0.95)),
                    min(820, int(screen.height() * 0.90)))
        self._results = []
        self._failures = []
        self._worker = None
        self._mini = []          # 8 个分方向小剖面 PlotWidget
        self._prog_done = 0
        self._grid_side = None   # 右侧正方形容器当前边长（防重复 setFixedSize）
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = QVBoxLayout(self)

        top = QHBoxLayout()
        main.addLayout(top)

        left_col = QVBoxLayout()

        # ---- 左侧参数区 ----
        params_gb = QGroupBox("参数")
        form = QFormLayout(params_gb)

        self.lat_le = QLineEdit("36.256")
        self.lon_le = QLineEdit("117.106")
        self.lat_le.setFixedWidth(120)
        self.lon_le.setFixedWidth(120)

        self.height_sb = QDoubleSpinBox()
        self.height_sb.setRange(0, 200)
        self.height_sb.setDecimals(1)
        self.height_sb.setValue(30)
        self.height_sb.setSuffix(" m")

        self.mech_sb = QDoubleSpinBox()
        self.mech_sb.setRange(-5, 20)
        self.mech_sb.setDecimals(1)
        self.mech_sb.setValue(3)
        self.mech_sb.setSuffix("°")

        self.elec_sb = QDoubleSpinBox()
        self.elec_sb.setRange(0, 12)
        self.elec_sb.setDecimals(1)
        self.elec_sb.setValue(3)
        self.elec_sb.setSuffix("°")

        self.vbw_sb = QDoubleSpinBox()
        self.vbw_sb.setRange(1, 90)
        self.vbw_sb.setDecimals(1)
        self.vbw_sb.setValue(7.0)
        self.vbw_sb.setSuffix("°")
        self.vbw_sb.setToolTip(
            "垂直波束宽度：用于画上/下波束虚线（Tab1 同款）。\n"
            "「从选中要素获取」时若图层有垂直波束宽度字段会自动带入。"
        )

        self.maxdist_sb = QSpinBox()
        self.maxdist_sb.setRange(100, 10000)
        self.maxdist_sb.setSingleStep(100)
        self.maxdist_sb.setValue(2000)
        self.maxdist_sb.setSuffix(" m")

        self.step_sb = QSpinBox()
        self.step_sb.setRange(5, 200)
        self.step_sb.setSingleStep(5)
        self.step_sb.setValue(25)
        self.step_sb.setSuffix(" m")

        self.source_combo = QComboBox()
        self.source_combo.addItems(["本地 DEM (离线)", "Open-Meteo (在线)"])
        self.source_combo.setCurrentIndex(1)  # 默认在线

        form.addRow("纬度 Lat:", self.lat_le)
        form.addRow("经度 Lon:", self.lon_le)
        form.addRow("天线挂高:", self.height_sb)
        form.addRow("机械下倾:", self.mech_sb)
        form.addRow("电子下倾:", self.elec_sb)
        form.addRow("垂直波束宽度:", self.vbw_sb)
        form.addRow("最大距离:", self.maxdist_sb)
        form.addRow("采样步长:", self.step_sb)
        form.addRow("地形源:", self.source_combo)

        btn_row = QHBoxLayout()
        self.btn_pick = QPushButton("在地图上点选取点")
        self.btn_pick.setToolTip(
            "在地图上点击目标位置（推荐）：\n"
            "· 点位上有基站/扇区要素 → 自动带入 经纬度 + 挂高 + 下倾 + 波束宽度\n"
            "· 点位是空地/无要素 → 只取该点经纬度，RF 参数请手动填\n"
            "点完自动恢复原来的地图工具。"
        )
        self.btn_generate = QPushButton("生成环向剖面")
        self.btn_generate.setStyleSheet("font-weight:bold;")
        self.btn_close = QPushButton("关闭")
        btn_row.addWidget(self.btn_pick)
        btn_row.addWidget(self.btn_generate)
        btn_row.addWidget(self.btn_close)
        form.addRow(btn_row)

        self.status_lbl = QLabel("输入经纬度后点「生成环向剖面」。")
        self.status_lbl.setWordWrap(True)
        form.addRow(self.status_lbl)

        params_gb.setMinimumWidth(350)
        params_gb.setMaximumWidth(430)  # 余宽让给汇总表和九宫格，参数区不无限拉宽
        left_col.addWidget(params_gb)

        # ---- 左列下方：8 方向汇总表（方案C：挪到参数下侧）----
        self.table = QTableWidget(8, 4)
        self.table.setHorizontalHeaderLabels(
            ["方向", "遮挡 (m)", "山体 (m)", "结论"]
        )
        hdr = self.table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(QHeaderView.Stretch)
        # 水平 Ignored：表格 sizeHint 不再抬高左列最小宽度（曾把九宫格挤到溢出）
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        left_col.addWidget(self.table, 1)

        # ---- 右侧：3×3 九宫格（8 方向剖面按罗盘方位 + 中心玫瑰图）----
        # 正方形由「容器整体固定为正方形」保证（resizeEvent 里算边长），
        # 格子内部等分行列拉伸——容器边长 = 3×格边长 + 2×间距，格子必然正方形；
        # 容器自身最小尺寸恒为 0，与左列之间不存在尺寸反馈，任何窗口尺寸都不会溢出。
        if pg is not None:
            self._grid_holder = QWidget()
            outer = QVBoxLayout(self._grid_holder)
            outer.setContentsMargins(0, 0, 0, 0)
            mid = QHBoxLayout()
            mid.setContentsMargins(0, 0, 0, 0)
            grid = QGridLayout()
            grid.setSpacing(4)
            for c in range(3):
                grid.setColumnStretch(c, 1)
            for r in range(3):
                grid.setRowStretch(r, 1)
            # 罗盘方位排布：索引 = azimuth // 45
            #   (0,0)NW (0,1)N (0,2)NE
            #   (1,0)W  (1,1)玫瑰 (1,2)E
            #   (2,0)SW (2,1)S (2,2)SE
            POS = {0: (0, 1), 1: (0, 2), 2: (1, 2), 3: (2, 2),
                   4: (2, 1), 5: (2, 0), 6: (1, 0), 7: (0, 0)}
            self._mini = []
            for i in range(8):
                pw = pg.PlotWidget(background="w")
                # Ignored：完全跟随网格等分空间（正方形容器的 1/3 减间距）
                pw.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                pw.setMinimumSize(60, 60)
                pw.showGrid(x=True, y=True, alpha=0.25)
                # 性能优化（与 vendor TerrainProfileWidget 一致）
                pw.setClipToView(True)
                pw.setDownsampling(auto=True)
                r, c = POS[i]
                # 只在边缘行/列显示轴刻度与标签，节省九宫格空间
                if c == 0:
                    pw.setLabel("left", "高程 (m)")
                else:
                    pw.getAxis("left").setStyle(showValues=False)
                if r == 2:
                    pw.setLabel("bottom", "距离 (m)")
                else:
                    pw.getAxis("bottom").setStyle(showValues=False)
                grid.addWidget(pw, r, c)
                self._mini.append(pw)

            # 中心：阻挡玫瑰图
            self.rose_pw = pg.PlotWidget(background="w")
            self.rose_pw.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self.rose_pw.setMinimumSize(60, 60)
            self.rose_pw.setAspectLocked(True)
            self.rose_pw.hideAxis("left")
            self.rose_pw.hideAxis("bottom")
            grid.addWidget(self.rose_pw, 1, 1)
            mid.addLayout(grid, 1)
            outer.addLayout(mid, 1)
            top.addLayout(left_col)
            top.addWidget(self._grid_holder, 1)
        else:
            self._grid_holder = None
            self.rose_pw = None
            self._mini = []
            top.addLayout(left_col)
            top.addWidget(QLabel(
                "⚠️ 本环境未安装 pyqtgraph，无法绘制图表（仍可在左侧表格查看结果）。"
            ))

        # ---- 信号 ----
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_pick.clicked.connect(self._on_pick)
        self.btn_close.clicked.connect(self.close)

    # ------------------------------------------------------------------
    # 九宫格正方形容器：页尺寸变化时把右侧容器固定为正方形
    # side = min(页宽-左列最小宽, 页高) → 3×格边长 = side - 2×间距，格子必然正方形。
    # 左列最小宽从布局对象解析式取得（不用陈旧的 geometry），无尺寸反馈、无滞后。
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_grid()

    def _fit_grid(self):
        holder = getattr(self, "_grid_holder", None)
        if holder is None:
            return
        main_lay = self.layout()
        if main_lay is None or main_lay.count() < 1:
            return
        top = main_lay.itemAt(0).layout()
        if top is None or top.count() < 2:
            return
        left_min = top.itemAt(0).minimumSize().width()   # 左列最小宽（稳定值）
        avail_w = self.width() - left_min - 24           # 9×2 页边距 + 6 项间距
        avail_h = self.height() - 18                     # 9×2 页边距
        side = max(240, int(min(avail_w, avail_h)))
        if side != self._grid_side:
            self._grid_side = side
            holder.setFixedSize(side, side)

    # ------------------------------------------------------------------
    # 经纬度预填
    # ------------------------------------------------------------------
    # （经度/纬度字段名与控件的对应关系，供 _apply_rf_vals 统一处理）
    RF_TARGETS = [
        ("height", "height_sb", "挂高"),
        ("mech_tilt", "mech_sb", "机械下倾"),
        ("elec_tilt", "elec_sb", "电子下倾"),
    ]

    def _on_pick(self):
        """进入一次性地图点选模式，等待用户在画布上点击。"""
        try:
            canvas = iface.mapCanvas()
        except Exception as e:  # nosec
            self.status_lbl.setText(f"无法获取地图画布: {e}")
            return
        prev_tool = canvas.mapTool()
        tool = RingPickTool(canvas, prev_tool=prev_tool)
        tool.picked.connect(self._apply_pick)
        # 必须长期持有引用：QGIS 只保存 C++ 指针，Python 对象被 GC 会悬空
        self._pick_tool = tool
        canvas.setMapTool(tool)
        self.status_lbl.setText(
            "请在地图上点击目标位置…（点完自动回到原工具；Esc 可中断）"
        )

    def _apply_pick(self, lon, lat, layer, feat):
        """点选结果落地：有要素就连带 RF 参数，无要素只落经纬度。"""
        try:
            self.lon_le.setText(f"{lon:.6f}")
            self.lat_le.setText(f"{lat:.6f}")

            hit = (feat is not None and feat.isValid()
                   and isinstance(layer, QgsVectorLayer))
            if not hit:
                self.status_lbl.setText(
                    f"已取点 ({lat:.6f}, {lon:.6f}) — 该位置没有基站/扇区要素，"
                    f"仅填入经纬度，挂高/下倾请手动填写。"
                )
                return

            fields = list(layer.fields())
            # 经纬度：字段优先（扇区图层几何质心 ≠ 天线位置）
            lon_f = _match_field(fields, FIELD_CANDIDATES["longitude"])
            lat_f = _match_field(fields, FIELD_CANDIDATES["latitude"])
            coord_src = "点击点坐标"
            if lon_f and lat_f:
                try:
                    self.lon_le.setText(f"{float(feat[lon_f]):.6f}")
                    self.lat_le.setText(f"{float(feat[lat_f]):.6f}")
                    coord_src = "要素经纬度字段"
                except (ValueError, TypeError, KeyError):  # nosec
                    pass

            vals = extract_site_values(
                {f.name(): feat[f.name()] for f in fields}, {}
            )
            got, miss = self._apply_rf_vals(vals)

            msg = (f"已选中 [{layer.name()}] 要素 — 经纬度取自{coord_src}；"
                   f"已带入：" + ("、".join(got) if got else "无"))
            if miss:
                msg += f"｜未识别({'/'.join(miss)})，请手动填写"
            self.status_lbl.setText(msg)
        except Exception as e:  # nosec
            self.status_lbl.setText(f"点选取值失败: {e}")

    def _apply_rf_vals(self, vals):
        """把提取到的 RF 值填入控件，返回 (已取到, 未取到) 名称列表。"""
        got, miss = [], []
        for key, attr, label in self.RF_TARGETS:
            sb = getattr(self, attr, None)
            v = vals.get(key)
            try:
                fv = float(v) if v is not None else None
            except (ValueError, TypeError):  # nosec
                fv = None
            if sb is not None and fv is not None:
                sb.setValue(fv)
                got.append(label)
            else:
                miss.append(label)

        vbw = vals.get("v_beamwidth")
        try:
            vbw = float(vbw) if vbw is not None else None
        except (ValueError, TypeError):  # nosec
            vbw = None
        if vbw is not None and 1 <= vbw <= 90:
            self.vbw_sb.setValue(vbw)
            got.append("波束宽度")
        else:
            miss.append("波束宽度")
        return got, miss

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    def _make_sampler(self, source):
        """按地形源构造 TerrainSampler；失败返回 (None, 错误信息)。"""
        dem = _find_dem_layer()
        from .vendor.core.terrain.terrain_sampler import TerrainSampler
        if dem is None:
            if source == "online":
                # 在线 Open-Meteo 路径不使用本地 DEM，可绕过构造检查
                import threading as _threading
                sampler = object.__new__(TerrainSampler)
                sampler.dem = None
                sampler._cache = {}
                sampler._cache_lock = _threading.Lock()
                sampler._cache_access_time = {}
                return sampler, None
            return None, (
                "本地 DEM 模式需要项目中加载一个高程栅格图层；\n"
                "若没有本地 DEM，请将「地形源」切换为 Open-Meteo (在线)。"
            )
        try:
            return TerrainSampler(dem), None
        except Exception as e:  # nosec
            return None, f"地形采样器初始化失败:\n{e}"

    def _on_generate(self):
        try:
            lat = float(self.lat_le.text().strip())
            lon = float(self.lon_le.text().strip())
        except ValueError:
            QMessageBox.warning(self, "环向剖面", "经纬度必须是数字。")
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            QMessageBox.warning(self, "环向剖面", "经纬度超出合理范围。")
            return

        source = "local" if self.source_combo.currentIndex() == 0 else "online"
        sampler, err = self._make_sampler(source)
        if sampler is None:
            QMessageBox.warning(self, "环向剖面", err)
            return

        height = self.height_sb.value()
        total_tilt = self.mech_sb.value() + self.elec_sb.value()
        self._last_vbw = self.vbw_sb.value()   # 上/下波束虚线用（生成时定格）
        max_d = self.maxdist_sb.value()
        step = max(1, self.step_sb.value())
        azimuths = [i * 45 for i in range(8)]
        site = QgsPointXY(lon, lat)

        self._prog_done = 0
        self.status_lbl.setText("正在采样 8 个方向地形剖面，请稍候… (0/8)")
        self.btn_generate.setEnabled(False)
        QApplication_process()

        # 本地 DEM 在主线程采样（避免栅格 identify 跨线程）；在线走后台 worker
        if source == "local":
            def cb(az, ok, msg):
                self._on_progress(az, ok, msg)
                QApplication_process()
            try:
                results, failures = compute_ring(
                    sampler, site, azimuths, max_d, step, source,
                    height, total_tilt, progress_cb=cb
                )
                self._on_results(results, failures)
            except Exception as e:  # nosec
                self._on_error(str(e))
            self._on_worker_done()
        else:
            self._worker = _RingWorker(
                sampler, site, azimuths, max_d, step, source, height, total_tilt
            )
            self._worker.result_ready.connect(self._on_results)
            self._worker.progress.connect(self._on_progress)
            self._worker.error_occured.connect(self._on_error)
            self._worker.finished.connect(self._on_worker_done)
            self._worker.start()

    # ------------------------------------------------------------------
    # 进度 / 结果 / 错误
    # ------------------------------------------------------------------
    def _on_progress(self, az, ok, msg):
        """每完成一个方向的实时反馈（主线程）。"""
        self._prog_done += 1
        label = AZ_TO_LABEL.get(az, f"{az}°")
        mark = "✓" if ok else "✗"
        self.status_lbl.setText(
            f"采样中… ({self._prog_done}/8)  {mark} {label}: {msg}"
        )

    def _on_results(self, results, failures):
        self._results = results
        self._failures = failures or []
        self._render(results)
        self._fill_table(results)
        ok_n = len(results)
        fail_n = len(self._failures)
        if fail_n:
            bad = ", ".join(AZ_TO_LABEL.get(az, f"{az}°")
                            for az, _ in self._failures)
            self.status_lbl.setText(
                f"完成 {ok_n}/8 方向；失败 {fail_n} 个（{bad}）。"
                "失败方向详见剖面宫格标题。"
            )
        else:
            self.status_lbl.setText(
                f"完成 8/8 方向采样。其中 "
                f"{sum(1 for r in results if r['first_occ'] < self.maxdist_sb.value())}"
                " 个方向存在地形遮挡（详见表格红色行）。"
            )

    def _on_error(self, msg):
        self.status_lbl.setText(f"采样失败: {msg}")
        QMessageBox.warning(self, "环向剖面", f"地形采样失败:\n{msg}")

    def _on_worker_done(self):
        self.btn_generate.setEnabled(True)
        if not self._results and not self._failures:
            self.status_lbl.setText("无有效采样结果（请检查经纬度/地形源）。")

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render(self, results):
        if pg is None or not self._mini:
            return
        by_az = {r["az"]: r for r in results}
        user_max = self.maxdist_sb.value()

        # ---- 全局统一 Y 量程：8 张图共用，刻度完全对齐 ----
        # 上界 = max(塔顶 sg+h, 最高地形) × 1.08；下界锁 0（地形本身为负时取地形最低点）
        y_top = 0.0
        y_bottom = 0.0
        for res in results:
            elevs = res.get("elevs") or []
            y_top = max(y_top,
                        res["site_ground"] + self.height_sb.value(),
                        max(elevs) if elevs else 0.0)
            y_bottom = min(y_bottom, min(elevs) if elevs else 0.0)
        if y_top <= 0:
            y_top = 100.0
        y_top = y_top * 1.08 + 1.0

        # ---- 3×3 九宫格：每方向一张独立剖面 ----
        for i, pw in enumerate(self._mini):
            pw.clear()
            az = i * 45
            res = by_az.get(az)
            if res is None:
                reason = next(
                    (m for a, m in self._failures if a == az), "无数据"
                )
                self._draw_mini_empty(pw, az, reason, user_max,
                                      y_bottom, y_top)
            else:
                self._draw_mini(pw, res, user_max, y_bottom, y_top)

        # ---- 阻挡玫瑰图 ----
        if self.rose_pw is not None:
            self._render_rose(results, user_max)

    def _draw_mini(self, pw, res, user_max, y0, y1):
        az = res["az"]
        label = AZ_TO_LABEL.get(az, f"{az}°")
        dists, elevs, beam = res["dists"], res["elevs"], res["beam"]
        fo = res["first_occ"]
        clear = fo >= user_max
        sg = res["site_ground"]
        h = self.height_sb.value()

        # ---- Tab1 同款：地形滑动平均平滑（window=3，纯 Python）----
        def _smooth(vals, win=3):
            n = len(vals)
            if n <= win:
                return list(vals)
            half = win // 2
            return [sum(vals[max(0, i - half):min(n, i + half + 1)])
                    / (min(n, i + half + 1) - max(0, i - half))
                    for i in range(n)]
        sm = _smooth(elevs)

        # ---- 波束几何（总下倾 ± 垂直波束宽度/2，Tab1 同款三线）----
        tilt = res.get("tilt",
                       self.mech_sb.value() + self.elec_sb.value())
        vbw = getattr(self, "_last_vbw", self.vbw_sb.value())
        ang_u = max(min(tilt - vbw / 2.0, 89.5), -89.5)
        ang_l = max(min(tilt + vbw / 2.0, 89.5), -89.5)
        upper = [sg + h - d * math.tan(math.radians(ang_u)) for d in dists]
        lower = [sg + h - d * math.tan(math.radians(ang_l)) for d in dists]
        main = (beam if beam and len(beam) == len(dists) else
                [sg + h - d * math.tan(math.radians(tilt)) for d in dists])

        def _clip(line):
            """波束线止于首次触地（线性插值截断），返回 [(d, h, i), ...]。"""
            pts = []
            for i, (d, lv) in enumerate(zip(dists, line)):
                if d <= 1:
                    pts.append((d, lv, i))
                    continue
                if sm[i] >= lv:
                    if pts:
                        pd, pl, pi = pts[-1]
                        gp = pl - sm[pi]
                        gi = sm[i] - lv
                        f = gp / (gp + gi) if (gp + gi) > 0 else 0.0
                        pts.append((pd + f * (d - pd),
                                    pl + f * (lv - pl), i))
                    break
                pts.append((d, lv, i))
            return pts

        # ---- 青色波束覆盖区（Tab1 同款 tosca，透明度 60；超界由 Y 锁裁掉）----
        bf = pg.FillBetweenItem(pg.PlotDataItem(dists, upper),
                                pg.PlotDataItem(dists, lower),
                                brush=pg.mkBrush(6, 250, 250, 60))
        bf.setZValue(-10)
        pw.addItem(bf)

        # ---- 地形（Tab1 同款：不透明赭黄填充 + 棕色脊线；填到 Y 锁下限）----
        pw.plot(dists, sm, pen=pg.mkPen("brown", width=2),
                fillLevel=y0,
                fillBrush=pg.mkBrush(203, 145, 57, 255))

        # ---- 分色地形脊线（Tab1 同款：净空>10m 绿 / 0~10m 橙 / <0 红）----
        mc = _clip(main)
        cls_colors = ((0, 180, 0), (255, 180, 0), (200, 0, 0))
        runs, cur_cls, cur_pts, prev_pt = [], None, [], None
        for d, lv, i in mc:
            terr = sm[i]
            cl = lv - terr
            c = 0 if cl > 10 else (1 if cl > 0 else 2)
            if c != cur_cls:
                if cur_pts:
                    runs.append((cur_cls, cur_pts))
                cur_cls = c
                cur_pts = [prev_pt] if prev_pt is not None else []
            cur_pts.append((d, terr))
            prev_pt = (d, terr)
        if cur_pts:
            runs.append((cur_cls, cur_pts))
        for c, pts in runs:
            if len(pts) >= 2:
                pw.plot([p[0] for p in pts], [p[1] for p in pts],
                        pen=pg.mkPen(cls_colors[c], width=3))

        # ---- 三条波束线：止于各自首次触地点（Tab1 同款颜色与线宽）----
        uc = _clip(upper)
        lc = _clip(lower)
        pw.plot([p[0] for p in uc], [p[1] for p in uc],
                pen=pg.mkPen("blue", width=2, style=Qt.DashLine))
        pw.plot([p[0] for p in lc], [p[1] for p in lc],
                pen=pg.mkPen("red", width=2, style=Qt.DashLine))
        pw.plot([p[0] for p in mc], [p[1] for p in mc],
                pen=pg.mkPen((0, 160, 0), width=3))

        # ---- 塔桅（Tab1 同款：收边塔身 + 横撑 + 天线杆 + 红色天线头）----
        base_half = max(user_max * 0.012, 5.0)
        for sgn in (-1, 1):
            pw.plot([sgn * base_half, 0], [sg, sg + h],
                    pen=pg.mkPen((60, 60, 60), width=1.2))
        for frac in (0.25, 0.55, 0.85):
            y = sg + h * frac
            xw = base_half * (1.0 - frac)
            pw.plot([-xw, xw], [y, y], pen=pg.mkPen((60, 60, 60), width=1))
        mast_h = (y1 - y0) * 0.035
        pw.plot([0, 0], [sg + h, sg + h + mast_h],
                pen=pg.mkPen((50, 50, 50), width=2))
        pw.addItem(pg.ScatterPlotItem(
            x=[0], y=[sg + h + mast_h], size=6,
            pen=pg.mkPen((120, 40, 40), width=0.8),
            brush=pg.mkBrush(200, 60, 60)))

        # ---- 交点标记（Tab1 同款：上蓝/下红白描边、主波束落地点绿点黑描边）----
        for cl_line, col in ((uc, (42, 125, 225)), (lc, (255, 0, 0))):
            if cl_line and cl_line[-1][0] < dists[-1] - 1e-6:
                cd, _ch, ci = cl_line[-1]
                pw.addItem(pg.ScatterPlotItem(
                    x=[cd], y=[sm[ci]], size=10,
                    pen=pg.mkPen("w", width=1.5), brush=pg.mkBrush(*col)))
        if not clear and mc and mc[-1][0] < dists[-1] - 1e-6:
            cd, _ch, ci = mc[-1]
            pw.addItem(pg.ScatterPlotItem(
                x=[cd], y=[sm[ci]], size=12,
                pen=pg.mkPen("k", width=1.5), brush=pg.mkBrush(0, 160, 0)))
            ti = pg.TextItem(f"{fo:.0f} m", color="#333333",
                             anchor=(0.5, 1.15))
            ti.setPos(cd, sm[ci])
            pw.addItem(ti)

        title = (f"{label} · 畅通" if clear
                 else f"{label} · {fo:.0f}m 遮挡")
        pw.setTitle(title)
        # 锁定显示范围：X 留塔桅余量，Y 下限锁 0 —— 波束超出 0 以下直接裁掉，
        # 量程固定不随数据跳变（padding=0 保证 8 图刻度完全一致）
        x0 = -user_max * 0.02
        pw.setXRange(x0, user_max, padding=0)
        pw.setYRange(y0, y1, padding=0)
        pw.setLimits(xMin=x0, xMax=user_max, yMin=y0, yMax=y1)

    def _draw_mini_empty(self, pw, az, reason, user_max, y0, y1):
        label = AZ_TO_LABEL.get(az, f"{az}°")
        pw.setTitle(f"{label} · 采样失败")
        t = pg.TextItem(f"✗ {reason}", color="#d62728", anchor=(0.5, 0.5))
        t.setPos(user_max / 2.0, (y0 + y1) / 2.0)
        pw.addItem(t)
        pw.setXRange(0, user_max, padding=0)
        pw.setYRange(y0, y1, padding=0)
        pw.setLimits(xMin=0, xMax=user_max, yMin=y0, yMax=y1)

    def _render_rose(self, results, user_max):
        pw = self.rose_pw
        pw.clear()
        pw.setTitle("阻挡玫瑰图\n(半径=首次遮挡距离)")

        # 参考圈（0.25/0.5/0.75/1.0 × 最大距离）
        for frac in (0.25, 0.5, 0.75, 1.0):
            r_c = user_max * frac
            circ_x = [r_c * math.cos(math.radians(t)) for t in range(0, 361, 10)]
            circ_y = [r_c * math.sin(math.radians(t)) for t in range(0, 361, 10)]
            pw.plot(circ_x, circ_y,
                    pen=pg.mkPen(color="#bbbbbb", width=1,
                                 style=Qt.DotLine if frac < 1.0 else Qt.SolidLine))

        for res in results:
            az = res["az"]
            theta = math.radians(90 - az)  # N 朝上
            r = res["first_occ"]
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            blocked = r < user_max - 1e-6   # 按用户最大距离判阻挡
            col = "#d62728" if blocked else "#2ca02c"
            pw.plot([0, x], [0, y], pen=pg.mkPen(color=col, width=3))
            # 方向标签（按方位角，不按下标）
            lx = (user_max * 1.08) * math.cos(theta)
            ly = (user_max * 1.08) * math.sin(theta)
            ti = pg.TextItem(AZ_TO_LABEL.get(az, f"{az}°").split()[0],
                             color="#333333", anchor=(0.5, 0.5))
            ti.setPos(lx, ly)
            pw.addItem(ti)
        pw.setXRange(-user_max * 1.2, user_max * 1.2)
        pw.setYRange(-user_max * 1.2, user_max * 1.2)

    def _fill_table(self, results):
        """固定 8 行；无结果的方向显示失败原因（红字）。"""
        by_az = {r["az"]: r for r in results}
        fail_map = dict(self._failures)
        user_max = self.maxdist_sb.value()
        self.table.setRowCount(8)
        for i in range(8):
            az = i * 45
            label = AZ_TO_LABEL[az]
            res = by_az.get(az)
            self.table.setItem(i, 0, QTableWidgetItem(label))
            if res is None:
                reason = fail_map.get(az, "无数据")
                for cidx in (1, 2):
                    self.table.setItem(i, cidx, QTableWidgetItem("—"))
                v_item = QTableWidgetItem(f"采样失败: {reason}")
                v_item.setForeground(QColor("#d62728"))
                self.table.setItem(i, 3, v_item)
                continue
            fo = res["first_occ"]
            max_hill = res["max_hill"]
            if fo >= user_max:
                v_item = QTableWidgetItem("全程畅通")
                v_item.setForeground(QColor("#2ca02c"))
            else:
                v_item = QTableWidgetItem(f"{fo:.0f} m 处被遮挡")
                v_item.setForeground(QColor("#d62728"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{fo:.0f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{max_hill:.1f}"))
            self.table.setItem(i, 3, v_item)


def QApplication_process():
    """触发一次事件循环，更新界面（用于在生成前刷新状态文本）。"""
    try:
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
    except Exception:  # nosec
        pass
