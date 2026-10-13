# -*- coding: utf-8 -*-
"""
TiltMaster - RF Vertical Analysis for QGIS

Copyright (C) 2026 Achmad Amrulloh

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

"""
terrain_profile_widget.py

RF Vertical Terrain Profile Widget
menggunakan PyQtGraph.

Menampilkan:
- terrain profile
- main beam
- upper beam
- lower beam
- impact point
"""

import os
import math
import traceback  # <-- TAMBAHKAN INI
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
                             QMessageBox, QApplication, QGraphicsLineItem,
                             QGraphicsRectItem, QGraphicsItemGroup, QGraphicsEllipseItem)
from PyQt5 import QtCore
from PyQt5.QtGui import QLinearGradient, QColor, QBrush, QPen
from .profile_legend_frame import ProfileLegendFrame
from PyQt5.QtCore import QTimer, QPointF, Qt

# ======================================================
# PYQTGRAPH IMPORT DENGAN GRACEFUL FALLBACK
# ======================================================
PYQTGRAPH_AVAILABLE = True
PG_IMPORT_ERROR = None

try:
    import pyqtgraph as pg
except ImportError as e:
    PYQTGRAPH_AVAILABLE = False
    PG_IMPORT_ERROR = str(e)
    print(f"⚠️ PyQtGraph tidak tersedia: {e}")
    print("⚠️ TerrainProfileWidget akan menampilkan pesan error")
    
    # Buat dummy class untuk mencegah crash saat kompilasi
    class DummyPg:
        class PlotWidget:
            def __init__(self, parent=None): 
                self.plotItem = None
            def setBackground(self, *args): pass
            def showGrid(self, *args): pass
            def setLabel(self, *args): pass
            def setMouseEnabled(self, *args): pass
            def getViewBox(self): return DummyViewBox()
            def setClipToView(self, *args): pass
            def setDownsampling(self, *args): pass
            def setAntialiasing(self, *args): pass
            def addItem(self, *args): pass
            def enableAutoRange(self, *args): pass
            def scene(self): return DummyScene()
        
        class DummyViewBox:
            def setMouseMode(self, *args): pass
            def setMouseEnabled(self, *args): pass
            def enableAutoRange(self, *args): pass
            def viewRange(self): return [[0,1000], [0,100]]
            def height(self): return 400
            def mapFromView(self, point): return QPointF(0,0)
        
        class DummyScene:
            def sigMouseMoved(self): return DummySignal()
        
        class DummySignal:
            def connect(self, *args): pass
        
        class mkPen:
            def __new__(cls, *args, **kwargs): return None
        
        class InfiniteLine:
            def __init__(self, *args, **kwargs): pass
            def setZValue(self, *args): pass
        
        class TextItem:
            def __init__(self, *args, **kwargs): pass
            def setPos(self, *args): pass
            def setZValue(self, *args): pass
            def stackBefore(self, *args): pass
        
        class ScatterPlotItem:
            def __init__(self, *args, **kwargs): pass
            def setZValue(self, *args): pass
        
        class FillBetweenItem:
            def __init__(self, *args, **kwargs): pass
            def setZValue(self, *args): pass
        
        class LinearRegionItem:
            def __init__(self, *args, **kwargs): pass
            def setZValue(self, *args): pass
        
        class PlotDataItem:
            def __init__(self, *args, **kwargs): pass
        
        class SignalProxy:
            def __init__(self, *args, **kwargs): pass
        
        def mkBrush(*args, **kwargs): return None
    
    pg = DummyPg()



class TerrainProfileWidget(QWidget):

    def __init__(self, parent=None):

        super().__init__(parent)

        # ======================================================
        # MAIN LAYOUT
        # ======================================================

        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)


        # ======================================================
        # CREATE EMPTY PLACEHOLDER
        # ======================================================

        self.plot = None
        self.plot_item = None


        # ======================================================
        # CEK KETERSEDIAAN PYQTGRAPH
        # ======================================================
        if not PYQTGRAPH_AVAILABLE:
            # Buat link ke GitHub troubleshooting guide
            # Ganti 'username/repo' dengan repository GitHub Anda yang sebenarnya
            github_repo = ""
            troubleshooting_url = ""
            
            error_label = QLabel(
                f"<b>⚠️ PyQtGraph Not Installed</b><br><br>"
                f"本插件需要 PyQtGraph 才能显示地形剖面图。<br><br>"
                f"<b>How to install PyQtGraph - Using OSGeo4W (Windows):</b><br>"
                f"<a href='{troubleshooting_url}'>Click here for detailed troubleshooting guide</a><br><br>"
                f"<small>Error: {PG_IMPORT_ERROR}</small>"
            )
            error_label.setWordWrap(True)
            error_label.setOpenExternalLinks(True)  # Aktifkan klik link
            error_label.setStyleSheet("""
                QLabel {
                    color: #c1121f;
                    background-color: #fff3f3;
                    border: 2px solid #c1121f;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 10px;
                    font-size: 11pt;
                }
                code {
                    background-color: #f0f0f0;
                    padding: 2px 5px;
                    border-radius: 3px;
                    font-family: monospace;
                }
                a {
                    color: #0c6075;
                    text-decoration: none;
                }
                a:hover {
                    text-decoration: underline;
                }
            """)
            error_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(error_label)
            
            # Set dummy plot untuk mencegah error
            self.plot = None
            self.plot_item = None
            self.vLine = None
            self.hLine = None
            self.proxy = None
            
            # Return early, jangan lanjutkan inisialisasi
            return

        # ======================================================
        # INIT PLOT WIDGET AFTER LAYOUT ATTACH
        # ======================================================

        self.plot = pg.PlotWidget(parent=self)
        layout.addWidget(self.plot)

        self.plot_item = self.plot.getPlotItem()
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True)
        
        # performance optimizations
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True)
        self.plot.setAntialiasing(False)
        
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True)
        
        # =====================================================
        # FLAG UNTUK CEK STATUS DESTROY
        # =====================================================
        self._is_destroying = False

        # ======================================================
        # AXIS LABELS - AKAN DIUPDATE NANTI
        # ======================================================
        
        self.plot.setLabel("left", "Elevation")
        self.plot.setLabel("bottom", "Distance")
        
        # Simpan referensi untuk update nanti
        self._axis_units = "metric"  # default
        
        # ======================================================
        # NONAKTIFKAN SEMUA INTERAKSI MOUSE (SCROLL DAN DRAG)
        # ======================================================
        
        # Matikan zoom dengan scroll
        self.plot.setMouseEnabled(x=False, y=False)
        
        # Matikan drag zoom dan pan
        viewbox = self.plot.getViewBox()
        viewbox.setMouseMode(viewbox.PanMode)  # Set ke PanMode dulu
        viewbox.setMouseEnabled(False, False)  # Matikan mouse di viewbox
        
        # Kunci view agar tidak bisa diubah
        viewbox.setMouseMode(viewbox.PanMode)
        viewbox.enableAutoRange(False)
        
        # ======================================================
        # LEGEND (FRAME BASED - DRAGGABLE)
        # ======================================================
        self.legend_frame = ProfileLegendFrame(self)
        self.legend_frame.move(20, 20)  # Sementara di kiri dulu
        self.legend_frame.raise_()
        self.legend_frame.show()
        # Pindahkan ke kanan atas setelah widget siap
        QTimer.singleShot(100, self._position_legend_top_right)
        
        # Force update layout
        self.legend_frame.updateGeometry()
        self.legend_frame.adjustSize()
        QApplication.processEvents()
        
        # ======================================================
        # TOWER ITEM REFERENCE (UNTUK CLEANUP)
        # ======================================================
        
        self._tower_item = None  # <-- TAMBAHKAN INI
        self._tower_params = None  # <-- TAMBAHKAN INI
        
        # ======================================================
        # CURVES
        # ======================================================

        self.terrain_curve = self.plot_item.plot([], [], pen=pg.mkPen("brown", width=2), name="Terrain")

        self.terrain_strong = self.plot_item.plot([], [], pen=pg.mkPen((0,180,0), width=3), name="Strong")

        self.terrain_weak = self.plot_item.plot([], [], pen=pg.mkPen((255,180,0), width=3), name="Weak")

        self.terrain_shadow = self.plot_item.plot([], [], pen=pg.mkPen((200,0,0), width=3), name="Shadow")

        self.main_beam_curve = self.plot_item.plot([], [], pen=pg.mkPen((0,160,0), width=3), name="Main Beam")

        self.upper_beam_curve = self.plot_item.plot([], [], pen=pg.mkPen("blue", width=2, style=QtCore.Qt.DashLine), name="Upper Beam")

        self.lower_beam_curve = self.plot_item.plot([], [], pen=pg.mkPen("red", width=2, style=QtCore.Qt.DashLine), name="Lower Beam")
               
                       
        # ======================================================
        # INTERSECTION LABELS
        # ======================================================
        
        self._intersection_labels = []  # List untuk menyimpan label intersection
                
        # ======================================================
        # IMPACT POINT TRACKING (BARU)
        # ======================================================
        
        self._last_impact_point = None
        
        # ======================================================
        # CROSSHAIR
        # ======================================================

        self.vLine = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen((150,150,150), width=1)
        )
        self.vLine.setZValue(-100)  # <-- TAMBAHKAN INI (sangat rendah)
        self.hLine = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen((150,150,150), width=1)
        )
        self.hLine.setZValue(-100)  # <-- TAMBAHKAN INI!
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)

        # ======================================================
        # DATA HOLDER
        # ======================================================

        self._distances = []
        self._terrain = []
        self._beam = []

        # ======================================================
        # MOUSE TRACKING - OPTIMIZED
        # ======================================================

        self.proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=20,  # Turunkan dari 60 ke 20
            slot=self._mouse_moved
        )
        
        # Cache untuk binary search
        self._distances_array = None  # Akan di-update saat plot
    
    
    def cleanup_timers(self):
        """
        Clean up timers to prevent QGIS hang on close
        """
        print("🧹 Cleaning up TerrainProfileWidget timers...")
        
        # =====================================================
        # SET FLAG DESTROYING
        # =====================================================
        self._is_destroying = True
        
        # =====================================================
        # DISCONNECT SIGNAL PROXY
        # =====================================================
        if hasattr(self, 'proxy') and self.proxy:
            try:
                # SignalProxy tidak memiliki method disconnect langsung,
                # tapi kita bisa set ke None
                self.proxy = None
            except:
                pass
        
        print("✅ TerrainProfileWidget timers cleaned up")
    
    
    def set_unit_system(self, is_metric):
        """
        Update unit system for axis labels
        Called from dialog when unit changes
        """
        self._axis_units = "metric" if is_metric else "imperial"
        print(f"📏 TerrainProfileWidget unit system set to: {self._axis_units}")
        
        # Update axis labels immediately if plot exists
        if hasattr(self, 'plot_item') and self.plot_item:
            left_axis = self.plot_item.getAxis("left")
            bottom_axis = self.plot_item.getAxis("bottom")
            
            if is_metric:
                left_axis.setLabel("Elevation (m)")
                bottom_axis.setLabel("Distance (m)")
            else:
                left_axis.setLabel("Elevation (ft)")
                bottom_axis.setLabel("Distance (mi)")  # <-- PASTIKAN "mi"
            
    
    def _add_vline_with_label(self, x_pos, color, label_text):
        """
        Add vertical line with label at bottom of chart
        
        Parameters
        ----------
        x_pos : float
            X position in meters
        color : tuple or str
            Color for line and label
        label_text : str
            Text to display (e.g. "583 m")
        """
        # Add vertical line
        vline = pg.InfiniteLine(
            pos=x_pos,
            angle=90,
            pen=pg.mkPen(color, width=1, style=QtCore.Qt.DashLine)
        )
        vline.setZValue(100)
        self.plot_item.addItem(vline)
        
        # Add label at bottom
        # Get current Y range to place label at bottom
        view_range = self.plot_item.viewRange()
        y_min = view_range[1][0]  # minimum Y in view
        
        # Place label slightly above bottom axis
        label_y = y_min - 5  # 5 meters below visible range
        
        label = pg.TextItem(
            text=label_text,
            anchor=(0.5, 1),  # anchor at top-center
            color=color,
            html=None
        )
        label.setPos(x_pos, label_y)
        label.setZValue(150)  # Above everything
        self.plot_item.addItem(label)
        
        # Store reference for potential updates
        if not hasattr(self, '_vline_labels'):
            self._vline_labels = []
        self._vline_labels.append((vline, label, x_pos))
        
        # ======================================================
        # INTERSECTION DATA FOR LABELS
        # ======================================================
        self._last_impact_point = None
        self._last_impact_y = None
        self._last_upper_x = None
        self._last_upper_y = None
        self._last_lower_x = None
        self._last_lower_y = None
        
    
    
    def _add_intersection_labels(self):
        """
        Add labels for intersection points with white background
        Labels appear at BOTTOM CENTER of the point (below the point)
        Menggunakan style yang sama dengan MapLegendFrame
        """
        print("\n🔍 _add_intersection_labels CALLED")
        
        # Dapatkan viewBox
        vb = self.plot_item.getViewBox()
        if vb is None:
            print("   ⚠️ ViewBox is None")
            return
        
        # ======================================================
        # TENTUKAN UNIT UNTUK LABEL
        # ======================================================
        is_metric = getattr(self, '_axis_units', 'metric') == 'metric'
        
        # Debug: cek data yang tersimpan
        print(f"   Data yang tersimpan:")
        print(f"   - _last_impact_point: {getattr(self, '_last_impact_point', None)}")
        print(f"   - _last_impact_y: {getattr(self, '_last_impact_y', None)}")
        print(f"   - _last_upper_x: {getattr(self, '_last_upper_x', None)}")
        print(f"   - _last_upper_y: {getattr(self, '_last_upper_y', None)}")
        print(f"   - _last_lower_x: {getattr(self, '_last_lower_x', None)}")
        print(f"   - _last_lower_y: {getattr(self, '_last_lower_y', None)}")
        
        # Kumpulkan data intersection
        intersections = []
        
        # Helper untuk format jarak berdasarkan unit
        def format_distance(d):
            if d is None:
                return "—"
            if is_metric:
                if d >= 1000:
                    return f"{d/1000:.2f} km"
                else:
                    return f"{d:.0f} m"
            else:
                d_ft = d * 3.28084
                if d_ft >= 5280:
                    return f"{d_ft/5280:.2f} mi"
                else:
                    return f"{d_ft:.0f} ft"
        
        # Main impact
        if hasattr(self, '_last_impact_point') and self._last_impact_point is not None:
            if hasattr(self, '_last_impact_y') and self._last_impact_y is not None:
                intersections.append((self._last_impact_point, self._last_impact_y, 
                                    format_distance(self._last_impact_point), (0, 160, 0)))
                print(f"   ✅ Main impact added: {self._last_impact_point:.0f}m")
        
        # Upper intersection
        if hasattr(self, '_last_upper_x') and self._last_upper_x is not None:
            if hasattr(self, '_last_upper_y') and self._last_upper_y is not None:
                intersections.append((self._last_upper_x, self._last_upper_y,
                                    format_distance(self._last_upper_x), (42, 125, 225)))
                print(f"   ✅ Upper intersection added: {self._last_upper_x:.0f}m")
        
        # Lower intersection
        if hasattr(self, '_last_lower_x') and self._last_lower_x is not None:
            if hasattr(self, '_last_lower_y') and self._last_lower_y is not None:
                intersections.append((self._last_lower_x, self._last_lower_y,
                                    format_distance(self._last_lower_x), (255, 0, 0)))
                print(f"   ✅ Lower intersection added: {self._last_lower_x:.0f}m")
        
        print(f"   Total intersections to draw: {len(intersections)}")
        
        # ======================================================
        # HAPUS LABEL LAMA SEBELUM MENAMBAH YANG BARU
        # ======================================================
        if hasattr(self, '_intersection_labels'):
            for label in self._intersection_labels:
                try:
                    self.plot_item.removeItem(label)
                except:
                    pass
            self._intersection_labels = []
        else:
            self._intersection_labels = []
        
        for i, (x_pos, y_pos, text, color) in enumerate(intersections):
            print(f"   Drawing label {i+1}: {text} at plot ({x_pos:.1f}, {y_pos:.1f})")
            
            # ======================================================
            # KONVERSI Y POS KE UNIT YANG SESUAI UNTUK PLOT
            # ======================================================
            if not is_metric:
                # Konversi y_pos dari meter ke feet untuk imperial
                plot_y = y_pos * 3.28084
            else:
                plot_y = y_pos
            
            # Konversi warna ke format rgba untuk opacity
            if isinstance(color, tuple):
                r, g, b = color
                color_str = f"rgb({r}, {g}, {b})"
            else:
                color_str = color
            
            # ======================================================
            # STYLE: SAMA DENGAN MAP LEGEND FRAME
            # ======================================================
            html_text = f"""
            <div style="
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid #2c5a6b;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 9pt;
                font-weight: 500;
                color: {color_str};
                font-family: 'Segoe UI', Arial, sans-serif;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                letter-spacing: 0.3px;
            ">&nbsp;{text}</div>
            """
            
            # ======================================================
            # TENTUKAN OFFSET BERDASARKAN UNIT
            # ======================================================
            if is_metric:
                offset = 10  # 10 meter ke bawah
            else:
                offset = 33  # 10 meter ≈ 33 feet ke bawah
            
            # Anchor (0.5, 1) berarti bottom-center dari teks berada di posisi yang ditentukan
            # Dengan posisi di (x_pos, plot_y - offset), teks akan muncul di BAWAH titik
            label = pg.TextItem(
                html=html_text,
                anchor=(0.5, 1)  # anchor di bottom-center
            )
            
            # Set posisi dengan offset ke BAWAH
            label.setPos(x_pos, plot_y - offset)
            label.setZValue(2000)
            
            # Paksa di atas crosshair
            if hasattr(self, 'vLine') and self.vLine is not None:
                label.stackBefore(self.vLine)
            if hasattr(self, 'hLine') and self.hLine is not None:
                label.stackBefore(self.hLine)
            
            # Tambahkan ke plot
            self.plot_item.addItem(label)
            self._intersection_labels.append(label)
            
            # Debug print dengan unit yang sesuai
            if is_metric:
                print(f"      ✅ Label added at plot ({x_pos:.1f}, {plot_y:.1f}) with offset -{offset}m (BOTTOM)")
            else:
                print(f"      ✅ Label added at plot ({x_pos:.1f}, {plot_y:.1f}) with offset -{offset}ft (BOTTOM)")
        
    
    # ======================================================
    # PLOT PROFILE (REFactored Stable Version)
    # ======================================================

    def plot_profile(
        self,
        distances,
        elevations,
        antenna_height,
        main_beam_angle,
        upper_beam_angle,
        lower_beam_angle,
        impact_distance=None,
        mech_tilt=None,
        elec_tilt=None,  # <-- TAMBAHKAN INI
        beamwidth=None,
        # PARAMETER BARU
        main_intersection_distance=None,
        upper_intersection_distance=None,
        lower_intersection_distance=None,
        shadow_regions=None,
        # TAMBAHKAN PARAMETER BARU INI
        main_beam_height=None,
        upper_beam_height=None,
        lower_beam_height=None
    ):
        # ======================================================
        # GUARD CLAUSE: Jika PyQtGraph tidak tersedia, return early
        # ======================================================
        if not PYQTGRAPH_AVAILABLE or self.plot is None or self.plot_item is None:
            print("⚠️ TerrainProfileWidget: PyQtGraph tidak tersedia, plot_profile di-skip")
            return
        
        distances = list(distances)
        elevations = list(elevations)

        if not distances or not elevations:
            return

        print("PLOT PROFILE CALLED")
        
        # ======================================================
        # PASTIKAN UNIT SYSTEM
        # ======================================================
        is_metric = getattr(self, '_axis_units', 'metric') == 'metric'
        print(f"📏 Unit system: {'Metric' if is_metric else 'Imperial'}")
        
        # =====================================================
        # HAPUS TOWER LAMA JIKA ADA
        # =====================================================
        self._remove_tower()
        
        
        # ======================================================
        # DEBUG: CEK DATA YANG DITERIMA
        # ======================================================
        print(f"\n🔍 DATA RECEIVED BY WIDGET:")
        print(f"  • main_beam_height: {main_beam_height} (type: {type(main_beam_height)})")
        print(f"  • main_intersection_distance: {main_intersection_distance}")
        print(f"  • upper_beam_height: {upper_beam_height}")
        print(f"  • lower_beam_height: {lower_beam_height}")
        print(f"  • impact_distance: {impact_distance}")

        # ======================================================
        # CLEAN DYNAMIC ITEMS
        # ======================================================

        # Hapus vline labels yang tersimpan
        if hasattr(self, '_vline_labels'):
            for vline, label, _ in self._vline_labels:
                try:
                    self.plot_item.removeItem(vline)
                    self.plot_item.removeItem(label)
                except:
                    pass
            self._vline_labels = []

        for item in list(self.plot_item.items):
            # Skip crosshair lines
            if item is self.vLine or item is self.hLine:
                continue
                
            if isinstance(item, (
                pg.ScatterPlotItem,
                pg.LinearRegionItem,
                pg.ArrowItem,
                pg.TextItem,
                pg.FillBetweenItem,
                pg.InfiniteLine
            )):
                self.plot_item.removeItem(item)
        
        # Hapus terrain fill jika ada (sebagai tambahan)
        if hasattr(self, 'terrain_fill'):
            try:
                self.plot_item.removeItem(self.terrain_fill)
            except:
                pass
            self.terrain_fill = None
        
        
        # Hapus header items
        if hasattr(self, '_header_items'):
            for item in self._header_items:
                try:
                    self.plot_item.removeItem(item)
                except:
                    pass
            self._header_items = []
        
        
        # Hapus point labels yang tersimpan
        if hasattr(self, '_point_labels'):
            for proxy in self._point_labels:
                try:
                    self.plot_item.scene().removeItem(proxy)
                except:
                    pass
            self._point_labels = []
        
        # Hapus debug rects
        if hasattr(self, '_debug_rects'):
            for rect in self._debug_rects:
                try:
                    self.plot_item.scene().removeItem(rect)
                except:
                    pass
            self._debug_rects = []
            
                
        # Hapus intersection labels
        if hasattr(self, '_intersection_labels'):
            for label in self._intersection_labels:
                try:
                    self.plot_item.removeItem(label)
                except:
                    pass
            self._intersection_labels = []
            
            
        # ======================================================
        # TERRAIN SMOOTHING - OPTIMIZED (O(n) instead of O(n²))
        # ======================================================

        window = 3  # Kurangi window size dari 5 ke 3
        n = len(elevations)
        
        if n > window * 2:
            # Gunakan teknik moving average dengan convolution
            try:
                import numpy as np
                elevations_array = np.array(elevations)
                kernel = np.ones(window) / window
                smooth = np.convolve(elevations_array, kernel, mode='same')
                
                # Handle edges
                smooth[:window//2] = elevations_array[:window//2]
                smooth[-window//2:] = elevations_array[-window//2:]
                elevations = smooth.tolist()
            except ImportError:
                # Fallback ke method lama jika numpy tidak ada
                smooth = []
                for i in range(n):
                    start = max(0, i - window)
                    end = min(n, i + window + 1)
                    segment = elevations[start:end]
                    smooth.append(sum(segment) / len(segment))
                elevations = smooth
        else:
            # Jika data terlalu sedikit, gunakan method sederhana
            smooth = []
            for i in range(n):
                start = max(0, i - window)
                end = min(n, i + window + 1)
                segment = elevations[start:end]
                smooth.append(sum(segment) / len(segment))
            elevations = smooth

        # ======================================================
        # DISTANCE AXIS FORMAT
        # ======================================================

        # Tentukan unit system
        is_metric = getattr(self, '_axis_units', 'metric') == 'metric'
        
        # Bottom axis (Distance)
        bottom_axis = self.plot.getPlotItem().getAxis("bottom")
        left_axis = self.plot.getPlotItem().getAxis("left")
        
        # Set label berdasarkan unit
        if is_metric:
            left_axis.setLabel("Elevation (m)")
            bottom_axis.setLabel("Distance (m)")
        else:
            left_axis.setLabel("Elevation (ft)")
            bottom_axis.setLabel("Distance (mi)")  # <-- PASTIKAN INI "mi"
        
        # Format ticks untuk bottom axis (Distance)
        max_d = distances[-1]
        
        if is_metric:
            # Metric: tampilkan dalam km jika >= 1000m
            if max_d >= 5000:
                step_km = (max_d / 1000) / 4
                ticks = []
                for i in range(5):
                    v_km = step_km * i
                    v_m = v_km * 1000
                    ticks.append((v_m, f"{v_km:.1f} km"))
            else:
                step = max_d / 4 if max_d > 0 else 1
                ticks = []
                for i in range(5):
                    v = step * i
                    ticks.append((v, f"{v:.0f} m"))
        else:
            # Imperial: konversi ke feet
            max_ft = max_d * 3.28084
            
            # Tentukan jumlah ticks yang reasonable (5-6 ticks)
            # Tampilkan dari 0 sampai max_ft
            if max_ft >= 10000:
                # Untuk jarak jauh, gunakan interval 2000ft
                nice_interval = 2000
                num_ticks = min(7, int(max_ft / nice_interval) + 1)
            elif max_ft >= 5000:
                # Untuk jarak menengah, gunakan interval 1000ft
                nice_interval = 1000
                num_ticks = min(7, int(max_ft / nice_interval) + 1)
            elif max_ft >= 2000:
                # Untuk jarak pendek, gunakan interval 500ft
                nice_interval = 500
                num_ticks = min(7, int(max_ft / nice_interval) + 1)
            else:
                # Untuk jarak sangat pendek, gunakan interval 200ft
                nice_interval = 200
                num_ticks = min(7, int(max_ft / nice_interval) + 1)
            
            ticks = []
            for i in range(num_ticks):
                v_ft = i * nice_interval
                if v_ft <= max_ft:
                    v_m = v_ft / 3.28084
                    if v_ft >= 5280:
                        # Tampilkan dalam miles jika >= 1 mile
                        v_mi = v_ft / 5280
                        ticks.append((v_m, f"{v_mi:.2f} mi"))
                    else:
                        ticks.append((v_m, f"{v_ft:.0f} ft"))
            
            # Pastikan max_ft masuk sebagai tick terakhir
            last_tick_ft = (num_ticks - 1) * nice_interval
            if last_tick_ft < max_ft:
                # Tambahkan tick di max_ft
                v_m = max_d
                if max_ft >= 5280:
                    v_mi = max_ft / 5280
                    ticks.append((v_m, f"{v_mi:.2f} mi"))
                else:
                    ticks.append((v_m, f"{max_ft:.0f} ft"))
        
        # Set ticks
        bottom_axis.setTicks([ticks])
        bottom_axis.setLabel("Distance (mi)")  # <-- TAMBAHKAN INI UNTUK MEMASTIKAN

        
        # ======================================================
        # DEBUG: VERIFIKASI KONSISTENSI DATA INTERSECTION
        # ======================================================
        
        # =====================================================
        # ANTENNA POSITION (DEFINISIKAN VARIABEL)
        # =====================================================
        site_ground = elevations[0]
        antenna_abs = site_ground + antenna_height
        
        print(f"\n🔍 PROFILE WIDGET DEBUG:")
        print(f"  📐 site_ground: {site_ground:.1f}m")
        print(f"  📐 antenna_height: {antenna_height:.1f}m")
        print(f"  📐 antenna_abs: {antenna_abs:.1f}m")
        print(f"  📐 main_beam_angle: {main_beam_angle}°")
        print(f"  📐 main_intersection_distance: {main_intersection_distance}")
        print(f"  📐 impact_distance: {impact_distance}")
        
        if main_intersection_distance is not None:
            # Hitung manual beam height di titik intersection
            manual_beam_h = antenna_abs - math.tan(math.radians(main_beam_angle)) * main_intersection_distance
            print(f"  📐 Manual beam height at {main_intersection_distance:.0f}m: {manual_beam_h:.1f}m")
            
            # Cari terrain height di titik yang sama
            terrain_at_intersection = None
            for d, e in zip(distances, elevations):
                if d >= main_intersection_distance:
                    terrain_at_intersection = e
                    print(f"  📐 Terrain height at {d:.0f}m: {e:.1f}m")
                    break
            
            if terrain_at_intersection is not None:
                print(f"  📐 Clearance: {manual_beam_h - terrain_at_intersection:.1f}m")
        
        print("="*50)


        # ======================================================
        # BUILD BEAM GEOMETRY - DENGAN INTERSECTION POINT DAN BEAM HEIGHT
        # ======================================================

        def beam_line(angle, stop_at_distance):
            """
            Buat beam line yang berhenti di jarak tertentu
            dengan interpolasi titik akhir untuk presisi
            
            Parameters
            ----------
            angle : float
                Beam angle in degrees
            stop_at_distance : float or None
                Jarak di mana beam harus berhenti (intersection)
                Jika None, beam digambar penuh sampai max_distance
                
            Returns
            -------
            tuple (x_values, y_values)
                Koordinat x dan y untuk beam line
            """
            xs = []
            ys = []
            
            # Validasi input
            if angle is None:
                print(f"⚠️ beam_line: angle is None")
                return [], []
            
            # Buat list jarak dan beam height untuk semua sample
            for d in distances:
                try:
                    beam_h = antenna_abs - math.tan(math.radians(angle)) * d
                    
                    # Cek NaN atau infinity
                    if math.isnan(beam_h) or math.isinf(beam_h):
                        print(f"⚠️ beam_line: invalid beam_h at d={d}")
                        continue
                    
                    # Jika stop_at_distance adalah None, simpan semua titik
                    if stop_at_distance is None:
                        xs.append(d)
                        ys.append(beam_h)
                    # Jika d <= stop_at_distance, simpan titik
                    elif d <= stop_at_distance:
                        xs.append(d)
                        ys.append(beam_h)
                    else:
                        # Setelah melewati stop_at_distance, berhenti
                        break
                except Exception as e:
                    print(f"⚠️ beam_line error at d={d}: {e}")
                    continue
            
            # Jika stop_at_distance tidak None dan tidak sama dengan jarak terakhir
            if stop_at_distance is not None and stop_at_distance > 0 and (not xs or xs[-1] != stop_at_distance):
                try:
                    # Hitung beam height di stop_at_distance
                    beam_h_at_stop = antenna_abs - math.tan(math.radians(angle)) * stop_at_distance
                    
                    # Cek NaN atau infinity
                    if not (math.isnan(beam_h_at_stop) or math.isinf(beam_h_at_stop)):
                        # Tambahkan titik tepat di stop_at_distance
                        xs.append(stop_at_distance)
                        ys.append(beam_h_at_stop)
                except Exception as e:
                    print(f"⚠️ beam_line error at stop distance: {e}")
            
            return xs, ys

        
        # Beam line berhenti di titik intersection dengan interpolasi
        main_x, main_y = beam_line(main_beam_angle, main_intersection_distance)
        upper_x, upper_y = beam_line(upper_beam_angle, upper_intersection_distance)
        lower_x, lower_y = beam_line(lower_beam_angle, lower_intersection_distance)
                
        
        # =====================================================
        # BEAM ENVELOPE (FOOTPRINT LOBE) - TETAP MENERUS
        # =====================================================

        # Hapus beam fill lama jika ada
        if hasattr(self, 'beam_fill'):
            try:
                self.plot_item.removeItem(self.beam_fill)
            except:
                pass

        # Buat beam fill baru yang tetap penuh (tidak terpotong intersection)
        # Gunakan data asli tanpa filter untuk envelope
        full_upper = [antenna_abs - math.tan(math.radians(upper_beam_angle)) * d for d in distances]
        full_lower = [antenna_abs - math.tan(math.radians(lower_beam_angle)) * d for d in distances]

        if is_metric:
            # Plot dalam meter
            temp_upper = pg.PlotDataItem(distances, full_upper)
            temp_lower = pg.PlotDataItem(distances, full_lower)
        else:
            # Konversi ke feet untuk imperial
            full_upper_ft = [y * 3.28084 for y in full_upper]
            full_lower_ft = [y * 3.28084 for y in full_lower]
            temp_upper = pg.PlotDataItem(distances, full_upper_ft)
            temp_lower = pg.PlotDataItem(distances, full_lower_ft)

        # TOSCA: Menggunakan warna cyan/tosca dengan opacity 60 (sama dengan map)
        self.beam_fill = pg.FillBetweenItem(
            temp_upper,
            temp_lower,
            brush=pg.mkBrush(6, 250, 250, 60)  # Tosca dengan opacity 60
        )
        self.plot_item.addItem(self.beam_fill)

        # ======================================================
        # TERRAIN CURVE
        # ======================================================

        # Tentukan unit system
        is_metric = getattr(self, '_axis_units', 'metric') == 'metric'
        
        if is_metric:
            # Plot dalam meter
            self.terrain_curve.setData(distances, elevations)
            plot_elevations = elevations
            plot_antenna_height = antenna_height
        else:
            # Konversi ke feet untuk imperial
            elevations_ft = [e * 3.28084 for e in elevations]
            distances_mi_or_ft = distances  # Jarak tetap dalam meter untuk internal
            plot_elevations = elevations_ft
            plot_antenna_height = antenna_height * 3.28084  # Antenna height dalam feet
            
            # Plot dengan data dalam feet
            self.terrain_curve.setData(distances, elevations_ft)
        
        # Simpan untuk digunakan di bagian lain
        plot_distances = distances  # Jarak internal tetap meter
        
        # ======================================================
        # FILL AREA DI BAWAH TERRAIN (WARNA #D8E5E9)
        # ======================================================
        
        if is_metric:
            min_elev = min(elevations)
            baseline_y = min_elev - 20
            plot_min = min_elev
        else:
            min_elev_ft = min(elevations) * 3.28084
            baseline_y = min_elev_ft - 66  # 20 meter ≈ 66 ft
            plot_min = min_elev_ft
        
        # Buat data baseline (garis lurus horizontal)
        baseline_x = [distances[0], distances[-1]]
        baseline_y_values = [baseline_y, baseline_y]
        
        # Buat curve untuk baseline
        baseline_curve = pg.PlotDataItem(baseline_x, baseline_y_values)
        
        # Hapus fill lama jika ada
        if hasattr(self, 'terrain_fill'):
            try:
                self.plot_item.removeItem(self.terrain_fill)
            except:
                pass
        
        # Buat fill antara terrain curve dan baseline
        self.terrain_fill = pg.FillBetweenItem(
            self.terrain_curve,
            baseline_curve,
            brush=pg.mkBrush(203, 145, 57, 255)
        )
        
        # Set z-order agar fill di belakang (nilai kecil)
        self.terrain_fill.setZValue(-5)
        
        # Tambahkan ke plot
        self.plot_item.addItem(self.terrain_fill)


        # ======================================================
        # RF TERRAIN COLOR CLASSIFICATION
        # ======================================================
        import numpy as np
        strong_x = []
        strong_y = []
        weak_x = []
        weak_y = []
        shadow_x = []
        shadow_y = []

        # Validasi main_x dan main_y tidak kosong
        if main_x and main_y:
            # Gunakan main_x dan main_y yang sudah memiliki titik interpolasi
            for d, beam in zip(main_x, main_y):
                # Cari terrain di jarak yang sama
                idx = min(range(len(distances)), key=lambda i: abs(distances[i] - d))
                
                if is_metric:
                    terrain = elevations[idx]
                    clearance = beam - terrain
                else:
                    # Beam dalam meter, terrain dalam meter asli
                    terrain_m = elevations[idx]
                    clearance_m = beam - terrain_m
                    clearance = clearance_m * 3.28084  # Konversi ke feet untuk klasifikasi
                    terrain = terrain_m * 3.28084  # Terrain dalam feet untuk plot
                
                # Threshold dalam feet untuk imperial
                if is_metric:
                    threshold = 10  # meter
                else:
                    threshold = 33  # feet (≈10m)
                
                if clearance > threshold:
                    strong_x.append(d)
                    strong_y.append(terrain)
                elif clearance > 0:
                    weak_x.append(d)
                    weak_y.append(terrain)
                else:
                    shadow_x.append(d)
                    shadow_y.append(terrain)
        else:
            print("⚠️ main_x or main_y is empty, skipping RF terrain classification")

        self.terrain_strong.setData(strong_x, strong_y)
        self.terrain_weak.setData(weak_x, weak_y)
        self.terrain_shadow.setData(shadow_x, shadow_y)

        # ======================================================
        # DRAW BEAMS - DENGAN INTERPOLASI TITIK AKHIR
        # ======================================================

        if is_metric:
            # Plot dalam meter
            self.upper_beam_curve.setData(upper_x, upper_y)
            self.lower_beam_curve.setData(lower_x, lower_y)
            self.main_beam_curve.setData(main_x, main_y)
        else:
            # Konversi beam lines ke feet untuk imperial
            upper_y_ft = [y * 3.28084 for y in upper_y]
            lower_y_ft = [y * 3.28084 for y in lower_y]
            main_y_ft = [y * 3.28084 for y in main_y]
            
            self.upper_beam_curve.setData(upper_x, upper_y_ft)
            self.lower_beam_curve.setData(lower_x, lower_y_ft)
            self.main_beam_curve.setData(main_x, main_y_ft)
               
        
        # ======================================================
        # SHADOW PATH OVERLAYS
        # ======================================================
        
        if shadow_regions:
            for start_d, end_d in shadow_regions:
                # Cari index untuk start dan end
                start_idx = None
                end_idx = None
                for i, d in enumerate(distances):
                    if start_idx is None and d >= start_d:
                        start_idx = i
                    if end_idx is None and d >= end_d:
                        end_idx = i
                        break
                
                if start_idx is not None and end_idx is not None:
                    # Buat polygon untuk shadow region
                    shadow_x = distances[start_idx:end_idx+1]
                    shadow_y_top = [max(elevations[start_idx:end_idx+1])] * len(shadow_x)
                    shadow_y_bottom = [min(elevations[start_idx:end_idx+1])] * len(shadow_x)
                    
                    # Buat FillBetweenItem untuk shadow
                    shadow_top = pg.PlotDataItem(shadow_x, shadow_y_top)
                    shadow_bottom = pg.PlotDataItem(shadow_x, shadow_y_bottom)
                    
                    shadow_fill = pg.FillBetweenItem(
                        shadow_top,
                        shadow_bottom,
                        brush=pg.mkBrush(108, 37, 44, 40)  # Coklat transparan
                    )
                    self.plot_item.addItem(shadow_fill)

        # ======================================================
        # IMPACT POINT (SEGITIGA HITAM) - Titik pertama beam intersection dengan terrain
        # ======================================================

        # Cari titik pertama main beam intersection dengan terrain
        impact_point_d = None
        impact_point_h = None
        
        # Gunakan main_intersection_distance jika ada, atau cari manual
        if main_intersection_distance is not None:
            # Cari elevasi di titik intersection dengan interpolasi yang tepat
            for i, (d, e) in enumerate(zip(distances, elevations)):
                if d >= main_intersection_distance:
                    if i > 0 and d > main_intersection_distance:
                        # Interpolasi linear antara dua titik sample
                        prev_d = distances[i-1]
                        prev_e = elevations[i-1]
                        ratio = (main_intersection_distance - prev_d) / (d - prev_d)
                        impact_point_h = prev_e + ratio * (e - prev_e)
                        print(f"  📐 Interpolated terrain: {prev_e:.1f}m + {ratio:.2f}*({e:.1f}m - {prev_e:.1f}m) = {impact_point_h:.1f}m")
                    else:
                        # Tepat pada sample point
                        impact_point_h = e
                    impact_point_d = main_intersection_distance
                    break
            print(f"📍 Using main_intersection_distance: {main_intersection_distance:.0f}m")
        
        # Fallback: cari manual jika tidak ada
        if impact_point_d is None:
            # Gunakan main_x dan main_y yang sudah ada
            beam_dict = dict(zip(main_x, main_y))
            for d, t in zip(distances, elevations):
                if d in beam_dict and t >= beam_dict[d]:  # Terrain mencapai atau di atas beam
                    impact_point_d = d
                    impact_point_h = t
                    break
            if impact_point_d:
                print(f"📍 Manual impact point at {impact_point_d:.0f}m")
                
        # ======================================================
        # MAIN INTERSECTION POINT (LINGKARAN HIJAU)
        # ======================================================
        if impact_point_d is not None and impact_point_h is not None:
            if is_metric:
                plot_y = impact_point_h
            else:
                plot_y = impact_point_h * 3.28084  # Konversi ke feet
                
            impact = pg.ScatterPlotItem(
                x=[impact_point_d],
                y=[plot_y],
                size=14,  # Naikkan ukuran dari 12 ke 14
                brush=pg.mkBrush(0, 160, 0),  # Hijau solid
                pen=pg.mkPen("k", width=1.5),  # Outline hitam lebih tebal
                symbol="o",
                name="Impact Point (Main Lobe Touchdown)"
            )

            impact.setZValue(1000)  # Naikkan dari 500 ke 1000
            self.plot_item.addItem(impact)
            print(f"🎯 Main impact point drawn at {impact_point_d:.0f}m -> {plot_y:.1f}ft")
            
            # ======================================================
            # SIMPAN NILAI UNTUK DIAKSES DIALOG (BARU)
            # ======================================================
            self._last_impact_point = impact_point_d
            self._last_impact_y = impact_point_h
           

        else:
            print("⚠️ No impact point found")
            self._last_impact_point = None

        # ======================================================
        # VERIFIKASI BEAM HEIGHT DI TITIK IMPACT (UPDATED)
        # ======================================================
        # Cari beam height di titik impact dari main_x, main_y
        if 'main_x' in locals() and 'main_y' in locals() and impact_point_d is not None:
            for i, d in enumerate(main_x):
                if abs(d - impact_point_d) < 1.0:
                    beam_at_impact = main_y[i]
                    print(f"  ✅ BEAM LINE VERIFICATION:")
                    print(f"     • Distance: {d:.1f}m")
                    print(f"     • Beam height from line: {beam_at_impact:.2f}m")
                    if impact_point_h is not None:
                        print(f"     • Terrain height: {impact_point_h:.2f}m")
                        print(f"     • Difference: {beam_at_impact - impact_point_h:.2f}m")
                    else:
                        print(f"     • Terrain height: None")
                    break

        # ======================================================
        # VERIFIKASI BEAM LINE VS MARKER (UPDATED)
        # ======================================================
        if main_intersection_distance is not None and main_beam_height is not None and impact_point_d is not None:
            if 'main_x' in locals() and 'main_y' in locals() and main_x and main_y:
                # Cari nilai beam line di titik intersection
                for i, d in enumerate(main_x):
                    if d is not None and main_intersection_distance is not None:
                        if abs(d - main_intersection_distance) < 1.0:  # Toleransi 1 meter
                            beam_at_intersection = main_y[i]
                            print(f"\n✅ BEAM LINE VS MARKER VERIFICATION:")
                            print(f"   • Intersection at {main_intersection_distance:.1f}m")
                            print(f"   • Beam line height: {beam_at_intersection:.2f}m")
                            print(f"   • Terrain height: {main_beam_height:.2f}m")
                            if impact_point_h is not None:
                                print(f"   • Marker height: {impact_point_h:.2f}m")
                                print(f"   • Beam-Marker diff: {beam_at_intersection - impact_point_h:.2f}m")
                                if abs(beam_at_intersection - impact_point_h) < 0.5:
                                    print(f"   ✓ BEAM LINE MEETS MARKER PERFECTLY")
                                elif abs(beam_at_intersection - impact_point_h) < 2.0:
                                    print(f"   ⚠️ Beam line and marker slightly off")
                                else:
                                    print(f"   ❌ Beam line and marker mismatch")
                            else:
                                print(f"   • Marker height: None")
                            break
                    
        # ======================================================
        # UPPER INTERSECTION POINT (LINGKARAN BIRU)
        # ======================================================
        if upper_intersection_distance is not None:
            # Cari elevasi di titik upper intersection
            upper_point_h = None
            for d, e in zip(distances, elevations):
                if d >= upper_intersection_distance:
                    upper_point_h = e
                    break
            
            if upper_point_h is not None:
                if is_metric:
                    plot_y = upper_point_h
                else:
                    plot_y = upper_point_h * 3.28084
                    
                upper_intersection = pg.ScatterPlotItem(
                    x=[upper_intersection_distance],
                    y=[plot_y],
                    size=14,  # Naikkan ukuran jadi 14
                    brush=pg.mkBrush(42, 125, 225),  # Biru
                    pen=pg.mkPen("w", width=1.5),  # Outline putih lebih tebal
                    symbol="o",
                    name="Upper Beam Intersection"
                )
                upper_intersection.setZValue(1000)  # Naikkan ZValue ke 1000
                self.plot_item.addItem(upper_intersection)
                print(f"🔵 Upper intersection point drawn at {upper_intersection_distance:.0f}m -> {plot_y:.1f}ft")
                
                # SIMPAN DATA UNTUK LABEL
                self._last_upper_x = upper_intersection_distance
                self._last_upper_y = upper_point_h

        
        # ======================================================
        # LOWER INTERSECTION POINT (LINGKARAN MERAH)
        # ======================================================
        if lower_intersection_distance is not None:
            # Cari elevasi di titik lower intersection
            lower_point_h = None
            for d, e in zip(distances, elevations):
                if d >= lower_intersection_distance:
                    lower_point_h = e
                    break
            
            if lower_point_h is not None:
                if is_metric:
                    plot_y = lower_point_h
                else:
                    plot_y = lower_point_h * 3.28084
                    
                lower_intersection = pg.ScatterPlotItem(
                    x=[lower_intersection_distance],
                    y=[plot_y],
                    size=14,  # Naikkan ukuran
                    brush=pg.mkBrush(255, 0, 0),  # Merah
                    pen=pg.mkPen("w", width=1.5),  # Outline putih
                    symbol="o",
                    name="Lower Beam Intersection"
                )
                lower_intersection.setZValue(1000)  # ZValue tinggi
                self.plot_item.addItem(lower_intersection)
                print(f"🔴 Lower intersection point drawn at {lower_intersection_distance:.0f}m -> {plot_y:.1f}ft")
                
                # SIMPAN DATA UNTUK LABEL
                self._last_lower_x = lower_intersection_distance
                self._last_lower_y = lower_point_h

        # ======================================================
        # SHADOW BAND - UPDATED
        # ======================================================

        if 'main_x' in locals() and 'main_y' in locals() and main_x and main_y:
            shadow_start = None
            shadow_bands = []
            
            # Buat dictionary untuk mapping jarak ke beam height
            if is_metric:
                beam_dict = dict(zip(main_x, main_y))
            else:
                # Konversi beam ke feet untuk perbandingan dengan terrain (sudah dalam feet)
                main_y_ft = [y * 3.28084 for y in main_y]
                beam_dict = dict(zip(main_x, main_y_ft))
            
            for i, d in enumerate(distances):
                # Cari beam height di jarak ini (jika ada)
                if d in beam_dict:
                    b = beam_dict[d]
                    if is_metric:
                        t = elevations[i]
                    else:
                        t = elevations[i] * 3.28084  # terrain dalam feet
                    
                    if t > b:
                        if shadow_start is None:
                            shadow_start = d
                    else:
                        if shadow_start is not None:
                            # Buat shadow band dari shadow_start sampai d
                            band = pg.LinearRegionItem(
                                values=(shadow_start, d),
                                orientation=pg.LinearRegionItem.Vertical,
                                brush=(200, 0, 0, 40),
                                movable=False
                            )
                            band.setZValue(-10)
                            self.plot_item.addItem(band)
                            shadow_start = None
            
            # Handle shadow yang berlanjut sampai akhir
            if shadow_start is not None:
                band = pg.LinearRegionItem(
                    values=(shadow_start, distances[-1]),
                    orientation=pg.LinearRegionItem.Vertical,
                    brush=(200, 0, 0, 40),
                    movable=False
                )
                band.setZValue(-10)
                self.plot_item.addItem(band)
        
                   
        # ======================================================
        # STORE DATA
        # ======================================================

        self._distances = distances
        self._terrain = elevations
        self._beam = (main_x, main_y)  # <-- SIMPAN SEBAGAI TUPLE
        
        # ======================================================
        # UPDATE CACHE UNTUK BINARY SEARCH
        # ======================================================
        
        # Pastikan distances terurut untuk binary search
        import numpy as np
        self._distances_array = np.array(distances)  # Untuk binary search yang lebih cepat

        # ======================================================
        # FORCE AXIS RANGE UPDATE
        # ======================================================

        try:
            max_d = max(distances)
            
            if is_metric:
                # Metric: range dari terrain terendah - 10m sampai atas beam
                min_terrain = min(elevations)
                max_terrain = max(elevations)
                tower_top = max_terrain + antenna_height
                
                # Tentukan min range: 10m di bawah terrain terendah
                min_range = max(0, min_terrain - 10)
                
                # Tentukan max range: 10m di atas elemen tertinggi
                max_elements = max(max_terrain, tower_top)
                if impact_point_h is not None:
                    max_elements = max(max_elements, impact_point_h)
                if upper_intersection_distance is not None:
                    for d, e in zip(distances, elevations):
                        if d >= upper_intersection_distance:
                            max_elements = max(max_elements, e)
                            break
                if lower_intersection_distance is not None:
                    for d, e in zip(distances, elevations):
                        if d >= lower_intersection_distance:
                            max_elements = max(max_elements, e)
                            break
                
                max_range = max_elements + 10  # Turunkan dari 20
                
                self.plot_item.setYRange(min_range, max_range, padding=0)
                print(f"📊 Y range set to: {min_range:.1f} - {max_range:.1f} m")
                print(f"   📍 Min terrain: {min_terrain:.1f} m, Max terrain: {max_terrain:.1f} m")
                print(f"   📍 Tower top: {tower_top:.1f} m")
                
            else:
                # Imperial: konversi semua ke feet
                elevations_ft = [e * 3.28084 for e in elevations]
                ground_ft = elevations_ft[0]
                antenna_ft = antenna_height * 3.28084
                
                # Hitung min dan max
                min_terrain_ft = min(elevations_ft)
                max_terrain_ft = max(elevations_ft)
                
                # Min range: 50 ft di bawah terrain terendah (turunkan dari 100)
                min_range_ft = max(0, min_terrain_ft - 50)
                
                # Max range: 50 ft di atas elemen tertinggi (turunkan dari 100)
                max_elements_ft = max(max_terrain_ft, ground_ft + antenna_ft)
                if impact_point_h is not None:
                    impact_ft = impact_point_h * 3.28084
                    max_elements_ft = max(max_elements_ft, impact_ft)
                if upper_intersection_distance is not None:
                    for d, e in zip(distances, elevations):
                        if d >= upper_intersection_distance:
                            max_elements_ft = max(max_elements_ft, e * 3.28084)
                            break
                if lower_intersection_distance is not None:
                    for d, e in zip(distances, elevations):
                        if d >= lower_intersection_distance:
                            max_elements_ft = max(max_elements_ft, e * 3.28084)
                            break
                
                max_range_ft = max_elements_ft + 50  # Turunkan dari 100
                
                self.plot_item.setYRange(min_range_ft, max_range_ft, padding=0)
                print(f"📊 Y range set to: {min_range_ft:.1f} - {max_range_ft:.1f} ft")
                print(f"   📍 Min terrain: {min_terrain_ft:.1f} ft, Max terrain: {max_terrain_ft:.1f} ft")
                print(f"   📍 Tower top: {ground_ft + antenna_ft:.1f} ft")

            self.plot_item.setXRange(0, max_d, padding=0)

        except Exception as e:
            print(f"⚠️ Error setting range: {e}")
        
        
        # =====================================================
        # GAMBAR SVG TOWER
        # =====================================================
        
        # Gambar SVG tower (selalu dalam meter untuk internal)
        self._draw_tower(site_ground, antenna_abs, antenna_height)
        

        # Hubungkan signal untuk update saat zoom (hanya sekali)
        try:
            # Coba disconnect dulu jika sudah terhubung
            self.plot_item.getViewBox().sigRangeChanged.disconnect()
        except (TypeError, RuntimeError):
            # Tidak ada connection sebelumnya, lanjutkan
            pass
        
        # Hubungkan signal
        self.plot_item.getViewBox().sigRangeChanged.connect(
            lambda: self._update_tower_scale()
        )
        
        
        # =====================================================
        # TAMBAHKAN LABEL INTERSECTION
        # =====================================================
        self._add_intersection_labels()
        
        # ======================================================
        # REFRESH (STABLE VERSION)
        # ======================================================

        try:

            # disable autorange agar drag stabil
            self.plot.enableAutoRange(False)

            # hanya update sekali
            self.plot_item.update()
            
            # ======================================================
            # PASTIKAN LEGEND DI ATAS
            # ======================================================
            if hasattr(self, 'legend_frame'):
                self.legend_frame.raise_()

        except Exception:
            pass
        
        # ======================================================
        # STORE CURRENT RANGE FOR RESET VIEW
        # ======================================================
        
        current_range = self.plot_item.viewRange()
        self._saved_range = {
            'x': (current_range[0][0], current_range[0][1]),
            'y': (current_range[1][0], current_range[1][1])
        }
        print(f"💾 Saved range for reset view: X {self._saved_range['x']}, Y {self._saved_range['y']}")
    
    
    def _draw_tower(self, site_ground, antenna_abs, antenna_height):
        """内联绘制铁塔（QGraphics 图元组，无外部文件依赖）。

        Parameters
        ----------
        site_ground : float
            Ground elevation at site (meters)
        antenna_abs : float
            Absolute antenna elevation (site_ground + antenna_height)
        antenna_height : float
            Antenna height above ground (meters)
        """
        if not PYQTGRAPH_AVAILABLE or self.plot_item is None:
            return

        try:
            is_metric = getattr(self, '_axis_units', 'metric') == 'metric'
            view_range = self.plot_item.viewRange()
            y_min, y_max = view_range[1]
            viewbox_height_px = self.plot_item.getViewBox().height()

            if viewbox_height_px <= 0 or (y_max - y_min) <= 0:
                return

            pixel_per_unit = viewbox_height_px / (y_max - y_min)
            target_height_px = antenna_height * pixel_per_unit

            # 塔顶 = 天线绝对标高（波束起点），塔底 = 地面标高
            beam_start = self.plot_item.getViewBox().mapFromView(QPointF(0, antenna_abs))
            ground_pos = self.plot_item.getViewBox().mapFromView(QPointF(0, site_ground))

            tower_top_y = beam_start.y()
            tower_bottom_y = ground_pos.y()

            # 塔宽按高度比例（约 16%）
            tower_half_w = max(6.0, target_height_px * 0.08)
            top_half_w = max(2.0, tower_half_w * 0.35)

            group = QGraphicsItemGroup()

            # 塔身主体：梯形（底部宽、顶部窄），两条斜腿 + 横撑
            leg_pen = QPen(QColor(60, 60, 60), 1.6)
            leg_pen.setCosmetic(True)
            left_leg = QGraphicsLineItem(ground_pos.x() - tower_half_w, tower_bottom_y,
                                         ground_pos.x() - top_half_w, tower_top_y)
            left_leg.setPen(leg_pen)
            group.addToGroup(left_leg)
            right_leg = QGraphicsLineItem(ground_pos.x() + tower_half_w, tower_bottom_y,
                                          ground_pos.x() + top_half_w, tower_top_y)
            right_leg.setPen(leg_pen)
            group.addToGroup(right_leg)

            # 顶部天线平台
            platform_pen = QPen(QColor(90, 90, 90), 1.8)
            platform_pen.setCosmetic(True)
            platform = QGraphicsLineItem(ground_pos.x() - top_half_w, tower_top_y,
                                         ground_pos.x() + top_half_w, tower_top_y)
            platform.setPen(platform_pen)
            group.addToGroup(platform)

            # 横撑（每隔 25% 高度加一条）
            cross_pen = QPen(QColor(140, 140, 140), 1.0)
            cross_pen.setCosmetic(True)
            for i in range(1, 4):
                frac = i / 4.0
                y = tower_top_y + (tower_bottom_y - tower_top_y) * frac
                half = tower_half_w - (tower_half_w - top_half_w) * frac
                c = QGraphicsLineItem(ground_pos.x() - half, y, ground_pos.x() + half, y)
                c.setPen(cross_pen)
                group.addToGroup(c)

            # 天线杆（塔顶竖直细杆）
            mast_pen = QPen(QColor(50, 50, 50), 2.2)
            mast_pen.setCosmetic(True)
            mast_h = max(8.0, target_height_px * 0.12)
            mast = QGraphicsLineItem(ground_pos.x(), tower_top_y,
                                     ground_pos.x(), tower_top_y - mast_h)
            mast.setPen(mast_pen)
            group.addToGroup(mast)
            # 天线头：小圆点
            head = QGraphicsEllipseItem(ground_pos.x() - 2.5, tower_top_y - mast_h - 2.5, 5.0, 5.0)
            head.setBrush(QColor(200, 60, 60))
            head.setPen(QPen(QColor(120, 40, 40), 0.6))
            group.addToGroup(head)

            group.setZValue(20)
            self.plot_item.scene().addItem(group)

            self._tower_item = group
            self._tower_params = (site_ground, antenna_abs, antenna_height)

            print(f"✅ 铁塔已绘制: 高={antenna_height:.1f}m -> {target_height_px:.1f}px")

        except RuntimeError:
            # C++ object already deleted
            self._tower_item = None
            self._tower_params = None
        except Exception as e:
            print(f"❌ Error drawing tower: {e}")
            import traceback
            traceback.print_exc()
    def _update_tower_scale(self):
        """Update tower scale when view changes (zoom/pan)"""
        
        # ======================================================
        # GUARD CLAUSE 1: Cek status destroying
        # ======================================================
        if hasattr(self, '_is_destroying') and self._is_destroying:
            print("  ⏭️ _update_tower_scale skipped - widget is destroying")
            return
        
        # ======================================================
        # GUARD CLAUSE 2: Cek ketersediaan PyQtGraph
        # ======================================================
        if not PYQTGRAPH_AVAILABLE or self.plot_item is None:
            return
        
        # ======================================================
        # GUARD CLAUSE 3: Cek _tower_params
        # ======================================================
        if not hasattr(self, '_tower_params') or self._tower_params is None:
            return
            
        # Cek apakah _tower_params memiliki 3 nilai
        if len(self._tower_params) != 3:
            print(f"⚠️ _tower_params has wrong length: {len(self._tower_params)}")
            return
        
        # ======================================================
        # CEK APAKAH VIEWBOX MASIH VALID
        # ======================================================
        try:
            viewbox = self.plot_item.getViewBox()
            if viewbox is None:
                print("⚠️ ViewBox is None, skipping tower update")
                return
        except RuntimeError:
            # C++ object already deleted
            print("⚠️ ViewBox already deleted, skipping tower update")
            return
            
        try:
            site_ground, antenna_abs, antenna_height = self._tower_params
            
            # Hapus tower lama
            self._remove_tower()
            
            # Gambar ulang dengan scale baru
            self._draw_tower(site_ground, antenna_abs, antenna_height)
            
        except RuntimeError as e:
            # C++ object already deleted - ini yang sering cause crash
            print(f"⚠️ RuntimeError in _update_tower_scale (C++ object deleted): {e}")
            self._tower_item = None
            self._tower_params = None
            
        except Exception as e:
            print(f"⚠️ Error in _update_tower_scale: {e}")
            import traceback
            traceback.print_exc()

    # ======================================================
    # GANTI method '_remove_tower' yang lama dengan versi ini
    # ======================================================
    def _remove_tower(self):
        """Remove existing tower item from scene with extra safety checks."""
        if hasattr(self, '_tower_item') and self._tower_item is not None:
            try:
                # Cek apakah item masih memiliki scene dan masih valid
                if self._tower_item.scene() is not None:
                    self._tower_item.scene().removeItem(self._tower_item)
                self._tower_item = None
                self._tower_params = None
                print("🧹 Previous tower removed (or was already dead).")
            except RuntimeError as e:
                # Error umum ketika C++ object sudah dihapus
                print(f"⚠️ Ignoring RuntimeError during tower removal: {e}")
                self._tower_item = None
                self._tower_params = None
            except Exception as e:
                print(f"⚠️ Error removing tower: {e}")
                self._tower_item = None
                self._tower_params = None
                
            
    def _position_legend_top_right(self):
        """Pindahkan legend ke posisi kanan atas"""
        if hasattr(self, 'legend_frame'):
            # Hitung posisi: lebar widget - lebar legend - margin
            new_x = self.width() - self.legend_frame.width() - 60
            new_y = 20
            self.legend_frame.move(new_x, new_y)
            self.legend_frame.raise_()
    
    # ======================================================
    # RESIZE EVENT
    # ======================================================
    
    def resizeEvent(self, event):
        """Handle resize untuk memastikan legend tetap di kanan atas"""
        super().resizeEvent(event)
        
        if hasattr(self, 'legend_frame'):
            # Hitung posisi baru saat widget di-resize
            new_x = self.width() - self.legend_frame.width() - 60
            new_y = 20
            self.legend_frame.move(new_x, new_y)


    # ======================================================
    # MOUSE INSPECTOR - OPTIMIZED DENGAN BINARY SEARCH
    # ======================================================

    def _mouse_moved(self, evt):
        """Mouse moved event dengan binary search untuk performa"""
        
        # ======================================================
        # GUARD CLAUSE 1: Cek status destroying
        # ======================================================
        if hasattr(self, '_is_destroying') and self._is_destroying:
            return
        
        # ======================================================
        # GUARD CLAUSE 2: Jika PyQtGraph tidak tersedia
        # ======================================================
        if not PYQTGRAPH_AVAILABLE or self.plot is None:
            return
        
        # ======================================================
        # GUARD CLAUSE 3: Cek data availability
        # ======================================================
        if not self._distances or len(self._distances) == 0:
            return
        
        # ======================================================
        # GUARD CLAUSE 4: Cek viewbox validity
        # ======================================================
        try:
            vb = self.plot.getViewBox()
            if vb is None:
                return
        except RuntimeError:
            # C++ object already deleted
            return

        # ======================================================
        # CEK APAKAH POSISI MOUSE DI DALAM VIEW
        # ======================================================
        pos = evt[0]
        try:
            if not vb.sceneBoundingRect().contains(pos):
                return
        except RuntimeError:
            return

        # ======================================================
        # KONVERSI KE KOORDINAT VIEW
        # ======================================================
        try:
            mousePoint = vb.mapSceneToView(pos)
        except RuntimeError:
            return
            
        x = mousePoint.x()
        
        # Validasi x tidak infinite atau NaN
        if not math.isfinite(x):
            return
        
        # ======================================================
        # BINARY SEARCH UNTUK JARAK TERDEKAT
        # ======================================================
        import bisect
        idx = bisect.bisect_left(self._distances, x)
        
        # Handle boundary cases dengan safe access
        try:
            if idx == 0:
                d = self._distances[0]
                terrain = self._terrain[0]
                # Cek tipe self._beam
                if isinstance(self._beam, tuple) and len(self._beam) == 2:
                    # self._beam berisi (main_x, main_y)
                    main_x, main_y = self._beam
                    # Cari beam height di jarak terdekat
                    if len(main_x) > 0:
                        # Cari index terdekat di main_x
                        beam_idx = min(range(len(main_x)), key=lambda i: abs(main_x[i] - d))
                        beam = main_y[beam_idx]
                    else:
                        beam = 0
                else:
                    # Fallback ke list biasa
                    beam = self._beam[0] if len(self._beam) > 0 else 0
                    
            elif idx == len(self._distances):
                d = self._distances[-1]
                terrain = self._terrain[-1]
                # Cek tipe self._beam
                if isinstance(self._beam, tuple) and len(self._beam) == 2:
                    main_x, main_y = self._beam
                    if len(main_x) > 0:
                        beam_idx = min(range(len(main_x)), key=lambda i: abs(main_x[i] - d))
                        beam = main_y[beam_idx]
                    else:
                        beam = 0
                else:
                    beam = self._beam[-1] if len(self._beam) > 0 else 0
                    
            else:
                # Cek mana yang lebih dekat
                left_dist = abs(self._distances[idx-1] - x)
                right_dist = abs(self._distances[idx] - x)
                
                if left_dist < right_dist:
                    d = self._distances[idx-1]
                    terrain = self._terrain[idx-1]
                    # Cari beam height
                    if isinstance(self._beam, tuple) and len(self._beam) == 2:
                        main_x, main_y = self._beam
                        if len(main_x) > 0:
                            beam_idx = min(range(len(main_x)), key=lambda i: abs(main_x[i] - d))
                            beam = main_y[beam_idx]
                        else:
                            beam = 0
                    else:
                        beam = self._beam[idx-1] if idx-1 < len(self._beam) else 0
                else:
                    d = self._distances[idx]
                    terrain = self._terrain[idx]
                    if isinstance(self._beam, tuple) and len(self._beam) == 2:
                        main_x, main_y = self._beam
                        if len(main_x) > 0:
                            beam_idx = min(range(len(main_x)), key=lambda i: abs(main_x[i] - d))
                            beam = main_y[beam_idx]
                        else:
                            beam = 0
                    else:
                        beam = self._beam[idx] if idx < len(self._beam) else 0
        except (IndexError, ValueError) as e:
            # Safety catch untuk index errors
            print(f"⚠️ Error in mouse moved index calculation: {e}")
            return

        # ======================================================
        # VALIDASI NILAI
        # ======================================================
        if not all(math.isfinite(v) for v in [d, terrain, beam]):
            return
            
        clearance = beam - terrain

        # ======================================================
        # UPDATE CROSSHAIR DENGAN SAFE CHECK
        # ======================================================
        try:
            self.vLine.setPos(d)
            self.hLine.setPos(mousePoint.y())
        except RuntimeError:
            # C++ object already deleted
            return

        # ======================================================
        # AKTIFKAN TOOLTIP
        # ======================================================
        # Tentukan unit system
        is_metric = getattr(self, '_axis_units', 'metric') == 'metric'

        try:
            if is_metric:
                # Metric units
                text = (
                    f"📍 Distance: {d:.0f} m\n"
                    f"⛰️ Terrain: {terrain:.1f} m\n"
                    f"📡 Beam: {beam:.1f} m\n"
                    f"✨ Clearance: {clearance:.1f} m"
                )
            else:
                # Imperial units - FIXED VERSION
                d_ft = d * 3.28084
                terrain_ft = terrain * 3.28084
                beam_ft = beam * 3.28084
                clearance_ft = clearance * 3.28084
                
                # Format distance with proper unit
                if d_ft >= 5280:
                    d_str = f"{d_ft/5280:.2f} mi"
                else:
                    d_str = f"{d_ft:.0f} ft"
                
                # Format terrain, beam, clearance
                # Gunakan rounding yang konsisten
                terrain_str = f"{terrain_ft:.0f}" if terrain_ft < 1000 else f"{terrain_ft:.1f}"
                beam_str = f"{beam_ft:.0f}" if beam_ft < 1000 else f"{beam_ft:.1f}"
                clearance_str = f"{clearance_ft:.0f}" if abs(clearance_ft) < 1000 else f"{clearance_ft:.1f}"
                
                text = (
                    f"📍 Distance: {d_str}\n"
                    f"⛰️ Terrain: {terrain_str} ft\n"
                    f"📡 Beam: {beam_str} ft\n"
                    f"✨ Clearance: {clearance_str} ft"
                )
            
            self.setToolTip(text)
            
        except Exception as e:
            # Jangan crash hanya karena tooltip error
            print(f"⚠️ Error setting tooltip: {e}")
    
    # ======================================================
    # GET IMPACT POINT (BARU)
    # ======================================================
    
    def get_impact_point(self):
        """
        Mengembalikan jarak impact point yang digambar di graph.
        
        Returns
        -------
        float or None
            Jarak impact point dalam meter, atau None jika tidak ada
        """
        return self._last_impact_point
        
    
    def clear_plot(self):
        """
        Clear only analysis results (intersection points, beam lines, envelope, etc.)
        but KEEP the base terrain profile.
        """
        print("🧹 Clearing analysis results from terrain profile...")
        
        # =====================================================
        # HAPUS INTERSECTION POINTS (lingkaran warna)
        # =====================================================
        # Cari semua ScatterPlotItem (intersection points) dan hapus
        for item in list(self.plot_item.items):
            if isinstance(item, pg.ScatterPlotItem):
                try:
                    self.plot_item.removeItem(item)
                except:
                    pass
        
        # =====================================================
        # HAPUS INTERSECTION LABELS
        # =====================================================
        if hasattr(self, '_intersection_labels'):
            for label in self._intersection_labels:
                try:
                    self.plot_item.removeItem(label)
                except:
                    pass
            self._intersection_labels = []
        
        # =====================================================
        # HAPUS BEAM FILL (envelope tosca)
        # =====================================================
        if hasattr(self, 'beam_fill'):
            try:
                self.plot_item.removeItem(self.beam_fill)
            except:
                pass
            self.beam_fill = None
        
        
        # =====================================================
        # HAPUS SHADOW BANDS (LinearRegionItem)
        # =====================================================
        for item in list(self.plot_item.items):
            if isinstance(item, pg.LinearRegionItem):
                try:
                    self.plot_item.removeItem(item)
                except:
                    pass
        
        # =====================================================
        # HAPUS TOWER SVG
        # =====================================================
        if hasattr(self, '_tower_item') and self._tower_item is not None:
            try:
                if self._tower_item.scene() is not None:
                    self._tower_item.scene().removeItem(self._tower_item)
                self._tower_item = None
                self._tower_params = None
            except Exception as e:
                print(f"⚠️ Error removing tower: {e}")
        
        # =====================================================
        # RESET BEAM CURVES (garis beam) - ini yang harus direset
        # =====================================================
        self.main_beam_curve.setData([], [])
        self.upper_beam_curve.setData([], [])
        self.lower_beam_curve.setData([], [])
        
        # =====================================================
        # RESET TERRAIN COLOR CLASSIFICATION (strong/weak/shadow)
        # =====================================================
        self.terrain_strong.setData([], [])
        self.terrain_weak.setData([], [])
        self.terrain_shadow.setData([], [])
        
        # =====================================================
        # RESET DATA HOLDERS
        # =====================================================
        self._distances = []
        self._terrain = []
        self._beam = []
        self._distances_array = None
        self._last_impact_point = None
        self._last_impact_y = None
        self._last_upper_x = None
        self._last_upper_y = None
        self._last_lower_x = None
        self._last_lower_y = None
        
        # =====================================================
        # RESET AXIS LABELS (jika perlu)
        # =====================================================
        # Tapi jangan reset range, biarkan seperti adanya
        
        print("✅ Analysis results cleared, base terrain profile preserved")
        
        # =====================================================
        # RESET CURVES
        # =====================================================
        self.terrain_curve.setData([], [])
        self.terrain_strong.setData([], [])
        self.terrain_weak.setData([], [])
        self.terrain_shadow.setData([], [])
        self.main_beam_curve.setData([], [])
        self.upper_beam_curve.setData([], [])
        self.lower_beam_curve.setData([], [])
        
        # =====================================================
        # RESET DATA HOLDERS
        # =====================================================
        self._distances = []
        self._terrain = []
        self._beam = []
        self._distances_array = None
        self._last_impact_point = None
        self._last_impact_y = None
        self._last_upper_x = None
        self._last_upper_y = None
        self._last_lower_x = None
        self._last_lower_y = None

        
        # =====================================================
        # RESET AXIS RANGE (opsional - kembali ke default)
        # =====================================================
        try:
            # Reset ke range default (misal 0-3000m, 700-900m)
            self.plot_item.setXRange(0, 3000, padding=0)
            self.plot_item.setYRange(700, 900, padding=0)
        except:
            pass
        
        # Refresh plot
        self.plot_item.update()
        print("✅ Terrain profile plot cleared")
    
    
