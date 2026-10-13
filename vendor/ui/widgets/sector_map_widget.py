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
sector_map_widget.py

Embedded QGIS map canvas untuk Vertical Analysis.

Menampilkan:
- OSM basemap
- RF sector footprint
- impact marker
- beam edges
- center line
"""

import math
from datetime import datetime  # <-- TAMBAHKAN INI
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QFrame, QHBoxLayout   # <-- TAMBAHKAN QLabel
from PyQt5.QtCore import Qt, QTimer  # <-- PASTIKAN QTimer ADA
from PyQt5.QtGui import QColor, QFont 
from qgis.gui import QgsMapCanvas
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,  # <-- IMPORT INI DITAMBAHKAN
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSymbol,
    QgsMarkerSymbol,
    QgsFillSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,  # <-- INI JUGA DITAMBAHKAN
    QgsRectangle
)
from qgis.gui import QgsMapCanvasItem  # <-- PASTIKAN IMPORT INI ADA
from ...infrastructure.layers.layer_manager import LayerManager
from .map_legend_frame import MapLegendFrame  # Ganti import

class SectorMapWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # ======================================================
        # FLAG UNTUK CEK STATUS DESTROY (HARUS PALING ATAS)
        # ======================================================
        self._is_destroying = False
        self._flash_timer_running = False
        
        layout = QVBoxLayout()
        self.setLayout(layout)

        # ======================================================
        # MAP CANVAS
        # ======================================================

        self.canvas = QgsMapCanvas()
        layout.addWidget(self.canvas)

        self.canvas.setCanvasColor(QColor(255, 255, 255))
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

        # ======================================================
        # LAYER MANAGER
        # ======================================================

        self.layer_manager = LayerManager()

        # ======================================================
        # RF STATE
        # ======================================================

        self.site = None
        self.azimuth = 0
        self.h_beamwidth = 65

        self.radius = 0
        self.coverage = 0

        # ======================================================
        # LAYER REFERENCES (INITIALIZE TO NONE) - FIXED
        # ======================================================

        self._osm_layer = None
        self._antenna_layer = None
        self._sector_layer = None
        self._footprint_layer = None
        self._beam_layer = None
        self._los_layer = None
        self._center_layer = None
        self._impact_layer = None
        self._beam_end_layer = None
        self._upper_intersection_layer = None
        self._lower_intersection_layer = None

        # ======================================================
        # LOAD OSM BASEMAP
        # ======================================================

        self._load_osm_basemap()

        # ======================================================
        # INIT RF LAYERS
        # ======================================================

        self._init_rf_layers()

        # ======================================================
        # LEGEND (FRAME BASED - DRAGGABLE)
        # ======================================================
        self.legend_frame = MapLegendFrame(self)
        self.legend_frame.move(20, 20)  # Posisi sementara di kiri
        self.legend_frame.raise_()  # Pastikan di atas
        self.legend_frame.show()

        # ===== FORCE UPDATE LAYOUT =====
        self.legend_frame.updateGeometry()
        self.legend_frame.adjustSize()
        QApplication.processEvents()  # <-- PENTING: proses event queue
        
        # Pindahkan ke kanan atas setelah widget siap
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._position_legend_top_right)
        
        # CREATE METRICS OVERLAY
        self._create_metrics_overlay()
        
        # ======================================================
        # SETUP NAVIGATION TOOLS
        # ======================================================
        self._setup_navigation_tools()
        
        # Save extent for reset view
        self._saved_extent = None
        self._zoom_in_mode = False
        
        # Create dummy actions for tools (required by QgsMapTool)
        from qgis.PyQt.QtWidgets import QAction
        self._pan_action = QAction("Pan", self)
        self._zoom_action = QAction("Zoom", self)
        
        # ======================================================
        # DEBUG PRINT
        # ======================================================
        print("=" * 50)
        print("SectorMapWidget initialized")
        print(f"Canvas CRS: {self.canvas.mapSettings().destinationCrs().authid()}")
        print("=" * 50)
                
    
    # ======================================================
    # METRICS OVERLAY
    # ======================================================
    
    def _create_metrics_overlay(self):
        """
        Create overlay widget for beam intersection and coverage footprint
        Posisi: kiri bawah canvas
        """
        # Buat frame container
        self.metrics_frame = QFrame(self.canvas)
        self.metrics_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 220);
                border: 1px solid #c9d9e0;
                border-radius: 6px;
            }
        """)
        
        # Layout untuk konten
        layout = QVBoxLayout(self.metrics_frame)
        layout.setContentsMargins(8, 4, 8, 4)  # <-- PERKECIL MARGIN
        layout.setSpacing(2)                    # <-- PERKECIL SPACING
        
        # Beam Intersection
        intersection_layout = QHBoxLayout()
        intersection_layout.setSpacing(4)       # <-- PERKECIL SPACING
        
        intersection_icon = QLabel("📍")
        intersection_icon.setStyleSheet("font-size: 10pt;")  # <-- 12pt -> 10pt
        intersection_layout.addWidget(intersection_icon)
        
        self.overlay_intersection = QLabel("Main Beam Intersection: —")
        self.overlay_intersection.setStyleSheet("font-size: 8pt; color: #2c5a6b;")  # <-- 9pt -> 8pt
        intersection_layout.addWidget(self.overlay_intersection)
        intersection_layout.addStretch()
        layout.addLayout(intersection_layout)
        
        # Coverage Footprint
        footprint_layout = QHBoxLayout()
        footprint_layout.setSpacing(4)          # <-- PERKECIL SPACING
        
        footprint_icon = QLabel("🎯")
        footprint_icon.setStyleSheet("font-size: 10pt;")  # <-- 12pt -> 10pt
        footprint_layout.addWidget(footprint_icon)
        
        self.overlay_footprint = QLabel("Coverage Footprint: —")
        self.overlay_footprint.setStyleSheet("font-size: 8pt; color: #2c5a6b;")  # <-- 9pt -> 8pt
        footprint_layout.addWidget(self.overlay_footprint)
        footprint_layout.addStretch()
        layout.addLayout(footprint_layout)
        
        # Update posisi - PERKECIL LEBAR
        self.metrics_frame.setFixedWidth(240)   # <-- 280 -> 250
        
        # ===== PENTING: Set visible = True =====
        self.metrics_frame.setVisible(True)
        self.metrics_frame.show()
        
        # ===== PENTING: Raise agar di atas semua layer =====
        self.metrics_frame.raise_()
        
        # Adjust size setelah set fixed width
        self.metrics_frame.adjustSize()
        
        # Simpan ukuran untuk resize handling
        self._metrics_width = 240                # <-- UPDATE
        self._metrics_height = self.metrics_frame.height()
        
        # ===== TAMBAHKAN: Timer untuk raise ulang setelah canvas siap =====
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._ensure_overlay_on_top)
        
        print(f"✅ Metrics overlay created - Width: {self._metrics_width}, Height: {self._metrics_height}")
        
    
    def update_metrics(self, intersection_text, footprint_text):
        """
        Update overlay text
        
        Parameters
        ----------
        intersection_text : str
            Formatted beam intersection text (e.g. "588 m" or "0.59 km")
        footprint_text : str
            Formatted coverage footprint text (e.g. "328 m – 1.67 km")
        """
        if not hasattr(self, 'metrics_frame'):
            self._create_metrics_overlay()
        
        self.overlay_intersection.setText(f"Main Beam Intersection: {intersection_text}")
        self.overlay_footprint.setText(f"Coverage Footprint: {footprint_text}")
        
        # Adjust size if needed
        self.metrics_frame.adjustSize()
        self._metrics_height = self.metrics_frame.height()
        
        # ===== PASTIKAN VISIBLE =====
        self.metrics_frame.setVisible(True)
        self.metrics_frame.show()
        
        # Pastikan posisi tetap benar
        self._position_metrics_overlay()
        
        print(f"✅ Metrics updated - Visible: {self.metrics_frame.isVisible()}")
        
    
    def _position_metrics_overlay(self):
        """
        Position metrics overlay at bottom-left of canvas
        Dipanggil saat resize atau update
        """
        if hasattr(self, 'metrics_frame'):
            # Posisi: left=10px, bottom=10px dari canvas (LEBIH KE PINGGIR)
            canvas_width = self.canvas.width()
            canvas_height = self.canvas.height()
            frame_width = self._metrics_width
            frame_height = self._metrics_height
            
            new_x = 5                           # <-- 20 -> 10
            new_y = canvas_height - frame_height - 5  # <-- 20 -> 10
            
            self.metrics_frame.move(new_x, new_y)
            
            # ===== PASTIKAN VISIBLE DAN RAISE =====
            self.metrics_frame.setVisible(True)
            self.metrics_frame.show()
            self.metrics_frame.raise_()
            
            # Pastikan legend juga tetap di atas
            if hasattr(self, 'legend_frame'):
                self.legend_frame.raise_()
    
    def _ensure_overlay_on_top(self):
        """
        Ensure overlay is on top after canvas is fully loaded
        ONLY execute if widget is not being destroyed
        """
        # =====================================================
        # GUARD CLAUSE: Jangan eksekusi jika widget sedang di-destroy
        # =====================================================
        if hasattr(self, '_is_destroying') and self._is_destroying:
            print("  ⏭️ Skipping _ensure_overlay_on_top - widget is destroying")
            return
            
        if hasattr(self, 'metrics_frame'):
            # Cek apakah frame masih valid (masih bagian dari widget)
            if self.metrics_frame and not self._is_destroying:
                self.metrics_frame.setVisible(True)
                self.metrics_frame.show()
                self.metrics_frame.raise_()
                print(f"✅ Metrics overlay raised and visible (delayed) - Visible: {self.metrics_frame.isVisible()}")
        
        if hasattr(self, 'legend_frame') and self.legend_frame and not self._is_destroying:
            self.legend_frame.raise_()
    
    def hide_metrics(self):
        """Sembunyikan metrics overlay"""
        if hasattr(self, 'metrics_frame'):
            self.metrics_frame.hide()
    
    
    def show_metrics(self):
        """Tampilkan metrics overlay"""
        if hasattr(self, 'metrics_frame'):
            self.metrics_frame.show()
            
            
    # ======================================================
    # POSITION LEGEND TOP RIGHT
    # ======================================================
    
    def _position_legend_top_right(self):
        """Pindahkan legend ke posisi kanan atas dengan margin lebih kecil"""
        if hasattr(self, 'legend_frame'):
            # Hitung posisi: lebar widget - lebar legend - margin
            new_x = self.width() - self.legend_frame.width() - 15  # <-- 20 -> 15
            new_y = 15                                              # <-- 20 -> 15
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
            new_x = self.width() - self.legend_frame.width() - 15  # <-- 20 -> 15
            new_y = 15                                              # <-- 20 -> 15
            self.legend_frame.move(new_x, new_y)
            self.legend_frame.raise_()
        
        # Reposition metrics overlay
        self._position_metrics_overlay()
    
    
    # ======================================================
    # BASEMAP METHODS
    # ======================================================
    
    # ======================================================
    # GANTI method 'set_basemap' yang lama dengan versi ini
    # ======================================================
    def set_basemap(self, layer_name=None):
        """
        Set basemap dari layer project, atau load default OSM.
        MEMAKSA rebuild ulang layer stack canvas.
        """
        print(f"🔄 Setting basemap to: {layer_name if layer_name else 'Default OSM'}")

        # 1. Hapus referensi OSM layer lama
        if self._osm_layer and self._osm_layer.isValid():
            self._osm_layer = None
            print("  🧹 Cleared previous basemap reference.")

        # 2. Load basemap baru
        if layer_name is None:
            self._load_osm_basemap()
        else:
            project = QgsProject.instance()
            layers = project.mapLayersByName(layer_name)

            if layers:
                self._osm_layer = layers[0]
                print(f"✅ Using basemap: {layer_name}")
                if hasattr(self._osm_layer, 'setCrs'):
                    self._osm_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
            else:
                print(f"⚠️ Basemap layer '{layer_name}' not found, using default OSM")
                self._load_osm_basemap()

        # 3. CRITICAL: Rebuild ulang layer stack
        self._rebuild_canvas_layers()

        # 4. Pastikan overlay di atas setelah rebuild
        QTimer.singleShot(100, self._ensure_overlay_on_top)

    # ======================================================
    # TAMBAHKAN method baru ini setelah method 'set_basemap'
    # ======================================================
    def _rebuild_canvas_layers(self):
        """
        Memaksa rebuild ulang layer stack canvas.
        Urutan layer SAMA PERSIS dengan _fix_z_order().
        """
        print("🔄 Rebuilding canvas layer stack...")
        all_layers = []
        
        # ======================================================
        # URUTAN SAMA PERSIS DENGAN _fix_z_order()
        # ======================================================
        
        # LAPISAN ATAS - Titik-titik (point)
        if self._antenna_layer and self._antenna_layer.isValid():
            all_layers.append(self._antenna_layer)
            print("  - RF_Antenna")
        
        if self._impact_layer and self._impact_layer.isValid():
            all_layers.append(self._impact_layer)
            print("  - RF_Impact")
        
        if self._beam_end_layer and self._beam_end_layer.isValid():
            all_layers.append(self._beam_end_layer)
            print("  - RF_BeamEnd")
        
        if self._upper_intersection_layer and self._upper_intersection_layer.isValid():
            all_layers.append(self._upper_intersection_layer)
            print("  - RF_UpperIntersection")

        if self._lower_intersection_layer and self._lower_intersection_layer.isValid():
            all_layers.append(self._lower_intersection_layer)
            print("  - RF_LowerIntersection")
        
        if self._center_layer and self._center_layer.isValid():
            all_layers.append(self._center_layer)
            print("  - RF_CenterLine")
        
        # LAPISAN BAWAH - Area luas (polygon)
        if self._footprint_layer and self._footprint_layer.isValid():
            all_layers.append(self._footprint_layer)
            print("  - RF_Footprint")
        
        if self._sector_layer and self._sector_layer.isValid():
            all_layers.append(self._sector_layer)
            print("  - RF_Sector")
        
        # LAPISAN TENGAH - Garis putus (line)
        if self._beam_layer and self._beam_layer.isValid():
            all_layers.append(self._beam_layer)
            print("  - RF_BeamEdges")
        
        # OSM DI PALING ATAS
        if self._osm_layer and self._osm_layer.isValid():
            all_layers.append(self._osm_layer)
            print("  - OSM Basemap (TOP)")
        else:
            print("  - No OSM basemap to add")
        
        # LOS layer (tambahan)
        if self._los_layer and self._los_layer.isValid():
            all_layers.append(self._los_layer)
            print("  - RF_LOS")
        
        # Set layer list ke canvas
        if all_layers:
            self.canvas.setLayers(all_layers)
            print(f"✅ Canvas rebuilt with {len(all_layers)} layers.")
        else:
            print("❌ No valid layers to display.")
        
        # Force refresh canvas
        self.canvas.refresh()
        
        # Raise overlays
        if hasattr(self, 'raise_overlays'):
            self.raise_overlays()
        
    # ======================================================
    # DEFAULT VIEW METHODS
    # ======================================================
    
    def _set_indonesia_default_view(self):
        """
        Set default view ke tengah Indonesia dengan radius yang sesuai
        Koordinat: -2.0, 118.0 (tengah Indonesia)
        Radius: 1500km (cukup untuk mencakup seluruh Indonesia)
        """
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
            import math
            
            # Koordinat tengah Indonesia (WGS84)
            indonesia_center = QgsPointXY(118.0, -2.0)
            
            # Transform ke Web Mercator (EPSG:3857) karena canvas menggunakan CRS ini
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsCoordinateReferenceSystem("EPSG:3857"),
                QgsProject.instance()
            )
            
            center_mercator = transform.transform(indonesia_center)
            
            # Radius 1500km dalam meter (cukup untuk seluruh Indonesia)
            # Dari Sabang sampai Merauke sekitar 5000km, jadi 1500km radius cukup
            radius = 1500 * 1000  # 1.500.000 meter
            
            # Buat rectangle dengan center dan radius
            rect = QgsRectangle(
                center_mercator.x() - radius,
                center_mercator.y() - radius,
                center_mercator.x() + radius,
                center_mercator.y() + radius
            )
            
            self.canvas.setExtent(rect)
            self.canvas.refresh()
            
            print(f"📍 Default view set to Indonesia center: 118.0°E, -2.0°S")
            print(f"   Radius: {radius/1000:.0f}km")
            
        except Exception as e:
            print(f"⚠️ Failed to set Indonesia default view: {e}")
            # Fallback ke extent lama jika error
            from qgis.core import QgsRectangle
            self.canvas.setExtent(QgsRectangle(95, -11, 141, 6))
            self.canvas.refresh()
            
            
    # ======================================================
    # LOAD OSM BASEMAP (FIXED - DENGAN OPACITY)
    # ======================================================

    def _load_osm_basemap(self):
        """
        Load OpenStreetMap basemap dengan multiple fallback options.
        Layer is NOT added to QGIS project, only for embedded canvas.
        OSM opacity diatur 100% agar jelas sebagai base dari RF layers.
        """
        
        # Pastikan QgsRasterLayer sudah diimport
        from qgis.core import QgsRasterLayer, QgsCoordinateReferenceSystem
        
        # Try multiple OSM URL variants
        osm_urls = [
            # Standard OSM
            "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
            
            # Alternative OSM servers
            "type=xyz&url=http://a.tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
            "type=xyz&url=http://b.tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
            "type=xyz&url=http://c.tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
            
            # OpenStreetMap France (often more reliable)
            "type=xyz&url=https://tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png&zmax=19&zmin=0",
            
            # Humanitarian OSM (different style, but works)
            "type=xyz&url=https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png&zmax=19&zmin=0"
        ]
        
        # Try each URL until one works
        for url in osm_urls:
            try:
                print(f"Trying OSM URL: {url}")
                
                # Create raster layer
                self._osm_layer = QgsRasterLayer(url, "OSM Basemap", "wms")
                
                if self._osm_layer and self._osm_layer.isValid():
                    # Set CRS explicitly to Web Mercator
                    self._osm_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
                    
                    # ======================================================
                    # SET OSM OPACITY 100% (SOLID)
                    # ======================================================
                    
                    try:
                        # Set opacity 100% (solid)
                        self._osm_layer.setOpacity(1.0)
                        print("✅ OSM opacity set to 100%")
                    except Exception as e:
                        print(f"⚠️ Could not set OSM opacity: {e}")
                    
                    print(f"OSM basemap loaded successfully with URL: {url}")
                    
                    # Update canvas layers to include OSM
                    self._update_canvas_layers()
                    
                    # Force canvas to use Web Mercator
                    self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
                    
                    # Set initial extent ke tengah Indonesia jika belum ada site
                    if not self.site:
                        self._set_indonesia_default_view()
                    
                    self.canvas.refresh()

                    # Pastikan overlay di atas setelah refresh
                    QTimer.singleShot(200, self._ensure_overlay_on_top)
                    
                    # Pastikan overlay di atas
                    if hasattr(self, 'metrics_frame'):
                        self.metrics_frame.raise_()
                    if hasattr(self, 'legend_frame'):
                        self.legend_frame.raise_()
                        
                    return True
                    
            except Exception as e:
                print(f"Failed with URL {url}: {e}")
                continue
        
        # If all OSM URLs fail, try Google Maps as fallback
        print("All OSM URLs failed, trying Google Maps fallback")
        
        try:
            # Google Maps XYZ (may have usage restrictions)
            google_url = "type=xyz&url=http://mt0.google.com/vt/lyrs=m&x={x}&y={y}&z={z}&zmax=19&zmin=0"
            self._osm_layer = QgsRasterLayer(google_url, "Google Maps", "wms")
            
            if self._osm_layer and self._osm_layer.isValid():
                self._osm_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
                
                # ======================================================
                # SET GOOGLE MAPS OPACITY JUGA
                # ======================================================
                
                try:
                    self._osm_layer.setOpacity(0.6)
                    print("✅ Google Maps opacity set to 60%")
                except Exception as e:
                    print(f"⚠️ Could not set Google Maps opacity: {e}")
                
                self._update_canvas_layers()
                self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
                self.canvas.refresh()
                return True
        except Exception as e:
            print(f"Google Maps fallback failed: {e}")
        
        # If everything fails, create a dummy transparent layer as placeholder
        print("All basemap options failed, creating placeholder")
        self._osm_layer = None
        
        # Still update canvas with RF layers only
        self._update_canvas_layers()
        
        return False

    
    
    
    # ======================================================
    # INIT RF LAYERS (FIXED - EMBEDDED CANVAS ONLY)
    # ======================================================

    def _init_rf_layers(self):
        """
        Initialize RF layers using LayerManager.
        Layers are NOT added to QGIS project, only for embedded canvas.
        """

        # Create all RF layers with add_to_project=False
        self._antenna_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_Antenna", "Point", add_to_project=False
        )

        self._sector_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_Sector", "Polygon", add_to_project=False
        )

        self._footprint_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_Footprint", "Polygon", add_to_project=False
        )

        self._beam_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_BeamEdges", "LineString", add_to_project=False
        )

        self._center_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_CenterLine", "LineString", add_to_project=False
        )

        self._impact_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_Impact", "Point", add_to_project=False
        )
        
        # ======================================================
        # TAMBAHKAN LAYER BARU UNTUK BEAM END POINT (HIJAU)
        # ======================================================
        self._beam_end_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_BeamEnd", "Point", add_to_project=False
        )
        
        # ======================================================
        # TAMBAHKAN LAYER UNTUK UPPER & LOWER INTERSECTION
        # ======================================================
        self._upper_intersection_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_UpperIntersection", "Point", add_to_project=False
        )

        self._lower_intersection_layer = self.layer_manager.get_or_create_vector_layer(
            "RF_LowerIntersection", "Point", add_to_project=False
        )

        # Clear all features initially
        self.clear_all_layers()

        # ======================================================
        # SET INITIAL STYLES
        # ======================================================

        self._setup_layer_styles()

        # ======================================================
        # UPDATE CANVAS LAYERS (EMBEDDED CANVAS ONLY)
        # ======================================================

        self._update_canvas_layers()

    # ======================================================
    # SETUP LAYER STYLES (FIXED - TANPA ERROR PEN)
    # ======================================================

    def _setup_layer_styles(self):
        """
        Set default styles for all RF layers dengan warna kontras.
        Opacity 100% (normal), outline tebal agar terlihat di atas OSM.
        """

        # Antenna style - HITAM dengan outline putih
        if self._antenna_layer:
            symbol = QgsMarkerSymbol.createSimple({
                "name": "triangle",
                "color": "0,0,0",  # Hitam
                "outline_color": "255,255,255",
                "outline_width": "1.5",
                "size": "10"
            })
            self._antenna_layer.renderer().setSymbol(symbol)

        # Center line style - MERAH dengan style DASHED, width 1
        if self._center_layer:
            from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer
            from PyQt5.QtCore import Qt
            
            # Buat symbol layer dengan style dashed
            symbol_layer = QgsSimpleLineSymbolLayer()
            symbol_layer.setColor(QColor(255, 0, 0))  # Merah
            symbol_layer.setWidth(0.6)                  # Width 0.6
            symbol_layer.setPenStyle(Qt.DashLine)     # Style dashed
            
            # Buat symbol dan assign ke layer
            symbol = QgsLineSymbol()
            symbol.changeSymbolLayer(0, symbol_layer)
            self._center_layer.renderer().setSymbol(symbol)

        # Beam edges style - HITAM dengan style dashed
        if self._beam_layer:
            # Untuk dashed line, kita bisa gunakan createSimple
            from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer
            
            # Buat symbol layer dengan style dashed
            symbol_layer = QgsSimpleLineSymbolLayer()
            symbol_layer.setColor(QColor(0, 0, 0))
            symbol_layer.setWidth(3)
            
            # Set style dashed
            from PyQt5.QtCore import Qt
            symbol_layer.setPenStyle(Qt.DashLine)
            
            # Buat symbol dan tambahkan layer
            symbol = QgsLineSymbol()
            symbol.changeSymbolLayer(0, symbol_layer)
            
            self._beam_layer.renderer().setSymbol(symbol)

        # Impact style - HIJAU SOLID dengan outline HITAM
        if self._impact_layer:
            symbol = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "0,160,0",     # Hijau solid #00A000
                "outline_color": "0,0,0",  # Outline HITAM
                "outline_width": "0.4",
                "size": "4"
            })
            self._impact_layer.renderer().setSymbol(symbol)
        
        # Upper Intersection style - BIRU (sesuai upper beam)
        if self._upper_intersection_layer:
            symbol = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "42,125,225",        # Biru (#2a7de1)
                "color_border": "255,255,255",  # Outline putih
                "outline_width": "0.4",
                "size": "4"
            })
            self._upper_intersection_layer.renderer().setSymbol(symbol)

        # Lower Intersection style - MERAH (sesuai lower beam)
        if self._lower_intersection_layer:
            symbol = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "255,0,0",  # Merah
                "color_border": "255,255,255",  # Outline putih
                "outline_width": "0.4",
                "size": "4"
            })
            self._lower_intersection_layer.renderer().setSymbol(symbol)
    
    
        # Beam End style - HIJAU TERANG dengan outline PUTIH TEBAL
        if self._beam_end_layer:
            symbol = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "0,255,0",        # Hijau terang
                "color_border": "255,255,255",  # Outline putih
                "outline_width": "0.4",       # Outline lebih tebal
                "size": "4"                 # 
            })
            self._beam_end_layer.renderer().setSymbol(symbol)
            
            
        # Footprint style - TOSCA dengan outline DARK CYAN
        if self._footprint_layer:
            symbol = QgsFillSymbol.createSimple({
                "color": "6,250,250,255",  # Tosca solid
                "outline_color": "6,200,250",  # Dark cyan outline
                "outline_width": "2"
            })
            self._footprint_layer.renderer().setSymbol(symbol)
            
        # Sector style - Kuning dengan outline HITAM
        if self._sector_layer:
            symbol = QgsFillSymbol.createSimple({
                "color": "255,255,0,10",  # Kuning solid
                "outline_color": "255,255,0",  # Outline Kuning
                "outline_width": "1.5"
            })
            self._sector_layer.renderer().setSymbol(symbol)


    # ======================================================
    # UPDATE CANVAS LAYERS (SEDERHANA - PANGGIL FIX Z-ORDER)
    # ======================================================

    def _update_canvas_layers(self):
        """
        Update canvas layer stack - delegasi ke fix_z_order.
        """
        
        # Set canvas destination CRS to Web Mercator
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        
        # Panggil fix_z_order untuk mengatur urutan layer
        self._fix_z_order()
    

    # ======================================================
    # FIX Z-ORDER - RF LAYERS DENGAN URUTAN YANG BENAR
    # ======================================================

    def _fix_z_order(self):
        """
        Mengatur urutan RF layers dari bawah ke atas:
        - Bawah: Sector, Footprint (area luas)
        - Tengah: BeamEdges (garis)
        - Atas: Antenna, Impact, CenterLine (titik-titik penting)
        OSM tetap di paling atas (tidak diubah)
        """
        
        print("🔄 Fixing RF layer Z-order...")
        
        # Kumpulkan semua layers
        all_layers = []
        
                
        # ======================================================
        # LAPISAN ATAS - Titik-titik (point) - PALING IMPORTANT
        # ======================================================
        if self._antenna_layer and self._antenna_layer.isValid():
            all_layers.append(self._antenna_layer)
            print("  - RF_Antenna - Segitiga Hitam - Outline Putih")
        
        if self._impact_layer and self._impact_layer.isValid():
            all_layers.append(self._impact_layer)
            print("  - RF_Impact - Lingkaran Hijau Tua Outline Hitam")
        
        # BeamEnd di ATAS impact agar tidak tertutup
        if self._beam_end_layer and self._beam_end_layer.isValid():
            all_layers.append(self._beam_end_layer)
            print("  - RF_BeamEnd (top) - Titik Hijau")
            
        if self._upper_intersection_layer and self._upper_intersection_layer.isValid():
            all_layers.append(self._upper_intersection_layer)
            print("  - RF_UpperIntersection - Biru")

        if self._lower_intersection_layer and self._lower_intersection_layer.isValid():
            all_layers.append(self._lower_intersection_layer)
            print("  - RF_LowerIntersection - Merah")
    
        # PASTIKAN INI ADA (center line di lapisan atas)
        if self._center_layer and self._center_layer.isValid():
            all_layers.append(self._center_layer)
            print("  - RF_CenterLine - Garis Merah Dash")
                    
        # ======================================================
        # LAPISAN BAWAH - Area luas (polygon)
        # ======================================================
        if self._footprint_layer and self._footprint_layer.isValid():
            all_layers.append(self._footprint_layer)
            print("  - RF_Footprint")
            
        if self._sector_layer and self._sector_layer.isValid():
            all_layers.append(self._sector_layer)
            print("  - RF_Sector (bottom)")
        
            
        # ======================================================
        # LAPISAN TENGAH - Garis putus (line)
        # ======================================================
        if self._beam_layer and self._beam_layer.isValid():
            all_layers.append(self._beam_layer)
            print("  - RF_BeamEdges - Hitam Muncul")
        
        # ======================================================
        # OSM TETAP DI PALING ATAS (TIDAK DIUBAH)
        # ======================================================
        if self._osm_layer and self._osm_layer.isValid():
            all_layers.append(self._osm_layer)
            print("  - OSM Basemap (TOP - unchanged)")
        

        # Set layers ke canvas
        if all_layers:
            self.canvas.setLayers(all_layers)
            print(f"✅ Z-order fixed: {len(all_layers)} layers")
            
            # ===== PENTING: Raise overlay setelah setLayers =====
            if hasattr(self, 'metrics_frame'):
                self.metrics_frame.raise_()
                print("  ✅ Metrics overlay raised to top")
            
            if hasattr(self, 'legend_frame'):
                self.legend_frame.raise_()
                print("  ✅ Legend frame raised to top")
        else:
            print("❌ No layers to display")

        self.canvas.refresh() 
    
    

    # =====================================================
    # RAISE OVERLAYS
    # =====================================================
    
    def raise_overlays(self):
        """
        Raise both metrics and legend overlays to the top
        Bisa dipanggil dari dialog setelah map updates
        """
        if hasattr(self, 'metrics_frame'):
            # ===== PASTIKAN VISIBLE =====
            self.metrics_frame.setVisible(True)
            self.metrics_frame.show()
            self.metrics_frame.raise_()
            print(f"✅ Metrics overlay raised - Visible: {self.metrics_frame.isVisible()}")
        
        if hasattr(self, 'legend_frame'):
            self.legend_frame.raise_()
            print("✅ Legend frame raised")
        
        self.canvas.refresh()
        
        # ===== TAMBAHKAN: Second attempt with delay =====
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._ensure_overlay_on_top)
    
    # ======================================================
    # MAP NAVIGATION METHODS
    # ======================================================
    
    def _setup_navigation_tools(self):
        """
        Setup map tools - hanya pan tool yang digunakan
        Zoom in/out dilakukan via method, bukan map tool
        """
        from qgis.gui import QgsMapToolPan
        
        # Pan tool (default)
        self._pan_tool = QgsMapToolPan(self.canvas)
        
        # Set default mode
        self.set_pan_mode()
        
        print("✅ Navigation tools initialized")
    
    def set_pan_mode(self):
        """
        Set canvas ke mode pan (default mode)
        Kursor: hand
        """
        self.canvas.setCursor(Qt.OpenHandCursor)
        self.canvas.setMapTool(self._pan_tool)
        print("🖱️ Pan mode activated")
    
    def zoom_in(self):
        """
        Zoom in satu level (center tetap di tengah canvas)
        """
        # Get current extent
        extent = self.canvas.extent()
        
        # Zoom in by factor 0.8 (lebih kecil = lebih zoom in)
        center = extent.center()
        width = extent.width()
        height = extent.height()
        
        new_extent = QgsRectangle(
            center.x() - width * 0.4,
            center.y() - height * 0.4,
            center.x() + width * 0.4,
            center.y() + height * 0.4
        )
        
        self.canvas.setExtent(new_extent)
        self.canvas.refresh()
        
        print("🔍 Zoomed in")
    
    def zoom_out(self):
        """
        Zoom out satu level (center tetap di tengah canvas)
        """
        # Get current extent
        extent = self.canvas.extent()
        
        # Zoom out by factor 1.2
        center = extent.center()
        width = extent.width()
        height = extent.height()
        
        new_extent = QgsRectangle(
            center.x() - width * 0.6,
            center.y() - height * 0.6,
            center.x() + width * 0.6,
            center.y() + height * 0.6
        )
        
        self.canvas.setExtent(new_extent)
        self.canvas.refresh()
        
        print("🔍 Zoomed out")
    
    def reset_view(self):
        """
        Reset view ke tampilan optimal (saved extent dari analysis)
        """
        if hasattr(self, '_saved_extent') and self._saved_extent:
            self.canvas.setExtent(self._saved_extent)
            self.canvas.refresh()
            print("⟲ View reset to default")
        else:
            print("⚠️ No saved extent available, using smart zoom")
            self._smart_zoom()
        
        # Pastikan tetap di pan mode
        self.set_pan_mode()
    
    # ======================================================
    # SHOW EVENT
    # ======================================================
    
    def showEvent(self, event):
        """Called when widget is shown"""
        super().showEvent(event)
        # Raise overlays after widget is shown
        if hasattr(self, 'metrics_frame'):
            self.metrics_frame.setVisible(True)
            self.metrics_frame.show()
        QTimer.singleShot(100, self._ensure_overlay_on_top)
        

    # ======================================================
    # CLEAR ALL LAYERS (EXISTING)
    # ======================================================

    def clear_all_layers(self):
        """
        Clear all features from RF layers.
        """
        self.layer_manager.clear_layer("RF_Antenna")
        self.layer_manager.clear_layer("RF_Sector")
        self.layer_manager.clear_layer("RF_Footprint")
        self.layer_manager.clear_layer("RF_BeamEdges")
        self.layer_manager.clear_layer("RF_CenterLine")
        self.layer_manager.clear_layer("RF_Impact")
        self.layer_manager.clear_layer("RF_BeamEnd")
        self.layer_manager.clear_layer("RF_UpperIntersection")  # <-- TAMBAHKAN
        self.layer_manager.clear_layer("RF_LowerIntersection")  # <-- TAMBAHKAN
        # Reset metrics overlay
        self.hide_metrics()

    # ======================================================
    # HIDE ALL LAYERS (BEFORE RUN) - FIXED
    # ======================================================

    def hide_all_layers(self):
        """
        Hide all RF layers from canvas (clear features).
        Called before running new analysis.
        """
        print("🧹 Clearing all layers before new analysis...")
        self.clear_all_layers()
        
        # Force canvas refresh
        self.canvas.refresh()
        print("✅ All layers cleared")

    # ======================================================
    # NEW: SHOW LAYERS AFTER RUN
    # ======================================================

    def show_analysis_results(self, results):
        """
        Show analysis results - called after Run Analysis.
        results dict contains impact_point, footprint_start, etc.
        """
        # This will be called from dialog after analysis
        pass

    # ======================================================
    # SET SITE
    # ======================================================

    def set_site(self, lat, lon):
        """
        Set site location and zoom to it.
        """

        self.site = QgsPointXY(lon, lat)

        # Draw antenna
        self._draw_antenna()

        # Zoom to site
        self._zoom_to_site()


    # ======================================================
    # ZOOM TO SITE (FIXED - PROPORTIONAL)
    # ======================================================

    def _zoom_to_site(self):
        """
        Zoom canvas to site location dengan radius proporsional.
        Canvas dalam EPSG:3857, site dalam EPSG:4326.
        """

        if not self.site:
            return

        from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle

        # Create transform from WGS84 to Web Mercator
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsProject.instance()
        )

        try:
            # Transform site point to Web Mercator
            site_mercator = transform.transform(self.site)

            # Default radius 5km untuk initial view
            # Ini akan memberikan konteks geografis yang baik
            radius = 5000  # 5km dalam mercator coordinates
            
            # Jika sudah ada footprint, gunakan radius yang lebih besar
            if self._footprint_layer and self._footprint_layer.featureCount() > 0:
                extent = self._footprint_layer.extent()
                if not extent.isNull():
                    footprint_width = extent.width()
                    footprint_height = extent.height()
                    footprint_radius = max(footprint_width, footprint_height) / 2
                    radius = max(radius, footprint_radius * 3)  # Minimal 3x footprint
            
            rect = QgsRectangle(
                site_mercator.x() - radius,
                site_mercator.y() - radius,
                site_mercator.x() + radius,
                site_mercator.y() + radius
            )

            self.canvas.setExtent(rect)
            self.canvas.refresh()
            
            print(f"Zoomed to site: {self.site.x()}, {self.site.y()} -> Mercator: {site_mercator.x()}, {site_mercator.y()}")
            print(f"  - Radius: {radius}m")
            
        except Exception as e:
            print(f"Zoom to site failed: {e}")
            
            # Fallback: use WGS84 extent directly (canvas will reproject)
            lat = self.site.y()
            lon = self.site.x()
            
            # Approximate degree to meter conversion at equator
            deg_to_m = 111320
            radius_deg = 5000 / (deg_to_m * math.cos(math.radians(lat)))  # 5km
            
            rect = QgsRectangle(
                lon - radius_deg,
                lat - radius_deg,
                lon + radius_deg,
                lat + radius_deg
            )
            
            self.canvas.setExtent(rect)
            
            # ======================================================
            # SAVE EXTENT FOR RESET VIEW
            # ======================================================
            self._saved_extent = rect
            self.canvas.refresh()


    # ======================================================
    # AUTO ZOOM CERDAS (SEPERTI WEB VERSION)
    # ======================================================

    def _smart_zoom(self):
        """
        Zoom cerdas yang menampilkan seluruh area RF dengan konteks geografis.
        Menggunakan center dari semua layer RF, bukan site.
        """
        
        if not self.site:
            return
        
        from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle
        
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsProject.instance()
        )
        
        try:
            # Kumpulkan semua extent dari RF layers
            all_extents = []
            
            # Cek footprint
            if self._footprint_layer and self._footprint_layer.featureCount() > 0:
                extent = self._footprint_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
                    print(f"  - Footprint extent: {extent.toString()}")
            
            # Cek sector
            if self._sector_layer and self._sector_layer.featureCount() > 0:
                extent = self._sector_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
                    print(f"  - Sector extent: {extent.toString()}")
            
            # Cek beam edges
            if self._beam_layer and self._beam_layer.featureCount() > 0:
                extent = self._beam_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
            
            # Cek LOS
            if self._los_layer and self._los_layer.featureCount() > 0:
                extent = self._los_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
            
            # Cek center line
            if self._center_layer and self._center_layer.featureCount() > 0:
                extent = self._center_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
            
            # Cek impact
            if self._impact_layer and self._impact_layer.featureCount() > 0:
                extent = self._impact_layer.extent()
                if not extent.isNull():
                    all_extents.append(extent)
            
            if not all_extents:
                # Fallback ke site
                site_mercator = transform.transform(self.site)
                view_radius = 1000
                rect = QgsRectangle(
                    site_mercator.x() - view_radius,
                    site_mercator.y() - view_radius,
                    site_mercator.x() + view_radius,
                    site_mercator.y() + view_radius
                )
                self.canvas.setExtent(rect)
                self.canvas.refresh()
                return
            
            # Gabungkan semua extent
            combined_extent = all_extents[0]
            for ext in all_extents[1:]:
                combined_extent.combineExtentWith(ext)
            
            # Hitung center dari combined extent
            center_x = (combined_extent.xMaximum() + combined_extent.xMinimum()) / 2
            center_y = (combined_extent.yMaximum() + combined_extent.yMinimum()) / 2
            center_point = QgsPointXY(center_x, center_y)
            
            # Konversi center ke mercator
            center_mercator = transform.transform(center_point)
            
            # Hitung radius maksimum dari center ke semua ujung
            min_mercator = transform.transform(QgsPointXY(combined_extent.xMinimum(), combined_extent.yMinimum()))
            max_mercator = transform.transform(QgsPointXY(combined_extent.xMaximum(), combined_extent.yMaximum()))
            
            d1 = math.sqrt((min_mercator.x() - center_mercator.x())**2 + (min_mercator.y() - center_mercator.y())**2)
            d2 = math.sqrt((max_mercator.x() - center_mercator.x())**2 + (max_mercator.y() - center_mercator.y())**2)
            max_distance = max(d1, d2)
            
            # Padding 30% (sudah proper dari pengalaman)
            view_radius = max_distance * 1.3
            
            print(f"🔍 Smart zoom:")
            print(f"  - Combined extent (WGS84): {combined_extent.toString()}")
            print(f"  - Center: {center_x:.6f}, {center_y:.6f}")
            print(f"  - Max distance from center: {max_distance:.0f}m")
            print(f"  - View radius: {view_radius:.0f}m (with 30% padding)")
            
            rect = QgsRectangle(
                center_mercator.x() - view_radius,
                center_mercator.y() - view_radius,
                center_mercator.x() + view_radius,
                center_mercator.y() + view_radius
            )
            
            self.canvas.setExtent(rect)
            
            # ======================================================
            # SAVE EXTENT FOR RESET VIEW
            # ======================================================
            self._saved_extent = rect
            print(f"💾 Saved extent for reset view")

            self.canvas.refresh()

            
        except Exception as e:
            print(f"Smart zoom failed: {e}")
            import traceback
            traceback.print_exc()
            self._zoom_to_site()  # Fallback

    # ======================================================
    # DRAW ANTENNA
    # ======================================================

    def _draw_antenna(self):
        """
        Draw antenna icon at site location.
        """

        if not self.site or not self._antenna_layer:
            return

        self.layer_manager.clear_layer("RF_Antenna")

        provider = self._antenna_layer.dataProvider()

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(self.site))

        provider.addFeature(feat)

        self._antenna_layer.updateExtents()

        # Update symbol with current azimuth
        symbol = QgsMarkerSymbol.createSimple({
            "name": "triangle",
            "color": "0,0,0",
            "outline_color": "255,255,255",
            "size": "8"
        })

        symbol.setAngle(self.azimuth)
        self._antenna_layer.renderer().setSymbol(symbol)

        self._antenna_layer.triggerRepaint()

    # ======================================================
    # SET AZIMUTH
    # ======================================================

    def set_azimuth(self, azimuth):
        """
        Set antenna azimuth.
        """

        self.azimuth = azimuth
        self._draw_antenna()  # Update antenna direction

    # ======================================================
    # SET HORIZONTAL BEAMWIDTH
    # ======================================================

    def set_beamwidth(self, bw):
        """
        Set horizontal beamwidth.
        """

        self.h_beamwidth = bw

    # ======================================================
    # SET SECTOR RADIUS
    # ======================================================

    def set_sector_radius(self, radius):
        """
        Set sector visualization radius.
        """

        self.radius = radius


    # ======================================================
    # DRAW SECTOR - MENGGUNAKAN STYLE DARI _setup_layer_styles()
    # ======================================================

    def draw_sector(self, distance):
        """
        Draw basic sector polygon.
        Menggunakan style dari _setup_layer_styles(), tidak override style.

        Parameters
        ----------
        distance : float
            Sector radius in meters
        """

        if not self.site or distance <= 0:
            print("draw_sector: invalid parameters")
            return

        self.coverage = distance
        self.layer_manager.clear_layer("RF_Sector")

        if not self._sector_layer:
            print("draw_sector: _sector_layer is None")
            return

        provider = self._sector_layer.dataProvider()
        if not provider:
            print("draw_sector: provider is None")
            return

        start_angle = self.azimuth - self.h_beamwidth / 2
        end_angle = self.azimuth + self.h_beamwidth / 2

        steps = 40

        # Earth radius in meters
        R = 6378137.0

        lat1 = math.radians(self.site.y())
        lon1 = math.radians(self.site.x())

        points = [self.site]  # Start at site

        # Create arc
        for i in range(steps + 1):
            angle_deg = start_angle + (end_angle - start_angle) * i / steps
            angle_rad = math.radians(angle_deg)
            
            # Calculate point at distance
            lat2 = math.asin(
                math.sin(lat1) * math.cos(distance / R) +
                math.cos(lat1) * math.sin(distance / R) * math.cos(angle_rad)
            )
            
            lon2 = lon1 + math.atan2(
                math.sin(angle_rad) * math.sin(distance / R) * math.cos(lat1),
                math.cos(distance / R) - math.sin(lat1) * math.sin(lat2)
            )
            
            points.append(QgsPointXY(
                math.degrees(lon2),
                math.degrees(lat2)
            ))

        points.append(self.site)  # Close polygon

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPolygonXY([points]))

        if provider.addFeature(feat):
            print(f"✅ Sector added with radius {distance:.0f}m")
        else:
            print("❌ Failed to add sector feature")
            return

        # ======================================================
        # TIDAK MENGAPPLY STYLE DI SINI - MENGGUNAKAN DARI _setup_layer_styles()
        # ======================================================

        self._sector_layer.updateExtents()
        self._sector_layer.triggerRepaint()
        
        # ======================================================
        # FIX Z-ORDER SETELAH MENAMBAH FEATURE
        # ======================================================
        
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_sector]")
            
        # ======================================================
        # FORCE CANVAS REFRESH
        # ======================================================
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_sector")
            

    # =====================================================
    # SET FOOTPRINT (ANNULAR SECTOR) - FIXED DENGAN Z-ORDER
    # =====================================================

    def set_footprint(self, start_distance, end_distance):
        """
        Draw annular sector footprint.

        Parameters
        ----------
        start_distance : float
            Inner radius in meters
        end_distance : float
            Outer radius in meters
        """

        if start_distance is None or end_distance is None:
            print("set_footprint: start_distance or end_distance is None")
            return

        if not self.site:
            print("set_footprint: site not set")
            return

        # Clear existing features
        self.layer_manager.clear_layer("RF_Footprint")

        # =====================================================
        # CEK LAYER DAN PROVIDER
        # =====================================================
        
        if not self._footprint_layer:
            print("set_footprint: _footprint_layer is None")
            # Coba inisialisasi ulang
            self._footprint_layer = self.layer_manager.get_or_create_vector_layer(
                "RF_Footprint", "Polygon", add_to_project=False
            )
            if not self._footprint_layer:
                print("set_footprint: failed to create footprint layer")
                return

        provider = self._footprint_layer.dataProvider()
        if not provider:
            print("set_footprint: provider is None")
            return

        # Build annular sector polygon
        polygon = self._build_annular_sector(
            self.site,
            self.azimuth,
            self.h_beamwidth,
            start_distance,
            end_distance
        )

        if not polygon or len(polygon) < 3:
            print("set_footprint: polygon is empty or invalid")
            return

        # Buat feature
        feat = QgsFeature()
        geom = QgsGeometry.fromPolygonXY([polygon])
        
        if geom.isNull() or geom.isEmpty():
            print("set_footprint: generated geometry is null")
            return
            
        feat.setGeometry(geom)

        # Add feature ke layer
        if not provider.addFeature(feat):
            print("set_footprint: failed to add feature")
            return

        print(f"✅ Footprint added: {start_distance:.0f}m -> {end_distance:.0f}m")

        # =====================================================
        # FORCE STYLE UPDATE - TOSCA
        # =====================================================
        
        # Apply style dengan warna tosca (sama dengan profile)
        symbol = QgsFillSymbol.createSimple({
            "color": "6,250,250,60",  # Tosca dengan opacity 60
            "outline_color": "6,200,250",  # Dark cyan untuk outline
            "outline_width": "2.0"
        })
        self._footprint_layer.renderer().setSymbol(symbol)

        self._footprint_layer.updateExtents()
        self._footprint_layer.triggerRepaint()
        
        
        # ======================================================
        # SMART ZOOM (SEPERTI WEB VERSION) - REPLACE DENGAN INI
        # ======================================================
        
        self._smart_zoom()
        
        # ======================================================
        # FIX Z-ORDER - PASTIKAN OSM DI BAWAH
        # ======================================================
        
        # Panggil method fix_z_order untuk mengatur ulang urutan layer
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after footprint")
        else:
            # Fallback jika method belum ada
            print("⚠️ _fix_z_order method not found, using fallback")
            all_layers = []
            
            # OSM harus paling bawah
            if self._osm_layer and self._osm_layer.isValid():
                all_layers.append(self._osm_layer)
            
            # RF layers
            rf_layers = [
                self._footprint_layer,
                self._sector_layer,
                self._beam_layer,
                self._los_layer,
                self._center_layer,
                self._debug_layer,
                self._impact_layer,
                self._antenna_layer
            ]
            
            for layer in rf_layers:
                if layer and layer.isValid():
                    all_layers.append(layer)
            
            if all_layers:
                self.canvas.setLayers(all_layers)
                print(f"✅ Fallback Z-order fixed: {len(all_layers)} layers")
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after footprint")
        

    # ======================================================
    # BUILD ANNULAR SECTOR (FIXED CRS HANDLING)
    # ======================================================

    def _build_annular_sector(
        self,
        center,
        azimuth,
        beamwidth,
        inner_radius,
        outer_radius,
        steps=40
    ):
        """
        Build annular sector polygon points.
        All calculations in WGS84, canvas will reproject to EPSG:3857.
        
        Returns
        -------
        list[QgsPointXY] in WGS84
        """

        start_angle = azimuth - beamwidth / 2
        end_angle = azimuth + beamwidth / 2

        # Earth radius in meters
        R = 6378137.0

        lat1 = math.radians(center.y())
        lon1 = math.radians(center.x())

        points = []

        # ======================================================
        # OUTER ARC (COUNTER-CLOCKWISE)
        # ======================================================

        for i in range(steps + 1):
            angle_deg = start_angle + (end_angle - start_angle) * i / steps
            angle_rad = math.radians(angle_deg)
            
            # Calculate point at outer_radius distance
            lat2 = math.asin(
                math.sin(lat1) * math.cos(outer_radius / R) +
                math.cos(lat1) * math.sin(outer_radius / R) * math.cos(angle_rad)
            )
            
            lon2 = lon1 + math.atan2(
                math.sin(angle_rad) * math.sin(outer_radius / R) * math.cos(lat1),
                math.cos(outer_radius / R) - math.sin(lat1) * math.sin(lat2)
            )
            
            points.append(QgsPointXY(
                math.degrees(lon2),
                math.degrees(lat2)
            ))

        # ======================================================
        # INNER ARC (CLOCKWISE)
        # ======================================================

        for i in range(steps, -1, -1):
            angle_deg = start_angle + (end_angle - start_angle) * i / steps
            angle_rad = math.radians(angle_deg)
            
            # Calculate point at inner_radius distance
            lat2 = math.asin(
                math.sin(lat1) * math.cos(inner_radius / R) +
                math.cos(lat1) * math.sin(inner_radius / R) * math.cos(angle_rad)
            )
            
            lon2 = lon1 + math.atan2(
                math.sin(angle_rad) * math.sin(inner_radius / R) * math.cos(lat1),
                math.cos(inner_radius / R) - math.sin(lat1) * math.sin(lat2)
            )
            
            points.append(QgsPointXY(
                math.degrees(lon2),
                math.degrees(lat2)
            ))

        return points


    # ======================================================
    # DRAW BEAM EDGES (UPDATED - GUNAKAN UPPER INTERSECTION)
    # ======================================================

    def draw_beam_edges(self, upper_intersection):
        """
        Draw left and right beam edges sampai upper intersection.
        
        Parameters
        ----------
        upper_intersection : float
            Upper beam intersection distance in meters
        """
        
        if not self.site or upper_intersection <= 0:
            return
        
        self.layer_manager.clear_layer("RF_BeamEdges")
        
        if not self._beam_layer:
            print("draw_beam_edges: _beam_layer is None")
            return
        
        provider = self._beam_layer.dataProvider()
        if not provider:
            print("draw_beam_edges: provider is None")
            return
        
        R = 6378137.0
        lat1 = math.radians(self.site.y())
        lon1 = math.radians(self.site.x())
        
        left_angle = self.azimuth - self.h_beamwidth / 2
        right_angle = self.azimuth + self.h_beamwidth / 2
        
        features = []
        
        for angle_deg in (left_angle, right_angle):
            angle_rad = math.radians(angle_deg)
            
            # Calculate end point at upper_intersection
            lat2 = math.asin(
                math.sin(lat1) * math.cos(upper_intersection / R) +
                math.cos(lat1) * math.sin(upper_intersection / R) * math.cos(angle_rad)
            )
            
            lon2 = lon1 + math.atan2(
                math.sin(angle_rad) * math.sin(upper_intersection / R) * math.cos(lat1),
                math.cos(upper_intersection / R) - math.sin(lat1) * math.sin(lat2)
            )
            
            end_point = QgsPointXY(
                math.degrees(lon2),
                math.degrees(lat2)
            )
            
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolylineXY([self.site, end_point]))
            features.append(feat)
        
        if provider.addFeatures(features):
            print(f"✅ Beam edges added: {len(features)} lines to {upper_intersection:.0f}m")
        else:
            print("❌ Failed to add beam edges")
        
        # Apply style - dashed black line
        from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer
        symbol_layer = QgsSimpleLineSymbolLayer()
        symbol_layer.setColor(QColor(0, 0, 0))
        symbol_layer.setWidth(2)
        from PyQt5.QtCore import Qt
        symbol_layer.setPenStyle(Qt.DashLine)
        
        symbol = QgsLineSymbol()
        symbol.changeSymbolLayer(0, symbol_layer)
        self._beam_layer.renderer().setSymbol(symbol)
        
        self._beam_layer.updateExtents()
        self._beam_layer.triggerRepaint()
        
            
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_beam_edges]")
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_beam_edges")
        


    # ======================================================
    # DRAW CENTER LINE (UPDATED - DASHED RED LINE)
    # ======================================================

    def draw_center_line(self, distance):
        """
        Draw center line at given azimuth (dashed red line).
        
        Parameters
        ----------
        distance : float
            Length of center line in meters
        """

        if not self.site or distance <= 0:
            return

        self.layer_manager.clear_layer("RF_CenterLine")

        if not self._center_layer:
            print("draw_center_line: _center_layer is None")
            return

        provider = self._center_layer.dataProvider()
        if not provider:
            print("draw_center_line: provider is None")
            return

        R = 6378137.0
        lat1 = math.radians(self.site.y())
        lon1 = math.radians(self.site.x())
        angle_rad = math.radians(self.azimuth)

        # Calculate end point
        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance / R) +
            math.cos(lat1) * math.sin(distance / R) * math.cos(angle_rad)
        )
        
        lon2 = lon1 + math.atan2(
            math.sin(angle_rad) * math.sin(distance / R) * math.cos(lat1),
            math.cos(distance / R) - math.sin(lat1) * math.sin(lat2)
        )
        
        end_point = QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPolylineXY([self.site, end_point]))

        if provider.addFeature(feat):
            print(f"✅ Center line added: {distance:.0f}m")
        else:
            print("❌ Failed to add center line")

        # Style sudah di-set di _setup_layer_styles()
        self._center_layer.updateExtents()
        self._center_layer.triggerRepaint()
        
        # ======================================================
        # FIX Z-ORDER SETELAH MENAMBAH FEATURE
        # ======================================================
        
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_center_line]")
            
        # ======================================================
        # FORCE CANVAS REFRESH
        # ======================================================
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_center_line")



    # ======================================================
    # DRAW BEAM END POINT (HIJAU) - MENGGUNAKAN LAYER KHUSUS
    # ======================================================

    def draw_beam_end_point(self, distance):
        """
        Draw green point at the end of main beam (center line)
        Menggunakan layer khusus RF_BeamEnd (Point)
        
        Parameters
        ----------
        distance : float
            Distance from site in meters
        """
        
        print(f"🟢 draw_beam_end_point called with distance={distance}m")
        
        if not self.site:
            print("  ❌ self.site is None")
            return
            
        if distance <= 0:
            print(f"  ❌ distance invalid: {distance}")
            return
        
        # Clear previous beam end point
        self.layer_manager.clear_layer("RF_BeamEnd")
        print("  ✅ Cleared previous beam end layer")
        
        if not self._beam_end_layer:
            print("  ❌ _beam_end_layer is None")
            return
        
        provider = self._beam_end_layer.dataProvider()
        if not provider:
            print("  ❌ provider is None")
            return
        
        # Hitung titik akhir
        R = 6378137.0
        lat1 = math.radians(self.site.y())
        lon1 = math.radians(self.site.x())
        angle_rad = math.radians(self.azimuth)
        
        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance / R) +
            math.cos(lat1) * math.sin(distance / R) * math.cos(angle_rad)
        )
        
        lon2 = lon1 + math.atan2(
            math.sin(angle_rad) * math.sin(distance / R) * math.cos(lat1),
            math.cos(distance / R) - math.sin(lat1) * math.sin(lat2)
        )
        
        end_point = QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )
        
        print(f"  📍 End point calculated: ({end_point.y():.6f}, {end_point.x():.6f})")
        
        # Buat feature point
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(end_point))
        
        if provider.addFeature(feat):
            print(f"  ✅ Feature added successfully")
        else:
            print("  ❌ Failed to add feature")
            return
        
        # Style sudah di-set di _setup_layer_styles()
        self._beam_end_layer.updateExtents()
        self._beam_end_layer.triggerRepaint()
        
        print(f"✅ Beam end point added at {distance:.0f}m")
        
        # Fix z-order
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_beam_end_point]")
        
        self.canvas.refresh()
        print("  ✅ Canvas refreshed after draw_beam_end_point")
        



    # ======================================================
    # DRAW IMPACT - MENGGUNAKAN STYLE DARI _setup_layer_styles()
    # ======================================================

    def draw_impact(self, lat, lon):
        """
        Draw impact point marker.
        Menggunakan style dari _setup_layer_styles(), tidak override style.

        Parameters
        ----------
        lat : float
            Latitude in degrees
        lon : float
            Longitude in degrees
        """

        self.layer_manager.clear_layer("RF_Impact")

        if not self._impact_layer:
            print("draw_impact: _impact_layer is None")
            return

        provider = self._impact_layer.dataProvider()
        if not provider:
            print("draw_impact: provider is None")
            return

        point = QgsPointXY(lon, lat)

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(point))

        if provider.addFeature(feat):
            print(f"✅ Impact point added: {lat:.6f}, {lon:.6f}")
        else:
            print("❌ Failed to add impact point")
            return


        self._impact_layer.updateExtents()
        self._impact_layer.triggerRepaint()
        
        # ======================================================
        # FIX Z-ORDER SETELAH MENAMBAH FEATURE
        # ======================================================
        
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_impact]")
        
        # ======================================================
        # FORCE CANVAS REFRESH
        # ======================================================
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_impact")
        
        # ======================================================
        # FLASHING EFFECT - TAMBAHKAN DI SINI
        # ======================================================
        try:
            self.flash_impact_point(times=5, interval=200)
        except Exception as e:
            print(f"⚠️ Flashing failed: {e}")

    
    # ======================================================
    # FLASHING EFFECT METHODS - AMAN VERSION
    # ======================================================
    
    def flash_impact_point(self, times=5, interval=200):
        """
        Membuat impact point berkedip - VERSI AMAN
        """
        print(f"✨ Starting safe flash ({times} times)")
        
        # Validasi layer
        if not self._impact_layer or not self._impact_layer.isValid():
            print("⚠️ Cannot flash: impact layer invalid")
            return
        
        # Hentikan flashing sebelumnya jika ada
        self._cleanup_flash_timer()
        
        # Simpan referensi
        self._impact_layer_ref = self._impact_layer
        self._original_style = None
        
        # Simpan style asli
        try:
            symbol = self._impact_layer.renderer().symbol()
            if symbol:
                self._original_style = {
                    "color": symbol.color().name(),
                    "size": symbol.size(),
                    "outline": symbol.color().name() if hasattr(symbol, 'outlineColor') else "#000000"
                }
        except:
            self._original_style = None
        
        # Setup flashing
        self._flash_step = 0
        self._flash_max = times * 2
        self._flash_timer_running = True
        
        # Mulai dengan QTimer.singleShot (lebih aman)
        self._schedule_next_flash(interval)
    
    def _schedule_next_flash(self, interval):
        """Schedule flash step berikutnya dengan safe checking"""
        
        # =====================================================
        # GUARD CLAUSE: Jangan lanjut jika widget sedang di-destroy
        # =====================================================
        if hasattr(self, '_is_destroying') and self._is_destroying:
            print("  ⏭️ Flash cancelled - widget is destroying")
            self._cleanup_flash_timer()
            return
            
        if not hasattr(self, '_flash_timer_running') or not self._flash_timer_running:
            return
        
        # Validasi layer masih ada
        if not self._impact_layer or not self._impact_layer.isValid():
            self._cleanup_flash_timer()
            return
        
        self._flash_step += 1
        
        try:
            # Ganti style
            if self._flash_step % 2 == 0:
                # Kembali ke style normal
                if self._original_style:
                    symbol = QgsMarkerSymbol.createSimple({
                        "name": "circle",
                        "color": self._original_style.get("color", "0,160,0"),
                        "outline_color": self._original_style.get("outline", "0,0,0"),
                        "size": str(self._original_style.get("size", 4))
                    })
                else:
                    symbol = QgsMarkerSymbol.createSimple({
                        "name": "circle",
                        "color": "0,160,0",
                        "outline_color": "0,0,0",
                        "size": "4"
                    })
            else:
                # Style flashing
                symbol = QgsMarkerSymbol.createSimple({
                    "name": "circle",
                    "color": "255,255,0",
                    "outline_color": "255,0,0",
                    "size": "5"
                })
            
            self._impact_layer.renderer().setSymbol(symbol)
            self._impact_layer.triggerRepaint()
            self.canvas.refresh()
            
        except Exception as e:
            print(f"⚠️ Flash error: {e}")
            self._cleanup_flash_timer()
            return
        
        # Cek apakah selesai
        if self._flash_step >= self._flash_max:
            print("✨ Safe flash completed")
            self._cleanup_flash_timer()
            return
        
        # =====================================================
        # SCHEDULE NEXT FLASH DENGAN SAFE LAMBDA
        # =====================================================
        # Gunakan lambda yang mengecek status destroy
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(interval, lambda: self._safe_schedule_next_flash(interval))
    
    def _safe_schedule_next_flash(self, interval):
        """
        Safe wrapper untuk schedule next flash
        Mengecek status destroy sebelum lanjut
        """
        if hasattr(self, '_is_destroying') and self._is_destroying:
            print("  ⏭️ Safe flash skipped - widget is destroying")
            return
        self._schedule_next_flash(interval)
    
    
    
    def _cleanup_flash_timer(self):
        """Cleanup flash timer"""
        print("🧹 Cleaning up flash timer")
        self._flash_timer_running = False
        self._flash_step = 0
        
        # Kembalikan ke style normal
        try:
            if self._impact_layer and self._impact_layer.isValid():
                if self._original_style:
                    symbol = QgsMarkerSymbol.createSimple({
                        "name": "circle",
                        "color": self._original_style.get("color", "0,160,0"),
                        "outline_color": self._original_style.get("outline", "0,0,0"),
                        "size": str(self._original_style.get("size", 4))
                    })
                    self._impact_layer.renderer().setSymbol(symbol)
                    self._impact_layer.triggerRepaint()
                    self.canvas.refresh()
        except:
            pass
    
    def closeEvent(self, event):
        """
        Clean up resources when widget is closed
        """
        print("🚪 SectorMapWidget closeEvent")
        
        # Set flag destroying
        self._is_destroying = True
        
        # Cleanup timers
        self.cleanup_timers()
        
        # Clear all layers
        self.clear_all_layers()
        
        # Accept the close event
        event.accept()
    
    
    def hide_all_layers(self):
        """Hide all RF layers from canvas (clear features)."""
        print("🧹 Clearing all layers before new analysis...")
        
        # Hentikan flashing dulu
        self._cleanup_flash_timer()
        
        self.clear_all_layers()
        self.canvas.refresh()
        print("✅ All layers cleared")
    
    # ======================================================
    # DRAW UPPER INTERSECTION POINT
    # ======================================================

    def draw_upper_intersection(self, lat, lon):
        """
        Draw upper beam intersection point (biru).
        
        Parameters
        ----------
        lat : float
            Latitude in degrees
        lon : float
            Longitude in degrees
        """
        
        self.layer_manager.clear_layer("RF_UpperIntersection")
        
        if not self._upper_intersection_layer:
            print("draw_upper_intersection: _upper_intersection_layer is None")
            return
        
        provider = self._upper_intersection_layer.dataProvider()
        if not provider:
            print("draw_upper_intersection: provider is None")
            return
        
        point = QgsPointXY(lon, lat)
        
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        
        if provider.addFeature(feat):
            print(f"✅ Upper intersection point added: {lat:.6f}, {lon:.6f}")
        else:
            print("❌ Failed to add upper intersection point")
            return
        
        self._upper_intersection_layer.updateExtents()
        self._upper_intersection_layer.triggerRepaint()
        
        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_upper_intersection]")
        
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_upper_intersection")


    # ======================================================
    # DRAW LOWER INTERSECTION POINT
    # ======================================================

    def draw_lower_intersection(self, lat, lon):
        """
        Draw lower beam intersection point (merah).
        
        Parameters
        ----------
        lat : float
            Latitude in degrees
        lon : float
            Longitude in degrees
        """
        
        self.layer_manager.clear_layer("RF_LowerIntersection")
        
        if not self._lower_intersection_layer:
            print("draw_lower_intersection: _lower_intersection_layer is None")
            return
        
        provider = self._lower_intersection_layer.dataProvider()
        if not provider:
            print("draw_lower_intersection: provider is None")
            return
        
        point = QgsPointXY(lon, lat)
        
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        
        if provider.addFeature(feat):
            print(f"✅ Lower intersection point added: {lat:.6f}, {lon:.6f}")
        else:
            print("❌ Failed to add lower intersection point")
            return
        
        self._lower_intersection_layer.updateExtents()
        self._lower_intersection_layer.triggerRepaint()

        if hasattr(self, '_fix_z_order'):
            self._fix_z_order()
            print("✅ Z-order fixed after [draw_lower_intersection]")
            
        self.canvas.refresh()
        print("✅ Canvas refreshed after draw_lower_intersection")
        

        
    # ======================================================
    # UPDATE LEGEND
    # ======================================================

    def update_legend(self, visible_layers):
        """
        Update legend berdasarkan layer yang visible.
        
        Parameters
        ----------
        visible_layers : list
            List of layer names that are visible
        """
        # Legend sudah static, tidak perlu update
        pass
        
        
    # ======================================================
    # ZOOM TO EXTENT
    # ======================================================

    def _zoom_to_extent(self, points):
        """
        Zoom canvas to fit given points.

        Parameters
        ----------
        points : list[QgsPointXY]
            Points in WGS84
        """

        if not points:
            return

        # Convert to mercator
        from qgis.core import QgsCoordinateTransform
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsProject.instance()
        )

        mercator_points = [transform.transform(p) for p in points]

        # Calculate extent with padding
        x_coords = [p.x() for p in mercator_points]
        y_coords = [p.y() for p in mercator_points]

        padding = 500  # meters

        rect = QgsRectangle(
            min(x_coords) - padding,
            min(y_coords) - padding,
            max(x_coords) + padding,
            max(y_coords) + padding
        )

        self.canvas.setExtent(rect)
        self.canvas.refresh()

    # ======================================================
    # REFRESH
    # ======================================================

    def refresh(self):
        """
        Refresh canvas.
        """

        self.canvas.refresh()
        
    
    # ======================================================
    # FORCE REDRAW ALL LAYERS (FIXED - PAKAI SMART ZOOM)
    # ======================================================

    def force_redraw(self):
        """
        Force redraw semua layer untuk memastikan visibility.
        """
        
        print("🔄 Force redrawing all layers...")
        
        # Refresh semua layer
        layers_to_refresh = [
            self._antenna_layer,
            self._sector_layer,
            self._footprint_layer,
            self._beam_layer,
            self._los_layer,
            self._center_layer,
            self._impact_layer
        ]
        
        for layer in layers_to_refresh:
            if layer and layer.isValid():
                layer.triggerRepaint()
                layer.updateExtents()
                print(f"  - {layer.name()} refreshed")
        
        # ======================================================
        # FIX Z-ORDER (BARU)
        # ======================================================
        
        self._fix_z_order()
        
        # ======================================================
        # SMART ZOOM - PAKAI INI, BUKAN YANG LAMA
        # ======================================================
        
        self._smart_zoom()  # <-- PANGGIL SMART ZOOM
        
        self.canvas.refresh()
        print("✅ Force redraw complete")