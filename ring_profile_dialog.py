# -*- coding: utf-8 -*-
# ============================================================================
# ring_profile_dialog.py — 环向剖面分析 (45° × 8 方向)
#
# 给定经纬度(天线挂高 + 机械/电子下倾)，对 8 个方向(每 45°)采样地形剖面，
# 计算「首次地形遮挡距离」与「最大山体高度」，并用 pyqtgraph 渲染：
#   - 上：8 条叠加地形剖面 + 主波束参考线
#   - 下：极坐标阻挡玫瑰图（半径=首次遮挡距离，红=被遮挡/绿=全程畅通）
#   - 底：8 方向汇总表
#
# 复用内嵌 TerrainSampler（本地 DEM / Open-Meteo 在线），无需额外依赖。
# ============================================================================

import math

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QDoubleSpinBox, QSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QHeaderView
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

# 8 个方向标签与固定配色
DIRECTION_LABELS = ["N (0°)", "NE (45°)", "E (90°)", "SE (135°)",
                    "S (180°)", "SW (225°)", "W (270°)", "NW (315°)"]
DIRECTION_COLORS = [
    "#d62728", "#ff7f0e", "#bcbd22", "#2ca02c",
    "#1f77b4", "#9467bd", "#8c564b", "#17becf",
]


def compute_ring(sampler, site, azimuths, max_d, step, source,
                 height, total_tilt):
    """核心：对 8 个方向采样地形剖面并计算遮挡/山体指标。"""
    tilt_rad = math.radians(total_tilt)
    results = []
    for az in azimuths:
        prof = sampler.sample_profile(
            site, az, max_d, step, source=source, timeout=60
        )
        dists = prof.get("distances", [])
        elevs = prof.get("elevations", [])
        if not dists:
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
        })
    return results


class _RingWorker(QThread):
    """后台采样 8 个方向地形剖面（避免在线请求时界面卡死）。"""
    result_ready = pyqtSignal(list)
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

    def run(self):
        try:
            results = compute_ring(
                self.sampler, self.site, self.azimuths, self.max_d,
                self.step, self.source, self.height, self.total_tilt
            )
            self.result_ready.emit(results)
        except Exception as e:  # nosec
            self.error_occured.emit(str(e))


class RingProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("环向剖面分析 (45° × 8 方向)")
        self.resize(1000, 720)
        self._results = []
        self._worker = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = QVBoxLayout(self)

        top = QHBoxLayout()
        main.addLayout(top)

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
        form.addRow(self.status_lbl)

        top.addWidget(params_gb)

        # ---- 右侧绘图区 ----
        right = QVBoxLayout()
        top.addLayout(right, 1)

        if pg is not None:
            # 白底黑字，跟随 QGIS 浅色主题（默认黑底在浅色主题下不可读）
            self.profile_pw = pg.PlotWidget(
                title="8 方向地形剖面 (相对站点地面, m)", background="w"
            )
            self.rose_pw = pg.PlotWidget(
                title="阻挡玫瑰图 (半径=首次遮挡距离)", background="w"
            )
            self.profile_pw.setMinimumHeight(260)
            self.rose_pw.setMinimumHeight(300)
            right.addWidget(self.profile_pw)
            right.addWidget(self.rose_pw)
        else:
            self.profile_pw = None
            self.rose_pw = None
            right.addWidget(QLabel("⚠️ 本环境未安装 pyqtgraph，无法绘制图表（仍可在下方表格查看结果）。"))

        # ---- 底部汇总表 ----
        self.table = QTableWidget(8, 4)
        self.table.setHorizontalHeaderLabels(
            ["方向", "首次遮挡距离 (m)", "最大山体高度 (m)", "结论"]
        )
        hdr = self.table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(QHeaderView.Stretch)
        main.addWidget(self.table)

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
            self.status_lbl.setText("已从选中要素获取经纬度与 RF 参数。")
        except Exception as e:  # nosec
            self.status_lbl.setText(f"从选中要素获取失败: {e}")

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
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
            else:
                QMessageBox.warning(
                    self, "环向剖面",
                    "本地 DEM 模式需要项目中加载一个高程栅格图层；\n"
                    "若没有本地 DEM，请将「地形源」切换为 Open-Meteo (在线)。"
                )
                return
        else:
            try:
                sampler = TerrainSampler(dem)
            except Exception as e:
                QMessageBox.warning(self, "环向剖面", f"地形采样器初始化失败:\n{e}")
                return

        height = self.height_sb.value()
        total_tilt = self.mech_sb.value() + self.elec_sb.value()
        max_d = self.maxdist_sb.value()
        step = max(1, self.step_sb.value())
        azimuths = [i * 45 for i in range(8)]
        site = QgsPointXY(lon, lat)

        self.status_lbl.setText("正在采样 8 个方向地形剖面，请稍候…")
        self.btn_generate.setEnabled(False)
        QApplication_process()

        # 本地 DEM 在主线程采样（避免栅格 identify 跨线程）；在线走后台 worker
        if source == "local":
            try:
                results = compute_ring(
                    sampler, site, azimuths, max_d, step, source,
                    height, total_tilt
                )
                self._on_results(results)
            except Exception as e:  # nosec
                self._on_error(str(e))
            self._on_worker_done()
        else:
            self._worker = _RingWorker(
                sampler, site, azimuths, max_d, step, source, height, total_tilt
            )
            self._worker.result_ready.connect(self._on_results)
            self._worker.error_occured.connect(self._on_error)
            self._worker.finished.connect(self._on_worker_done)
            self._worker.start()

    def _on_results(self, results):
        self._results = results
        self._render(results)
        self._fill_table(results)

    def _on_error(self, msg):
        self.status_lbl.setText(f"采样失败: {msg}")
        QMessageBox.warning(self, "环向剖面", f"地形采样失败:\n{msg}")

    def _on_worker_done(self):
        self.btn_generate.setEnabled(True)
        if not self._results:
            self.status_lbl.setText("无有效采样结果（请检查经纬度/地形源）。")

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render(self, results):
        if pg is None or self.profile_pw is None:
            return
        self.profile_pw.clear()
        self.rose_pw.clear()

        if not results:
            return

        # 叠加 8 方向剖面
        self.profile_pw.addLegend()
        for i, res in enumerate(results):
            color = DIRECTION_COLORS[i % len(DIRECTION_COLORS)]
            self.profile_pw.plot(
                res["dists"], res["elevs"],
                pen=pg.mkPen(color=color, width=1.5),
                name=DIRECTION_LABELS[i % 8]
            )
        # 主波束参考线（取第一个方向的站点地面为基准）
        base = results[0]
        self.profile_pw.plot(
            base["dists"], base["beam"],
            pen=pg.mkPen(color="#000000", width=2, style=Qt.DashLine),
            name="主波束中心线"
        )
        self.profile_pw.setLabel("bottom", "距离 (m)")
        self.profile_pw.setLabel("left", "高程 (m, 相对海平面)")
        self.profile_pw.showGrid(x=True, y=True, alpha=0.3)

        # 极坐标玫瑰图
        self.rose_pw.setAspectLocked(True)
        self.rose_pw.hideAxis("left")
        self.rose_pw.hideAxis("bottom")
        max_d = max((r["first_occ"] for r in results), default=1)
        # 参考圆
        circ_x = [max_d * math.cos(math.radians(t)) for t in range(0, 361, 10)]
        circ_y = [max_d * math.sin(math.radians(t)) for t in range(0, 361, 10)]
        if circ_x:
            self.rose_pw.plot(circ_x, circ_y,
                              pen=pg.mkPen(color="#999999", width=1))
        for i, res in enumerate(results):
            az = res["az"]
            theta = math.radians(90 - az)  # N 朝上
            r = res["first_occ"]
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            blocked = res["first_occ"] < max_d
            col = "#d62728" if blocked else "#2ca02c"
            self.rose_pw.plot([0, x], [0, y],
                              pen=pg.mkPen(color=col, width=3))
            # 方向标签
            lx = (max_d * 1.08) * math.cos(theta)
            ly = (max_d * 1.08) * math.sin(theta)
            ti = pg.TextItem(DIRECTION_LABELS[i % 8].split()[0],
                             color=col, anchor=(0.5, 0.5))
            ti.setPos(lx, ly)
            self.rose_pw.addItem(ti)
        self.rose_pw.setXRange(-max_d * 1.2, max_d * 1.2)
        self.rose_pw.setYRange(-max_d * 1.2, max_d * 1.2)

    def _fill_table(self, results):
        self.table.setRowCount(len(results))
        for i, res in enumerate(results):
            az = res["az"]
            first_occ = res["first_occ"]
            max_hill = res["max_hill"]
            clear = first_occ >= self.maxdist_sb.value()
            if clear:
                verdict = "全程畅通"
                v_item = QTableWidgetItem(verdict)
                v_item.setForeground(QColor("#2ca02c"))
            else:
                verdict = f"{first_occ:.0f} m 处被遮挡"
                v_item = QTableWidgetItem(verdict)
                v_item.setForeground(QColor("#d62728"))
            self.table.setItem(i, 0, QTableWidgetItem(DIRECTION_LABELS[i % 8]))
            self.table.setItem(i, 1, QTableWidgetItem(f"{first_occ:.0f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{max_hill:.1f}"))
            self.table.setItem(i, 3, v_item)


def QApplication_process():
    """触发一次事件循环，更新界面（用于在生成前刷新状态文本）。"""
    try:
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
    except Exception:  # nosec
        pass
