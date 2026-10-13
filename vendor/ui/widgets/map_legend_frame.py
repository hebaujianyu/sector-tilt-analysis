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
map_legend_frame.py

QFrame based legend untuk Sector Map yang bisa di-drag.
Menampilkan legend static (hardcoded).
"""

from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush


class MapLegendFrame(QFrame):
    """
    Legend widget sebagai QFrame yang bisa di-drag.
    Menampilkan legend static (hardcoded).
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # ===== ENABLE DRAG =====
        self.drag_start_pos = None
        self.setMouseTracking(True)
        
        # Style
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 220);
                border: 1px solid #aaaaaa;
                border-radius: 4px;
            }
            QLabel {
                background: transparent;
                border: none;
                font-size: 8pt;
                padding: 2px;
            }
        """)
        
        # Setup layout
        self.setup_legend()
        
        # Set fixed width
        self.setFixedWidth(150)
        
    def setup_legend(self):
        """Setup static legend items"""
        # Hapus layout lama jika ada
        if self.layout():
            QWidget().setLayout(self.layout())
        
        # Buat layout baru
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        
        # Title
        title = QLabel("<b>射频图例</b>")
        title.setAlignment(Qt.AlignLeft)
        layout.addWidget(title)
        
        
        # Static legend items
        items = [
            # Point items
            {"label": "铁塔/天线", "color": QColor(0, 0, 0), "type": "point", "border": "white", "shape": "triangle"},  # <-- TAMBAHKAN shape
            {"label": "主波束落地(Impact)", "color": QColor(0, 160, 0), "type": "point", "border": "black"},
            {"label": "波束末端", "color": QColor(0, 255, 0), "type": "point", "border": "white"},
            {"label": "上交点(上波束)", "color": QColor(0, 0, 225), "type": "point", "border": "white"},
            {"label": "下交点(下波束)", "color": QColor(255, 0, 0), "type": "point", "border": "white"},
                        
            # Polygon items
            {"label": "覆盖足迹", "color": QColor(6, 250, 250), "type": "polygon", "border": "white"},
            {"label": "扇区", "color": QColor(255, 255, 0), "type": "polygon", "border": "yellow", "low_opacity": True},
            
            # Line items
            {"label": "中心线", "color": QColor(255, 0, 0), "type": "line"}
        ]
        
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(6)
            
            # Color box / line / polygon
            if item["type"] == "point":
                # Untuk point, gunakan kotak kecil dengan border
                box = QLabel()
                box.setFixedSize(12, 12)
                
                # Set border color berdasarkan item
                border_color = item.get("border", "black")
                box.setStyleSheet(f"""
                    background-color: {item['color'].name()};
                    border: 1px solid {border_color};
                    border-radius: 6px;
                """)
                row.addWidget(box)
                
            elif item["type"] == "line":
                # Untuk line, gunakan garis putus-putus
                line_label = QLabel("---")
                line_label.setStyleSheet(f"color: {item['color'].name()}; font-weight: bold; font-size: 14pt;")
                row.addWidget(line_label)
                
            else:  # polygon
                # Untuk polygon, gunakan kotak dengan fill dan outline
                box = QLabel()
                box.setFixedSize(12, 12)
                
                # Konversi QColor ke string rgba untuk opacity
                color = item["color"]
                border_color = item.get("border", "white")
                
                # Untuk sector dengan opacity rendah
                if item.get("low_opacity"):
                    box.setStyleSheet(f"""
                        background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 255);
                        border: 1px solid {border_color};
                    """)
                else:
                    box.setStyleSheet(f"""
                        background-color: {color.name()};
                        border: 1px solid {border_color};
                    """)
                row.addWidget(box)
            
            # Label
            label = QLabel(item["label"])
            label.setStyleSheet("font-size: 8pt;")
            row.addWidget(label)
            row.addStretch()
            
            layout.addLayout(row)
        
        # Set fixed width
        self.setFixedWidth(160)
        
    def showEvent(self, event):
        """Dipanggil saat widget ditampilkan"""
        super().showEvent(event)
        # Force update layout
        self.updateGeometry()
        self.adjustSize()
        
    def resizeEvent(self, event):
        """Dipanggil saat widget di-resize"""
        super().resizeEvent(event)
        self.updateGeometry()
    
    # ======================================================
    # DRAG HANDLING
    # ======================================================
    
    def mousePressEvent(self, event):
        """Handle mouse press untuk memulai drag"""
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move untuk drag"""
        if self.drag_start_pos is not None:
            delta = event.pos() - self.drag_start_pos
            self.move(self.pos() + delta)
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if event.button() == Qt.LeftButton and self.drag_start_pos is not None:
            self.drag_start_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)