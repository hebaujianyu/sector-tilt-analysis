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
profile_legend_frame.py

QFrame based legend untuk Visual Profile yang bisa di-drag.
Menampilkan legend static untuk beam lines.
"""

from PyQt5.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


class ProfileLegendFrame(QFrame):
    """
    Legend widget sebagai QFrame yang bisa di-drag untuk Visual Profile.
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
        self.setFixedWidth(130)
        
        
    def setup_legend(self):
        """Setup static legend items dengan garis menggunakan QFrame"""
        # Hapus layout lama jika ada
        if self.layout():
            QWidget().setLayout(self.layout())
        
        # Buat layout baru
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        
        # Title
        title = QLabel("<b>波束图例</b>")
        title.setAlignment(Qt.AlignLeft)
        layout.addWidget(title)
        

        # Static legend items - SESUAIKAN DENGAN CURVE DI terrain_profile_widget.py
        items = [
            {"label": "主波束", "color": QColor(0, 160, 0), "type": "line", "style": "solid"},     # Hijau tua (sesuai curve)
            {"label": "上波束", "color": QColor(0, 0, 255), "type": "line", "style": "dash"},     # Biru (sesuai curve)
            {"label": "下波束", "color": QColor(255, 0, 0), "type": "line", "style": "dash"}      # Merah (sesuai curve)
        ]
        
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(6)
            
            # ======================================================
            # LINE SAMPLE MENGGUNAKAN QFrame DENGAN BORDER
            # ======================================================
            line_container = QFrame()
            line_container.setFixedSize(38, 6)  # Panjang 40px, tinggi 10px
            
            if item["style"] == "solid":
                # Garis solid
                line_container.setStyleSheet(f"""
                    QFrame {{
                        background-color: transparent;
                        border: none;
                        border-bottom: 2px solid {item['color'].name()};
                    }}
                """)
            else:  # dash
                # Garis putus-putus (dash)
                line_container.setStyleSheet(f"""
                    QFrame {{
                        background-color: transparent;
                        border: none;
                        border-bottom: 2px dashed {item['color'].name()};
                    }}
                """)
            
            row.addWidget(line_container)
            
            # ======================================================
            # LABEL
            # ======================================================
            label = QLabel(item["label"])
            label.setStyleSheet("font-size: 8pt;")
            row.addWidget(label)
            row.addStretch()
            
            layout.addLayout(row)
        
        # Set fixed width
        self.setFixedWidth(130)
    
    def showEvent(self, event):
        """Dipanggil saat widget ditampilkan"""
        super().showEvent(event)
        self.updateGeometry()
        self.adjustSize()
    
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