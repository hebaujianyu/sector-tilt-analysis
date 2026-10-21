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
    QLabel, QLineEdit, QDoubleSpinBox, QSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QHeaderView,
    QWidget, QScrollArea, QApplication
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
from qgis.utils import iface

from .tilt_core import _find_dem_layer, _match_field, FIELD_CANDIDATES, extract_site_values

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


class RingProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("环向剖面分析 (45° × 8 方向)")
        # 窗口自适应屏幕：不超过可用区域的 95%×90%，渲染时不被内容撑大（防跳变）
        screen = QApplication.desktop().availableGeometry()
        self.resize(min(1150, int(screen.width() * 0.95)),
                    min(820, int(screen.height() * 0.90)))
        self.setMaximumSize(screen.width(), screen.height() - 30)
        self._results = []
        self._failures = []
        self._worker = None
        self._mini = []          # 8 个分方向小剖面 PlotWidget
        self._prog_done = 0
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
        self.btn_center = QPushButton("从地图中心获取")
        self.btn_sel = QPushButton("从选中要素获取")
        self.btn_generate = QPushButton("生成环向剖面")
        self.btn_generate.setStyleSheet("font-weight:bold;")
        self.btn_close = QPushButton("关闭")
        btn_row.addWidget(self.btn_center)
        btn_row.addWidget(self.btn_sel)
        btn_row.addWidget(self.btn_generate)
        btn_row.addWidget(self.btn_close)
        form.addRow(btn_row)

        self.status_lbl = QLabel("输入经纬度后点「生成环向剖面」。")
        self.status_lbl.setWordWrap(True)
        form.addRow(self.status_lbl)

        params_gb.setMinimumWidth(350)
        left_col.addWidget(params_gb)

        # ---- 左列下方：8 方向汇总表（方案C：挪到参数下侧）----
        self.table = QTableWidget(8, 4)
        self.table.setHorizontalHeaderLabels(
            ["方向", "遮挡 (m)", "山体 (m)", "结论"]
        )
        hdr = self.table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(QHeaderView.Stretch)
        left_col.addWidget(self.table, 1)

        # ---- 右侧：3×3 九宫格（8 方向剖面按罗盘方位 + 中心玫瑰图）----
        if pg is not None:
            grid_holder = QWidget()
            grid = QGridLayout(grid_holder)
            grid.setSpacing(4)
            # 罗盘方位排布：索引 = azimuth // 45
            #   (0,0)NW (0,1)N (0,2)NE
            #   (1,0)W  (1,1)玫瑰 (1,2)E
            #   (2,0)SW (2,1)S (2,2)SE
            POS = {0: (0, 1), 1: (0, 2), 2: (1, 2), 3: (2, 2),
                   4: (2, 1), 5: (2, 0), 6: (1, 0), 7: (0, 0)}
            self._mini = []
            for i in range(8):
                pw = pg.PlotWidget(background="w")
                pw.setMinimumHeight(170)
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
            self.rose_pw.setAspectLocked(True)
            self.rose_pw.hideAxis("left")
            self.rose_pw.hideAxis("bottom")
            grid.addWidget(self.rose_pw, 1, 1)
            top.addLayout(left_col)
            top.addWidget(grid_holder, 1)
        else:
            self.rose_pw = None
            self._mini = []
            top.addLayout(left_col)
            top.addWidget(QLabel(
                "⚠️ 本环境未安装 pyqtgraph，无法绘制图表（仍可在左侧表格查看结果）。"
            ))

        # ---- 信号 ----
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_center.clicked.connect(self._from_map_center)
        self.btn_sel.clicked.connect(self._from_selection)
        self.btn_close.clicked.connect(self.close)

    # ------------------------------------------------------------------
    # 经纬度预填
    # ------------------------------------------------------------------
    def _from_map_center(self):
        try:
            canvas = iface.mapCanvas()
            center = canvas.center()
            crs = canvas.mapSettings().destinationCrs()
            if crs is not None and crs.authid() != "EPSG:4326":
                xform = QgsCoordinateTransform(
                    crs, QgsProject.instance().crsFromAuthId("EPSG:4326"),
                    QgsProject.instance()
                )
                pt = xform.transform(center)
            else:
                pt = center
            self.lon_le.setText(f"{pt.x():.6f}")
            self.lat_le.setText(f"{pt.y():.6f}")
            self.status_lbl.setText("已从地图中心获取经纬度。")
        except Exception as e:  # nosec
            self.status_lbl.setText(f"获取地图中心失败: {e}")

    def _from_selection(self):
        try:
            layer = iface.activeLayer()
            if not isinstance(layer, QgsVectorLayer):
                self.status_lbl.setText("请在图层树中选中一个矢量图层。")
                return
            sel = layer.selectedFeatures()
            if len(sel) != 1:
                self.status_lbl.setText("请选中恰好 1 个要素。")
                return
            feat = sel[0]
            fields = list(layer.fields())
            lon = lat = None
            lon_f = _match_field(fields, FIELD_CANDIDATES["longitude"])
            lat_f = _match_field(fields, FIELD_CANDIDATES["latitude"])
            if lon_f and lat_f:
                try:
                    lon = float(feat[lon_f])
                    lat = float(feat[lat_f])
                except (ValueError, TypeError, KeyError):  # nosec
                    lon = lat = None
            if lat is None or lon is None:
                geom = feat.geometry()
                if geom is not None and not geom.isEmpty():
                    centroid = geom.centroid().asPoint()
                    src_crs = layer.crs()
                    if src_crs is not None and src_crs.authid() != "EPSG:4326":
                        xform = QgsCoordinateTransform(
                            src_crs, QgsProject.instance().crsFromAuthId("EPSG:4326"),
                            QgsProject.instance()
                        )
                        pt = xform.transform(centroid)
                    else:
                        pt = centroid
                    lon, lat = pt.x(), pt.y()
            if lat is None or lon is None:
                self.status_lbl.setText("选中要素无法获取经纬度。")
                return
            self.lon_le.setText(f"{lon:.6f}")
            self.lat_le.setText(f"{lat:.6f}")
            # 顺便带入挂高/下倾（若有字段）
            vals = extract_site_values(
                {f.name(): feat[f.name()] for f in fields}, {}
            )
            if vals.get("height") is not None:
                try:
                    self.height_sb.setValue(float(vals["height"]))
                except (ValueError, TypeError):  # nosec
                    pass
            if vals.get("mech_tilt") is not None:
                try:
                    self.mech_sb.setValue(float(vals["mech_tilt"]))
                except (ValueError, TypeError):  # nosec
                    pass
            if vals.get("elec_tilt") is not None:
                try:
                    self.elec_sb.setValue(float(vals["elec_tilt"]))
                except (ValueError, TypeError):  # nosec
                    pass
            if vals.get("v_beamwidth") is not None:
                try:
                    vbw = float(vals["v_beamwidth"])
                    if 1 <= vbw <= 90:
                        self.vbw_sb.setValue(vbw)
                except (ValueError, TypeError):  # nosec
                    pass
            self.status_lbl.setText("已从选中要素获取经纬度与 RF 参数。")
        except Exception as e:  # nosec
            self.status_lbl.setText(f"从选中要素获取失败: {e}")

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

        # ---- 2×4 八宫格：每方向一张独立剖面 ----
        for i, pw in enumerate(self._mini):
            pw.clear()
            az = i * 45
            res = by_az.get(az)
            if res is None:
                reason = next(
                    (m for a, m in self._failures if a == az), "无数据"
                )
                self._draw_mini_empty(pw, az, reason, user_max)
            else:
                self._draw_mini(pw, res, user_max)

        # ---- 阻挡玫瑰图 ----
        if self.rose_pw is not None:
            self._render_rose(results, user_max)

    def _draw_mini(self, pw, res, user_max):
        az = res["az"]
        label = AZ_TO_LABEL.get(az, f"{az}°")
        dists, elevs, beam = res["dists"], res["elevs"], res["beam"]
        fo = res["first_occ"]
        clear = fo >= user_max
        sg = res["site_ground"]
        h = self.height_sb.value()

        # ---- 地形（Tab1 同款：赭黄实填充 + 红棕脊线）----
        pw.plot(dists, elevs, pen=pg.mkPen("#A0522D", width=2),
                fillLevel=min(elevs),
                fillBrush=pg.mkBrush(205, 133, 63, 170))

        # ---- 主波束（绿实线）+ 上/下波束（蓝/红虚线，总下倾±垂直波束宽度/2）----
        tilt = res.get("tilt",
                       self.mech_sb.value() + self.elec_sb.value())
        vbw = getattr(self, "_last_vbw", self.vbw_sb.value())
        ang_u = max(min(tilt - vbw / 2.0, 89.5), -89.5)
        ang_l = max(min(tilt + vbw / 2.0, 89.5), -89.5)
        upper = [sg + h - d * math.tan(math.radians(ang_u)) for d in dists]
        lower = [sg + h - d * math.tan(math.radians(ang_l)) for d in dists]
        pw.plot(dists, beam, pen=pg.mkPen((0, 160, 0), width=2))
        pw.plot(dists, upper,
                pen=pg.mkPen("#185FA5", width=1.5, style=Qt.DashLine))
        pw.plot(dists, lower,
                pen=pg.mkPen("#A32D2D", width=1.5, style=Qt.DashLine))

        # ---- 塔桅（Tab1 同款铁塔造型：两条收边线 + 三道横撑 + 塔顶黑点）----
        base_half = max(user_max * 0.012, 5.0)
        for sgn in (-1, 1):
            pw.plot([sgn * base_half, 0], [sg, sg + h],
                    pen=pg.mkPen("k", width=1))
        for frac in (0.25, 0.55, 0.85):
            y = sg + h * frac
            xw = base_half * (1.0 - frac)
            pw.plot([-xw, xw], [y, y], pen=pg.mkPen("k", width=1))
        pw.addItem(pg.ScatterPlotItem(
            x=[0], y=[sg + h], size=8,
            pen=None, brush=pg.mkBrush("k")))

        # ---- 波束-地形交点（上=蓝点 / 下=红点，对应 Tab1 覆盖图 RF Legend）----
        def _first_cross(line):
            for d, e, lv in zip(dists, elevs, line):
                if d > 1 and e > lv:
                    return d, e
            return None, None

        for line, color in ((upper, "#185FA5"), (lower, "#A32D2D")):
            cd, ce = _first_cross(line)
            if cd is not None:
                pw.addItem(pg.ScatterPlotItem(
                    x=[cd], y=[ce], size=8,
                    pen=pg.mkPen(color, width=1.5),
                    brush=pg.mkBrush(color)))

        # ---- 首次遮挡点（红点 + 距离标注，对应 Tab1 的 "246 m" 标签）----
        if not clear:
            idx = min(range(len(dists)), key=lambda k: abs(dists[k] - fo))
            pw.addItem(pg.ScatterPlotItem(
                x=[dists[idx]], y=[elevs[idx]], size=12,
                pen=pg.mkPen("#A32D2D", width=2),
                brush=pg.mkBrush("#A32D2D")))
            ti = pg.TextItem(f"{fo:.0f} m", color="#A32D2D",
                             anchor=(0.5, 1.15))
            ti.setPos(dists[idx], elevs[idx])
            pw.addItem(ti)

        title = (f"{label} — 全程畅通" if clear
                 else f"{label} — {fo:.0f} m 处遮挡")
        pw.setTitle(title)
        pw.setXRange(0, user_max)

    def _draw_mini_empty(self, pw, az, reason, user_max):
        label = AZ_TO_LABEL.get(az, f"{az}°")
        pw.setTitle(f"{label} — 采样失败")
        t = pg.TextItem(f"✗ {reason}", color="#d62728", anchor=(0.5, 0.5))
        t.setPos(user_max / 2.0, 0.5)
        pw.addItem(t)
        pw.setXRange(0, user_max)
        pw.setYRange(0, 1)

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
