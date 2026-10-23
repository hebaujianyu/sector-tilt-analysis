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
vertical_analysis_dialog.py

RF Vertical Analysis Dialog
UI dibuat mengikuti RF-Universe Downtilt Calculator.

Layout:

Inputs | Visual Profile
       | Sector Map
"""


import time
import gc
import math
import json
import csv
import os
from datetime import datetime  # <-- PASTIKAN INI ADA
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from qgis.core import QgsMessageLog, Qgis, QgsPointXY, QgsProject, QgsRasterLayer, QgsVectorTileLayer
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QSlider,
    QDoubleSpinBox,
    QPushButton,
    QMessageBox,
    QWidget,
    QFrame,
    QScrollArea,  # <-- TAMBAHKAN INI
    QComboBox,
    QCheckBox,
    QLineEdit,
    QSizePolicy,
    QSplitter,
    QFileDialog,
    QProgressBar,
    QTabWidget,  # <-- TAMBAHKAN INI
    QGroupBox,   # <-- TAMBAHKAN INI (untuk konsistensi)
    QSpinBox     # <-- TAMBAHKAN INI (untuk DualHandleSlider)
)

from PyQt5 import QtCore
from qgis.utils import iface
from ..widgets import TerrainProfileWidget
from ..widgets.sector_map_widget import SectorMapWidget
from ...utils.kmz_exporter import KMZExporter
from .defaults import RFDefaults  # Sesuaikan path

_PIN_ON_STYLE = (
    "QPushButton{font-size:13px; padding:0px; border:1px solid #c9a227;"
    "border-radius:3px; background:#fff8dc; color:#b8860b;}"
    "QPushButton:hover{background:#ffeeba;}"
)
_PIN_OFF_STYLE = (
    "QPushButton{font-size:13px; padding:0px; border:1px solid #bfbfbf;"
    "border-radius:3px; background:#f5f5f5; color:#8a8a8a;}"
    "QPushButton:hover{background:#e6e6e6; color:#333;}"
)


def _push_info(title, msg):
    """往 QGIS 消息栏推一条提示；无 GUI / 无 iface 环境静默跳过。"""
    try:
        if iface is not None and iface.messageBar() is not None:
            iface.messageBar().pushMessage(title, msg, level=Qgis.Info, duration=3)
    except Exception:  # nosec
        pass


def _get_store():
    """拿到 settings_store 模块（同时兼容相对导入与绝对导入两种加载方式）。"""
    try:
        from .... import settings_store as mod
        return mod
    except Exception:  # nosec
        pass
    try:
        import sector_tiltm_auto.settings_store as mod  # noqa
        return mod
    except Exception:  # nosec
        return None


def _make_default_pin(parent, tip):
    """造一个 25×25 的『设为默认』星标按钮。

    没存过默认时是灰色空心星，存过之后点亮成金色实心星。
    """
    btn = QPushButton("★", parent)
    btn.setFixedSize(25, 25)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tip)
    btn.setStyleSheet(_PIN_OFF_STYLE)
    return btn


def _flash_pin(btn, text=None):
    """把星标点亮 1.2 秒，给出『已记住』的视觉反馈。"""
    btn.setStyleSheet(_PIN_ON_STYLE)
    if text:
        btn.setText(text)
    QTimer.singleShot(1200, lambda: None)


class DualHandleSlider(QWidget):
    """
    Custom widget with two handles for min-max range selection
    """
    valueChanged = QtCore.pyqtSignal(int, int)  # (min, max)
    
    def __init__(self, parent=None, min_val=0, max_val=20, step=1):
        super().__init__(parent)
        
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
        # Min spinbox
        self.min_spin = QSpinBox()
        self.min_spin.setRange(min_val, max_val)
        self.min_spin.setSingleStep(step)
        self.min_spin.setValue(min_val)
        self.min_spin.setFixedWidth(50)
        layout.addWidget(self.min_spin)
        
        # Slider (sebagai visual, tapi sebenarnya kita pakai dua spinbox)
        # Untuk dual-handle yang sebenarnya perlu QxtSpanSlider atau custom,
        # tapi untuk sederhana kita pakai dua spinbox dengan label range
        self.range_label = QLabel(f"{min_val}° – {max_val}°")
        self.range_label.setAlignment(QtCore.Qt.AlignCenter)
        self.range_label.setStyleSheet("background: #e9eef2; border-radius: 3px; padding: 4px;")
        layout.addWidget(self.range_label)
        
        # Max spinbox
        self.max_spin = QSpinBox()
        self.max_spin.setRange(min_val, max_val)
        self.max_spin.setSingleStep(step)
        self.max_spin.setValue(max_val)
        self.max_spin.setFixedWidth(50)
        layout.addWidget(self.max_spin)
        
        # Connections
        self.min_spin.valueChanged.connect(self._on_min_changed)
        self.max_spin.valueChanged.connect(self._on_max_changed)
    
    def _on_min_changed(self, value):
        if value > self.max_spin.value():
            self.min_spin.setValue(self.max_spin.value())
        self.range_label.setText(f"{self.min_spin.value()}° – {self.max_spin.value()}°")
        self.valueChanged.emit(self.min_spin.value(), self.max_spin.value())
    
    def _on_max_changed(self, value):
        if value < self.min_spin.value():
            self.max_spin.setValue(self.min_spin.value())
        self.range_label.setText(f"{self.min_spin.value()}° – {self.max_spin.value()}°")
        self.valueChanged.emit(self.min_spin.value(), self.max_spin.value())
    
    def get_values(self):
        return self.min_spin.value(), self.max_spin.value()
    
    def set_values(self, min_val, max_val):
        self.min_spin.setValue(min_val)
        self.max_spin.setValue(max_val)



class OptimizeWorker(QObject):
    """Worker object untuk running optimasi di background thread"""
    
    progress = pyqtSignal(int, str, dict)  # (persen, status, current_result)
    finished = pyqtSignal(list)  # list of top 5 results
    cancelled = pyqtSignal()
    error = pyqtSignal(str)  # <-- TAMBAHKAN SIGNAL INI
    
    
    def __init__(self, controller, params, mech_range, elec_range, criteria, is_metric=True):
        super().__init__()
        self.controller = controller
        # =====================================================
        # TILT OPTIMIZER THREADING
        # =====================================================
                
        self.params = params
        self.mech_min, self.mech_max = mech_range
        self.elec_min, self.elec_max = elec_range
        self.criteria = criteria  # {'max_coverage': bool, 'target_distance': float, 'balanced': (min, max)}
        self.is_metric = is_metric  # <-- TAMBAHKAN INI
        self._is_cancelled = False
        
        # =====================================================
        # CACHE UNTUK HASIL ANALYSIS (TAMBAHKAN DI SINI)
        # =====================================================
        self._result_cache = {}  # key: (mech, elec) -> result
        self._total_tilt_cache = {}  # <-- TAMBAHKAN: key: total_tilt -> best_result
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_tilt_cache_hits = 0  # <-- TAMBAHKAN
        
        # =====================================================
        # RF OPTIMIZATION WEIGHTS (TAMBAHKAN DI SINI)
        # =====================================================
        from ...ui.dialogs.defaults import RFDefaults
        
        if self.is_metric:
            self.TARGET_MAX_SCORE = 1000
            self.TARGET_PENALTY_FACTOR = 10
            self.BALANCED_BASE_BONUS = RFDefaults.BALANCED_BASE_BONUS
            self.BALANCED_OPTIMAL_BONUS = RFDefaults.BALANCED_OPTIMAL_BONUS
            self.BALANCED_PENALTY_FACTOR = RFDefaults.BALANCED_PENALTY_FACTOR
            self.COVERAGE_BONUS_FACTOR = 50
            self.WIDTH_BONUS_FACTOR = 100
        else:
            # Imperial conversions
            self.TARGET_MAX_SCORE = 3280  # 1000 * 3.28
            self.TARGET_PENALTY_FACTOR = 33  # 10 * 3.28
            self.BALANCED_BASE_BONUS = RFDefaults.BALANCED_BASE_BONUS * 3.28084
            self.BALANCED_OPTIMAL_BONUS = RFDefaults.BALANCED_OPTIMAL_BONUS * 3.28084
            self.BALANCED_PENALTY_FACTOR = RFDefaults.BALANCED_PENALTY_FACTOR * 3.28084
            self.COVERAGE_BONUS_FACTOR = 164  # 50 * 3.28
            self.WIDTH_BONUS_FACTOR = 328  # 100 * 3.28
        
        # =====================================================
        # VALIDASI CRITERIA (TAMBAHKAN DI SINI)
        # =====================================================
        # Pastikan target_distance positif
        if 'target_distance' in self.criteria:
            target = self.criteria['target_distance']
            if target <= 0:
                self._log(f"Warning: target_distance={target} invalid, using default 700m", Qgis.Warning)
                self.criteria['target_distance'] = 700.0

        if 'balanced' in self.criteria:
            min_d, max_d = self.criteria['balanced']
            if min_d >= max_d or min_d < 0:
                self._log(f"Warning: balanced range [{min_d}, {max_d}] invalid, using default [200, 800]", Qgis.Warning)
                self.criteria['balanced'] = (200.0, 800.0)
                
        self._all_results = []  # Simpan SEMUA kombinasi yang dievaluasi

        
    def _get_total_tilt_range(self):
        """Calculate min and max total tilt from mech/elec ranges"""
        return self.mech_min + self.elec_min, self.mech_max + self.elec_max  

        
    # =====================================================
    # HELPER FUNCTION UNTUK SAFE FORMATTING (FINAL VERSION 2)
    # =====================================================
    def _safe_format(self, value, format_spec=""):
        """Safe formatting untuk menghindari error NoneType"""
        if value is None:
            return "None"
        
        # Jika value adalah string yang berisi "None", return "None"
        if isinstance(value, str) and value.lower() == "none":
            return "None"
        
        # Jika format_spec tidak kosong, pastikan value bisa diformat
        if format_spec:
            try:
                # Pastikan value bisa dikonversi ke float
                if isinstance(value, (int, float)):
                    return format(float(value), format_spec)
                elif isinstance(value, str):
                    # Coba parsing string ke float
                    try:
                        float_val = float(value)
                        return format(float_val, format_spec)
                    except ValueError:
                        # String bukan angka
                        return value
                else:
                    # Tipe lain, coba konversi
                    float_val = float(value)
                    return format(float_val, format_spec)
            except (TypeError, ValueError, AttributeError) as e:
                # Log error untuk debugging (tapi jangan crash)
                error_str = str(e)
                if "format" not in error_str and "NoneType" not in error_str:
                    print(f"⚠️ _safe_format error: {error_str[:100]} for value={value}, format={format_spec}")
                # Fallback ke string biasa
                return str(value)
        else:
            # Tanpa format spec, langsung return string
            return str(value)
    

    def _log(self, message, level=Qgis.Info):
        """Log message to console and QGIS message log"""
        # Always print to console for development
        print(f"[OptimizeWorker] {message}")
        
        # Also log to QGIS with appropriate level
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                str(message),
                "扇区Tilt分析",
                level
            )
        except Exception:  # nosec
            pass  # Fail silently if QGIS not available
    
    def run(self):
        """
        Main optimization loop - dengan pengecekan cancelled yang lebih baik
        """
        try:
            self._log(f"OptimizeWorker.run() STARTED on thread: {QThread.currentThread()}")
            self._log(f"Controller: {self.controller}")
            
            # Test controller call immediately
            self._log("Testing controller with dummy params...")
            try:
                test_params = self.params.copy()
                test_params["mech"] = 0
                test_params["elec"] = 0
                test_result = self.controller.run_analysis(test_params)
                self._log(f"Test controller call result: {test_result is not None}")
            except Exception as e:
                self._log(f"Test controller call EXCEPTION: {e}", Qgis.Critical)
                import traceback
                traceback.print_exc()
            
            results = []
            total_iterations = (self.mech_max - self.mech_min + 1) * (self.elec_max - self.elec_min + 1)
            self._log(f"total_iterations = {total_iterations}")
            
            current_iter = 0
            self._log(f"current_iter = {current_iter}")
            
            # =====================================================
            # TIMEOUT DAN ESTIMASI WAKTU (FIXED - HIGH PRECISION)
            # =====================================================
            
            self._log("Setting up perf_counter...")
            # Gunakan perf_counter untuk akurasi tinggi
            self._perf_start = time.perf_counter()
            self._log(f"_perf_start = {self._perf_start}")
            
            start_time = time.time()  # tetap pakai time.time() untuk timeout
            self._log(f"start_time = {start_time}")
            
            last_log_time = start_time
            first_iter_time = None
            timeout_seconds = 300  # 5 menit timeout
            self._log("Timeout setup complete")
            
            # Catat juga waktu real untuk perbandingan
            now = datetime.now()
            self._log(f"Worker started at {now.strftime('%H:%M:%S.%f')[:-3]}")
            self._log(f"Performance counter: {self._perf_start:.6f}")
            
            # =====================================================
            # ENGINE WARMUP - PRODUCTION READY (FIX V4)
            # =====================================================
            self._log("Starting warmup preparation...")
            
            # Reset cache statistics di awal setiap optimasi
            self._result_cache = {}
            self._cache_hits = 0
            self._cache_misses = 0
            self._log("Cache reset complete")
            
            self._log("🔄 Warming up engine...")

            
            # Tentukan kombinasi warmup berdasarkan range yang ada
            warmup_combinations = []
            self._log(f"mech_min={self.mech_min}, mech_max={self.mech_max}, elec_max={self.elec_max}")

            # Warmup beberapa mechanical tilt dengan electrical tilt 0
            # Gunakan 5 nilai pertama dalam range, atau kurang jika range lebih kecil
            warmup_mech_values = []
            for m in range(self.mech_min, self.mech_max + 1):
                if len(warmup_mech_values) < 5:  # Ambil max 5 nilai
                    warmup_mech_values.append(m)
                else:
                    break

            for m in warmup_mech_values:
                warmup_combinations.append((m, 0))
                self._log(f"Added warmup: M{m} E0")

            # Warmup beberapa kombinasi dengan electrical tilt kecil
            # Gunakan 3 mechanical pertama dengan electrical 1-2
            warmup_mech_small = warmup_mech_values[:3]  # Ambil 3 pertama
            for m in warmup_mech_small:
                for e in range(1, min(3, self.elec_max + 1)):  # E1-E2
                    if e <= self.elec_max:
                        warmup_combinations.append((m, e))
                        self._log(f"Added warmup: M{m} E{e}")
            
            # Hapus duplikat dengan convert ke set lalu kembali ke list
            warmup_combinations = list(set(warmup_combinations))
            self._log(f"After dedup: {len(warmup_combinations)} combinations")
            
            # Urutkan berdasarkan mechanical lalu electrical
            warmup_combinations.sort()
            self._log(f"Sorted warmup combinations: {warmup_combinations}")
            
            self._log(f"Running {len(warmup_combinations)} warmup combinations...")
            
            for i, (w_mech, w_elec) in enumerate(warmup_combinations):
                self._log(f"Warmup {i+1}/{len(warmup_combinations)}: M{w_mech}° E{w_elec}°")
                try:
                    test_params = self.params.copy()
                    test_params["mech"] = w_mech
                    test_params["elec"] = w_elec
                    
                    self._log(f"Calling controller.run_analysis() for warmup...")
                    # Jalankan analysis
                    test_result = self.controller.run_analysis(test_params)
                    self._log(f"Controller returned for warmup: {type(test_result)}")
                    
                    # Validasi result dengan safe checking
                    if test_result is not None and isinstance(test_result, dict):
                        main_dist = test_result.get("main_intersection_distance")
                        impact_dist = test_result.get("impact_distance")
                        distance = main_dist if main_dist is not None else impact_dist
                        
                        # Simpan ke cache
                        cache_key = (w_mech, w_elec)
                        self._result_cache[cache_key] = test_result
                        self._cache_misses += 1
                        
                        # Log dengan safe formatting
                        dist_str = self._safe_format(distance, '.0f') if distance else 'None'
                        self._log(f"Warmup M{w_mech}° E{w_elec}°: impact={dist_str}m [CACHED]")
                    else:
                        self._log(f"Warmup M{w_mech}° E{w_elec}° returned invalid result: {test_result}", Qgis.Warning)
                        
                except Exception as e:
                    # Log error tapi jangan crash
                    error_msg = str(e) if e is not None else "Unknown error"
                    self._log(f"Warmup error M{w_mech}° E{w_elec}°: {error_msg}", Qgis.Warning)
                    import traceback
                    traceback.print_exc()
                
                # Force flush print buffer - AMAN
                import sys
                try:
                    if sys.stdout is not None:
                        sys.stdout.flush()
                except (AttributeError, IOError):
                    pass  # Abaikan jika stdout tidak bisa di-flush
            
            self._log(f"Warmup complete: {self._cache_misses} combinations cached")
            
            # =====================================================
            # LOG KONFIGURASI OPTIMIZER (TAMBAHKAN DI SINI)
            # =====================================================
            print("\n" + "="*60)
            print("🔧 TILT OPTIMIZER CONFIGURATION")
            print("="*60)
            self._log(f"Mechanical tilt range: [{self.mech_min}° to {self.mech_max}°] step 1°")
            self._log(f"Electrical tilt range: [{self.elec_min}° to {self.elec_max}°] step 1°")
            self._log(f"Optimization criteria:")
            
            if self.criteria.get('max_coverage', False):
                print(f"   • Maximum Coverage: Enabled")
            
            if 'target_distance' in self.criteria:
                target = self.criteria['target_distance']
                print(f"   • Target Distance: {target:.0f}m")
            
            if 'balanced' in self.criteria:
                min_d, max_d = self.criteria['balanced']
                print(f"   • Balanced Coverage: {min_d:.0f}m – {max_d:.0f}m")
            
            self._log(f"Total iterations: {total_iterations}")
            print("="*60 + "\n")
            
            # Gunakan counter untuk membatasi log agar tidak spam
            log_interval = max(1, total_iterations // 20)  # Log ~20 kali saja
            
            # =====================================================
            # ANALISIS TERRAIN UNTUK SKIP BEAM NEGATIF (TAMBAHKAN)
            # =====================================================
            # Cek apakah ada terrain yang lebih tinggi dari antena
            antenna_height = self.params.get("height", 40)
            # Asumsikan terrain maksimum bisa didapat dari result pertama atau dari data
            # Kita akan cek di loop pertama, tapi untuk efisiensi kita skip dulu semua negatif
            # karena dari log sebelumnya, terrain selalu lebih rendah dari antena (771 vs 811)
            self._log(f"Terrain analysis: Antenna at {antenna_height}m above ground")
            self._log(f"   → Skipping negative mechanical tilts (no terrain above antenna)")
            
            # =====================================================
            # LOG NILAI RANGE YANG AKAN DIUJI
            # =====================================================
            self._log(f"Testing all electrical tilt combinations from {self.elec_min}° to {self.elec_max}°")
            self._log(f"Testing all mechanical tilt combinations from {self.mech_min}° to {self.mech_max}°")
            
            # =====================================================
            # OPTIMIZATION MODE DISPATCH
            # =====================================================
            mode = self.params.get("optimization_mode", 1)  # Default ke Smart (1)
            
                        
            # =====================================================
            # VALIDASI MODE - Fallback jika mode tidak dikenal
            # =====================================================
            if mode not in [0, 1, 2]:
                self._log(f"Unknown optimization mode: {mode}, falling back to SMART mode (1)", Qgis.Warning)
                mode = 1
            
            if mode == 2:  # FAST MODE - Mechanical only
                self._log(f"Running FAST mode: Mechanical tilt only (elec=0)")
                for mech in range(self.mech_min, self.mech_max + 1):
                    if self._is_cancelled:
                        print("🛑 Optimization cancelled by user")
                        self.cancelled.emit()
                        return
                    
                    if mech < 0:
                        continue
                    
                    elec = 0
                    self._process_single_combination(mech, elec, results, current_iter, 
                                                     total_iterations, log_interval, 
                                                     last_log_time, first_iter_time, start_time)
                    
            elif mode == 0:  # PRECISE MODE - Total tilt only
                self._log(f"Running PRECISE mode: Total tilt only (21 iterations)")
                self._run_total_tilt_only(results, current_iter, total_iterations, 
                                          log_interval, last_log_time, first_iter_time, start_time)
                
            else:  # SMART MODE - Total tilt + top 5 distributions (default)
                self._log(f"Running SMART mode: Total tilt first + top 5 distributions")
                self._run_smart_optimization(results, current_iter, total_iterations, 
                                               log_interval, last_log_time, first_iter_time, start_time,
                                               store_result=True)  # <-- TAMBAHKAN store_result=True
            
            # Sort and get top 5
            results.sort(key=lambda x: x['score'], reverse=True)
            top5 = results[:5]
            
            # =====================================================
            # TAMPILKAN RINGKASAN HASIL TERBAIK - DENGAN FORMAT LEBIH BAIK
            # =====================================================
            if top5:
                print("\n" + "="*60)
                print("🏆 OPTIMIZATION COMPLETE - TOP 5 RESULTS")
                print("="*60)
                for i, res in enumerate(top5[:5]):
                    mech = res['mech']
                    elec = res['elec']
                    dist = res['distance']
                    score = res['score']
                    lower = res.get('lower_footprint')
                    upper = res.get('upper_footprint')
                    
                    # Format jarak (main beam)
                    if dist >= 1000:
                        dist_str = f"{dist/1000:.2f} km"
                    else:
                        dist_str = f"{dist:.0f} m"
                    
                    # Format footprint jika ada dan valid
                    footprint_str = ""
                    if lower is not None and upper is not None and lower > 0 and upper > 0:
                        # Format lower
                        if lower >= 1000:
                            lower_str = f"{lower/1000:.2f} km"
                        else:
                            lower_str = f"{lower:.0f} m"
                        
                        # Format upper
                        if upper >= 1000:
                            upper_str = f"{upper/1000:.2f} km"
                        else:
                            upper_str = f"{upper:.0f} m"
                        
                        footprint_str = f" [FP: {lower_str} – {upper_str}]"
                    
                    # Tambahkan indikator target
                    target = self.criteria.get('target_distance', 700)
                    deviation = abs(dist - target)
                    target_indicator = ""
                    if deviation <= 100:
                        target_indicator = " ✓"
                    elif deviation <= 300:
                        target_indicator = " ∼"
                    else:
                        target_indicator = " ✗"
                    
                    self._log(f"{i+1}. M{mech}° E{elec}° → {dist_str}{footprint_str} (score: {score:.0f}){target_indicator}")
                print("="*60 + "\n")
            else:
                self._log("No valid results found during optimization", Qgis.Warning)
            

            # =====================================================
            # TAMPILKAN STATISTIK CACHE (FINAL VERSION 2)
            # =====================================================
            total_cache = self._cache_hits + self._cache_misses
            if total_cache > 0:
                hit_rate = (self._cache_hits / total_cache) * 100
                
                # Hitung potensi maksimal cache
                total_possible = (self.mech_max - self.mech_min + 1) * (self.elec_max - self.elec_min + 1)
                coverage = (len(self._result_cache) / total_possible) * 100
                
                self._log(f"Cache Performance Summary:")
                self._log(f"   • Regular cache hits: {self._cache_hits}")
                self._log(f"   • Regular cache misses: {self._cache_misses}")
                self._log(f"   • Total tilt cache hits: {self._total_tilt_cache_hits}")
                self._log(f"   • Hit Rate: {hit_rate:.1f}%")
                self._log(f"   • Cache Size: {len(self._result_cache)} unique combinations")
                self._log(f"   • Coverage: {coverage:.1f}% of total possible ({total_possible})")
                

                # Analisis performa
                if hit_rate > 50:
                    self._log(f"   ✅ Excellent cache performance!")
                elif hit_rate > 30:
                    self._log(f"   👍 Good cache performance")
                elif hit_rate > 10:
                    self._log(f"   ⚠️ Low cache hit rate. Consider increasing warmup combinations.", Qgis.Warning)
                else:
                    self._log(f"   ❌ Very low cache hit rate. Warmup strategy needs improvement.", Qgis.Warning)
            else:
                self._log(f"Cache Statistics: No cache operations performed")
            
            # Emit finished
            self.finished.emit(top5)
            
            # =====================================================
            # HITUNG WAKTU DENGAN DUA METODE UNTUK VERIFIKASI
            # =====================================================

            
            perf_end = time.perf_counter()
            time_end = time.time()
            
            perf_duration = perf_end - self._perf_start
            time_duration = time_end - start_time
            
            current_time = datetime.now()
            time_str = current_time.strftime("%H:%M:%S")
            ms_str = f"{current_time.microsecond//1000:03d}"
            
            self._log(f"Optimization completed:")
            self._log(f"   • time.time() duration: {time_duration:.3f} seconds")
            self._log(f"   • perf_counter duration: {perf_duration:.3f} seconds")
            self._log(f"   • Finished at: {time_str}.{ms_str}")
            
            # Tampilkan perbedaan jika ada
            diff = abs(perf_duration - time_duration)
            if diff > 0.1:
                self._log(f"   ⚠️ Warning: Time measurement discrepancy: {diff:.3f}s", Qgis.Warning)
            
            # Simpan ke attribute untuk referensi
            self._last_run_time = perf_duration
            
        except Exception as e:
            self._log(f"CRITICAL ERROR in OptimizeWorker.run(): {e}", Qgis.Critical)
            import traceback
            traceback.print_exc()
            # Emit error signal
            self.error.emit(str(e))
            self.finished.emit([])
        
        
    def _calculate_score(self, distance, lower_footprint=None, upper_footprint=None):
        """
        Calculate score based on selected criteria
        Supports both metric and imperial units
        
        RF ENHANCED: 
        - Balanced coverage dengan bonus bertingkat (parabolic)
        - Target distance dengan Gaussian scoring
        - Maximum coverage bonus proporsional
        """
        score = 0
        
        # Validasi distance
        if distance is None or distance <= 0:
            return 0
        
        self._log(f"Calculating score for distance={distance:.0f}m")
        
        # =====================================================
        # FAKTOR KONVERSI UNTUK IMPERIAL
        # =====================================================
        # Kita akan menggunakan rasio untuk menyesuaikan parameter
        # 1 meter ≈ 3.28 feet
        # 1 km ≈ 0.62 miles
        
        # Tentukan faktor skala untuk parameter
        if self.is_metric:
            # Parameter dalam meter
            TARGET_MAX_SCORE = 1000
            TARGET_PENALTY_FACTOR = 10
            BALANCED_BONUS = 500
            BALANCED_PENALTY_FACTOR = 5
            COVERAGE_BONUS_FACTOR = 50
            WIDTH_BONUS_FACTOR = 100
        else:
            # Parameter dalam feet
            TARGET_MAX_SCORE = 3280  # 1000m * 3.28
            TARGET_PENALTY_FACTOR = 33  # 10m * 3.28
            BALANCED_BONUS = 1640  # 500m * 3.28
            BALANCED_PENALTY_FACTOR = 16.4  # 5m * 3.28
            COVERAGE_BONUS_FACTOR = 164  # 50m * 3.28
            WIDTH_BONUS_FACTOR = 328  # 100m * 3.28
        

        # =====================================================
        # 1. TARGET DISTANCE (GAUSSIAN SCORING)
        # =====================================================
        if 'target_distance' in self.criteria:
            target = self.criteria['target_distance']
            deviation = abs(distance - target)
            
            # Gaussian scoring: smooth penalty, tidak linear
            # sigma = target/4 (agar di deviation=target, score ~ 1% dari max)
            target_score = self.TARGET_MAX_SCORE * math.exp(-(deviation**2) / (2 * (target/4)**2))
            score += target_score
            self._log(f"  🎯 Target {target:.0f}m: dev={deviation:.0f}m, +{target_score:.1f}")
        
        # =====================================================
        # 2. BALANCED COVERAGE - BONUS BERTINGKAT (PARABOLIC)
        # =====================================================
        if 'balanced' in self.criteria:
            min_d, max_d = self.criteria['balanced']
            
            if min_d <= distance <= max_d:
                # Hitung posisi relatif dalam range (0 = min, 1 = max)
                relative_pos = (distance - min_d) / (max_d - min_d)
                
                # =====================================================
                # FUNGSI PARABOLA: 4 * x * (1 - x)
                # Nilai maksimum 1 di tengah (relative_pos = 0.5)
                # Nilai minimum 0 di ujung (relative_pos = 0 atau 1)
                # =====================================================
                parabola_factor = 4 * relative_pos * (1 - relative_pos)
                
                # Balanced bonus = base + (optimal - base) * parabola_factor
                balanced_bonus = self.BALANCED_BASE_BONUS + (self.BALANCED_OPTIMAL_BONUS - self.BALANCED_BASE_BONUS) * parabola_factor
                
                score += balanced_bonus
                self._log(f"  ⚖️ Balanced [{min_d:.0f}-{max_d:.0f}m]: pos={relative_pos:.2f}, para={parabola_factor:.2f}, +{balanced_bonus:.1f}")
            else:
                # Penalty eksponensial jika di luar range
                if distance < min_d:
                    # Exponential penalty: semakin jauh dari range, penalty makin besar
                    distance_out = min_d - distance
                    penalty = self.BALANCED_PENALTY_FACTOR * (math.exp(distance_out / 200) - 1)
                    self._log(f"  ⚖️ Below range ({distance_out:.0f}m out): -{penalty:.1f}")
                else:
                    distance_out = distance - max_d
                    penalty = self.BALANCED_PENALTY_FACTOR * (math.exp(distance_out / 200) - 1)
                    self._log(f"  ⚖️ Above range ({distance_out:.0f}m out): -{penalty:.1f}")
                score -= penalty
        
        # =====================================================
        # 3. MAXIMUM COVERAGE (LINEAR BONUS)
        # =====================================================
        if self.criteria.get('max_coverage', False):
            # Bonus linear untuk coverage luas
            coverage_bonus = distance / self.COVERAGE_BONUS_FACTOR
            score += coverage_bonus
            self._log(f"  📏 Coverage bonus: +{coverage_bonus:.1f}")
            
            # Bonus tambahan untuk footprint width (beamwidth coverage)
            if lower_footprint and upper_footprint and upper_footprint > lower_footprint:
                footprint_width = upper_footprint - lower_footprint
                width_bonus = footprint_width / self.WIDTH_BONUS_FACTOR
                score += width_bonus
                self._log(f"  📐 Footprint width: +{width_bonus:.1f}")
        
        self._log(f"  ✅ Final score: {score:.1f}")
        return max(0, score)  # Non-negative score
    
    
    
    def _run_smart_optimization(self, results, current_iter, total_iterations, 
                                 log_interval, last_log_time, first_iter_time, start_time,
                                 store_result=True):
        """
        Smart optimization strategy with total tilt caching:
        1. Iterate all TOTAL TILT values (mech+elec) - gunakan cache
        2. Take top 5 total tilts
        3. Explore all distributions for top 5 total tilts - gunakan existing cache
        
        Parameters
        ----------
        store_result : bool
            Whether to store results in the results list
        """
        self._log("SMART MODE: Optimizing by total tilt first (with caching)...")
        
        # Step 1: Get total tilt range
        total_min = self.mech_min + self.elec_min
        total_max = self.mech_max + self.elec_max
        self._log(f"Total tilt range: {total_min}° to {total_max}°")
        
        # Store results for each total tilt (sampling)
        total_tilt_samples = []
        
        # Step 2: Sample each total tilt once (gunakan cache)
        for total in range(total_min, total_max + 1):
            if self._is_cancelled:
                self._log("Optimization cancelled by user")
                self.cancelled.emit()
                return
            
            # Cek cache total tilt dulu
            if total in self._total_tilt_cache:
                # Gunakan dari cache
                cached = self._total_tilt_cache[total]
                self._total_tilt_cache_hits += 1
                self._log(f"  📦 TOTAL TILT CACHE HIT: Total {total}° → M{cached['mech']}° E{cached['elec']}° (score: {cached['score']:.0f})")
                
                total_tilt_samples.append({
                    'total': total,
                    'mech': cached['mech'],
                    'elec': cached['elec'],
                    'distance': cached['distance'],
                    'lower_footprint': cached.get('lower_footprint'),  # <-- TAMBAHKAN
                    'upper_footprint': cached.get('upper_footprint'),  # <-- TAMBAHKAN
                    'score': cached['score']
                })
                
                # Update progress counter (estimasi)
                current_iter += 1
                continue
            
            # Jika tidak ada di cache, cari kombinasi terbaik untuk total tilt ini
            best_for_total = None
            best_score = -1
            best_result_dict = None  # <-- TAMBAHKAN UNTUK MENYIMPAN RESULT LENGKAP
            
            # Coba beberapa distribusi untuk total tilt ini
            # Prioritaskan electrical tilt (bisa remote)
            test_combinations = []
            
            # 1. Coba dengan electrical maksimal
            elec1 = min(total, self.elec_max)
            mech1 = total - elec1
            if self.mech_min <= mech1 <= self.mech_max and self.elec_min <= elec1 <= self.elec_max:
                test_combinations.append((mech1, elec1))
            
            # 2. Coba dengan mechanical minimal
            mech2 = max(self.mech_min, total - self.elec_max)
            elec2 = total - mech2
            if self.mech_min <= mech2 <= self.mech_max and self.elec_min <= elec2 <= self.elec_max:
                if (mech2, elec2) not in test_combinations:
                    test_combinations.append((mech2, elec2))
            
            # 3. Coba dengan electrical minimal
            elec3 = max(self.elec_min, total - self.mech_max)
            mech3 = total - elec3
            if self.mech_min <= mech3 <= self.mech_max and self.elec_min <= elec3 <= self.elec_max:
                if (mech3, elec3) not in test_combinations:
                    test_combinations.append((mech3, elec3))
            
            # 4. Coba distribusi tengah (jika ada)
            if len(test_combinations) < 3:
                mid_mech = (self.mech_min + self.mech_max) // 2
                mid_elec = total - mid_mech
                if self.mech_min <= mid_mech <= self.mech_max and self.elec_min <= mid_elec <= self.elec_max:
                    if (mid_mech, mid_elec) not in test_combinations:
                        test_combinations.append((mid_mech, mid_elec))
            
            self._log(f"  Testing total tilt {total}° with {len(test_combinations)} distributions:")
            
            for mech, elec in test_combinations:
                self._log(f"    Testing M{mech}° E{elec}°")
                
                result_dict = self._process_single_combination(
                    mech, elec, results, current_iter, total_iterations, 
                    log_interval, last_log_time, first_iter_time, start_time,
                    store_result=False  # Jangan simpan ke results dulu
                )
                
                if result_dict and 'score' in result_dict:
                    score = result_dict['score']
                    if score > best_score:
                        best_score = score
                        # =====================================================
                        # SIMPAN SEMUA DATA DARI result_dict (PERBAIKAN)
                        # =====================================================
                        best_for_total = {
                            'mech': mech,
                            'elec': elec,
                            'distance': result_dict['distance'],
                            'lower_footprint': result_dict.get('lower_footprint'),  # <-- SEKARANG ADA!
                            'upper_footprint': result_dict.get('upper_footprint'),  # <-- SEKARANG ADA!
                            'score': score
                        }
                        best_result_dict = result_dict  # <-- SIMPAN RESULT LENGKAP
                
                # Update counters
                if result_dict:
                    current_iter = result_dict.get('current_iter', current_iter)
                    last_log_time = result_dict.get('last_log_time', last_log_time)
                    first_iter_time = result_dict.get('first_iter_time', first_iter_time)
            
            # Simpan yang terbaik ke cache - DENGAN FOOTPRINT LENGKAP
            if best_for_total:
                self._total_tilt_cache[total] = best_for_total
                self._log(f"  ✅ Cached total tilt {total}°: M{best_for_total['mech']}° E{best_for_total['elec']}° (score: {best_for_total['score']:.0f})")
                
                total_tilt_samples.append({
                    'total': total,
                    'mech': best_for_total['mech'],
                    'elec': best_for_total['elec'],
                    'distance': best_for_total['distance'],
                    'lower_footprint': best_for_total.get('lower_footprint'),  # <-- TAMBAHKAN
                    'upper_footprint': best_for_total.get('upper_footprint'),  # <-- TAMBAHKAN
                    'score': best_for_total['score']
                })
        
        # Step 3: Sort by score and get top 5 total tilts
        total_tilt_samples.sort(key=lambda x: x['score'], reverse=True)
        top_total_tilts = total_tilt_samples[:5]
        
        self._log(f"Top 5 TOTAL TILT candidates (cache hits: {self._total_tilt_cache_hits}):")
        for i, tt in enumerate(top_total_tilts):
            self._log(f"  {i+1}. Total {tt['total']}° (M{tt['mech']}° E{tt['elec']}°) → {tt['distance']:.0f}m (score: {tt['score']:.0f})")
        

        # Step 4: For each top total tilt, explore all distributions
        self._log(f"Exploring all distributions for top 5 total tilts...")
        for tt_idx, tt in enumerate(top_total_tilts):
            total = tt['total']
            self._log(f"  [{tt_idx+1}] Total tilt {total}°:")
            
            # =====================================================
            # INISIALISASI VARIABEL UNTUK SETIAP TOTAL TILT (TAMBAHKAN DI SINI)
            # =====================================================
            best_score_so_far = -1
            best_result = None
            
            # Generate all valid (mech, elec) pairs for this total
            for mech in range(self.mech_min, self.mech_max + 1):
                if self._is_cancelled:
                    self._log("Optimization cancelled by user")
                    self.cancelled.emit()
                    return
                
                elec = total - mech
                if self.elec_min <= elec <= self.elec_max:
                    # =====================================================
                    # CEK CACHE TOTAL TILT - PASTIKAN KONSISTENSI
                    # =====================================================
                    if total in self._total_tilt_cache:
                        # Gunakan hasil dari cache untuk semua distribusi total tilt yang sama
                        cached = self._total_tilt_cache[total]
                        self._total_tilt_cache_hits += 1
                        
                        self._log(f"    📦 TOTAL TILT CACHE: M{mech}° E{elec}° menggunakan hasil dari M{cached['mech']}° E{cached['elec']}°")
                        
                        # Buat result dictionary dengan mech/elec yang sesuai
                        cached_result = {
                            'mech': mech,
                            'elec': elec,
                            'distance': cached['distance'],
                            'lower_footprint': cached.get('lower_footprint'),  # <-- FOOTPRINT SEKARANG ADA!
                            'upper_footprint': cached.get('upper_footprint'),  # <-- FOOTPRINT SEKARANG ADA!
                            'score': cached['score']
                        }
                        
                        # Update progress counter
                        current_iter += 1
                        
                        # Simpan ke results jika store_result=True
                        if store_result:
                            results.append(cached_result)
                        
                        # Update best so far
                        if cached_result['score'] > best_score_so_far:
                            best_score_so_far = cached_result['score']
                            best_result = cached_result
                        
                        continue
                    
                    # Jika tidak ada di cache, proses seperti biasa
                    self._log(f"    Testing M{mech}° E{elec}°")
                    
                    result_dict = self._process_single_combination(
                        mech, elec, results, current_iter, total_iterations, 
                        log_interval, last_log_time, first_iter_time, start_time,
                        store_result=True
                    )
                    
                    if result_dict:
                        current_iter = result_dict.get('current_iter', current_iter)
                        last_log_time = result_dict.get('last_log_time', last_log_time)
                        first_iter_time = result_dict.get('first_iter_time', first_iter_time)
                        
                        # Update best so far
                        if 'score' in result_dict and result_dict['score'] > best_score_so_far:
                            best_score_so_far = result_dict['score']
                            best_result = result_dict
    
    
    def _run_total_tilt_only(self, results, current_iter, total_iterations, 
                              log_interval, last_log_time, first_iter_time, start_time):
        """
        Precise mode - iterasi total tilt dengan distribusi yang bervariasi
        BUKAN hanya electrical tilt saja!
        """
        self._log("PRECISE MODE: Optimizing by total tilt with varied distributions...")
        
        # Step 1: Get total tilt range
        total_min = self.mech_min + self.elec_min
        total_max = self.mech_max + self.elec_max
        self._log(f"Total tilt range: {total_min}° to {total_max}°")
        
        # Step 2: Sample each total tilt dengan distribusi yang bervariasi
        for total in range(total_min, total_max + 1):
            if self._is_cancelled:
                self._log("Optimization cancelled by user")
                self.cancelled.emit()
                return
            
            # =====================================================
            # GENERATE BEBERAPA DISTRIBUSI UNTUK SETIAP TOTAL TILT
            # =====================================================
            
            # List untuk menyimpan kombinasi yang akan diuji
            combinations_to_test = []
            
            # 1. Coba dengan mechanical minimal (electrical maksimal)
            elec1 = min(total, self.elec_max)
            mech1 = total - elec1
            if self.mech_min <= mech1 <= self.mech_max and self.elec_min <= elec1 <= self.elec_max:
                combinations_to_test.append((mech1, elec1))
            
            # 2. Coba dengan electrical minimal (mechanical maksimal)
            mech2 = min(total, self.mech_max)
            elec2 = total - mech2
            if self.mech_min <= mech2 <= self.mech_max and self.elec_min <= elec2 <= self.elec_max:
                if (mech2, elec2) not in combinations_to_test:
                    combinations_to_test.append((mech2, elec2))
            
            # 3. Coba dengan distribusi tengah (jika ada)
            if len(combinations_to_test) < 3:
                # Coba mechanical di tengah range
                mid_mech = (self.mech_min + self.mech_max) // 2
                mid_elec = total - mid_mech
                if self.mech_min <= mid_mech <= self.mech_max and self.elec_min <= mid_elec <= self.elec_max:
                    if (mid_mech, mid_elec) not in combinations_to_test:
                        combinations_to_test.append((mid_mech, mid_elec))
            
            # 4. Jika masih kurang, coba variasi lain
            if len(combinations_to_test) < 3:
                # Coba mechanical = 2
                mech3 = 2
                elec3 = total - mech3
                if self.mech_min <= mech3 <= self.mech_max and self.elec_min <= elec3 <= self.elec_max:
                    if (mech3, elec3) not in combinations_to_test:
                        combinations_to_test.append((mech3, elec3))
            
            self._log(f"  Testing total tilt {total}° with {len(combinations_to_test)} distributions:")
            
            for mech, elec in combinations_to_test:
                self._log(f"    Testing M{mech}° E{elec}°")
                
                # Process this combination
                result_dict = self._process_single_combination(
                    mech, elec, results, current_iter, total_iterations, 
                    log_interval, last_log_time, first_iter_time, start_time,
                    store_result=True
                )
                
                if result_dict:
                    current_iter = result_dict.get('current_iter', current_iter)
                    last_log_time = result_dict.get('last_log_time', last_log_time)
                    first_iter_time = result_dict.get('first_iter_time', first_iter_time)
        
        self._log(f"PRECISE mode completed: {total_max - total_min + 1} total tilts tested")
    
    
    def _process_single_combination(self, mech, elec, results, current_iter, 
                                     total_iterations, log_interval, last_log_time, 
                                     first_iter_time, start_time, store_result=True):
        """
        Process a single (mech, elec) combination
        Returns dict with updated counters if successful, None otherwise
        """
        # Cek cancelled
        if self._is_cancelled:
            return None
            
        # =====================================================
        # PERIODIC GARBAGE COLLECTION (every 50 iterations)
        # =====================================================
        if current_iter > 0 and current_iter % 50 == 0:
            import gc
            collected = gc.collect()
            self._log(f"🧹 Periodic GC: collected {collected} objects") 

            
        # =====================================================
        # VALIDASI CONTROLLER DAN DEM LAYER
        # =====================================================
        if self.controller is None:
            self._log("ERROR: Controller is None - cannot run analysis", Qgis.Critical)
            return None
            
        # Cek apakah DEM layer masih tersedia
        if hasattr(self.controller, 'dem_layer') and self.controller.dem_layer is None:
            self._log("ERROR: DEM layer is not available", Qgis.Critical)
            return None
            
        cache_key = (mech, elec)
        result = None
        
        # Cek cache
        if cache_key in self._result_cache:
            result = self._result_cache[cache_key]
            self._cache_hits += 1
            if self._cache_hits % 5 == 0 or current_iter % log_interval == 0:
                self._log(f"📦 CACHE HIT: M{mech}° E{elec}° (hit #{self._cache_hits})")
        else:
            # Run analysis
            self.params["mech"] = mech
            self.params["elec"] = elec
            
            try:
                iter_start = time.time()
                result = self.controller.run_analysis(self.params)
                iter_time = time.time() - iter_start
                
                if result and isinstance(result, dict):
                    distance = result.get("main_intersection_distance") or result.get("impact_distance")
                    if distance and distance > 0:
                        self._result_cache[cache_key] = result
                        self._cache_misses += 1
                        
                        if first_iter_time is None:
                            first_iter_time = iter_time
                            self._log(f"First iteration took {iter_time:.2f}s - estimating remaining...")
                        
                        if current_iter % log_interval == 0:
                            self._log(f"📦 CACHE SAVED: M{mech}° E{elec}° (took {iter_time:.2f}s)")
            except Exception as e:
                self._log(f"Error at mech={mech}, elec={elec}: {str(e)[:100]}", Qgis.Warning)
                current_iter += 1
                return {
                    'current_iter': current_iter,
                    'last_log_time': last_log_time
                }
        
        if result is None:
            current_iter += 1
            return {
                'current_iter': current_iter,
                'last_log_time': last_log_time
            }
        
        # Extract distance
        main_intersection = result.get("main_intersection_distance")
        impact_distance = result.get("impact_distance")
        distance = main_intersection if main_intersection is not None else impact_distance
        
        if distance is None or distance <= 0:
            current_iter += 1
            return {
                'current_iter': current_iter,
                'last_log_time': last_log_time
            }
        
        # =====================================================
        # AMBIL FOOTPRINT DARI RESULT
        # =====================================================
        lower = result.get("lower_intersection_distance")
        upper = result.get("upper_intersection_distance")
        
        # Calculate score
        score = self._calculate_score(distance, lower, upper)
        
        # =====================================================
        # YANG BENAR: GUNAKAN BLOCK INI, HAPUS YANG DI ATASNYA
        # =====================================================
        if store_result:
            result_entry = {
                'mech': mech,
                'elec': elec,
                'distance': distance,
                'lower_footprint': lower,
                'upper_footprint': upper,
                'score': score
            }
            results.append(result_entry)
            
            # =====================================================
            # TAMBAHKAN: Simpan juga ke _all_results
            # =====================================================
            if hasattr(self, '_all_results'):
                self._all_results.append(result_entry)
                
        # Update progress
        current_iter += 1
        percent = int(current_iter * 100 / total_iterations)
        
        # Progress reporting
        current_time = time.time()
        elapsed = current_time - start_time
        
        if percent % 5 == 0 and current_time - last_log_time > 2:
            if current_iter > 0 and first_iter_time is not None:
                avg_time = elapsed / current_iter
                remaining = avg_time * (total_iterations - current_iter)
                
                remaining_min = int(remaining // 60)
                remaining_sec = int(remaining % 60)
                elapsed_min = int(elapsed // 60)
                elapsed_sec = int(elapsed % 60)
                
                self._log(f"Progress: {percent}% - Elapsed: {elapsed_min}:{elapsed_sec:02d} - Est. remaining: {remaining_min}:{remaining_sec:02d}")
                                
                # =====================================================
                # TAMBAHKAN INFORMASI CACHE HIT RATE
                # =====================================================
                total_cache_ops = self._cache_hits + self._cache_misses
                if total_cache_ops > 0:
                    hit_rate = (self._cache_hits / total_cache_ops) * 100
                    self._log(f"      📦 Cache hit rate: {hit_rate:.1f}% ({self._cache_hits} hits, {self._cache_misses} misses)")
                    
                last_log_time = current_time
        
        # Get best so far for status
        best = None
        if results:
            best = max(results, key=lambda x: x['score'])
        
        status = f"M{mech}° E{elec}°"
        if best:
            best_mech = best['mech']
            best_elec = best['elec']
            best_dist = best['distance']
            best_score = best['score']
            
            if best_dist >= 1000:
                best_dist_str = f"{best_dist/1000:.2f}km"
            else:
                best_dist_str = f"{best_dist:.0f}m"
            
            status += f" | Best: M{best_mech}° E{best_elec}° → {best_dist_str} (score: {best_score:.0f})"
        
        # Emit progress
        if total_iterations <= 50:
            # Kirim best jika ada, jika None kirim dict kosong
            self.progress.emit(percent, status, best if best is not None else {})
        elif current_iter % max(1, total_iterations // 20) == 0 or percent == 100:
            self.progress.emit(percent, status, best if best is not None else {})
        
        # =====================================================
        # RETURN DENGAN FOOTPRINT (PERBAIKAN UTAMA)
        # =====================================================
        return {
            'current_iter': current_iter,
            'last_log_time': last_log_time,
            'first_iter_time': first_iter_time,
            'result': result,
            'distance': distance,
            'lower_footprint': lower,      # <-- TAMBAHKAN INI
            'upper_footprint': upper,      # <-- TAMBAHKAN INI
            'score': score
        }
    
    
    def cancel(self):
        """
        Cancel optimization
        """
        self._log("Cancel signal received")
        self._is_cancelled = True



class VerticalAnalysisDialog(QDialog):

    def __init__(self, controller=None, parent=None):

        super().__init__(parent)
        # =====================================================
        # FLAG UNTUK CEK STATUS DESTROY
        # =====================================================
        self._is_destroying = False

        self.controller = controller

        # =====================================================
        # SET WINDOW TITLE DAN ICON
        # =====================================================
        self.setWindowTitle("扇区Tilt分析 - 垂直波瓣分析")
        
        # Set window icon from plugin's SVG file
        import os
        icon_path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', '..', 'icon.svg'
        )
        if os.path.exists(icon_path):
            from PyQt5.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"⚠️ Icon not found: {icon_path}")
        
        # =====================================================
        # ENABLE MAXIMIZE/MINIMIZE BUTTONS (IMPROVEMENT UX)
        # =====================================================
        # Add maximize and minimize buttons while keeping existing behavior
        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint
        )

        # 当前小区号（用于在标题栏显示，区分"选择问题"还是"筛选/绘制问题"）
        self.current_cell_id = None
        
        # =====================================================
        # AUTO-ADJUST DIALOG SIZE BASED ON SCREEN RESOLUTION
        # =====================================================
        
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QGuiApplication
        
        # Dapatkan ukuran layar yang tersedia (exclude taskbar)
        screen = QApplication.primaryScreen()
        if screen is None:
            # Fallback jika tidak ada screen
            screen_geometry = QGuiApplication.primaryScreen().availableGeometry()
        else:
            screen_geometry = screen.availableGeometry()
        
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()
        
        print(f"📺 Screen resolution detected: {screen_width} x {screen_height}")
        
        # Tentukan ukuran dialog berdasarkan resolusi
        if screen_width >= 1400 and screen_height >= 940:
            dialog_width = 1400
            dialog_height = 940
            print("  ✅ Using large layout (1400x940)")
        elif screen_width >= 1200 and screen_height >= 800:
            dialog_width = 1200
            dialog_height = 800
            print("  ✅ Using medium layout (1200x800)")
        elif screen_width >= 1000 and screen_height >= 700:
            dialog_width = screen_width - 50
            dialog_height = screen_height - 100
            print(f"  ⚠️ Using small layout ({dialog_width}x{dialog_height})")
        else:
            dialog_width = screen_width - 20
            dialog_height = screen_height - 80
            print(f"  ⚠️ Using minimal layout ({dialog_width}x{dialog_height})")
        
        self.resize(dialog_width, dialog_height)
        self.setMinimumSize(950, 650)


        # =====================================================
        # GLOBAL STYLE
        # =====================================================

        self.setStyleSheet("""

        QDialog{
            background:#f3f7f9;
        }

        QFrame.card{
            background:#ffffff;
            border:1px solid #c9d9e0;
            border-radius:10px;
        }

        QLabel.section_title{
            font-weight:bold;
            color:#0c6075;
            font-size:14px;
        }

        QLabel.subtitle{
            color:#5f7a84;
            font-size:11px;
        }

        QPushButton.primary{
            background:#0c6075;
            color:white;
            border-radius:6px;
            padding:6px;
        }

        QPushButton.primary:hover{
            background:#094e60;
        }

        QFrame.result_card{
            background:#f4f9fb;
            border:1px solid #d7e7ed;
            border-radius:8px;
        }

        QFrame.elevation_box{
            background:#f6fbfd;
            border:1px dashed #c9d9e0;
            border-radius:8px;
        }

        QFrame.legend_box{
            border-top:1px solid #e3edf2;
        }
        
        QPushButton.secondary {
            background: #e9eef2;
            color: #2c5a6b;
            border: 1px solid #c9d9e0;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 11px;
        }
        
        QPushButton.secondary:hover {
            background: #dae4e9;
        }

        /* ===== TOTAL TILT CLASSES ===== */
        QLabel.total_tilt_normal {
            font-weight: bold;
            color: #0c6075;
            background: #f0f5f8;
            padding: 4px 8px;
            border-radius: 4px;
            border: 1px solid #c9d9e0;
        }
        
        QLabel.total_tilt_high {
            font-weight: bold;
            color: #ffb100;
            background: #f0f5f8;
            padding: 4px 8px;
            border-radius: 4px;
            border: 1px solid #c9d9e0;
        }
        
        QLabel.total_tilt_negative {
            font-weight: bold;
            color: #c1121f;
            background: #f0f5f8;
            padding: 4px 8px;
            border-radius: 4px;
            border: 1px solid #c9d9e0;
        }
        """)
        
        # Path ke icons (untuk digunakan di seluruh dialog)
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        icons_dir = os.path.join(plugin_dir, 'resources', 'icons')
        
        # =====================================================
        # MAIN LAYOUT
        # =====================================================

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(4, 4, 6, 4)
        main_layout.setSpacing(5)
        self.setLayout(main_layout)

        # =====================================================
        # INPUT PANEL DENGAN SCROLL AREA UNTUK LAYAR KECIL
        # =====================================================
        
        # Buat scroll area terlebih dahulu
        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setMinimumWidth(250)
        self.input_scroll.setMaximumWidth(300)
        self.input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                width: 8px;
                background: #f0f5f8;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #c9d9e0;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a5b6c2;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)
        
        # Buat card sebagai widget di dalam scroll area
        inputs_card = QFrame()
        inputs_card.setProperty("class", "card")
        inputs_card.setFixedWidth(272)  # v0.4.15: 390 -> 272（紧凑参数区）
        inputs_card.setStyleSheet("""
            QFrame.card {
                background: #ffffff;
                border: 1px solid #c9d9e0;
                border-radius: 10px;
                margin: 5px;  /* margin simetris semua sisi */
            }
        """)

        # Main layout untuk card
        card_layout = QVBoxLayout()
        inputs_card.setLayout(card_layout)

        title = QLabel("射频参数")
        title.setProperty("class", "section_title")
        card_layout.addWidget(title)
        card_layout.setSpacing(4)  # v0.4.15: 8 -> 4

        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)  # Agar lebih rapi
        card_layout.addWidget(self.tab_widget)
        
        # Set card sebagai widget scroll area
        self.input_scroll.setWidget(inputs_card)

        # =====================================================
        # TAB 1: BASIC RF
        # =====================================================
        
        self.tab_basic = QWidget()
        basic_layout = QVBoxLayout(self.tab_basic)
        basic_layout.setSpacing(4)
        
        # =====================================================
        # SECTION 1+2: SITE + RF（合并为单一分组，紧凑布局）
        # v0.4.15：原「站点位置」「射频参数」两框合并，减少分框与留白；
        # 行距/内边距/输入框宽度全面收紧，参数区无需滚动即可看完。
        # =====================================================
        _compact_group_style = """
            QGroupBox {
                font-weight: bold;
                border: 1px solid #c9d9e0;
                border-radius: 6px;
                margin-top: 16px;
                padding-top: 0px;
                padding-left: 6px;
                padding-right: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px 0 4px;
            }
        """

        param_group = QGroupBox("站点与射频参数")
        param_group.setStyleSheet(_compact_group_style)

        param_layout = QFormLayout(param_group)
        param_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        param_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        param_layout.setContentsMargins(6, 5, 6, 4)
        param_layout.setSpacing(3)
        param_layout.setHorizontalSpacing(6)

        # 输入框统一窄宽度：数字类 96px 足够显示 10000 m / 359.99°；
        # 经纬度 104px 保证 39.904200 十字符完整显示
        spinbox_width = 96

        # Latitude
        self.latitude_input = QLineEdit()
        self.latitude_input.setText("39.904200")
        self.latitude_input.setPlaceholderText("39.904200")
        self.latitude_input.setFixedWidth(104)
        param_layout.addRow("纬度:", self.latitude_input)

        # Longitude
        self.longitude_input = QLineEdit()
        self.longitude_input.setText("116.407400")
        self.longitude_input.setPlaceholderText("116.407400")
        self.longitude_input.setFixedWidth(104)
        param_layout.addRow("经度:", self.longitude_input)

        # Azimuth
        self.azimuth_spin = QDoubleSpinBox()
        self.azimuth_spin.setRange(0, 359.99)
        self.azimuth_spin.setDecimals(1)
        self.azimuth_spin.setSingleStep(5)
        self.azimuth_spin.setValue(90)
        self.azimuth_spin.setSuffix("°")
        self.azimuth_spin.setFixedWidth(spinbox_width)
        param_layout.addRow("Azimuth:", self.azimuth_spin)
        
        # =====================================================
        # SECTION 2: RF PARAMETERS（并入上方「站点与射频参数」分组）
        # =====================================================
        # UNIT SYSTEM
        self.unit_combo = QComboBox()
        self.unit_combo.setFixedWidth(spinbox_width)
        self.unit_combo.addItems(["公制 (m, km)", "英制 (ft, mi)"])
        param_layout.addRow("单位制:", self.unit_combo)

        # ANTENNA HEIGHT
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(0, 200)
        self.height_spin.setValue(RFDefaults.ANTENNA_HEIGHT)
        self.height_spin.setSuffix(" m")
        self.height_spin.setFixedWidth(spinbox_width)
        # HAPUS self.height_spin.setAlignment(Qt.AlignRight)
        param_layout.addRow("天线挂高:", self.height_spin)

        # MECHANICAL TILT
        self.mech_tilt_spin = QDoubleSpinBox()
        self.mech_tilt_spin.setRange(-5, 20)
        self.mech_tilt_spin.setValue(RFDefaults.MECHANICAL_TILT)
        self.mech_tilt_spin.setSuffix("°")
        self.mech_tilt_spin.setFixedWidth(spinbox_width)
        # HAPUS self.mech_tilt_spin.setAlignment(Qt.AlignRight)
        param_layout.addRow("机械下倾:", self.mech_tilt_spin)

        # ELECTRICAL TILT
        self.elec_tilt_spin = QDoubleSpinBox()
        self.elec_tilt_spin.setRange(0, 12)
        self.elec_tilt_spin.setValue(RFDefaults.ELECTRICAL_TILT)
        self.elec_tilt_spin.setSuffix("°")
        self.elec_tilt_spin.setFixedWidth(spinbox_width)
        # HAPUS self.elec_tilt_spin.setAlignment(Qt.AlignRight)
        param_layout.addRow("电子下倾:", self.elec_tilt_spin)

        # TOTAL TILT (READONLY)
        total_layout = QHBoxLayout()
        
        # Hitung total tilt awal dari nilai spinbox
        initial_total = self.mech_tilt_spin.value() + self.elec_tilt_spin.value()
        self.total_tilt_label = QLabel(f"{initial_total:.1f}°")
        
        # Set fixed width dan height agar tidak berubah
        self.total_tilt_label.setFixedWidth(56)
        self.total_tilt_label.setFixedHeight(20)
        self.total_tilt_label.setAlignment(Qt.AlignCenter)
        
        # Set class berdasarkan nilai awal
        if initial_total < 0:
            self.total_tilt_label.setProperty("class", "total_tilt_negative")
        elif initial_total > 8:
            self.total_tilt_label.setProperty("class", "total_tilt_high")
        else:
            self.total_tilt_label.setProperty("class", "total_tilt_normal")
        
        total_layout.addWidget(self.total_tilt_label)
        total_layout.addStretch()
        param_layout.addRow("总下倾:", total_layout)

        # VERTICAL BEAMWIDTH
        self.beamwidth_spin = QDoubleSpinBox()
        self.beamwidth_spin.setRange(0, 30)
        self.beamwidth_spin.setValue(RFDefaults.VERTICAL_BEAMWIDTH)
        self.beamwidth_spin.setSingleStep(0.1)
        self.beamwidth_spin.setDecimals(1)
        self.beamwidth_spin.setSuffix("°")
        self.beamwidth_spin.setFixedWidth(spinbox_width)
        # HAPUS self.beamwidth_spin.setAlignment(Qt.AlignRight)
        param_layout.addRow("垂直波瓣角:", self.beamwidth_spin)

        # HORIZONTAL BEAMWIDTH
        self.h_beamwidth_spin = QDoubleSpinBox()
        self.h_beamwidth_spin.setRange(0, 120)
        self.h_beamwidth_spin.setValue(RFDefaults.HORIZONTAL_BEAMWIDTH)
        self.h_beamwidth_spin.setSuffix("°")
        self.h_beamwidth_spin.setFixedWidth(spinbox_width)
        # HAPUS self.h_beamwidth_spin.setAlignment(Qt.AlignRight)
        param_layout.addRow("水平波瓣角:", self.h_beamwidth_spin)
        basic_layout.addWidget(param_group)


        # =====================================================
        # SECTION 3+4: ANALYSIS RANGE + DATA SOURCE（合并为「分析与数据源」）
        # =====================================================
        ds_group = QGroupBox("分析与数据源")
        ds_group.setStyleSheet(_compact_group_style)

        ds_layout = QFormLayout(ds_group)
        ds_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ds_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        ds_layout.setContentsMargins(6, 5, 6, 4)
        ds_layout.setSpacing(3)
        ds_layout.setHorizontalSpacing(6)


        # MAX DISTANCE
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0, 10000)
        self.distance_spin.setValue(RFDefaults.MAX_DISTANCE)
        self.distance_spin.setSingleStep(10)
        self.distance_spin.setSuffix(" m")
        self.distance_spin.setFixedWidth(spinbox_width)
        ds_layout.addRow("最大距离:", self.distance_spin)

        # DISTANCE SLIDER
        slider_layout = QHBoxLayout()
        self.distance_slider = QSlider(QtCore.Qt.Horizontal)
        self.distance_slider.setRange(0, 10000)
        self.distance_slider.setSingleStep(10)
        self.distance_slider.setPageStep(100)
        self.distance_slider.setValue(5000)
        self.distance_label = QLabel("5000 m")
        self.distance_label.setFixedWidth(40)
        slider_layout.addWidget(self.distance_slider)
        slider_layout.setSpacing(4)
        slider_layout.addWidget(self.distance_label)
        ds_layout.addRow("", slider_layout)
        
        # =====================================================
        # SECTION 4: DATA SOURCE（并入上方「分析与数据源」分组）
        # =====================================================

        # Container untuk DEM combobox + status label
        dem_container = QWidget()
        dem_container_layout = QVBoxLayout(dem_container)
        dem_container_layout.setContentsMargins(0, 0, 0, 0)
        dem_container_layout.setSpacing(2)

        self.dem_source_combo = QComboBox()
        self.dem_source_combo.addItems(["本地DEM (离线)", "Open-Meteo (在线)"])
        self.dem_source_combo.setCurrentIndex(1)
        self.dem_source_combo.setFixedWidth(spinbox_width)
        self.dem_source_combo.setToolTip(
            "选择高程数据源:\n"
            "• 本地DEM: 使用工程中已加载的DEM图层(离线,快速)\n"
            "• Open-Meteo: 从在线API获取全球高程数据(需联网)\n\n"
            "点右侧 ★ 可把当前选择存为默认，之后每次打开自动生效。"
        )
        dem_row = QHBoxLayout()
        dem_row.setContentsMargins(0, 0, 0, 0)
        dem_row.setSpacing(3)
        dem_row.addWidget(self.dem_source_combo)
        self.pin_dem_btn = _make_default_pin(
            self,
            "设为默认：把当前【高程数据源】记住\n"
            "下次打开工具箱自动选中它，不用再手动切换。",
        )
        dem_row.addWidget(self.pin_dem_btn)
        dem_row.addStretch()
        self.pin_dem_btn.clicked.connect(self._on_pin_dem_source)
        dem_container_layout.addLayout(dem_row)

        # Status indicator untuk koneksi online
        self.online_status_label = QLabel("🌐 在线: 就绪")
        self.online_status_label.setStyleSheet("color: #00b050; font-size: 10px; padding: 2px 0px 0px 5px;")
        self.online_status_label.setVisible(True)
        dem_container_layout.addWidget(self.online_status_label)

        ds_layout.addRow("DEM数据源:", dem_container)

        # =====================================================
        # BASEMAP SELECTION
        # =====================================================

        # Container untuk basemap combo + refresh button
        basemap_container = QWidget()
        basemap_container_layout = QHBoxLayout(basemap_container)
        basemap_container_layout.setContentsMargins(0, 0, 0, 0)
        basemap_container_layout.setSpacing(20)

        self.basemap_combo = QComboBox()
        self.basemap_combo.setFixedWidth(spinbox_width)
        self.basemap_combo.setToolTip(
            "从QGIS工程选择底图图层\n"
            "• 仅显示栅格图层\n"
            "• 选择'无'使用默认OSM\n\n"
            "点右侧 ★ 可把当前选择存为默认，之后每次打开自动生效。"
        )
        basemap_container_layout.addWidget(self.basemap_combo)

        self.pin_basemap_btn = _make_default_pin(
            self,
            "设为默认：把当前【底图图层】记住\n"
            "下次打开工具箱自动选中它，不用再手动切换。",
        )
        basemap_container_layout.addWidget(self.pin_basemap_btn)
        self.pin_basemap_btn.clicked.connect(self._on_pin_basemap)

        # Tombol Refresh Basemap dengan icon SVG
        self.refresh_basemap_btn = QPushButton()
        refresh_icon_path = os.path.join(icons_dir, 'refresh_basemap.svg')
        if os.path.exists(refresh_icon_path):
            self.refresh_basemap_btn.setIcon(QIcon(refresh_icon_path))
            self.refresh_basemap_btn.setIconSize(QtCore.QSize(22, 22))
            self.refresh_basemap_btn.setToolTip("刷新底图列表")
        else:
            self.refresh_basemap_btn.setText("↻")
            self.refresh_basemap_btn.setToolTip("刷新底图列表")
        self.refresh_basemap_btn.setProperty("class", "secondary")
        self.refresh_basemap_btn.setFixedSize(25, 25)
        self.refresh_basemap_btn.clicked.connect(self._refresh_basemap_list)
        basemap_container_layout.addWidget(self.refresh_basemap_btn)
        basemap_container_layout.addStretch()  # Ini penting agar tombol tetap di kanan
       
        ds_layout.addRow("底图:", basemap_container)
        basic_layout.addWidget(ds_group)
        
        # =====================================================
        # TAMBAHKAN: Hubungkan signal untuk mengganti basemap secara real-time
        # =====================================================
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_changed)
        

        
        # =====================================================
        # SECTION 5: ACTIONS
        # =====================================================
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(4, 6, 4, 2)
        
        self.run_button = QPushButton("运行分析")
        self.run_button.setProperty("class", "primary")
        # self.run_button.setMinimumHeight(35)
        self.run_button.setMinimumWidth(96)
        
        self.reset_button = QPushButton("重置")
        self.reset_button.setProperty("class", "secondary")
        # self.reset_button.setMinimumHeight(35)
        self.reset_button.setMinimumWidth(96)
        
        action_layout.addWidget(self.reset_button)
        action_layout.addWidget(self.run_button)
        
        # action_layout.addStretch()
        basic_layout.addLayout(action_layout)
        
        # =====================================================
        # ELEVATION INFO (STATUS)
        # =====================================================
        self.elevation_info = QLabel(
            "高程: 已加载(64个DEM采样点)。射频地形仿真待运行。"
        )
        self.elevation_info.setWordWrap(True)
        self.elevation_info.setStyleSheet("""
            QLabel {
                background: #f0f5f8;
                border: 1px solid #c9d9e0;
                border-radius: 8px;
                padding: 6px;
                margin-top: 3px;
                color: #2c5a6b;
            }
        """)
        basic_layout.addWidget(self.elevation_info)

        
        
        # =====================================================
        # TAB 2: TILT OPTIMIZER
        # =====================================================
        
        self.tab_optimizer = QWidget()
        optimizer_layout = QVBoxLayout(self.tab_optimizer)
        
        # =====================================================
        # RANGE SETTINGS - MECHANICAL
        # =====================================================
        
        mech_group = QGroupBox("机械下倾范围")
        mech_layout = QVBoxLayout()
        mech_group.setLayout(mech_layout)
        
        mech_range_label = QLabel("范围:")
        mech_layout.addWidget(mech_range_label)
        
        self.mech_range = DualHandleSlider(min_val=0, max_val=10, step=1)  # <-- UBAH INI
        mech_layout.addWidget(self.mech_range)
        
        optimizer_layout.addWidget(mech_group)
        
        # =====================================================
        # RANGE SETTINGS - ELECTRICAL
        # =====================================================
        
        elec_group = QGroupBox("电子下倾范围")
        elec_layout = QVBoxLayout()
        elec_group.setLayout(elec_layout)
        
        elec_range_label = QLabel("范围:")
        elec_layout.addWidget(elec_range_label)
        
        self.elec_range = DualHandleSlider(min_val=0, max_val=12, step=1)
        elec_layout.addWidget(self.elec_range)
        
        optimizer_layout.addWidget(elec_group)
        
        # =====================================================
        # OPTIMIZATION CRITERIA
        # =====================================================
        
        criteria_group = QGroupBox("优化准则")
        criteria_layout = QVBoxLayout()
        criteria_group.setLayout(criteria_layout)
        
        # Maximum Coverage
        self.cb_max_coverage = QCheckBox("最大覆盖")
        self.cb_max_coverage.setChecked(True)
        criteria_layout.addWidget(self.cb_max_coverage)
        
        # Target Distance
        target_layout = QHBoxLayout()
        self.cb_target_distance = QCheckBox("目标距离")
        self.target_distance_spin = QDoubleSpinBox()
        self.target_distance_spin.setRange(0, 10000)
        self.target_distance_spin.setValue(RFDefaults.TARGET_DISTANCE)
        self.target_distance_spin.setSingleStep(10)
        self.target_distance_spin.setSuffix(" m")
        self.target_distance_spin.setEnabled(False)
        target_layout.addWidget(self.cb_target_distance)
        target_layout.addWidget(self.target_distance_spin)
        target_layout.addStretch()
        criteria_layout.addLayout(target_layout)
        
        # Balanced Coverage - REDESIGN dengan QFormLayout
        # Balanced Coverage - REDESIGN: Baris 1 checkbox, Baris 2 Min dan Max sejajar dengan spinbox Target Distance
        balanced_container = QWidget()
        balanced_layout = QVBoxLayout(balanced_container)
        balanced_layout.setContentsMargins(0, 0, 0, 0)
        balanced_layout.setSpacing(5)
        
        # Baris 1: Checkbox + Balanced Coverage (tanpa spinbox)
        self.cb_balanced = QCheckBox("均衡覆盖")
        balanced_layout.addWidget(self.cb_balanced)
        
        # Baris 2: Min dan Max dengan indentasi sejajar spinbox Target Distance
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        
        # Indentasi: hitung lebar checkbox + spacing
        # Checkbox lebar ~20px, spacing 10px = 30px
        # Ditambah jarak antara label "Target Distance" dengan spinbox di baris sebelumnya
        # Agar sejajar dengan spinbox Target Distance (800.00 m)
        row2_layout.addSpacing(10)  # Indentasi mengikuti posisi spinbox Target Distance
        
        # Min section
        min_label = QLabel("最小:")
        row2_layout.addWidget(min_label)
        
        self.balanced_min_spin = QDoubleSpinBox()
        self.balanced_min_spin.setRange(0, 10000)
        self.balanced_min_spin.setValue(RFDefaults.BALANCED_MIN)
        self.balanced_min_spin.setSingleStep(10)
        self.balanced_min_spin.setSuffix(" m")
        self.balanced_min_spin.setEnabled(False)
        self.balanced_min_spin.setFixedWidth(100)
        row2_layout.addWidget(self.balanced_min_spin)
        
        # Spacer antara Min dan Max
        row2_layout.addSpacing(20)
        
        # Max section
        max_label = QLabel("最大:")
        row2_layout.addWidget(max_label)
        
        self.balanced_max_spin = QDoubleSpinBox()
        self.balanced_max_spin.setRange(0, 10000)
        self.balanced_max_spin.setValue(RFDefaults.BALANCED_MAX)
        self.balanced_max_spin.setSingleStep(10)
        self.balanced_max_spin.setSuffix(" m")
        self.balanced_max_spin.setEnabled(False)
        self.balanced_max_spin.setFixedWidth(100)
        row2_layout.addWidget(self.balanced_max_spin)
        
        row2_layout.addStretch()
        balanced_layout.addLayout(row2_layout)
        
        criteria_layout.addWidget(balanced_container)
        
        optimizer_layout.addWidget(criteria_group)
        
        # =====================================================
        # OPTIMIZATION MODE
        # =====================================================
        mode_group = QGroupBox("优化模式")
        mode_layout = QVBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Precise - Total tilt only (21 iterations, ~20s)",
            "Smart - Total tilt + preferred distributions (35 iterations, ~35s)",
            "Fast - Mechanical tilt only (11 iterations, ~10s)"
        ])
        self.mode_combo.setCurrentIndex(1)  # Default ke Smart
        self.mode_combo.setToolTip(
            "Choose optimization speed vs detail:\n\n"
            "• Precise: Test all TOTAL TILT values (2° to 22°)\n"
            "  - 21 iterations\n"
            "  - Fastest way to find optimal total tilt\n"
            "  - Does not show all mechanical/electrical distributions\n\n"
            "• Smart: Find best TOTAL TILT first, then explore top 5 distributions\n"
            "  - ~35 iterations\n"
            "  - Shows all possible (M,E) pairs for top 5 total tilts\n"
            "  - Prioritizes electrical tilt (remote adjustable)\n\n"
            "• Fast: Mechanical tilt only (electrical fixed at 0°)\n"
            "  - 11 iterations\n"
            "  - Very fast, but ignores electrical tilt"
        )
        mode_layout.addWidget(self.mode_combo)
        
        optimizer_layout.addWidget(mode_group)
        
        
        # =====================================================
        # ACTION BUTTONS
        # =====================================================
        
        button_layout = QHBoxLayout()
        
        self.start_optimize_btn = QPushButton("开始优化")
        self.start_optimize_btn.setProperty("class", "primary")
        # self.start_optimize_btn.setMinimumHeight(30)
        button_layout.addWidget(self.start_optimize_btn)

        self.cancel_optimize_btn = QPushButton("取消")
        self.cancel_optimize_btn.setEnabled(False)
        self.cancel_optimize_btn.setProperty("class", "secondary")
        button_layout.addWidget(self.cancel_optimize_btn)

        
        optimizer_layout.addLayout(button_layout)
        
        # =====================================================
        # PROGRESS AREA
        # =====================================================
        
        progress_group = QGroupBox("进度")
        progress_layout = QVBoxLayout()
        progress_group.setLayout(progress_layout)
        
        self.optimize_progress = QProgressBar()
        self.optimize_progress.setRange(0, 100)
        self.optimize_progress.setValue(0)
        progress_layout.addWidget(self.optimize_progress)
        
        self.optimize_status = QLabel("准备优化")
        self.optimize_status.setWordWrap(True)
        self.optimize_status.setStyleSheet("color: #2c5a6b; font-size: 10px;")
        progress_layout.addWidget(self.optimize_status)
        
        self.optimize_best = QLabel("当前最优: —")
        self.optimize_best.setStyleSheet("color: #0c6075; font-weight: bold; font-size: 11px;")
        progress_layout.addWidget(self.optimize_best)
        
        optimizer_layout.addWidget(progress_group)
        
        # =====================================================
        # RESULTS AREA
        # =====================================================
        
        results_group = QGroupBox("结果")
        results_layout = QVBoxLayout()
        results_group.setLayout(results_layout)
        
        self.optimize_result_label = QLabel("最优下倾将显示在此处")
        self.optimize_result_label.setWordWrap(True)
        self.optimize_result_label.setStyleSheet("color: #0c6075; font-weight: bold;")
        results_layout.addWidget(self.optimize_result_label)
        
        # Top 5 results (expandable)
        self.top5_expand_btn = QPushButton("▼ 前5组合")
        self.top5_expand_btn.setProperty("class", "secondary")
        self.top5_expand_btn.setCheckable(True)
        self.top5_expand_btn.setChecked(False)
        results_layout.addWidget(self.top5_expand_btn)
        
        self.top5_widget = QWidget()
        self.top5_layout = QVBoxLayout(self.top5_widget)
        self.top5_layout.setContentsMargins(10, 5, 10, 5)
        
        self.top5_labels = []
        for i in range(5):
            label = QLabel(f"{i+1}. —")
            label.setStyleSheet("font-size: 10px;")
            self.top5_layout.addWidget(label)
            self.top5_labels.append(label)
        
        self.top5_widget.setVisible(False)
        results_layout.addWidget(self.top5_widget)
        
        optimizer_layout.addWidget(results_group)
                
        # Apply button - CENTERED
        apply_layout = QHBoxLayout()
        
        self.apply_optimize_btn = QPushButton("应用最优下倾")
        self.apply_optimize_btn.setProperty("class", "primary")
        self.apply_optimize_btn.setEnabled(False)
        self.apply_optimize_btn.setMaximumWidth(130)
        apply_layout.addWidget(self.apply_optimize_btn)
        
        optimizer_layout.addLayout(apply_layout)
        
        # =====================================================
        # EXPORT RESULTS - COLLAPSIBLE PANEL (SEPERTI TOP 5)
        # =====================================================
        
        # Export expand/collapse button
        self.export_expand_btn = QPushButton("▼ 导出选项(3种格式)")
        self.export_expand_btn.setProperty("class", "secondary")
        self.export_expand_btn.setCheckable(True)
        self.export_expand_btn.setChecked(False)
        self.export_expand_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 6px;
                font-weight: bold;
            }
        """)
        optimizer_layout.addWidget(self.export_expand_btn)
        
        # Export options widget (collapsible)
        self.export_widget = QWidget()
        self.export_layout = QVBoxLayout(self.export_widget)
        self.export_layout.setContentsMargins(10, 5, 10, 5)
        self.export_layout.setSpacing(5)
        
        # CSV Button
        csv_layout = QHBoxLayout()
        self.export_csv_btn = QPushButton("📊 导出CSV")
        self.export_csv_btn.setProperty("class", "secondary")
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setToolTip("导出前20条结果到CSV文件")
        self.export_csv_btn.setMinimumHeight(28)
        csv_layout.addWidget(self.export_csv_btn)
        csv_layout.addStretch()
        self.export_layout.addLayout(csv_layout)
        
        # Excel Button
        excel_layout = QHBoxLayout()
        self.export_excel_btn = QPushButton("📈 导出Excel")
        self.export_excel_btn.setProperty("class", "secondary")
        self.export_excel_btn.setEnabled(False)
        self.export_excel_btn.setToolTip("导出前20条结果到Excel文件(需openpyxl)")
        self.export_excel_btn.setMinimumHeight(28)
        excel_layout.addWidget(self.export_excel_btn)
        excel_layout.addStretch()
        self.export_layout.addLayout(excel_layout)
        
        # JSON Button
        json_layout = QHBoxLayout()
        self.export_json_btn = QPushButton("🔧 导出JSON")
        self.export_json_btn.setProperty("class", "secondary")
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.setToolTip("导出结果到JSON以进一步分析")
        self.export_json_btn.setMinimumHeight(28)
        json_layout.addWidget(self.export_json_btn)
        json_layout.addStretch()
        self.export_layout.addLayout(json_layout)
        
        # Set visible berdasarkan state button
        self.export_widget.setVisible(False)
        optimizer_layout.addWidget(self.export_widget)
        
        optimizer_layout.addStretch()
        
        # =====================================================
        # ADD TABS TO WIDGET
        # =====================================================
        
        self.tab_widget.addTab(self.tab_basic, "基础射频")
        self.tab_widget.addTab(self.tab_optimizer, "下倾优化")


        # =====================================================
        # RIGHT COLUMN
        # =====================================================

        right_splitter = QSplitter(Qt.Vertical)

        # -----------------------------------------------------
        # PROFILE CARD
        # -----------------------------------------------------

        profile_card = QFrame()
        profile_card.setProperty("class","card")

        profile_layout = QVBoxLayout()
        profile_card.setLayout(profile_layout)

        # =====================================================
        # PROFILE HEADER DENGAN TOMBOL RESET
        # =====================================================
        
        profile_header = QHBoxLayout()
        
        profile_title = QLabel("地形分析")
        profile_title.setProperty("class", "section_title")
        profile_header.addWidget(profile_title)
        
        profile_header.addStretch()
        
        # Tombol Reset View dengan icon + teks
        self.reset_view_btn = QPushButton(" 重置视图")
        reset_icon_path = os.path.join(icons_dir, 'reset.svg')
        if os.path.exists(reset_icon_path):
            self.reset_view_btn.setIcon(QIcon(reset_icon_path))
            self.reset_view_btn.setIconSize(QtCore.QSize(22, 22))
            self.reset_view_btn.setToolTip("缩放/拖动后重置图表为最佳视图")
        else:
            self.reset_view_btn.setText("↺ 重置视图")
            self.reset_view_btn.setToolTip("缩放/拖动后重置图表为最佳视图")
        self.reset_view_btn.setProperty("class", "secondary")
        self.reset_view_btn.setFixedHeight(30)
        self.reset_view_btn.setMinimumWidth(100)
        self.reset_view_btn.clicked.connect(self._reset_graph_view)
        
        profile_header.addWidget(self.reset_view_btn)
        
        profile_layout.addLayout(profile_header)

        # =====================================================
        # BUAT PROFILE WIDGET
        # =====================================================
        self.profile_widget = TerrainProfileWidget()
        
        # Set initial unit system
        is_metric = self.unit_combo.currentIndex() == 0
        self.profile_widget.set_unit_system(is_metric)
        
        profile_layout.addWidget(self.profile_widget)
        
        # -----------------------------------------------------
        # MAP CARD
        # -----------------------------------------------------

        map_card = QFrame()
        map_card.setProperty("class","card")

        map_layout = QVBoxLayout()
        map_card.setLayout(map_layout)

        
        # =====================================================
        # MAP HEADER DENGAN TOOLBAR NAVIGASI & TOMBOL EXPORT KMZ
        # =====================================================
        
        map_header = QHBoxLayout()
        
        map_title = QLabel("覆盖地图")
        map_title.setProperty("class", "section_title")
        map_header.addWidget(map_title)
        
        map_header.addStretch()
        
        # =====================================================
        # NAVIGATION TOOLBAR
        # =====================================================
        
        # Import QIcon
        from PyQt5.QtGui import QIcon
        import os
        
        # Path ke icons
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        icons_dir = os.path.join(plugin_dir, 'resources', 'icons')
        
        # Zoom In button
        self.zoom_in_btn = QPushButton()
        zoom_in_path = os.path.join(icons_dir, 'zoom_in.svg')
        if os.path.exists(zoom_in_path):
            self.zoom_in_btn.setIcon(QIcon(zoom_in_path))
            self.zoom_in_btn.setIconSize(QtCore.QSize(22, 22))
        else:
            self.zoom_in_btn.setText("🔍+")
        self.zoom_in_btn.setProperty("class", "secondary")
        self.zoom_in_btn.setFixedSize(30, 30)
        self.zoom_in_btn.setToolTip("放大(点击或拖拽选择区域)")
        self.zoom_in_btn.clicked.connect(self._on_zoom_in_clicked)
        map_header.addWidget(self.zoom_in_btn)
        
        # Zoom Out button
        self.zoom_out_btn = QPushButton()
        zoom_out_path = os.path.join(icons_dir, 'zoom_out.svg')
        if os.path.exists(zoom_out_path):
            self.zoom_out_btn.setIcon(QIcon(zoom_out_path))
            self.zoom_out_btn.setIconSize(QtCore.QSize(22, 22))
        else:
            self.zoom_out_btn.setText("🔍-")
        self.zoom_out_btn.setProperty("class", "secondary")
        self.zoom_out_btn.setFixedSize(30, 30)
        self.zoom_out_btn.setToolTip("缩小")
        self.zoom_out_btn.clicked.connect(self._on_zoom_out_clicked)
        map_header.addWidget(self.zoom_out_btn)
        
        # Reset View button
        self.reset_map_btn = QPushButton()
        reset_view_path = os.path.join(icons_dir, 'view_default.svg')
        if os.path.exists(reset_view_path):
            self.reset_map_btn.setIcon(QIcon(reset_view_path))
            self.reset_map_btn.setIconSize(QtCore.QSize(22, 22))
        else:
            self.reset_map_btn.setText("⟲")
        self.reset_map_btn.setProperty("class", "secondary")
        self.reset_map_btn.setFixedSize(30, 30)
        self.reset_map_btn.setToolTip("重置为默认视图")
        self.reset_map_btn.clicked.connect(self._on_reset_map_clicked)
        map_header.addWidget(self.reset_map_btn)
        
        # Spacer
        map_header.addSpacing(10)
        

        # Tombol Export KMZ dengan icon + teks
        self.export_kmz_btn = QPushButton(" 导出KMZ")
        export_kmz_path = os.path.join(icons_dir, 'export_kmz.svg')
        if os.path.exists(export_kmz_path):
            self.export_kmz_btn.setIcon(QIcon(export_kmz_path))
            self.export_kmz_btn.setIconSize(QtCore.QSize(22, 22))
            self.export_kmz_btn.setToolTip("导出覆盖足迹到KMZ")
        else:
            self.export_kmz_btn.setText("📤 KMZ")
            self.export_kmz_btn.setToolTip("导出覆盖足迹到KMZ文件")
        self.export_kmz_btn.setProperty("class", "secondary")
        self.export_kmz_btn.setCursor(Qt.PointingHandCursor)
        self.export_kmz_btn.setFixedSize(30, 30)
        self.export_kmz_btn.setMinimumWidth(120)  # Lebar cukup untuk icon + teks "KMZ"
        self.export_kmz_btn.clicked.connect(self._export_kmz)
        
        map_header.addWidget(self.export_kmz_btn)
        
        map_layout.addLayout(map_header)

        # Map widget
        self.map_widget = SectorMapWidget()

        # Allow layout to control size instead of forcing minimum height
        self.map_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        map_layout.addWidget(self.map_widget)

        # Status label (tetap di bawah)
        self.status_label = QLabel("就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setOpenExternalLinks(True)  # <-- TAMBAHKAN INI
        self.status_label.setStyleSheet("color: #2c5a6b; font-size: 12px; padding: 6px;")  # 10px → 12px
        self.status_label.setMinimumHeight(20)  # Tambah tinggi agar tidak sempit
        self.status_label.setWordWrap(True)     # Wrap text jika terlalu panjang
        map_layout.addWidget(self.status_label)
        
        
        # =====================================================
        # KMZ EXPORTER
        # =====================================================
        
        self.kmz_exporter = KMZExporter(iface)

        # =====================================================
        # ADD LAYOUT
        # =====================================================

        right_splitter.addWidget(profile_card)
        right_splitter.addWidget(map_card)

        # Default split 50:50
        right_splitter.setSizes([400,400])

        # UX improvement
        right_splitter.setHandleWidth(6)
        right_splitter.setChildrenCollapsible(False)
        
        # auto refresh matplotlib when splitter moved
        right_splitter.splitterMoved.connect(self._refresh_profile_plot)


        profile_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        map_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.profile_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.map_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # =====================================================
        # FIX: USE SCROLL AREA FOR INPUT PANEL
        # =====================================================
        # sebelumnya inputs_card langsung dimasukkan ke layout
        # sehingga scroll tidak pernah muncul pada layar kecil

        main_layout.addWidget(self.input_scroll)
        main_layout.addWidget(right_splitter,1)

        # =====================================================
        # SIGNALS - FIXED (TANPA INFINITE LOOP)
        # =====================================================
        
        # =====================================================
        # CONNECT SPINBOX TO UPDATE METER VALUES
        # =====================================================
        self.height_spin.valueChanged.connect(self._update_height_in_meter)
        self.distance_spin.valueChanged.connect(self._update_distance_in_meter)

        # Slider ke Spinbox - DENGAN PEMBULATAN
        self.distance_slider.valueChanged.connect(
            lambda v: (
                self.distance_spin.blockSignals(True),
                self.distance_slider.blockSignals(True),  # Block slider juga
                self._update_distance_from_slider(self._round_slider_value(v)),
                self.distance_slider.blockSignals(False),
                self.distance_spin.blockSignals(False)
            )
        )

        # Spinbox ke Slider - DENGAN PEMBULATAN
        self.distance_spin.valueChanged.connect(
            lambda v: (
                self.distance_slider.blockSignals(True),
                self.distance_spin.blockSignals(True),  # Block spinbox juga
                self._update_slider_from_spinbox(v),
                self.distance_spin.blockSignals(False),
                self.distance_slider.blockSignals(False)
            )
        )
        
        # Di bagian SIGNALS, tambahkan:
        
        # Update footprint percentage when slider moves
        self.distance_slider.valueChanged.connect(
            lambda v: self._update_footprint_percentage(v)
        )
        
        self.distance_spin.valueChanged.connect(
            lambda v: self._update_footprint_percentage(v)
        )
        
        # run analysis button
        self.run_button.clicked.connect(self.run_analysis)
        
        # Unit system change
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        
        # Reset button
        self.reset_button.clicked.connect(self._reset_to_defaults)
        
        # DEM source change
        self.dem_source_combo.currentIndexChanged.connect(self._on_dem_source_changed)
        
        
        # Setup tooltips
        self._setup_tooltips()
        
        # =====================================================
        # CONNECT MECH/ELEC SPINBOX TO UPDATE TOTAL TILT
        # =====================================================
        self.mech_tilt_spin.valueChanged.connect(self._update_total_tilt)
        self.elec_tilt_spin.valueChanged.connect(self._update_total_tilt)
        
        # Reset view button
        self.reset_view_btn.clicked.connect(self._reset_graph_view)
        
        # =====================================================
        # TILT OPTIMIZER SIGNALS
        # =====================================================
        
        # Enable/disable target distance spinbox
        self.cb_target_distance.toggled.connect(self.target_distance_spin.setEnabled)
        
        # Enable/disable balanced min/max spinboxes
        self.cb_balanced.toggled.connect(self.balanced_min_spin.setEnabled)
        self.cb_balanced.toggled.connect(self.balanced_max_spin.setEnabled)
        
        # Ensure at least one criterion is selected
        self.cb_max_coverage.toggled.connect(self._update_criteria_check)
        self.cb_target_distance.toggled.connect(self._update_criteria_check)
        self.cb_balanced.toggled.connect(self._update_criteria_check)
        
        # Optimize button
        self.start_optimize_btn.clicked.connect(self._start_optimization)
        self.cancel_optimize_btn.clicked.connect(self._cancel_optimization)
        self.apply_optimize_btn.clicked.connect(self._apply_best_tilt)
        
        # Top 5 expand/collapse
        self.top5_expand_btn.toggled.connect(self.top5_widget.setVisible)
        
        # =====================================================
        # EXPORT BUTTONS SIGNALS (TAMBAHKAN DI SINI)
        # =====================================================
        self.export_csv_btn.clicked.connect(lambda: self._export_optimization_results("csv"))
        self.export_excel_btn.clicked.connect(lambda: self._export_optimization_results("excel"))
        self.export_json_btn.clicked.connect(self._export_optimization_json)  # <-- TAMBAHKAN
        # Export expand/collapse
        self.export_expand_btn.toggled.connect(self.export_widget.setVisible)
        self.export_expand_btn.toggled.connect(self._update_export_button_text)
        
        # =====================================================
        # EXPORT BUTTONS SHORTCUTS & ENHANCED TOOLTIPS
        # =====================================================
        # Set shortcut keys untuk power users
        self.export_csv_btn.setShortcut("Ctrl+E")  # Export
        self.export_excel_btn.setShortcut("Ctrl+Shift+E")
        self.export_json_btn.setShortcut("Ctrl+Alt+E")

        # Enhanced tooltips
        self.export_csv_btn.setToolTip(
            "Export ALL optimization results to CSV file\n"
            "• Includes complete metadata as comments\n"
            "• UTF-8 with BOM for Excel compatibility\n"
            "• All combinations (not just top 5)\n"
            "• Shortcut: Ctrl+E"
        )

        self.export_excel_btn.setToolTip(
            "Export ALL optimization results to Excel file\n"
            "• Uses xlsxwriter for better performance\n"
            "• Two sheets: Results and Metadata\n"
            "• Formatted with colors and frozen headers\n"
            "• All combinations (not just top 5)\n"
            "• Shortcut: Ctrl+Shift+E"
        )

        self.export_json_btn.setToolTip(
            "Export ALL results to JSON for further analysis\n"
            "• Includes terrain profile sample\n"
            "• Complete metadata and parameters\n"
            "• Ideal for scripting and automation\n"
            "• All combinations (not just top 5)\n"
            "• Shortcut: Ctrl+Alt+E"
        )
        
        
        # =====================================================
        # TAMBAHKAN: Penyimpanan untuk semua hasil optimasi
        # =====================================================
        self._all_optimization_results = []  # <-- Simpan SEMUA kombinasi, bukan hanya top 5
        self._optimization_metadata = {}     # <-- Simpan metadata untuk export
        
        # Refresh basemap list setelah dialog siap
        QTimer.singleShot(500, self._refresh_basemap_list)

        # =====================================================
        # 恢复用户已保存的「默认」选择（DEM 数据源 / 底图）
        # =====================================================
        self._restore_defaults()

    # ---------------------------------------------------------------
    # 默认项持久化
    # ---------------------------------------------------------------
    def _restore_defaults(self):
        """把上次通过 ★ 保存的默认选择应用回来。"""
        mod = _get_store()
        if mod is None:
            return

        idx = mod.get_dem_source(None)
        if idx in (0, 1):
            self.dem_source_combo.blockSignals(True)
            self.dem_source_combo.setCurrentIndex(idx)
            self.dem_source_combo.blockSignals(False)
            _flash_pin(self.pin_dem_btn)
            if hasattr(self, "online_status_label"):
                self.online_status_label.setVisible(idx == 1)

        name = mod.get_basemap(None)
        if name:
            self._pending_default_basemap = name
            # 底图列表要等 QTimer(500ms) 刷新完才有内容，故延迟再套用
            QTimer.singleShot(600, self._apply_default_basemap)

    def _apply_default_basemap(self):
        name = getattr(self, "_pending_default_basemap", None)
        if not name:
            return
        i = self.basemap_combo.findText(name)
        if i >= 0:
            self.basemap_combo.blockSignals(True)
            self.basemap_combo.setCurrentIndex(i)
            self.basemap_combo.blockSignals(False)
            _flash_pin(self.pin_basemap_btn)
            self._pending_default_basemap = None

    def _on_pin_dem_source(self):
        mod = _get_store()
        if mod is None:
            return
        idx = self.dem_source_combo.currentIndex()
        mod.set_dem_source(idx)
        self.pin_dem_btn.setStyleSheet(_PIN_ON_STYLE)
        if hasattr(self, "online_status_label"):
            self.online_status_label.setVisible(idx == 1)
        _push_info("扇区Tilt分析",
                   "已把【%s】设为默认高程数据源" % self.dem_source_combo.currentText())

    def _on_pin_basemap(self):
        mod = _get_store()
        if mod is None:
            return
        name = self.basemap_combo.currentText()
        mod.set_basemap(name)
        self.pin_basemap_btn.setStyleSheet(_PIN_ON_STYLE)
        _push_info("扇区Tilt分析", "已把【%s】设为默认底图" % name)

    def set_cell_info(self, cell_id, extra="", cell_name=None):
        """
        在窗口标题栏显示当前小区号 + 小区名称（用于区分「选择问题」还是「筛选/绘制问题」）。
        每次点选小区都会调用，不经过分析链路，即时同步。

        cell_name：小区名称（如 示例站-Ⅴ-ABC-1），有则显示在小区号后面。
        """
        self.current_cell_id = str(cell_id) if cell_id not in (None, "") else None
        self.current_cell_name = str(cell_name) if cell_name not in (None, "") else None
        base = "扇区Tilt分析 - 垂直波瓣分析"
        if self.current_cell_id:
            name_txt = f"：{self.current_cell_name}" if self.current_cell_name else ""
            if extra:
                title = f"{base}｜小区 {self.current_cell_id}{name_txt}（{extra}）"
            else:
                title = f"{base}｜小区 {self.current_cell_id}{name_txt}"
        else:
            title = base
        self.setWindowTitle(title)

    def closeEvent(self, event):
        """
        Clean up resources when dialog is closed
        """
        print("🚪 Closing Vertical Analysis Dialog - Cleaning up resources...")
        
        # =====================================================
        # SET FLAG DESTROYING UNTUK MENCEGAH CALLBACK BARU
        # =====================================================
        self._is_destroying = True
        
        # =====================================================
        # STOP PROFILE REFRESH TIMER
        # =====================================================
        if hasattr(self, '_profile_refresh_timer') and self._profile_refresh_timer:
            try:
                self._profile_refresh_timer.stop()
                self._profile_refresh_timer.deleteLater()
                print("  ✅ Profile refresh timer stopped")
            except Exception as e:
                print(f"  ⚠️ Error stopping profile timer: {e}")
        
        # =====================================================
        # CLEANUP MAP WIDGET TIMERS
        # =====================================================
        if hasattr(self, 'map_widget') and self.map_widget:
            try:
                if hasattr(self.map_widget, 'cleanup_timers'):
                    self.map_widget.cleanup_timers()
                print("  ✅ Map widget timers cleaned up")
            except Exception as e:
                print(f"  ⚠️ Error cleaning map widget timers: {e}")
        
        # =====================================================
        # CLEANUP OPTIMIZATION THREAD (IMPROVED)
        # =====================================================
        if hasattr(self, 'optimize_thread') and self.optimize_thread:
            if self.optimize_thread.isRunning():
                print("  ⏳ Stopping optimization thread...")
                
                # Signal worker untuk cancel
                if hasattr(self, 'optimize_worker') and self.optimize_worker:
                    self.optimize_worker.cancel()
                
                # Beri waktu untuk graceful shutdown
                self.optimize_thread.quit()
                
                # Wait dengan timeout lebih panjang (5 detik)
                if not self.optimize_thread.wait(5000):
                    print("  ⚠️ Thread did not finish gracefully, terminating...")
                    # Terminate hanya sebagai last resort
                    self.optimize_thread.terminate()
                    self.optimize_thread.wait(2000)
                
                print("  ✅ Optimization thread stopped")
        
        # =====================================================
        # DISCONNECT ALL SIGNALS (OPTIONAL, TAPI AMAN)
        # =====================================================
        try:
            # Disconnect signal yang berpotensi masalah
            if hasattr(self, 'distance_slider'):
                self.distance_slider.valueChanged.disconnect()
        except:  # nosec
            pass
        
        # =====================================================
        # CLEAR TERRAIN CACHE
        # =====================================================
        if hasattr(self, 'controller') and self.controller and hasattr(self.controller, 'engine'):
            if hasattr(self.controller.engine, 'sampler') and self.controller.engine.sampler is not None:
                print("  🧹 Clearing terrain cache...")
                try:
                    self.controller.engine.sampler.cleanup()  # <-- GUNAKAN METHOD BARU
                except Exception as e:
                    print(f"  ⚠️ Error clearing cache: {e}")

        # =====================================================
        # CLEAR INTERSECTION CACHE (FORCE CLEANUP)
        # =====================================================
        try:
            from ...core.rf_engine.intersection_solver import IntersectionCache
            cache = IntersectionCache()
            cache.cleanup()  # <-- GUNAKAN METHOD BARU
            print("  🧹 Intersection cache cleared")
        except Exception as e:  # nosec
            pass

        
        # =====================================================
        # FORCE GARBAGE COLLECTION
        # =====================================================
        import gc
        collected = gc.collect()
        print(f"  🧹 Garbage collected: {collected} objects")
        
        # Accept the close event
        event.accept()
        
        
    def _setup_tooltips(self):
        """Setup tooltips for UI elements"""
        
        impact_tooltip = (
            "Main Lobe Impact Point\n\n"
            "Horizontal distance from the antenna site to the first terrain\n"
            "intersection of the antenna's main radiation lobe.\n\n"
            "Calculated using:\n"
            "• Antenna height\n"
            "• Downtilt angle\n"
            "• Terrain elevation profile\n\n"
            "RF Engineering insight:\n"
            "• < 300 m: Tilt too high, coverage too short\n"
            "• 300-800 m: Ideal range\n"
            "• > 800 m: Tilt too low, potential overshooting"
        )
        
        # Set tooltip untuk label impact
        impact_title = self.findChild(QLabel, "MAIN LOBE IMPACT POINT")
        if impact_title:
            impact_title.setToolTip(impact_tooltip)
        
    
    def _update_total_tilt(self):
        """
        Update total tilt label when mech or elec tilt changes
        """
        mech = self.mech_tilt_spin.value()
        elec = self.elec_tilt_spin.value()
        total = mech + elec
        self.total_tilt_label.setText(f"{total:.1f}°")
        
        # Tentukan class berdasarkan nilai total
        if total < 0:
            new_class = "total_tilt_negative"
        elif total > 8:
            new_class = "total_tilt_high"
        else:
            new_class = "total_tilt_normal"
        
        # Update class jika berbeda
        if self.total_tilt_label.property("class") != new_class:
            self.total_tilt_label.setProperty("class", new_class)
            # Force style refresh
            self.total_tilt_label.style().unpolish(self.total_tilt_label)
            self.total_tilt_label.style().polish(self.total_tilt_label)  
            
    
    # =====================================================
    # DEM SOURCE HANDLER
    # =====================================================
    
    def _on_dem_source_changed(self, index):
        """
        Handle DEM source change
        index 0 = Local DEM (offline)
        index 1 = Open-Meteo (online)
        """
        if index == 0:
            print("📍 Using Local DEM (offline)")
            self.online_status_label.setVisible(False)
            # Cek apakah ada DEM layer di project
            if self.controller and self.controller.dem_layer:
                self.status_label.setText("Ready - Using local DEM")
            else:
                self.status_label.setText("⚠️ Warning: No DEM layer loaded in project")
                # Tampilkan warning tapi tidak blocking
                QMessageBox.information(
                    self,
                    "Local DEM Not Found",
                    "No DEM layer detected in current project.\n"
                    "Please load a DEM layer or switch to Online source."
                )
        else:
            print("🌐 Using Open-Meteo (online)")
            self.online_status_label.setVisible(True)
            
            # Cek koneksi internet dengan quick timeout
            # （修复：不再用 socket.setdefaulttimeout 污染全局，改用 _probe_open_meteo）
            try:
                if self._probe_open_meteo():
                    self.online_status_label.setText("🌐 Online: Connected")
                    self.online_status_label.setStyleSheet("color: #00b050; font-size: 10px; padding-left: 5px;")
                    self.status_label.setText("Ready - Using Open-Meteo API")
                else:
                    raise OSError("probe failed")
            except Exception as e:
                self.online_status_label.setText("🌐 Online: No Connection")
                self.online_status_label.setStyleSheet("color: #c1121f; font-size: 10px; padding-left: 5px;")
                self.status_label.setText("⚠️ No internet connection - Open-Meteo unavailable")
                
                # Tawarkan switch ke local DEM
                reply = QMessageBox.question(
                    self,
                    "No Internet Connection",
                    "Cannot connect to Open-Meteo API.\n\n"
                    "Would you like to switch to Local DEM?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    # Switch ke local DEM
                    self.dem_source_combo.blockSignals(True)
                    self.dem_source_combo.setCurrentIndex(0)
                    self.dem_source_combo.blockSignals(False)
                    self._on_dem_source_changed(0)  # Panggil handler untuk local
    
    
    def _check_dem_availability(self):
        """
        Check if DEM source is available before running analysis
        Returns tuple (is_available, user_friendly_error_message)
        """
        source_index = self.dem_source_combo.currentIndex()
        
        if source_index == 0:  # Local DEM
            if not self.controller or not self.controller.dem_layer:
                return False, (
                    "No elevation data layer found.\n\n"
                    "Please load a DEM raster layer in your project, or switch to 'Open-Meteo (Online)' "
                    "source to use global elevation data from the internet."
                )
            
            # Cek apakah DEM layer masih valid
            if not self.controller.dem_layer.isValid():
                return False, (
                    "The selected DEM layer cannot be read or is corrupted.\n\n"
                    "Please check if the layer is a valid raster file, or try switching to "
                    "'Open-Meteo (Online)' source."
                )
            
            # Cek extent (opsional, untuk informasi)
            try:
                extent = self.controller.dem_layer.extent()
                if extent.isNull():
                    return False, (
                        "The DEM layer has an invalid geographic extent.\n\n"
                        "Please check the layer's coordinate reference system and extent, "
                        "or try switching to 'Open-Meteo (Online)' source."
                    )
            except:  # nosec
                pass
                
            return True, ""
            
        else:  # Online
            if self._probe_open_meteo():
                return True, ""
            return False, (
                "Unable to connect to Open-Meteo elevation service.\n\n"
                "This could be due to:\n"
                "• No internet connection\n"
                "• Firewall blocking the connection\n"
                "• Open-Meteo service temporarily unavailable\n\n"
                "Please check your internet connection or switch to 'Local DEM' source."
            )

    @staticmethod
    def _probe_open_meteo(timeout=3.0, retries=1):
        """探测 Open-Meteo 可达性（供在线模式校验使用）。

        修复原实现两个问题：
          1. 原 socket.setdefaulttimeout(3) 会污染整个进程的默认超时；
          2. 原来只探 80 端口，而真实 API 走 HTTPS 443，易误报。
        现用独立 socket + settimeout，443/80 各试一次，可重试。
        """
        import socket
        hosts = (("api.open-meteo.com", 443), ("api.open-meteo.com", 80))
        for _ in range(retries + 1):
            for host, port in hosts:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                try:
                    s.connect((host, port))
                    return True
                except OSError:
                    continue
                finally:
                    try:
                        s.close()
                    except OSError:  # nosec
                        pass
        return False

    def _try_fallback_to_local_dem(self):
        """Open-Meteo 不可达时自动降级：在项目里找真正的 DEM 栅格重建 controller。

        返回图层名（成功）或 None（项目里没有可用 DEM）。
        排除 basemap 类图层与插件自建的 1×1 锚点（其高程无意义）。
        成功后把 DEM 源下拉切回 Local，保证后续 _check_dem_availability 走本地分支。
        """
        from qgis.core import QgsRasterLayer
        skip_keywords = [
            'bing', 'osm', 'openstreetmap', 'google', 'map', 'satellite',
            'imagery', 'basemap', 'sanwei', '三维', 'sector_tiltm_dem_anchor',
        ]
        candidates = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
                continue
            name = layer.name() or ""
            low = name.lower()
            if any(k in low for k in skip_keywords):
                continue
            if layer.crs() is None:
                continue
            candidates.append(layer)
        if not candidates:
            return None
        dem_layer = candidates[0]
        try:
            from ...modules.vertical_analysis.module import VerticalAnalysisModule
            module = VerticalAnalysisModule(dem_layer)
            self.controller = module.controller
        except Exception:  # nosec
            import traceback
            traceback.print_exc()
            return None
        self.dem_source_combo.blockSignals(True)
        self.dem_source_combo.setCurrentIndex(0)
        self.dem_source_combo.blockSignals(False)
        try:
            self.status_label.setText(
                f"Ready - fallback local DEM: {dem_layer.name()}"
            )
        except Exception:  # nosec
            pass
        return dem_layer.name()
    
    # =====================================================
    # BASEMAP METHODS
    # =====================================================
    
    def _scan_basemap_layers(self):
        """
        Scan QGIS project untuk raster dan vector tile layers yang bisa digunakan sebagai basemap
        Returns list of layer names
        """
        basemaps = []
        project = QgsProject.instance()
        
        for layer in project.mapLayers().values():
            # Cek apakah layer adalah raster layer
            if isinstance(layer, QgsRasterLayer):
                basemaps.append(layer.name())
            # Cek apakah layer adalah vector tile layer
            elif isinstance(layer, QgsVectorTileLayer):
                basemaps.append(layer.name())
        
        return sorted(basemaps)

    
    def _get_selected_basemap(self):
        """
        Get selected basemap layer name or None for default
        """
        text = self.basemap_combo.currentText()
        if text == "None (Default OSM Maps)":
            return None
        return text
        
    def _on_basemap_changed(self, index):
        """
        Dipanggil ketika user memilih basemap baru
        """
        if hasattr(self, 'map_widget') and hasattr(self.map_widget, 'set_basemap'):
            basemap_name = self._get_selected_basemap()
            print(f"🔄 Changing basemap to: {basemap_name if basemap_name else 'Default OSM'}")
            self.map_widget.set_basemap(basemap_name)    
            
    def _refresh_basemap_list(self):
        """
        Refresh daftar basemap dari project
        """
        current = self.basemap_combo.currentText()
        self.basemap_combo.blockSignals(True)  # Hindari trigger saat update
        self.basemap_combo.clear()
        
        # Tambahkan opsi None (gunakan default OSM)
        self.basemap_combo.addItem("None (Default OSM Maps)")
        
        # Scan basemap layers
        basemaps = self._scan_basemap_layers()
        for name in basemaps:
            self.basemap_combo.addItem(name)
        
        # Kembalikan ke pilihan sebelumnya jika masih ada
        index = self.basemap_combo.findText(current)
        if index >= 0:
            self.basemap_combo.setCurrentIndex(index)
        else:
            # Jika tidak ada, pilih "None (Default OSM Maps)"
            self.basemap_combo.setCurrentIndex(0)
        
        self.basemap_combo.blockSignals(False)
        print(f"🔄 Basemap list refreshed: {len(basemaps)} layers found")

        
    # =====================================================
    # UNIT CONVERSION METHODS
    # =====================================================

    def _convert_from_metric(self, value_m, unit_type):
        """
        Convert from metric to selected unit system
        unit_type: 'height', 'distance', 'beamwidth'
        """
        if self.unit_combo.currentIndex() == 0:  # Metric
            return value_m
        
        # Imperial
        if unit_type == 'height':
            return value_m * 3.28084  # meter to feet
        elif unit_type == 'distance':
            return value_m * 0.000621371  # meter to miles
        elif unit_type == 'beamwidth':
            return value_m  # beamwidth same in both
        return value_m

    def _convert_to_metric(self, value, unit_type):
        """
        Convert from selected unit system to metric
        """
        if self.unit_combo.currentIndex() == 0:  # Metric
            return value
        
        # Imperial
        if unit_type == 'height':
            return value / 3.28084  # feet to meter
        elif unit_type == 'distance':
            return value / 0.000621371  # miles to meter
        elif unit_type == 'beamwidth':
            return value
        return value


    def _update_unit_display(self):
        """Update unit labels based on selected system - TANPA MENGHAPUS WIDGET"""
        is_metric = self.unit_combo.currentIndex() == 0
        
        # Akses form layout
        form = self.findChild(QFormLayout)
        if not form:
            return
        
        # Update suffix di spinbox
        if is_metric:
            self.height_spin.setSuffix(" m")
            self.distance_spin.setSuffix(" m")
        else:
            self.height_spin.setSuffix(" ft")
            self.distance_spin.setSuffix(" mi")  # <-- PASTIKAN INI "mi" BUKAN "°"
        
        # Update label untuk setiap row
        # Row 0: Unit System (tidak perlu diubah)
        # Row 1: Antenna Height
        label_item = form.itemAt(1, QFormLayout.LabelRole)
        if label_item and label_item.widget():
            height_unit = " (m)" if is_metric else " (ft)"
            label_item.widget().setText(f"Antenna Height{height_unit}")
        
        # Row 5: Distance (index 5 karena ada beberapa row)
        # HITUNG ULANG INDEX KARENA BISA BERBEDA
        for i in range(form.rowCount()):
            label_item = form.itemAt(i, QFormLayout.LabelRole)
            if label_item and label_item.widget() and "Distance" in label_item.widget().text():
                distance_unit = " (m)" if is_metric else " (mi)"
                label_item.widget().setText(f"Distance{distance_unit}")
                break
    

    # =====================================================
    # UPDATE METER VALUES WHEN SPINBOX CHANGES
    # =====================================================
    
    def _update_height_in_meter(self, value):
        """Update stored height in meter when spinbox changes"""
        is_metric = self.unit_combo.currentIndex() == 0
        if is_metric:
            self.height_in_meter = value
        else:
            # Imperial: konversi feet ke meter
            self.height_in_meter = value / 3.28084
        print(f"📏 Height in meter updated: {self.height_in_meter:.1f}m")
    
    def _update_distance_in_meter(self, value):
        """Update stored distance in meter when spinbox changes"""
        is_metric = self.unit_combo.currentIndex() == 0
        if is_metric:
            self.distance_in_meter = value
        else:
            # Imperial: konversi miles ke meter
            self.distance_in_meter = value / 0.000621371
        print(f"📏 Distance in meter updated: {self.distance_in_meter:.0f}m")
        
     
    # =====================================================
    # TAMBAHKAN FUNGSI INI DI SINI (setelah _update_unit_display)
    # =====================================================
    
    def _validate_coordinates(self):
        """
        Validate latitude and longitude input
        Returns: (is_valid, error_message, warning_message)
        """
        lat_text = self.latitude_input.text().strip()
        lon_text = self.longitude_input.text().strip()
        warning_msg = ""
        
        # =====================================================
        # CHECK 1: Empty input (ERROR)
        # =====================================================
        if not lat_text:
            return False, "Latitude cannot be empty", ""
        if not lon_text:
            return False, "Longitude cannot be empty", ""
        
        # =====================================================
        # CHECK 2: Invalid characters (ERROR)
        # =====================================================
        import re
        scientific_pattern = r'^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$'
        
        if not re.match(scientific_pattern, lat_text):
            return False, "Invalid latitude format. Use decimal degrees (e.g., -6.1754) or scientific notation (e.g., 1.23e-5)", ""
        
        if not re.match(scientific_pattern, lon_text):
            return False, "Invalid longitude format. Use decimal degrees (e.g., 106.827) or scientific notation (e.g., 1.23e-5)", ""
        
        # =====================================================
        # CHECK 3: Number format (ERROR)
        # =====================================================
        try:
            lat_text = lat_text.replace(',', '.')
            lon_text = lon_text.replace(',', '.')
            
            lat = float(lat_text)
            lon = float(lon_text)
        except ValueError:
            return False, "Invalid number format. Use dot (.) as decimal separator", ""
        
        # =====================================================
        # CHECK 4: Valid range (ERROR)
        # =====================================================
        if lat < -90 or lat > 90:
            return False, f"Latitude must be between -90° and 90° (input: {lat}°)", ""
        
        if lon < -180 or lon > 180:
            return False, f"Longitude must be between -180° and 180° (input: {lon}°)", ""
        
        # =====================================================
        # CHECK 5: Deterministic swapped detection (WARNING ONLY)
        # =====================================================
        # Only trigger warning if values are clearly more suitable when swapped
        
        swapped_lat_valid = -90 <= lon <= 90
        swapped_lon_valid = -180 <= lat <= 180
        
        # If both swapped values are valid AND original looks suspicious
        if swapped_lat_valid and swapped_lon_valid:
            # Strong signal of swap:
            # latitude unusually large while longitude unusually small
            if abs(lat) > 90 * 0.8 and abs(lon) < 90:
                warning_msg = "Coordinates might be swapped (latitude/longitude reversed). Please double-check."
        
        # =====================================================
        # CHECK 6: Coordinates within DEM extent (ERROR for local DEM)
        # =====================================================
        if self.dem_source_combo.currentIndex() == 0:  # Local DEM
            try:
                dem_extent = self.controller.dem_layer.extent()
                if not dem_extent.contains(lon, lat):
                    return False, (f"Coordinates outside DEM layer extent\n"
                                   f"DEM Extent: ({dem_extent.xMinimum():.2f}, {dem_extent.yMinimum():.2f}) - "
                                   f"({dem_extent.xMaximum():.2f}, {dem_extent.yMaximum():.2f})"), ""
            except Exception as e:
                self._log(f"Failed to check DEM extent: {e}", Qgis.Warning)
        
        # =====================================================
        # CHECK 7: Minimum precision (WARNING)
        # =====================================================
        MIN_PRECISION = 4
        lat_precision = len(lat_text.split('.')[1]) if '.' in lat_text else 0
        lon_precision = len(lon_text.split('.')[1]) if '.' in lon_text else 0
        
        if lat_precision < MIN_PRECISION or lon_precision < MIN_PRECISION:
            accuracy = 111000 / (10 ** MIN_PRECISION)
            warning_msg = (f"Low coordinate precision (lat: {lat_precision}, lon: {lon_precision} decimals). "
                           f"Recommended minimum {MIN_PRECISION} decimals for ~{accuracy:.0f}m accuracy.")
        
        return True, "", warning_msg
    
    
    def _validate_rf_parameters(self):
        """
        Validate RF input parameters before running analysis
        Returns: (is_valid, error_message)
        """
        # =====================================================
        # CHECK 1: Antenna Height
        # =====================================================
        height = self.height_spin.value()
        if height <= 0:
            return False, "Antenna height must be greater than 0 meters."
        
        # =====================================================
        # CHECK 2: Vertical Beamwidth
        # =====================================================
        v_beamwidth = self.beamwidth_spin.value()
        if v_beamwidth <= 0:
            return False, "Vertical beamwidth must be greater than 0 degrees."
        if v_beamwidth > 30:
            return False, "Vertical beamwidth seems too high (>30°). Please check your input."
        
        # =====================================================
        # CHECK 3: Horizontal Beamwidth
        # =====================================================
        h_beamwidth = self.h_beamwidth_spin.value()
        if h_beamwidth <= 0:
            return False, "Horizontal beamwidth must be greater than 0 degrees."
        if h_beamwidth > 120:
            return False, "Horizontal beamwidth seems too high (>120°). Please check your input."
        
        # =====================================================
        # CHECK 4: Max Distance
        # =====================================================
        max_dist = self.distance_spin.value()
        if max_dist <= 0:
            return False, "Maximum distance must be greater than 0."
        if max_dist > 50000:
            return False, "Maximum distance is limited to 50 km (50000 m) for performance reasons."
        
        # =====================================================
        # CHECK 5: Azimuth
        # =====================================================
        azimuth = self.azimuth_spin.value()
        if azimuth < 0 or azimuth > 360:
            return False, "Azimuth must be between 0° and 360°."
        
        # =====================================================
        # CHECK 6: Mechanical Tilt
        # =====================================================
        mech_tilt = self.mech_tilt_spin.value()
        if mech_tilt < -5 or mech_tilt > 20:
            return False, "Mechanical tilt should be between -5° and 20° for realistic scenarios."
        
        # =====================================================
        # CHECK 7: Electrical Tilt
        # =====================================================
        elec_tilt = self.elec_tilt_spin.value()
        if elec_tilt < 0 or elec_tilt > 12:
            return False, "Electrical tilt should be between 0° and 12° for realistic scenarios."
        
        return True, ""
    
    
    
    def _update_distance_label(self):
        """Update distance label based on current unit and value"""
        is_metric = self.unit_combo.currentIndex() == 0
        value = self.distance_spin.value()
        
        if is_metric:
            self.distance_label.setText(f"{int(value)} m")
        else:
            self.distance_label.setText(f"{value:.2f} mi")
        
        
    def _rebuild_form_labels(self):
        """Rebuild form labels based on unit system"""
        # Hapus method ini karena kita tidak perlu rebuild entire form
        # Cukup update text di form layout yang sudah ada
        pass
        
    
    def _on_unit_changed(self):
        """Handle unit system change"""
        print(f"🎯 Unit changed to: {'Metric' if self.unit_combo.currentIndex()==0 else 'Imperial'}")
        is_metric = self.unit_combo.currentIndex() == 0
        
        # Block signals
        self.height_spin.blockSignals(True)
        self.distance_spin.blockSignals(True)
        self.distance_slider.blockSignals(True)
        
        # Ambil nilai dalam meter yang sudah tersimpan (paling update)
        current_height_m = getattr(self, 'height_in_meter', 40)
        current_distance_m = getattr(self, 'distance_in_meter', 3000)  # <-- SEKARANG AKAN TERUPDATE
        
        print(f"📏 Current height in meter: {current_height_m:.1f}m")
        print(f"📏 Current distance in meter: {current_distance_m:.0f}m")
        
        # Update spinbox ranges
        if is_metric:
            self.height_spin.setRange(0, 200)
            self.height_spin.setSingleStep(1)
            self.height_spin.setDecimals(0)
            self.height_spin.setSuffix(" m")
            self.height_spin.setValue(int(current_height_m))
            
            self.distance_spin.setRange(0, 10000)
            self.distance_spin.setSingleStep(10)
            self.distance_spin.setDecimals(0)
            self.distance_spin.setSuffix(" m")
            self.distance_spin.setValue(int(current_distance_m))
            
            self.distance_slider.setValue(int(current_distance_m))
            self.distance_label.setText(f"{int(current_distance_m)} m")
        else:
            # Metric to Imperial
            height_ft = current_height_m * 3.28084
            distance_mi = current_distance_m * 0.000621371
            
            self.height_spin.setRange(0, 656)
            self.height_spin.setSingleStep(3.28)
            self.height_spin.setDecimals(1)
            self.height_spin.setSuffix(" ft")
            self.height_spin.setValue(round(height_ft, 1))
            
            self.distance_spin.setRange(0, 6.2)
            self.distance_spin.setSingleStep(0.1)
            self.distance_spin.setDecimals(2)
            self.distance_spin.setSuffix(" mi")
            self.distance_spin.setValue(round(distance_mi, 2))
            
            self.distance_slider.setValue(int(current_distance_m))
            self.distance_label.setText(f"{round(distance_mi, 2):.2f} mi")
        
        # Nilai dalam meter sudah benar, tidak perlu diupdate lagi
        
        # Unblock signals
        self.height_spin.blockSignals(False)
        self.distance_spin.blockSignals(False)
        self.distance_slider.blockSignals(False)
        
        # Update labels
        self._update_unit_display()
        self._update_distance_label()  # <-- TAMBAHKAN
        
        # Update profile widget unit system
        if hasattr(self, 'profile_widget'):
            self.profile_widget.set_unit_system(is_metric)
            
        # =====================================================
        # TAMBAHKAN: UPDATE SUFFIX DI TAB OPTIMIZER
        # =====================================================
        suffix = " m" if is_metric else " mi"
        self.target_distance_spin.setSuffix(suffix)
        self.balanced_min_spin.setSuffix(suffix)
        self.balanced_max_spin.setSuffix(suffix)
    
    # =====================================================
    # RESET FUNCTIONALITY
    # =====================================================

    def _reset_to_defaults(self):
        """Reset all inputs to default values"""
        print("🔄 Resetting to defaults...")
        
        # Block signals selama reset
        self.height_spin.blockSignals(True)
        self.mech_tilt_spin.blockSignals(True)
        self.elec_tilt_spin.blockSignals(True)
        self.beamwidth_spin.blockSignals(True)
        self.h_beamwidth_spin.blockSignals(True)
        self.distance_spin.blockSignals(True)
        self.azimuth_spin.blockSignals(True)
        self.distance_slider.blockSignals(True)
        
        # Reset values berdasarkan unit yang aktif
        is_metric = self.unit_combo.currentIndex() == 0
        
        if is_metric:
            self.height_spin.setValue(RFDefaults.ANTENNA_HEIGHT)
            self.distance_spin.setValue(RFDefaults.MAX_DISTANCE)
            self.distance_slider.setValue(RFDefaults.MAX_DISTANCE)
            self.distance_label.setText(f"{RFDefaults.MAX_DISTANCE} m")
        else:
            # Convert to imperial
            height_ft = RFDefaults.ANTENNA_HEIGHT * 3.28084
            distance_mi = RFDefaults.MAX_DISTANCE * 0.000621371
            self.height_spin.setValue(round(height_ft, 1))
            self.distance_spin.setValue(round(distance_mi, 2))
            self.distance_slider.setValue(RFDefaults.MAX_DISTANCE)
            self.distance_label.setText(f"{round(distance_mi, 2):.2f} mi")
        
        self.mech_tilt_spin.setValue(RFDefaults.MECHANICAL_TILT)
        self.elec_tilt_spin.setValue(0)
        self.beamwidth_spin.setValue(RFDefaults.VERTICAL_BEAMWIDTH)
        self.h_beamwidth_spin.setValue(RFDefaults.HORIZONTAL_BEAMWIDTH)
        self.azimuth_spin.setValue(0)
        
        # Update total tilt
        self._update_total_tilt()
        
        # Reset coordinate inputs
        self.latitude_input.clear()
        self.longitude_input.clear()
        
        # Unblock signals
        self.height_spin.blockSignals(False)
        self.mech_tilt_spin.blockSignals(False)
        self.elec_tilt_spin.blockSignals(False)
        self.beamwidth_spin.blockSignals(False)
        self.h_beamwidth_spin.blockSignals(False)
        self.distance_spin.blockSignals(False)
        self.azimuth_spin.blockSignals(False)
        self.distance_slider.blockSignals(False)
        
        # =====================================================
        # CLEAR MAP AND PROFILE - IMPROVED
        # =====================================================
        
        # Clear map layers
        if hasattr(self, 'map_widget'):
            self.map_widget.clear_all_layers()
        
        # Clear profile plot completely (including intersections, beam fill, etc.)
        if hasattr(self, 'profile_widget'):
            self.profile_widget.clear_plot()  # <-- PANGGIL METHOD BARU
        
        # Reset elevation info
        if hasattr(self, 'elevation_info'):
            self.elevation_info.setText(
                "高程: 已加载(64个DEM采样点)。射频地形仿真待运行。"
            )
        
        # Reset status
        self.status_label.setText("Ready")
        
        # Reset impact tracking
        self._current_impact = None
        self.last_result = None
        
        # Reset slider color to default
        self._update_distance_slider_color(0)
        
        print("✅ Reset complete") 
    
    
    # =====================================================
    # RESET GRAPH VIEW
    # =====================================================
    
    def _reset_graph_view(self):
        """Reset graph to saved range from last analysis"""
        print("🔄 Resetting graph view...")
        
        if not hasattr(self, 'profile_widget') or not self.profile_widget:
            print("⚠️ Profile widget not available")
            return
        
        # Cek apakah ada saved range di profile_widget
        if hasattr(self.profile_widget, '_saved_range'):
            saved = self.profile_widget._saved_range
            self.profile_widget.plot_item.setXRange(saved['x'][0], saved['x'][1], padding=0)
            self.profile_widget.plot_item.setYRange(saved['y'][0], saved['y'][1], padding=0)
            print(f"✅ Restored saved range: X {saved['x'][0]:.1f}-{saved['x'][1]:.1f}, Y {saved['y'][0]:.1f}-{saved['y'][1]:.1f}")
        else:
            print("⚠️ No saved range available, using fallback calculation")
            # Fallback ke logika lama jika tidak ada saved range
            self._reset_graph_view_fallback()
        
        self.profile_widget.plot.enableAutoRange(False)
    
    def _reset_graph_view_fallback(self):
        """Fallback method jika tidak ada saved range"""
        if not hasattr(self, 'last_result') or not self.last_result:
            print("⚠️ No analysis results available")
            return
        
        distances = self.last_result.get("distances", [])
        elevations = self.last_result.get("elevations", [])
        antenna_height = self.height_spin.value()
        is_metric = self.unit_combo.currentIndex() == 0
        
        if not distances or not elevations:
            print("⚠️ No terrain data available")
            return
        
        if is_metric:
            max_d = max(distances)
            min_e = min(elevations)
            max_e = max(elevations) + antenna_height + 10
            self.profile_widget.plot_item.setXRange(0, max_d, padding=0)
            self.profile_widget.plot_item.setYRange(min_e - 20, max_e, padding=0)
        else:
            # Imperial: konversi ke feet
            max_d_ft = max(distances) * 3.28084
            elevations_ft = [e * 3.28084 for e in elevations]
            ground_ft = elevations_ft[0]
            antenna_ft = antenna_height * 3.28084
            
            min_terrain_ft = min(elevations_ft)
            max_terrain_ft = max(elevations_ft)
            tower_top_ft = ground_ft + antenna_ft
            
            min_range_ft = max(0, min_terrain_ft - 50)
            max_range_ft = max(max_terrain_ft, tower_top_ft) + 50
            
            self.profile_widget.plot_item.setXRange(0, max_d_ft, padding=0)
            self.profile_widget.plot_item.setYRange(min_range_ft, max_range_ft, padding=0)
            print(f"📊 Fallback Y range: {min_range_ft:.1f} - {max_range_ft:.1f} ft")
    
    
    # =====================================================
    # TILT OPTIMIZER METHODS
    # =====================================================
    
    def _update_criteria_check(self):
        """Ensure at least one optimization criterion is selected"""
        if not any([
            self.cb_max_coverage.isChecked(),
            self.cb_target_distance.isChecked(),
            self.cb_balanced.isChecked()
        ]):
            # If none selected, re-select max coverage
            self.cb_max_coverage.setChecked(True)
    
    def _update_export_button_text(self, checked):
        """Update export button text based on collapse state"""
        if checked:
            self.export_expand_btn.setText("▲ 导出选项(3种格式)")
        else:
            self.export_expand_btn.setText("▼ 导出选项(3种格式)")
            
    
    def _start_optimization(self):
        """
        Start tilt optimization process in background thread
        """
        print("🚀 Starting tilt optimization...")
        
        # Reset progress
        self.optimize_progress.setValue(0)
        self.optimize_status.setText("Starting optimization...")
        self.optimize_best.setText("Best so far: —")
        
        # =====================================================
        # CATAT WAKTU MULAI DENGAN PERFORMANCE COUNTER (AKURAT)
        # =====================================================
        
        # Gunakan time.perf_counter() untuk akurasi tinggi (nanosecond)
        self._optimize_start_perf = time.perf_counter()
        self._optimize_start_time = datetime.now()
        

        start_time_str = self._optimize_start_time.strftime("%H:%M:%S")
        print(f"⏱️ Optimization started at {start_time_str}")
        print(f"⏱️ Performance counter started: {self._optimize_start_perf:.6f}")
        
        # =====================================================
        # CLEANUP EXISTING THREAD - CRITICAL FIX
        # =====================================================
        
        # Jika ada thread lama yang masih running, terminate dengan aman
        if hasattr(self, 'optimize_thread') and self.optimize_thread and self.optimize_thread.isRunning():
            print("⚠️ Existing optimization thread detected, cleaning up...")
            
            # Signal worker untuk cancel
            if hasattr(self, 'optimize_worker') and self.optimize_worker:
                self.optimize_worker.cancel()
            
            # Disconnect all signals
            try:
                self.optimize_thread.started.disconnect()
                self.optimize_thread.finished.disconnect()
            except:  # nosec
                pass
            
            # Quit and wait (with timeout)
            self.optimize_thread.quit()
            if not self.optimize_thread.wait(3000):  # Wait max 3 seconds
                print("⚠️ Thread did not finish gracefully, terminating...")
                self.optimize_thread.terminate()
                self.optimize_thread.wait()
            
            # Clean references
            self.optimize_thread = None
            self.optimize_worker = None
            
            # Force garbage collection
            import gc
            gc.collect()
        
        if not self.controller:
            self.status_label.setText("Controller not connected")
            return
        
        # Disable UI controls
        self.start_optimize_btn.setEnabled(False)
        self.cancel_optimize_btn.setEnabled(True)
        self.apply_optimize_btn.setEnabled(False)
        self.tab_widget.setEnabled(False)
        
        # Get ranges
        mech_min, mech_max = self.mech_range.get_values()
        elec_min, elec_max = self.elec_range.get_values()
        
        
        # Get criteria
        criteria = {}
        if self.cb_max_coverage.isChecked():
            criteria['max_coverage'] = True
        
        if self.cb_target_distance.isChecked():
            target = self.target_distance_spin.value()
            if self.unit_combo.currentIndex() != 0:  # Imperial
                target = self._convert_to_metric(target, 'distance')
            criteria['target_distance'] = target
        
        if self.cb_balanced.isChecked():
            min_d = self.balanced_min_spin.value()
            max_d = self.balanced_max_spin.value()
            if self.unit_combo.currentIndex() != 0:  # Imperial
                min_d = self._convert_to_metric(min_d, 'distance')
                max_d = self._convert_to_metric(max_d, 'distance')
            criteria['balanced'] = (min_d, max_d)
            
        
                
        # =====================================================
        # VALIDASI: Pastikan setidaknya satu criteria dipilih
        # =====================================================
        if not any([
            self.cb_max_coverage.isChecked(),
            self.cb_target_distance.isChecked(),
            self.cb_balanced.isChecked()
        ]):
            QMessageBox.warning(
                self, 
                "No Optimization Criteria Selected",
                "Tilt optimization requires at least one criterion to find the best combination.\n\n"
                "Please select one or more of the following:\n"
                "• Maximum Coverage - Finds the longest possible coverage distance\n"
                "• Target Distance - Aims for a specific coverage distance\n"
                "• Balanced Coverage - Keeps coverage within a preferred range"
            )
            # Re-enable UI
            self.start_optimize_btn.setEnabled(True)
            self.cancel_optimize_btn.setEnabled(False)
            self.tab_widget.setEnabled(True)
            self.optimize_progress.setValue(0)
            self.optimize_status.setText("Optimization cancelled - no criteria selected")
            return
        

        # Prepare parameters - AMBIL DARI UI, BUKAN HARDCODED
        params = {
            "height": self.height_spin.value(),
            "mech": 0,  # Will be set in loop
            "elec": 0,  # Will be set in loop
            "beamwidth": self.beamwidth_spin.value(),
            "azimuth": self.azimuth_spin.value(),
            "distance": self.distance_spin.value(),
            "lat": float(self.latitude_input.text() or 0),
            "lon": float(self.longitude_input.text() or 0),
            "dem_source": self.dem_source_combo.currentIndex(),
            "optimization_mode": self.mode_combo.currentIndex()  # 0=Precise, 1=Smart, 2=Fast
        }
        
        # Reset progress
        self.optimize_progress.setValue(0)
        self.optimize_status.setText("Starting optimization...")
        self.optimize_best.setText("Best so far: —")
        
        # =====================================================
        # CREATE NEW WORKER AND THREAD
        # =====================================================
        
        # Create worker (without thread first)
        self.optimize_worker = OptimizeWorker(
            self.controller, params,
            (mech_min, mech_max), (elec_min, elec_max),
            criteria,
            is_metric=(self.unit_combo.currentIndex() == 0)  # <-- TAMBAHKAN INI
        )
        
        # Create QThread
        self.optimize_thread = QThread()
        
        # Move worker to thread
        self.optimize_worker.moveToThread(self.optimize_thread)
        
        # =====================================================
        # CONNECT SIGNALS (SINGLE CONNECTION ONLY)
        # =====================================================
        
        # Progress signals
        self.optimize_worker.progress.connect(self._update_optimization_progress)
        
        # Error signal - TAMBAHKAN
        self.optimize_worker.error.connect(self._on_optimization_error)

        
        # Finished signal - gunakan lambda untuk cleanup yang aman
        self.optimize_worker.finished.connect(
            lambda top5: self._optimization_finished_clean(top5)
        )
        
        # Cancelled signal
        self.optimize_worker.cancelled.connect(self._optimization_cancelled_clean)

        
        # Thread started
        self.optimize_thread.started.connect(
            lambda: print("🔥 THREAD STARTED SIGNAL EMITTED")
        )
        self.optimize_thread.started.connect(self.optimize_worker.run)
        
        # Thread finished - cleanup
        self.optimize_thread.finished.connect(self._cleanup_optimization_thread)
        
        # Start thread
        self.optimize_thread.start()
        
        print(f"✅ Thread started: {self.optimize_thread.isRunning()}")
        print(f"✅ Worker thread: {self.optimize_worker.thread()}")
        
        # Timer untuk mengecek apakah worker mulai berjalan
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1000, self._check_optimization_started)
    
    
    def _check_optimization_started(self):
        """Check if optimization has started running"""
        if self.optimize_progress.value() == 0:
            print("⚠️ Optimization hasn't started after 1 second!")
            if hasattr(self, 'optimize_worker'):
                print(f"⚠️ Worker still exists: {self.optimize_worker}")
            if hasattr(self, 'optimize_thread'):
                print(f"⚠️ Thread is running: {self.optimize_thread.isRunning()}")
    
    
    def _update_optimization_progress(self, percent, status, best):
        """Update progress bar and status during optimization"""
        self.optimize_progress.setValue(percent)
        self.optimize_status.setText(status)
        
        if best:
            mech = best.get('mech', 0)
            elec = best.get('elec', 0)
            dist = best.get('distance', 0)
            
            # GUNAKAN HELPER METHOD
            dist_text = self._format_distance(dist)
            
            self.optimize_best.setText(f"Best so far: M:{mech}° E:{elec}° → {dist_text}")
            
        
    def _optimization_finished_clean(self, top5):
        """
        Handle optimization completion with safe cleanup
        """
        print("✅ Optimization finished (clean handler)")
        
        # Disable cancel button
        self.cancel_optimize_btn.setEnabled(False)
        
        # =====================================================
        # SIMPAN SEMUA HASIL, BUKAN HANYA TOP 5 (BARIS BARU)
        # =====================================================
        if hasattr(self.optimize_worker, '_all_results') and self.optimize_worker._all_results:
            self._all_optimization_results = self.optimize_worker._all_results
            print(f"📊 Menyimpan {len(self._all_optimization_results)} kombinasi untuk export")
        else:
            # Fallback: jika worker tidak menyimpan semua hasil, gunakan top5 saja
            self._all_optimization_results = top5
            print(f"⚠️ Worker tidak menyimpan semua hasil, fallback ke {len(top5)} kombinasi")
        
        # Simpan metadata untuk export
        self._optimization_metadata = {
            'site_parameters': {
                'latitude': self.latitude_input.text(),
                'longitude': self.longitude_input.text(),
                'antenna_height': self.height_spin.value(),
                'azimuth': self.azimuth_spin.value(),
                'vertical_beamwidth': self.beamwidth_spin.value(),
                'horizontal_beamwidth': self.h_beamwidth_spin.value(),
                'max_distance': self.distance_spin.value()
            },
            'optimization_parameters': {
                'mode': self.mode_combo.currentText(),
                'mode_index': self.mode_combo.currentIndex(),
                'mech_range': self.mech_range.get_values(),
                'elec_range': self.elec_range.get_values(),
                'max_coverage': self.cb_max_coverage.isChecked(),
                'target_distance': {
                    'enabled': self.cb_target_distance.isChecked(),
                    'value': self.target_distance_spin.value()
                },
                'balanced': {
                    'enabled': self.cb_balanced.isChecked(),
                    'min': self.balanced_min_spin.value(),
                    'max': self.balanced_max_spin.value()
                }
            },
            'unit_system': 'Metric' if self.unit_combo.currentIndex() == 0 else 'Imperial',
            'total_combinations': len(self._all_optimization_results)
        }
        
        # Process results untuk UI (tetap tampilkan top 5)
        if not top5:
            if hasattr(self.optimize_worker, '_result_cache') and self.optimize_worker._result_cache:
                # Ada cache tapi tidak ada yang valid?
                self.optimize_result_label.setText(
                    "No Valid Tilt Combinations Found\n\n"
                    "All tested mechanical/electrical tilt combinations resulted in invalid coverage distances.\n\n"
                    "Possible causes:\n"
                    "• The DEM layer does not cover the area around the site\n"
                    "• The site location is in water where elevation data may be missing\n"
                    "• The tilt range is too extreme for the terrain\n\n"
                    "Suggestions:\n"
                    "• Check if the DEM layer covers your site location\n"
                    "• Try switching to Open-Meteo online source\n"
                    "• Adjust the mechanical/electrical tilt ranges"
                )
            else:
                self.optimize_result_label.setText(
                    "Optimization Failed\n\n"
                    "The optimization process did not return any results.\n\n"
                    "Possible causes:\n"
                    "• Network connection issues (if using Open-Meteo)\n"
                    "• DEM layer access problems\n"
                    "• Unexpected error in the analysis engine\n\n"
                    "Please check the QGIS Log Messages panel for detailed error information."
                )
            
            self.start_optimize_btn.setEnabled(True)
            self.tab_widget.setEnabled(True)
            self.optimize_status.setText("Optimization failed - please check settings")
            self.optimize_progress.setValue(100)
            return
        
        # Display best result
        best = top5[0]
        mech = best['mech']
        elec = best['elec']
        dist = best['distance']
        
        # Format distance
        is_metric = self.unit_combo.currentIndex() == 0
        if is_metric:
            if dist >= 1000:
                dist_text = f"{dist/1000:.2f} km"
            else:
                dist_text = f"{dist:.0f} m"
        else:
            dist_ft = dist * 3.28084
            if dist_ft >= 5280:
                dist_text = f"{dist_ft/5280:.2f} mi"
            else:
                dist_text = f"{dist_ft:.0f} ft"
        
        self.optimize_result_label.setText(
            f"Optimal: Mechanical {mech}°, Electrical {elec}° → {dist_text}"
        )
        
        # Store best result for apply button
        self._best_optimize_result = (mech, elec)
        self.apply_optimize_btn.setEnabled(True)
        
        # Update top 5 di UI
        for i, result in enumerate(top5[:5]):
            mech = result['mech']
            elec = result['elec']
            dist = result['distance']
            score = result['score']
            lower = result.get('lower_footprint')
            upper = result.get('upper_footprint')
            
            dist_text = self._format_distance(dist)
            
            if (lower is not None and upper is not None and 
                lower > 0 and upper > 0):
                lower_text = self._format_distance(lower)
                upper_text = self._format_distance(upper)
                footprint_text = f" [FP: {lower_text} – {upper_text}]"
            else:
                footprint_text = ""
            
            self.top5_labels[i].setText(f"{i+1}. M:{mech}° E:{elec}° → {dist_text}{footprint_text} (score: {score:.0f})")
        
        # Auto-expand top 5
        self.top5_expand_btn.setChecked(True)
        self.top5_widget.setVisible(True)
        
        self.optimize_status.setText("Optimization complete")
        self.optimize_progress.setValue(100)
        
        # =====================================================
        # TAMPILKAN WAKTU AKURAT DI STATUS
        # =====================================================
        
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        ms_str = f"{now.microsecond//1000:03d}"
        
        # =====================================================
        # TAMBAHKAN DONASI MESSAGE (RANDOM) - PATCH UTAMA
        # =====================================================
        import random
        
        
        donation_messages = ["本结果由「扇区Tilt分析」生成 · 垂直波瓣一键分析"]

        donation_msg = random.choice(donation_messages)  # nosec
        
        # Hitung durasi dari start menggunakan perf_counter
        if hasattr(self, '_optimize_start_perf'):
            perf_end = time.perf_counter()
            duration = perf_end - self._optimize_start_perf
            
            # Format durasi dengan milidetik
            if duration < 60:
                # Kurang dari 1 menit: tampilkan detik dengan 1 desimal
                status_text = f"✅ Optimization completed at {time_str}.{ms_str} (took {duration:.1f}s) | {donation_msg}"
                print(f"✅ UI Update - Duration: {duration:.3f}s (perf_counter)")
            else:
                # Lebih dari 1 menit: tampilkan menit:detik
                minutes = int(duration // 60)
                seconds = duration % 60
                status_text = f"✅ Optimization completed at {time_str}.{ms_str} (took {minutes}m {seconds:.1f}s) | {donation_msg}"
        elif hasattr(self, '_optimize_start_time'):
            # Fallback ke datetime jika perf_counter tidak ada
            duration = (now - self._optimize_start_time).total_seconds()
            status_text = f"✅ Optimization completed at {time_str}.{ms_str} (took {duration:.1f}s) | {donation_msg}"
        else:
            status_text = f"✅ Optimization completed at {time_str}.{ms_str} | {donation_msg}"
        
        # Set status text dengan donasi
        self.status_label.setText(status_text)
        
        # Re-enable UI
        self.start_optimize_btn.setEnabled(True)
        self.tab_widget.setEnabled(True)
        
        # =====================================================
        # AKTIFKAN TOMBOL EXPORT
        # =====================================================
        self.export_csv_btn.setEnabled(True)
        self.export_excel_btn.setEnabled(True)
        self.export_json_btn.setEnabled(True)
        
        
        # NOTE: Thread cleanup will be handled by _cleanup_optimization_thread    
        
        

    def _optimization_cancelled_clean(self):
        """
        Handle optimization cancellation with safe cleanup
        """
        print("🛑 Optimization cancelled (clean handler)")
        
        self.optimize_status.setText("Optimization cancelled")
        self.optimize_progress.setValue(0)
        
        # Disable cancel button immediately
        self.cancel_optimize_btn.setEnabled(False)
        
        # Re-enable UI
        self.start_optimize_btn.setEnabled(True)
        self.tab_widget.setEnabled(True)
        
        # NOTE: Thread cleanup will be handled by _cleanup_optimization_thread
        
    
    def _on_optimization_error(self, error_msg):
        """Handle optimization error dengan reset yang lebih baik"""
        print(f"❌ Optimization error: {error_msg}")
        
        # Reset progress bar
        self.optimize_progress.setValue(0)
        self.optimize_progress.setFormat("Error - %p%")
        
        # Update status dengan error message
        truncated_error = error_msg[:100] + "..." if len(error_msg) > 100 else error_msg
        self.optimize_status.setText(f"❌ Error: {truncated_error}")
        
        # Clear best result
        self.optimize_best.setText("Best so far: —")
        
        # Disable cancel button
        self.cancel_optimize_btn.setEnabled(False)
        
        # Re-enable UI
        self.start_optimize_btn.setEnabled(True)
        self.tab_widget.setEnabled(True)
        
        # =====================================================
        # LOG ERROR DETAIL KE QGIS MESSAGE LOG
        # =====================================================
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(
            f"Optimization error: {error_msg}\n{traceback.format_exc()}",
            "扇区Tilt分析",
            Qgis.Critical
        )
        
        # Show message box dengan opsi untuk melihat log
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("Optimization Error")
        msg_box.setText(f"An error occurred during optimization:\n\n{error_msg}")
        msg_box.setInformativeText("Check QGIS Log Messages panel for detailed error information.")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()
        

    def _cleanup_optimization_thread(self):
        """
        Clean up optimization thread safely
        """
        print("🧹 Cleaning up optimization thread...")
        
        if hasattr(self, 'optimize_thread') and self.optimize_thread:
            if self.optimize_thread.isRunning():
                self.optimize_thread.quit()
                if not self.optimize_thread.wait(3000):
                    self.optimize_thread.terminate()
                    self.optimize_thread.wait()
        
        # Disconnect signals to prevent double connections next time
        if hasattr(self, 'optimize_worker') and self.optimize_worker:
            try:
                self.optimize_worker.progress.disconnect()
                self.optimize_worker.finished.disconnect()
                self.optimize_worker.cancelled.disconnect()
            except:  # nosec
                pass
        
        if hasattr(self, 'optimize_thread') and self.optimize_thread:
            try:
                self.optimize_thread.started.disconnect()
                self.optimize_thread.finished.disconnect()
            except:  # nosec
                pass
        
        # Schedule deletion (Qt will handle this safely)
        if hasattr(self, 'optimize_worker') and self.optimize_worker:
            self.optimize_worker.deleteLater()
        
        if hasattr(self, 'optimize_thread') and self.optimize_thread:
            self.optimize_thread.deleteLater()
        
        # Clear references
        self.optimize_worker = None
        self.optimize_thread = None
        
        # =====================================================
        # TAMBAHKAN: FORCE GARBAGE COLLECTION
        # =====================================================
        import gc
        gc.collect()
        
        print("✅ Optimization thread cleaned up")
    
            
    
    def _cancel_optimization(self):
        """Cancel ongoing optimization"""
        print("🛑 Cancelling optimization...")
        if self.optimize_worker:
            self.optimize_worker.cancel()
        self.cancel_optimize_btn.setEnabled(False)
        self.optimize_status.setText("Cancelling...")
        
            
    
    def _apply_best_tilt(self):
        """Apply best tilt result to main dialog"""
        if hasattr(self, '_best_optimize_result'):
            mech, elec = self._best_optimize_result
            
            # Switch to Basic RF tab
            self.tab_widget.setCurrentIndex(0)
            
            # Update both tilt values
            self.mech_tilt_spin.setValue(mech)
            self.elec_tilt_spin.setValue(elec)
            
            # Update total tilt
            self._update_total_tilt()
            
            self.status_label.setText(f"Applied optimal tilt: Mech {mech}°, Elec {elec}°")
            
            # Run analysis with new tilt
            self.run_analysis()
    

    
    
    def _export_optimization_results(self, format_type="csv"):
        """
        Export ALL optimization results to CSV or Excel file
        """
        if not hasattr(self, '_all_optimization_results') or not self._all_optimization_results:
            QMessageBox.warning(
                self, 
                "Export Failed", 
                "No optimization results available for export.\n\n"
                "Please run a tilt optimization first before attempting to export results."
            )
            return
        
        # =====================================================
        # GUNAKAN SEMUA HASIL, BUKAN HANYA TOP 5
        # =====================================================
        all_results = self._all_optimization_results
        metadata = getattr(self, '_optimization_metadata', {})
        
        # Sort results by score (best first) untuk tampilan yang rapi
        sorted_results = sorted(all_results, key=lambda x: x['score'], reverse=True)
        
        print(f"📊 Exporting {len(sorted_results)} combinations to {format_type.upper()}")
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if format_type == "csv":
                import csv
                from PyQt5.QtWidgets import QFileDialog
                import os
                
                # Default ke Documents folder
                docs_folder = self._get_documents_folder()
                default_filename = os.path.join(docs_folder, f"tilt_optimization_results_{timestamp}.csv")
                
                # Tampilkan dialog save file
                filename, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save CSV File",
                    default_filename,
                    "CSV Files (*.csv)"
                )
                
                if not filename:
                    self.status_label.setText("Export cancelled")
                    return
                
                try:
                    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:

                        # =====================================================
                        # HEADER DONASI (PROFESIONAL)
                        # =====================================================
                        csvfile.write(f"# 扇区Tilt分析 - 垂直波瓣分析结果\n")
                        csvfile.write(f"# 本结果由「扇区Tilt分析」插件生成\n")
                        csvfile.write(f"# Export Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        csvfile.write(f"# Export Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        
                        # Site Parameters
                        site_params = metadata.get('site_parameters', {})
                        csvfile.write(f"# Site: {site_params.get('latitude', '')}, {site_params.get('longitude', '')}\n")
                        csvfile.write(f"# Antenna Height: {site_params.get('antenna_height', '')} m\n")
                        csvfile.write(f"# Azimuth: {site_params.get('azimuth', '')}°\n")
                        csvfile.write(f"# Vertical Beamwidth: {site_params.get('vertical_beamwidth', '')}°\n")
                        csvfile.write(f"# Horizontal Beamwidth: {site_params.get('horizontal_beamwidth', '')}°\n")
                        csvfile.write(f"# Max Distance: {site_params.get('max_distance', '')} m\n")
                        
                        # Optimization Parameters
                        opt_params = metadata.get('optimization_parameters', {})
                        mech_range = opt_params.get('mech_range', [0, 10])
                        elec_range = opt_params.get('elec_range', [0, 12])
                        csvfile.write(f"# Mechanical Range: {mech_range[0]}° - {mech_range[1]}°\n")
                        csvfile.write(f"# Electrical Range: {elec_range[0]}° - {elec_range[1]}°\n")
                        csvfile.write(f"# Optimization Mode: {opt_params.get('mode', '')}\n")
                        csvfile.write(f"# Max Coverage: {'Yes' if opt_params.get('max_coverage') else 'No'}\n")
                        
                        target = opt_params.get('target_distance', {})
                        csvfile.write(f"# Target Distance: {target.get('value', '')} m {'(enabled)' if target.get('enabled') else '(disabled)'}\n")
                        
                        balanced = opt_params.get('balanced', {})
                        if balanced.get('enabled'):
                            csvfile.write(f"# Balanced Range: {balanced.get('min', '')} - {balanced.get('max', '')} m (enabled)\n")
                        else:
                            csvfile.write(f"# Balanced Range: disabled\n")
                        
                        csvfile.write(f"# Unit System: {metadata.get('unit_system', 'Metric')}\n")
                        csvfile.write(f"# Total Combinations: {len(sorted_results)}\n")
                        csvfile.write("#" + "="*80 + "\n")
                        
                        # Header kolom
                        fieldnames = ['Rank', 'Mechanical_Tilt', 'Electrical_Tilt', 'Total_Tilt',
                                     'Main_Beam_Distance_m', 'Lower_Footprint_m', 
                                     'Upper_Footprint_m', 'Score']
                        
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        
                        # Write ALL results (sudah sorted by score)
                        for i, res in enumerate(sorted_results):
                            dist = res['distance']
                            lower = res.get('lower_footprint')
                            upper = res.get('upper_footprint')
                            
                            writer.writerow({
                                'Rank': i+1,
                                'Mechanical_Tilt': res['mech'],
                                'Electrical_Tilt': res['elec'],
                                'Total_Tilt': res['mech'] + res['elec'],
                                'Main_Beam_Distance_m': f"{dist:.1f}",
                                'Lower_Footprint_m': f"{lower:.1f}" if lower else 'N/A',
                                'Upper_Footprint_m': f"{upper:.1f}" if upper else 'N/A',
                                'Score': f"{res['score']:.1f}"
                            })
                    
                    self.status_label.setText(f"✅ Exported {len(sorted_results)} combinations to {os.path.basename(filename)}")
                    
                    # Tanya user apakah ingin membuka folder
                    reply = QMessageBox.question(
                        self, 
                        "Export Successful", 
                        f"Results saved to:\n{filename}\n\nOpen containing folder?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(filename)))
                    
                except Exception as e:
                    QMessageBox.critical(self, "Export Failed", f"Error saving file:\n{str(e)}")
                
            elif format_type == "excel":
                # =====================================================
                # EXCEL EXPORT - GUNAKAN SEMUA DATA
                # =====================================================
                from PyQt5.QtWidgets import QFileDialog, QApplication
                import os
                
                # Cek ketersediaan xlsxwriter
                try:
                    import xlsxwriter
                    XLSXWRITER_AVAILABLE = True
                except ImportError:
                    XLSXWRITER_AVAILABLE = False
                
                if not XLSXWRITER_AVAILABLE:
                    # ... kode instalasi yang sudah ada ...
                    return
                
                # Default ke Documents folder
                docs_folder = self._get_documents_folder()
                default_filename = os.path.join(docs_folder, f"tilt_optimization_results_{timestamp}.xlsx")
                
                # Tampilkan dialog save file
                filename, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Excel File",
                    default_filename,
                    "Excel Files (*.xlsx)"
                )
                
                if not filename:
                    self.status_label.setText("Export cancelled")
                    return
                
                try:
                    # Buat Excel dengan xlsxwriter
                    workbook = xlsxwriter.Workbook(filename)
                    
                    # =====================================================
                    # SHEET 1: ALL OPTIMIZATION RESULTS
                    # =====================================================
                    worksheet = workbook.add_worksheet("Results")
                    
                    # Define formats
                    header_format = workbook.add_format({
                        'bold': True,
                        'font_color': 'white',
                        'bg_color': '#0C6075',
                        'align': 'center',
                        'valign': 'vcenter',
                        'border': 1
                    })
                    
                    cell_format = workbook.add_format({
                        'align': 'center',
                        'valign': 'vcenter',
                        'border': 1
                    })
                    
                    number_format = workbook.add_format({
                        'align': 'center',
                        'valign': 'vcenter',
                        'border': 1,
                        'num_format': '0.0'
                    })
                    
                    # Headers
                    headers = ['Rank', 'Mechanical Tilt (°)', 'Electrical Tilt (°)', 'Total Tilt (°)',
                              'Main Beam Distance (m)', 'Lower Footprint (m)', 
                              'Upper Footprint (m)', 'Score']
                    
                    for col, header in enumerate(headers):
                        worksheet.write(0, col, header, header_format)
                        worksheet.set_column(col, col, 18)  # Width 18
                    
                    # Write ALL results
                    for row, res in enumerate(sorted_results, 1):
                        worksheet.write(row, 0, row, cell_format)  # Rank
                        worksheet.write(row, 1, res['mech'], cell_format)
                        worksheet.write(row, 2, res['elec'], cell_format)
                        worksheet.write(row, 3, res['mech'] + res['elec'], cell_format)
                        worksheet.write(row, 4, res['distance'], number_format)
                        
                        lower = res.get('lower_footprint')
                        upper = res.get('upper_footprint')
                        worksheet.write(row, 5, lower if lower else "N/A", cell_format)
                        worksheet.write(row, 6, upper if upper else "N/A", cell_format)
                        worksheet.write(row, 7, res['score'], number_format)
                    
                    # Freeze header row
                    worksheet.freeze_panes(1, 0)
                    
                    # =====================================================
                    # SHEET 2: METADATA & PARAMETERS
                    # =====================================================
                    meta_sheet = workbook.add_worksheet("Metadata")
                    
                    # Format untuk metadata
                    meta_header = workbook.add_format({
                        'bold': True,
                        'bg_color': '#E9EEF2',
                        'align': 'left',
                        'valign': 'vcenter',
                        'border': 1
                    })
                    
                    meta_cell = workbook.add_format({
                        'align': 'left',
                        'valign': 'vcenter',
                        'border': 1
                    })
                    
                    meta_sheet.set_column(0, 0, 25)
                    meta_sheet.set_column(1, 1, 35)
                    
                    # Title
                    meta_sheet.merge_range('A1:B1', 'EXPORT METADATA', 
                                           workbook.add_format({'bold': True, 'bg_color': '#0C6075', 
                                                               'font_color': 'white', 'align': 'center'}))
                    
                    # Build metadata list dari dictionary yang sudah disimpan
                    site_params = metadata.get('site_parameters', {})
                    opt_params = metadata.get('optimization_parameters', {})
                    mech_range = opt_params.get('mech_range', [0, 10])
                    elec_range = opt_params.get('elec_range', [0, 12])
                    target = opt_params.get('target_distance', {})
                    balanced = opt_params.get('balanced', {})
                    
                    metadata_rows = [
                        ["Export Time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                        ["Plugin Version", "扇区Tilt分析 0.2.0"],
                        ["", ""],
                        ["", ""],
                        ["SITE PARAMETERS", ""],
                        ["Latitude", site_params.get('latitude', '')],
                        ["Longitude", site_params.get('longitude', '')],
                        ["Antenna Height (m)", str(site_params.get('antenna_height', ''))],
                        ["Azimuth (°)", str(site_params.get('azimuth', ''))],
                        ["Vertical Beamwidth (°)", str(site_params.get('vertical_beamwidth', ''))],
                        ["Horizontal Beamwidth (°)", str(site_params.get('horizontal_beamwidth', ''))],
                        ["Max Distance (m)", str(site_params.get('max_distance', ''))],
                        ["", ""],
                        ["OPTIMIZATION PARAMETERS", ""],
                        ["Mode", opt_params.get('mode', '')],
                        ["Mechanical Range", f"{mech_range[0]}° - {mech_range[1]}°"],
                        ["Electrical Range", f"{elec_range[0]}° - {elec_range[1]}°"],
                        ["Max Coverage", "Yes" if opt_params.get('max_coverage') else "No"],
                        ["Target Distance", f"{target.get('value', '')} m" + (" (enabled)" if target.get('enabled') else " (disabled)")],
                        ["Balanced Range", f"{balanced.get('min', '')} - {balanced.get('max', '')} m" + (" (enabled)" if balanced.get('enabled') else " (disabled)")],
                        ["Unit System", metadata.get('unit_system', 'Metric')],
                        ["", ""],
                        ["STATISTICS", ""],
                        ["Total Combinations", str(len(sorted_results))],
                        ["Best Score", f"{sorted_results[0]['score']:.1f}" if sorted_results else "N/A"],
                        ["Best Combination", f"M{sorted_results[0]['mech']}° E{sorted_results[0]['elec']}°" if sorted_results else "N/A"],
                        ["Best Distance", f"{sorted_results[0]['distance']:.1f} m" if sorted_results else "N/A"]
                    ]
                    
                    for row, (key, value) in enumerate(metadata_rows, 2):  # Start from row 2
                        if key == "":
                            continue
                        if key in ["SITE PARAMETERS", "OPTIMIZATION PARAMETERS", "STATISTICS", "EXPORT METADATA"]:
                            meta_sheet.write(row, 0, key, workbook.add_format({'bold': True, 'bg_color': '#E9EEF2'}))
                            meta_sheet.write(row, 1, "", meta_cell)
                        else:
                            meta_sheet.write(row, 0, key, meta_header)
                            meta_sheet.write(row, 1, str(value), meta_cell)
                    
                    workbook.close()
                    
                    self.status_label.setText(f"✅ Exported {len(sorted_results)} combinations to {os.path.basename(filename)}")
                    
                    # Tanya user apakah ingin membuka folder
                    reply = QMessageBox.question(
                        self, 
                        "Export Successful", 
                        f"Results saved to:\n{filename}\n\nOpen containing folder?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(filename)))
                    
                except Exception as e:
                    QMessageBox.critical(self, "Export Failed", f"Error saving file:\n{str(e)}")
        
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error saving file:\n{str(e)}")


    
    
    def _export_optimization_json(self):
        """
        Export ALL optimization results to JSON file with complete metadata
        """
        if not hasattr(self, '_all_optimization_results') or not self._all_optimization_results:
            QMessageBox.warning(
                self, 
                "Export Failed", 
                "No optimization results available for export.\n\n"
                "Please run a tilt optimization first."
            )
            return
        
        from PyQt5.QtWidgets import QFileDialog
        import os
        import json
        
        # =====================================================
        # GUNAKAN SEMUA HASIL
        # =====================================================
        all_results = self._all_optimization_results
        metadata = getattr(self, '_optimization_metadata', {})
        
        # Sort results by score
        sorted_results = sorted(all_results, key=lambda x: x['score'], reverse=True)
        
        print(f"📊 Exporting {len(sorted_results)} combinations to JSON")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Default ke Documents folder
        docs_folder = self._get_documents_folder()
        default_filename = os.path.join(docs_folder, f"tilt_optimization_results_{timestamp}.json")
        
        # Tampilkan dialog save file
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save JSON File",
            default_filename,
            "JSON Files (*.json)"
        )
        
        if not filename:
            self.status_label.setText("Export cancelled")
            return
        
        # Prepare enhanced data for JSON
        export_data = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "plugin_version": "1.0.0",
                "export_type": "tilt_optimization_results",
                "total_combinations": len(sorted_results)
            },
            "site_parameters": metadata.get('site_parameters', {}),
            "optimization_parameters": metadata.get('optimization_parameters', {}),
            "unit_system": metadata.get('unit_system', 'Metric'),
            "summary": {
                "best_score": sorted_results[0]['score'] if sorted_results else None,
                "best_mech": sorted_results[0]['mech'] if sorted_results else None,
                "best_elec": sorted_results[0]['elec'] if sorted_results else None,
                "best_total_tilt": (sorted_results[0]['mech'] + sorted_results[0]['elec']) if sorted_results else None,
                "best_distance_m": sorted_results[0]['distance'] if sorted_results else None,
                "best_lower_footprint_m": sorted_results[0].get('lower_footprint') if sorted_results else None,
                "best_upper_footprint_m": sorted_results[0].get('upper_footprint') if sorted_results else None
            },
            "results": []
        }
        
        # Include terrain profile from last analysis if available (sample)
        if hasattr(self, 'last_result') and self.last_result:
            distances = self.last_result.get("distances", [])
            elevations = self.last_result.get("elevations", [])
            
            # Sample terrain profile (ambil max 200 titik untuk menghindari file terlalu besar)
            if distances and elevations:
                step = max(1, len(distances) // 200)
                export_data["terrain_profile_sample"] = [
                    {"distance_m": d, "elevation_m": e}
                    for d, e in zip(distances[::step], elevations[::step])
                ]
        
        # Add ALL optimization results
        for i, res in enumerate(sorted_results):
            export_data["results"].append({
                "rank": i + 1,
                "mechanical_tilt": res['mech'],
                "electrical_tilt": res['elec'],
                "total_tilt": res['mech'] + res['elec'],
                "main_beam_distance_m": round(res['distance'], 1),
                "lower_footprint_m": round(res.get('lower_footprint'), 1) if res.get('lower_footprint') else None,
                "upper_footprint_m": round(res.get('upper_footprint'), 1) if res.get('upper_footprint') else None,
                "score": round(res['score'], 1)
            })
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.status_label.setText(f"✅ Exported {len(sorted_results)} combinations to {os.path.basename(filename)}")
            
            # Tanya user apakah ingin membuka folder
            reply = QMessageBox.question(
                self, 
                "Export Successful", 
                f"Results saved to:\n{filename}\n\nOpen containing folder?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(filename)))
            
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error saving file:\n{str(e)}")
            
    
    def _log(self, message, level=Qgis.Info):
        """Log message to console and QGIS message log"""
        # Always print to console for development
        print(f"[VerticalAnalysis] {message}")
        
        # Also log to QGIS
        try:
            QgsMessageLog.logMessage(
                str(message),
                "扇区Tilt分析",
                level
            )
        except Exception:  # nosec
            pass
            
    def _get_documents_folder(self):
        """
        Get user's Documents folder path across different OS
        Returns user's home directory as fallback
        """
        import os
        from pathlib import Path
        
        try:
            # Windows
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes, windll
                
                # SHGetFolderPath CSIDL_PERSONAL = 5 for My Documents
                CSIDL_PERSONAL = 5
                SHGFP_TYPE_CURRENT = 0
                buf = ctypes.create_unicode_buffer(260)
                windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
                docs_path = buf.value
                if docs_path and os.path.exists(docs_path):
                    return docs_path
            
            # Linux / Mac
            else:
                home = Path.home()
                # Try common document folders
                candidates = [
                    home / "Documents",
                    home / "documents",
                    home / "Documentos",
                    home
                ]
                for folder in candidates:
                    if folder.exists():
                        return str(folder)
                return str(home)
                
        except Exception as e:
            print(f"Error getting Documents folder: {e}")
            # Fallback to home directory
            return str(Path.home())
        
        # Ultimate fallback
        return str(Path.home())

    
    # =====================================================
    # RUN ANALYSIS
    # =====================================================

    def run_analysis(self):
        print("\n" + "="*60)
        print("🔍 RUN ANALYSIS STARTED")
        print("="*60)
        
        # =====================================================
        # CLEAR INTERSECTION CACHE SAAT PARAMETER BERUBAH (TAMBAHKAN DI SINI)
        # =====================================================
        try:
            from ...core.rf_engine.intersection_solver import IntersectionCache
            cache = IntersectionCache()
            cache.clear()
            print("🧹 Intersection cache cleared for new analysis")
        except Exception as e:
            print(f"⚠️ Could not clear intersection cache: {e}")
        
        # =====================================================
        # DEBUG: CEK CONTROLLER
        # =====================================================
        print(f"🔌 Controller check: {self.controller}")
        if self.controller is None:
            self._log("Controller is None!", Qgis.Critical)
            QMessageBox.critical(
                self, 
                "Application Error", 
                "The RF analysis engine failed to initialize.\n\n"
                "This is usually caused by a missing DEM layer or a plugin loading issue.\n\n"
                "Please try:\n"
                "• Loading a DEM layer first\n"
                "• Restarting QGIS\n"
                "• Reinstalling the plugin if the problem persists"
            )
            return
        else:
            print(f"✅ Controller OK: {type(self.controller)}")
            print(f"✅ DEM Layer: {self.controller.dem_layer}")
            
        self._log("Run RF Vertical Analysis started")
        
        # =====================================================
        # VALIDASI DEM SOURCE SEBELUM PROCEED
        # =====================================================
        dem_available, dem_error = self._check_dem_availability()
        if not dem_available:
            source_name = "Local DEM" if self.dem_source_combo.currentIndex() == 0 else "Open-Meteo"

            if self.dem_source_combo.currentIndex() != 0:
                # Open-Meteo 不可达：优先自动降级到项目里的本地 DEM，不打断分析
                fallback_name = self._try_fallback_to_local_dem()
                if fallback_name is not None:
                    try:
                        from qgis.utils import iface
                        iface.messageBar().pushWarning(
                            "扇区Tilt分析",
                            f"Open-Meteo 不可达，已自动改用本地 DEM「{fallback_name}」继续分析。"
                        )
                    except Exception:  # nosec
                        print(f"[扇区Tilt分析] Open-Meteo 不可达，已降级本地 DEM: {fallback_name}")
                    dem_available, dem_error = True, ""
                else:
                    QMessageBox.warning(self, f"{source_name} Unavailable", dem_error)
                    self.status_label.setText(f"Analysis failed: {source_name} source unavailable")
                    return
            else:
                QMessageBox.warning(self, f"{source_name} Unavailable", dem_error)
                self.status_label.setText(f"Analysis failed: {source_name} source unavailable")
                return
        
        # =====================================================
        # TAMBAHKAN: VALIDASI RF PARAMETERS
        # =====================================================
        params_valid, params_error = self._validate_rf_parameters()
        if not params_valid:
            QMessageBox.warning(
                self,
                "Invalid RF Parameters",
                params_error
            )
            self.status_label.setText(f"Analysis failed: {params_error}")
            return
            
        # =====================================================
        # VALIDASI INPUT COORDINATES
        # =====================================================
        is_valid, error_msg, warning_msg = self._validate_coordinates()
        if not is_valid:
            QMessageBox.warning(self, "Input Error", error_msg)
            self.status_label.setText("Analysis failed: " + error_msg)
            return
        
        if warning_msg:
            print(f"⚠️ {warning_msg}")
            self.status_label.setText(warning_msg)
        
        # Print parameter yang digunakan
        print(f"📊 Parameters:")
        print(f"  - Height: {self.height_spin.value()} {self.height_spin.suffix()}")
        print(f"  - Mechanical Tilt: {self.mech_tilt_spin.value()}°")
        print(f"  - Electrical Tilt: {self.elec_tilt_spin.value()}°")
        print(f"  - Azimuth: {self.azimuth_spin.value()}°")
        print(f"  - Distance: {self.distance_spin.value()} {self.distance_spin.suffix()}")
        print(f"  - Unit: {'Metric' if self.unit_combo.currentIndex()==0 else 'Imperial'}")
        print("🎯 run_analysis() called")

        if not self.controller:
            self.status_label.setText("Controller not connected")
            return
        
        # =====================================================
        # CLEAR PREVIOUS RESULTS FROM MAP (NEW)
        # =====================================================
        
        try:
            if hasattr(self.map_widget, "hide_all_layers"):
                self.map_widget.hide_all_layers()
            else:
                # Fallback to clear_all_layers
                self.map_widget.clear_all_layers()
            print("🗺️ CLEAR map layers OK (before new analysis)")
        except Exception as e:
            self._log(f"Clear map failed: {e}", Qgis.Warning)
            import traceback
            traceback.print_exc()
        
        

        # =====================================================
        # COLLECT PARAMETERS (UPDATED WITH ELECTRICAL TILT)
        # =====================================================

        # Ambil nilai dari UI
        raw_height = self.height_spin.value()
        raw_distance = self.distance_spin.value()
        is_metric = self.unit_combo.currentIndex() == 0
        
        # Konversi ke meter untuk engine
        if is_metric:
            height_m = raw_height
            distance_m = raw_distance
        else:
            # Imperial to metric
            height_m = raw_height / 3.28084  # feet to meter
            distance_m = raw_distance / 0.000621371  # miles to meter
        
        params = {
            "height": height_m,  # <-- PASTIKAN INI DALAM METER!
            "mech": self.mech_tilt_spin.value(),
            "elec": self.elec_tilt_spin.value(),
            "beamwidth": self.beamwidth_spin.value(),
            "azimuth": self.azimuth_spin.value(),
            "distance": distance_m,  # <-- PASTIKAN INI DALAM METER!
            "lat": float(self.latitude_input.text() or 0),
            "lon": float(self.longitude_input.text() or 0),
            "dem_source": self.dem_source_combo.currentIndex()
        }

        # Print parameter yang digunakan
        source_text = "Local DEM" if params["dem_source"] == 0 else "Open-Meteo API"
        total_tilt = params["mech"] + params["elec"]
        print(f"\n📊 Parameters (converted to metric for engine):")
        print(f"  - Height: {params['height']:.1f} m ({raw_height:.1f} {'ft' if not is_metric else 'm'})")
        print(f"  - Mechanical Tilt: {params['mech']}°")
        print(f"  - Electrical Tilt: {params['elec']}°")
        print(f"  - Total Tilt: {total_tilt}°")
        print(f"  - Vertical Beamwidth: {self.beamwidth_spin.value()}°")
        print(f"  - Horizontal Beamwidth: {self.h_beamwidth_spin.value()}°")
        print(f"  - Azimuth: {params['azimuth']}°")
        print(f"  - Distance: {params['distance']:.0f} m ({raw_distance:.2f} {'mi' if not is_metric else 'm'})")
        print(f"  - DEM Source: {source_text}")
        
        # =====================================================
        # SEND RF PARAMETERS TO MAP WIDGET
        # =====================================================

        try:
            lat = float(self.latitude_input.text())
            lon = float(self.longitude_input.text())
            print(f"🗺️ MAP-WIDGET: lat={lat}, lon={lon}, azimuth={params['azimuth']}, hbw={self.h_beamwidth_spin.value()}")

            if hasattr(self.map_widget, "set_site"):
                self.map_widget.set_site(lat, lon)
                print(f"🗺️ set_site OK → site={getattr(self.map_widget, 'site', None)}")

            if hasattr(self.map_widget, "set_azimuth"):
                self.map_widget.set_azimuth(params["azimuth"])
                print(f"🗺️ set_azimuth OK → azimuth={getattr(self.map_widget, 'azimuth', None)}")

            if hasattr(self.map_widget, "set_beamwidth"):
                self.map_widget.set_beamwidth(self.h_beamwidth_spin.value())
                
            # Set basemap
            if hasattr(self.map_widget, "set_basemap"):
                basemap_name = self._get_selected_basemap()
                self.map_widget.set_basemap(basemap_name)

        except Exception:
            import traceback
            traceback.print_exc()
            print("🗺️ MAP-WIDGET send params FAILED (see traceback above)")

        # =====================================================
        # RUN ENGINE
        # =====================================================

        result = self.controller.run_analysis(params)
        self.last_result = result  # <-- TAMBAHKAN INI
        
        # ======================================================
        # DEBUG: CEK RESULT DARI ENGINE
        # ======================================================
        print(f"\n🔍 RESULT FROM ENGINE:")
        print(f"  • Keys in result: {list(result.keys())}")
        print(f"  • main_beam_height: {result.get('main_beam_height')}")
        print(f"  • upper_beam_height: {result.get('upper_beam_height')}")
        print(f"  • lower_beam_height: {result.get('lower_beam_height')}")

        if not result:
            self.status_label.setText("Analysis failed")
            return

        # =====================================================
        # UPDATE TERRAIN PROFILE
        # =====================================================

        # Ambil intersection points
        main_intersection = result.get("main_intersection_distance")
        upper_intersection = result.get("upper_intersection_distance")
        lower_intersection = result.get("lower_intersection_distance")
        
        # Untuk display, gunakan main_intersection (963 m) sebagai impact
        display_impact = main_intersection if main_intersection is not None else result.get("impact_distance")
        
        print(f"📊 DISPLAY IMPACT: {display_impact}m (main_intersection: {main_intersection}, fallback: {result.get('impact_distance')})")
        
        self.profile_widget.plot_profile(
            result["distances"],
            result["elevations"],
            params["height"],
            result["main_beam"],
            result["upper_beam"],
            result["lower_beam"],
            display_impact,
            mech_tilt=params["mech"],
            elec_tilt=params["elec"],  # <-- TAMBAHKAN INI
            beamwidth=params["beamwidth"],
            main_intersection_distance=main_intersection,
            upper_intersection_distance=upper_intersection,
            lower_intersection_distance=lower_intersection,
            shadow_regions=result.get("shadow_regions"),
            # TAMBAHKAN PARAMETER BARU INI
            main_beam_height=result.get("main_beam_height"),
            upper_beam_height=result.get("upper_beam_height"),
            lower_beam_height=result.get("lower_beam_height")
        )
        
        # =====================================================
        # AMBIL IMPACT POINT DARI WIDGET (BARU)
        # =====================================================
        
        # Tanya ke widget di mana impact point digambar
        widget_impact = None
        if hasattr(self.profile_widget, 'get_impact_point'):
            widget_impact = self.profile_widget.get_impact_point()
            if widget_impact:
                print(f"📢 Widget impact point: {widget_impact:.0f}m")
        
        # =====================================================
        # FIXED: SAFE IMPACT ASSIGNMENT DENGAN FALLBACK
        # =====================================================
        impact = None
        
        if widget_impact is not None:
            impact = widget_impact
            print(f"✅ Using widget impact point: {impact:.0f}m")
        elif main_intersection is not None:
            impact = main_intersection
            print(f"✅ Using main_intersection: {impact:.0f}m")
        elif result.get("impact_distance") is not None:
            impact = result.get("impact_distance")
            print(f"⚠️ Using fallback impact_distance: {impact:.0f}m")
        else:
            print(f"⚠️ No impact point found in any source")
        
        # Simpan impact untuk digunakan di seluruh dialog
        self._current_impact = impact
        
        # =====================================================
        # SIMPAN IMPACT UNTUK DIGUNAKAN DI SELURUH DIALOG (BARU)
        # =====================================================
        
        self._current_impact = impact
        
        # =====================================================
        # UPDATE ELEVATION INFO
        # =====================================================
        
        self._update_elevation_info(result)
        
        # =====================================================
        # IMPACT DISTANCE - FIXED (GUNAKAN DARI WIDGET)
        # =====================================================

        # Gunakan impact yang sudah diambil dari widget
        # (variabel 'impact' sudah didefinisikan di atas)
        
        # Update impact value di UI dengan unit yang benar
        if impact is not None:
            is_metric = self.unit_combo.currentIndex() == 0
            
            if is_metric:
                if impact >= 1000:
                    impact_text = f"{impact/1000:.2f} km"
                else:
                    impact_text = f"{impact:.0f} m"
            else:
                impact_ft = impact * 3.28084
                if impact_ft >= 5280:
                    impact_text = f"{impact_ft/5280:.2f} mi"
                else:
                    impact_text = f"{impact_ft:.0f} ft"
            
            print(f"✅ MAIN LOBE IMPACT POINT: {impact_text}")
            
        else:
            # self.impact_value.setText("—")  # <-- HAPUS atau COMMENT baris ini
            print("⚠️ No impact point found")


        # =====================================================
        # UPDATE SECTOR MAP WIDGET - FIXED MAIN LOBE DISPLAY
        # =====================================================

        try:
            impact_point = result.get("impact_point")
            footprint_start = result.get("footprint_start_distance")
            footprint_end = result.get("footprint_end_distance")
            
            # Gunakan main_intersection untuk semua yang related ke main lobe
            main_impact = result.get("main_intersection_distance")
            fallback_impact = result.get("impact_distance")
            
            print(f"\n📊 SECTOR MAP DEBUG:")
            print(f"  - main_impact: {main_impact}")
            print(f"  - fallback_impact: {fallback_impact}")
            print(f"  - impact_point: {impact_point}")
            print(f"  - upper_intersection: {upper_intersection}")
            print(f"  - lower_intersection: {lower_intersection}")
            print(f"  - footprint_start: {footprint_start}, footprint_end: {footprint_end}")
            print(f"  - map_widget.azimuth = {getattr(self.map_widget, 'azimuth', 'N/A')}")
            print(f"  - map_widget.site   = {getattr(self.map_widget, 'site', 'N/A')}")

            # =====================================================
            # UPDATE MAP WIDGET METRICS (OVERLAY)
            # =====================================================
            
            # Format Beam Intersection
            if impact is not None:
                is_metric = self.unit_combo.currentIndex() == 0
                if is_metric:
                    if impact >= 1000:
                        intersection_text = f"{impact/1000:.2f} km"
                    else:
                        intersection_text = f"{impact:.0f} m"
                else:
                    impact_ft = impact * 3.28084
                    if impact_ft >= 5280:
                        intersection_text = f"{impact_ft/5280:.2f} mi"
                    else:
                        intersection_text = f"{impact_ft:.0f} ft"
            else:
                intersection_text = "—"
            
            # Format Coverage Footprint
            footprint_text = "—"
            if footprint_start is not None and footprint_end is not None:
                is_metric = self.unit_combo.currentIndex() == 0
                if is_metric:
                    if footprint_start >= 1000:
                        start_display = f"{footprint_start/1000:.2f} km"
                    else:
                        start_display = f"{footprint_start:.0f} m"
                    
                    if footprint_end >= 1000:
                        end_display = f"{footprint_end/1000:.2f} km"
                    else:
                        end_display = f"{footprint_end:.0f} m"
                    
                    footprint_text = f"{start_display} – {end_display}"
                else:
                    start_ft = footprint_start * 3.28084
                    end_ft = footprint_end * 3.28084
                    
                    if start_ft >= 5280:
                        start_display = f"{start_ft/5280:.2f} mi"
                    else:
                        start_display = f"{start_ft:.0f} ft"
                    
                    if end_ft >= 5280:
                        end_display = f"{end_ft/5280:.2f} mi"
                    else:
                        end_display = f"{end_ft:.0f} ft"
                    
                    footprint_text = f"{start_display} – {end_display}"
            
            # Kirim ke map widget
            if hasattr(self.map_widget, "update_metrics"):
                self.map_widget.update_metrics(intersection_text, footprint_text)


            # Gambar semua elemen di map
            # =====================================================
            # BEAM END POINT (HIJAU) - Ujung beam di free space
            # Menggunakan radius sector, BUKAN main_impact
            # =====================================================
            if hasattr(self.map_widget, "draw_beam_end_point"):
                # Hitung radius sector dulu (sama seperti untuk center line)
                if upper_intersection:
                    beam_end_distance = min(upper_intersection * 2, 5000)
                elif fallback_impact:
                    beam_end_distance = min(fallback_impact * 2, 5000)
                else:
                    beam_end_distance = self.distance_spin.value()  # fallback ke max_distance
                
                self.map_widget.draw_beam_end_point(beam_end_distance)
                print(f"✅ Beam end point drawn at {beam_end_distance:.0f}m (beam end, free space)")

            # Center line (MERAH DASH) - dari site sampai radius sector
            if hasattr(self.map_widget, "draw_center_line") and upper_intersection:
                sector_radius = min(upper_intersection * 2, 5000)
                self.map_widget.draw_center_line(sector_radius)
                print(f"✅ Center line drawn from site to {sector_radius:.0f}m")
            elif hasattr(self.map_widget, "draw_center_line") and fallback_impact:
                sector_radius = min(fallback_impact * 2, 5000)
                self.map_widget.draw_center_line(sector_radius)
                print(f"⚠️ Center line drawn (fallback) to {sector_radius:.0f}m")

            # Beam edges - gunakan upper_intersection
            if hasattr(self.map_widget, "draw_beam_edges") and upper_intersection:
                self.map_widget.draw_beam_edges(upper_intersection)
                print(f"✅ Beam edges drawn at {upper_intersection}m")
            elif hasattr(self.map_widget, "draw_beam_edges") and fallback_impact:
                self.map_widget.draw_beam_edges(fallback_impact)
                print(f"⚠️ Beam edges drawn (fallback): {fallback_impact}m")

            # Impact marker - gunakan impact_point (LEBIH BESAR)
            if hasattr(self.map_widget, "draw_impact") and impact_point:
                self.map_widget.draw_impact(
                    impact_point.y(),
                    impact_point.x()
                )
                print(f"✅ Impact marker drawn at {impact_point.y():.6f}, {impact_point.x():.6f}")
                
            # =====================================================
            # TAMBAHKAN DI SINI - SETELAH IMPACT, SEBELUM SECTOR
            # =====================================================
            # UPPER & LOWER INTERSECTION POINTS
            if hasattr(self.map_widget, "draw_upper_intersection") and upper_intersection:
                upper_lat, upper_lon = self._project_point(
                    params["lat"], params["lon"], 
                    params["azimuth"], upper_intersection
                )
                self.map_widget.draw_upper_intersection(upper_lat, upper_lon)
                print(f"✅ Upper intersection point drawn at {upper_intersection:.0f}m")

            if hasattr(self.map_widget, "draw_lower_intersection") and lower_intersection:
                lower_lat, lower_lon = self._project_point(
                    params["lat"], params["lon"], 
                    params["azimuth"], lower_intersection
                )
                self.map_widget.draw_lower_intersection(lower_lat, lower_lon)
                print(f"✅ Lower intersection point drawn at {lower_intersection:.0f}m")

            # Sector - gunakan min(upper_intersection * 2, 5000)
            if hasattr(self.map_widget, "draw_sector") and upper_intersection:
                sector_radius = min(upper_intersection * 2, 5000)
                self.map_widget.draw_sector(sector_radius)
                print(f"✅ Sector drawn with radius {sector_radius:.0f}m (min({upper_intersection:.0f}m*2, 5000m))")
            elif hasattr(self.map_widget, "draw_sector") and fallback_impact:
                sector_radius = min(fallback_impact * 2, 5000)
                self.map_widget.draw_sector(sector_radius)
                print(f"⚠️ Sector drawn (fallback) with radius {sector_radius:.0f}m")

            # Footprint - gunakan footprint_start dan footprint_end
            if footprint_start is not None and footprint_end is not None:
                if hasattr(self.map_widget, "set_footprint"):
                    self.map_widget.set_footprint(footprint_start, footprint_end)
                    print(f"✅ Footprint drawn: {footprint_start:.0f}m – {footprint_end:.0f}m")

            # =====================================================
            # DIAGNOSTIC + FORCE REFRESH (SWITCH-CELL FIX)
            # =====================================================
            try:
                mw = self.map_widget
                for ln in ["RF_Antenna", "RF_Sector", "RF_Footprint", "RF_BeamEdges",
                           "RF_CenterLine", "RF_Impact", "RF_BeamEnd",
                           "RF_UpperIntersection", "RF_LowerIntersection"]:
                    lyr = getattr(mw, "_layer_manager", None)
                    if lyr is not None:
                        l = lyr._layers.get(ln) if hasattr(lyr, "_layers") else None
                        if l is not None:
                            print(f"🗺️ LAYER {ln}: {l.featureCount()} features")
                # 关键对比：map_widget 内部状态 vs 本次参数
                _mw_az = getattr(mw, "azimuth", None)
                _mw_site = getattr(mw, "site", None)
                print(f"🗺️ AZIMUTH CHECK: map_widget.azimuth={_mw_az} vs params.azimuth={params['azimuth']} → {'一致✓' if _mw_az == params['azimuth'] else '不一致✗'}")
                print(f"🗺️ SITE CHECK: map_widget.site={_mw_site} vs params lat/lon=({params['lat']},{params['lon']})")
                mw.canvas.refresh()
                print("🗺️ FORCE canvas.refresh() done")
            except Exception as e:
                print(f"🗺️ refresh diag failed: {e}")

        except Exception as e:
            self._log(f"Sector map update failed: {e}", Qgis.Warning)
            import traceback
            traceback.print_exc()
            
        
        # =====================================================
        # PASTIKAN OVERLAY DI ATAS
        # =====================================================
        
        if hasattr(self.map_widget, "raise_overlays"):
            self.map_widget.raise_overlays()
            # Panggil lagi setelah delay untuk memastikan
            QTimer.singleShot(300, self.map_widget.raise_overlays)
            

        # =====================================================
        # FOOTPRINT VS SELECTED DISTANCE - FIXED CALCULATION
        # =====================================================

        try:
            footprint_start = result.get("footprint_start_distance")
            footprint_end = result.get("footprint_end_distance")
            selected_dist = self.distance_spin.value()
            
            # Konversi selected distance ke meter jika perlu
            if self.unit_combo.currentIndex() != 0:  # Imperial
                selected_dist = self._convert_to_metric(selected_dist, 'distance')
            
            percent = 0
            if footprint_start is not None and footprint_end is not None and footprint_end > footprint_start:
                footprint_width = footprint_end - footprint_start
                
                if selected_dist <= footprint_start:
                    # Sebelum footprint start
                    percent = 0
                elif selected_dist >= footprint_end:
                    # Setelah footprint end
                    percent = 100
                else:
                    # Di dalam footprint
                    relative = selected_dist - footprint_start
                    percent = (relative / footprint_width) * 100
                
                # Update distance slider color
                self._update_distance_slider_color(percent)
                
                print(f"📊 Coverage Footprint vs Selected Distance:")
                print(f"  - Coverage Footprint {footprint_start:.0f}m – {footprint_end:.0f}m")
                print(f"  - Selected: {selected_dist:.0f}m")
                print(f"  - Width: {footprint_width:.0f}m")
                print(f"  - Percent: {percent:.1f}%")
                
        except Exception as e:
            self._log(f"Footprint distance calculation failed: {e}", Qgis.Warning)

        self._log("RF Vertical Analysis completed")
        print("\n" + "="*60)
        print("✅ RUN ANALYSIS COMPLETED")
        
        # Tampilkan nilai yang benar di summary
        current_impact = getattr(self, '_current_impact', None)
        if current_impact:
            if current_impact >= 1000:
                impact_display = f"{current_impact/1000:.2f} km"
            else:
                impact_display = f"{current_impact:.0f} m"
            print(f"  - Main Lobe Impact: {impact_display}")
        else:
            print(f"  - Main Lobe Impact: None")
        
                # Informasi dari hasil analisis
        is_metric = self.unit_combo.currentIndex() == 0
        
        if impact is not None:
            if is_metric:
                if impact >= 1000:
                    impact_display = f"{impact/1000:.2f} km"
                else:
                    impact_display = f"{impact:.0f} m"
            else:
                impact_ft = impact * 3.28084
                if impact_ft >= 5280:
                    impact_display = f"{impact_ft/5280:.2f} mi"
                else:
                    impact_display = f"{impact_ft:.0f} ft"
        else:
            impact_display = "None"
        
        if footprint_start is not None and footprint_end is not None:
            if is_metric:
                if footprint_start >= 1000:
                    start_display = f"{footprint_start/1000:.2f} km"
                else:
                    start_display = f"{footprint_start:.0f} m"
                
                if footprint_end >= 1000:
                    end_display = f"{footprint_end/1000:.2f} km"
                else:
                    end_display = f"{footprint_end:.0f} m"
                
                footprint_display = f"{start_display} – {end_display}"
            else:
                start_ft = footprint_start * 3.28084
                end_ft = footprint_end * 3.28084
                
                if start_ft >= 5280:
                    start_display = f"{start_ft/5280:.2f} mi"
                else:
                    start_display = f"{start_ft:.0f} ft"
                
                if end_ft >= 5280:
                    end_display = f"{end_ft/5280:.2f} mi"
                else:
                    end_display = f"{end_ft:.0f} ft"
                
                footprint_display = f"{start_display} – {end_display}"
        else:
            footprint_display = "None"
        
        print(f"  - Main Beam Intersection: {impact_display}")
        print(f"  - Coverage Footprint: {footprint_display}")
        print("="*60)
        
        # =====================================================
        # UPDATE STATUS
        # =====================================================

        self.status_label.setText("Analysis completed")
        # =====================================================
        # TAMBAHKAN DONASI MESSAGE DI STATUS (SUBTLE)
        # =====================================================
        # Gunakan random message agar tidak monoton
        import random

        donation_messages = ["本结果由「扇区Tilt分析」生成 · 垂直波瓣一键分析"]

        donation_msg = random.choice(donation_messages)  # nosec
        # 状态栏带上当前小区号，便于确认"这次结果属于哪个小区"
        _cell_txt = getattr(self, "current_cell_id", None)
        if _cell_txt:
            self.status_label.setText(
                f"✅ 小区 {_cell_txt} | Impact: {impact_display} m | {donation_msg}"
            )
        else:
            self.status_label.setText(f"Analysis completed - Impact: {impact_display} | {donation_msg}")
        
    
    def _project_point(self, lat, lon, azimuth, distance):
        """
        Project point from site at given azimuth and distance.
        
        Parameters
        ----------
        lat : float
            Site latitude
        lon : float
            Site longitude
        azimuth : float
            Azimuth in degrees
        distance : float
            Distance in meters
            
        Returns
        -------
        tuple
            (lat, lon) of projected point
        """

        
        R = 6378137.0
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        az = math.radians(azimuth)
        
        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance / R) +
            math.cos(lat1) * math.sin(distance / R) * math.cos(az)
        )
        
        lon2 = lon1 + math.atan2(
            math.sin(az) * math.sin(distance / R) * math.cos(lat1),
            math.cos(distance / R) - math.sin(lat1) * math.sin(lat2)
        )
        
        return math.degrees(lat2), math.degrees(lon2)
        
    
    # =====================================================
    # UPDATE DISTANCE SLIDER COLOR (RF STYLE)
    # =====================================================

    def _update_distance_slider_color(self, percent):
        """
        Update slider color based on footprint position
        0-20%: yellow (early footprint)
        20-80%: green (optimal coverage)
        80-100%: blue (edge coverage)
        >100%: red (beyond footprint)
        """
        try:
            if percent >= 100:
                color = "#c1121f"   # red (beyond footprint)
            elif percent >= 80:
                color = "#2a7de1"   # blue (edge coverage)
            elif percent >= 20:
                color = "#00b050"   # green (optimal coverage)
            else:
                color = "#ffb100"   # yellow (early footprint)

            self.distance_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height:6px;
                background:#d9e3e8;
                border-radius:3px;
            }}
            QSlider::sub-page:horizontal {{
                background:{color};
                border-radius:3px;
            }}
            QSlider::add-page:horizontal {{
                background:#e9eef2;
            }}
            QSlider::handle:horizontal {{
                background:#ffffff;
                border:1px solid #a5b6c2;
                width:14px;
                margin:-4px 0;
                border-radius:7px;
            }}
            """)
            
            print(f"🎨 Slider color updated to {color} for {percent:.1f}%")
            
        except Exception:  # nosec
            pass
            
                           
    
    # =====================================================
    # ELEVATION INFO UPDATE - FIXED (GUNAKAN DARI WIDGET)
    # =====================================================

    def _update_elevation_info(self, result):
        """Update elevation info label with analysis results"""
        try:
            distances = result.get("distances", [])
            elevations = result.get("elevations", [])
            # Gunakan self._current_impact yang sudah disimpan dari widget
            impact = getattr(self, '_current_impact', None) or result.get("impact_distance")
            coverage = result.get("final_coverage", {})
            is_metric = self.unit_combo.currentIndex() == 0
            
            if not distances or not elevations:
                return
            
            # Calculate statistics
            min_elev = min(elevations)
            max_elev = max(elevations)
            avg_elev = sum(elevations) / len(elevations)
            n_samples = len(distances)
            
            # Obstruction info
            obstruction_type = coverage.get("type", "unknown")
            if obstruction_type == "terrain_blocked":
                obstruction_text = "terrain blocked"
            elif obstruction_type == "ground_hit":
                obstruction_text = "ground hit"
            else:
                obstruction_text = "clear"
            
            # =====================================================
            # KONVERSI KE IMPERIAL JIKA DIPERLUKAN
            # =====================================================
            if is_metric:
                # Metric: tetap dalam meter
                min_display = min_elev
                max_display = max_elev
                avg_display = avg_elev
                unit = "m"
            else:
                # Imperial: konversi meter ke feet
                min_display = min_elev * 3.28084
                max_display = max_elev * 3.28084
                avg_display = avg_elev * 3.28084
                unit = "ft"
            
            # Format info text
            info_text = (
                f"Elevation: Loaded ({n_samples} DEM samples). "
                f"Range: {min_display:.0f}-{max_display:.0f} {unit}, "
                f"Avg: {avg_display:.0f} {unit}. "
                f"RF: {obstruction_text}"
            )
            
            if impact:
                # Tampilkan impact dengan unit yang benar (HANYA SEKALI)
                if is_metric:
                    if impact >= 1000:
                        impact_display = f"{impact/1000:.2f} km"
                    else:
                        impact_display = f"{impact:.0f} m"
                else:
                    impact_ft = impact * 3.28084
                    if impact_ft >= 5280:
                        impact_display = f"{impact_ft/5280:.2f} mi"
                    else:
                        impact_display = f"{impact_ft:.0f} ft"
                
                info_text += f", Impact: {impact_display}"  # <-- HANYA SEKALI
            
            self.elevation_info.setText(info_text)
            
        except Exception as e:
            print(f"Error updating elevation info: {e}")
            
    

    def _format_distance(self, distance_m):
        """
        Format distance in meters to display string based on current unit system
        """
        if distance_m is None:
            return "—"
        
        is_metric = self.unit_combo.currentIndex() == 0
        
        if is_metric:
            if distance_m >= 1000:
                return f"{distance_m/1000:.2f} km"
            else:
                return f"{distance_m:.0f} m"
        else:
            distance_ft = distance_m * 3.28084
            if distance_ft >= 5280:
                return f"{distance_ft/5280:.2f} mi"
            else:
                return f"{distance_ft:.0f} ft"    
    
    # =====================================================
    # KMZ EXPORT
    # =====================================================

    def _export_kmz(self):
        """Export current analysis to KMZ with complete RF visualization"""
        
        if not hasattr(self, 'last_result') or not self.last_result:
            self.status_label.setText("No analysis to export")
            QMessageBox.warning(
                self, 
                "Export Failed", 
                "No RF analysis results available for export.\n\n"
                "Please run an analysis first by clicking the 'Run Analysis' button."
            )
            return
        
        try:
            result = self.last_result
            
            # Get site point
            try:
                lat = float(self.latitude_input.text() or 0)
                lon = float(self.longitude_input.text() or 0)
                site_point = QgsPointXY(lon, lat)
            except:
                QMessageBox.warning(
                    self, 
                    "Export Failed", 
                    "Invalid site coordinates.\n\n"
                    "Please enter valid latitude and longitude values before exporting."
                )
                return
            
            # Get parameters from result
            footprint_start = result.get("footprint_start_distance")
            footprint_end = result.get("footprint_end_distance")
            impact_point = result.get("impact_point")
            
            # Get intersection distances
            upper_intersection_dist = result.get("upper_intersection_distance")
            lower_intersection_dist = result.get("lower_intersection_distance")
            main_intersection_dist = result.get("main_intersection_distance") or result.get("impact_distance")
            
            # Get azimuth and beamwidth from UI
            azimuth = self.azimuth_spin.value()
            h_beamwidth = self.h_beamwidth_spin.value()
            
            # Validate footprint data
            if not footprint_start or not footprint_end:
                QMessageBox.warning(
                    self, 
                    "Export Failed", 
                    "No coverage footprint data available.\n\n"
                    "The analysis may have failed to generate a valid footprint, or the beam may not intersect the ground.\n"
                    "Try adjusting the tilt values or checking the DEM coverage."
                )
                return
            
            # =====================================================
            # FIX: HARCODE SECTOR RADIUS & BEAM END KE 5000m
            # =====================================================
            SECTOR_RADIUS_HARDCODE = 5000  # meters
            print(f"📡 Using hardcoded sector radius: {SECTOR_RADIUS_HARDCODE}m")
            
            upper_point = None
            lower_point = None
            beam_end_point = None
            center_line_points = None
            beam_edges_points = None
            sector_radius = SECTOR_RADIUS_HARDCODE  # ← FORCE KE 5000m
            
            # Helper function to project point
            def project_point(distance):
                if distance is None or distance <= 0:
                    return None
                point_lat, point_lon = self._project_point(lat, lon, azimuth, distance)
                return QgsPointXY(point_lon, point_lat)
            
            # Upper intersection point (blue) - tetap pakai hasil perhitungan
            if upper_intersection_dist and upper_intersection_dist > 0:
                upper_point = project_point(upper_intersection_dist)
                print(f"  📍 Upper intersection: {upper_intersection_dist:.0f}m")
            
            # Lower intersection point (red) - tetap pakai hasil perhitungan
            if lower_intersection_dist and lower_intersection_dist > 0:
                lower_point = project_point(lower_intersection_dist)
                print(f"  📍 Lower intersection: {lower_intersection_dist:.0f}m")
            
            # =====================================================
            # BEAM END POINT - FORCE KE 5000m (bukan 2x main intersection)
            # =====================================================
            beam_end_point = project_point(SECTOR_RADIUS_HARDCODE)
            
            # Center line (red line from site to beam end at 5000m)
            if beam_end_point:
                center_line_points = [site_point, beam_end_point]
                print(f"  📍 Beam end point (hardcoded): {SECTOR_RADIUS_HARDCODE:.0f}m")
            
            # Beam edges (black dashed lines) - left and right edges
            half_bw = h_beamwidth / 2
            left_angle = azimuth - half_bw
            right_angle = azimuth + half_bw
            
            left_point_lat, left_point_lon = self._project_point(lat, lon, left_angle, SECTOR_RADIUS_HARDCODE)
            right_point_lat, right_point_lon = self._project_point(lat, lon, right_angle, SECTOR_RADIUS_HARDCODE)
            
            left_edge_point = QgsPointXY(left_point_lon, left_point_lat)
            right_edge_point = QgsPointXY(right_point_lon, right_point_lat)
            
            beam_edges_points = [
                [site_point, left_edge_point],
                [site_point, right_edge_point]
            ]
            print(f"  📍 Beam edges (hardcoded): left={left_angle:.1f}°, right={right_angle:.1f}°, radius={SECTOR_RADIUS_HARDCODE}m")
            
            # =====================================================
            # CALL EXPORTER WITH ALL PARAMETERS
            # =====================================================
            
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save KMZ File",
                "",
                "KMZ Files (*.kmz)"
            )

            if not filename:
                self.status_label.setText("KMZ export cancelled")
                return

            result = self.kmz_exporter.export_sector(
                site_point=site_point,
                azimuth=azimuth,
                h_beamwidth=h_beamwidth,
                footprint_start=footprint_start,
                footprint_end=footprint_end,
                impact_point=impact_point,
                upper_intersection_point=upper_point,
                lower_intersection_point=lower_point,
                beam_end_point=beam_end_point,
                center_line_points=center_line_points,
                beam_edges_points=beam_edges_points,
                sector_radius=sector_radius,
                filename=filename
            )

            # ======================================================
            # HANDLE RESULT
            # ======================================================
            if result is None:
                self.status_label.setText("KMZ export cancelled")
                return

            elif result is False:
                self.status_label.setText("❌ KMZ export failed")
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "An error occurred during KMZ export.\nCheck log for details."
                )
                return

            # ======================================================
            # SUCCESS → ASK OPEN GOOGLE EARTH
            # ======================================================
            self.status_label.setText("✅ KMZ export successful")

            reply = QMessageBox.question(
                self,
                "Export Successful",
                f"KMZ saved:\n{filename}\n\nOpen in Google Earth?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                try:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(filename))
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Open Failed",
                        f"Could not open Google Earth.\n\nError:\n{str(e)}"
                    )
            
        except Exception as e:
            self._log(f"KMZ export failed: {e}", Qgis.Warning)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, 
                "Export Failed", 
                f"An unexpected error occurred:\n\n{str(e)}"
            )
    
    # =====================================================
    # MAP NAVIGATION SLOTS
    # =====================================================
    
    def _on_zoom_in_clicked(self):
        """
        Handle zoom in button click
        """
        if hasattr(self.map_widget, 'zoom_in'):
            self.map_widget.zoom_in()
            print("🔍 Zoom in clicked")
    
    def _on_zoom_out_clicked(self):
        """
        Handle zoom out button click
        """
        if hasattr(self.map_widget, 'zoom_out'):
            self.map_widget.zoom_out()
    
    def _on_reset_map_clicked(self):
        """
        Handle reset map button click
        """
        if hasattr(self.map_widget, 'reset_view'):
            self.map_widget.reset_view()
            
            
    def _update_distance_from_slider(self, slider_value):
        """Update distance spinbox based on slider value and unit"""
        is_metric = self.unit_combo.currentIndex() == 0
        
        if is_metric:
            # Metric: slider dalam meter, spinbox dalam meter
            self.distance_spin.setValue(slider_value)
            self.distance_label.setText(f"{slider_value} m")
            # Update distance_in_meter langsung
            self.distance_in_meter = slider_value
        else:
            # Imperial: slider dalam meter, spinbox dalam miles
            miles = slider_value * 0.000621371
            miles_rounded = round(miles * 100) / 100  # 2 desimal
            self.distance_spin.setValue(miles_rounded)
            self.distance_label.setText(f"{miles_rounded:.2f} mi")
            # Update distance_in_meter langsung dari slider_value (dalam meter)
            self.distance_in_meter = slider_value
        
        self.distance_spin.blockSignals(False)
            
    
    def _update_slider_from_spinbox(self, spinbox_value):
        """Update slider based on spinbox value and unit"""
        is_metric = self.unit_combo.currentIndex() == 0
        
        if is_metric:
            # Metric: spinbox dalam meter, slider dalam meter
            slider_val = self._round_slider_value(spinbox_value)
            self.distance_slider.setValue(slider_val)
            self.distance_label.setText(f"{spinbox_value:.0f} m")
            # Update distance_in_meter langsung
            self.distance_in_meter = spinbox_value
        else:
            # Imperial: spinbox dalam miles, konversi ke meter untuk slider
            meters = spinbox_value / 0.000621371
            slider_val = self._round_slider_value(meters)
            self.distance_slider.setValue(slider_val)
            self.distance_label.setText(f"{spinbox_value:.2f} mi")
            # Update distance_in_meter dari hasil konversi
            self.distance_in_meter = meters
        
        self.distance_slider.blockSignals(False)
        
    def _round_slider_value(self, value):
        """
        Bulatkan nilai slider ke kelipatan 10 terdekat
        """
        rounded = int(round(value / 10.0) * 10)
        return max(0, min(10000, rounded))
        
        
    def _update_footprint_percentage(self, distance_value):
        """Update footprint percentage when distance changes"""
        try:
            if not hasattr(self, 'last_result') or not self.last_result:
                return
            
            footprint_start = self.last_result.get("footprint_start_distance")
            footprint_end = self.last_result.get("footprint_end_distance")
            
            if footprint_start is None or footprint_end is None:
                return
            
            # Validasi nilai
            if footprint_start <= 0 or footprint_end <= 0 or footprint_end <= footprint_start:
                return
            
            # Konversi distance_value ke meter jika imperial
            is_metric = self.unit_combo.currentIndex() == 0
            if is_metric:
                distance_m = distance_value
            else:
                # distance_value dalam miles, konversi ke meter
                distance_m = distance_value / 0.000621371
            
            footprint_width = footprint_end - footprint_start
            
            if distance_m <= footprint_start:
                percent = 0
            elif distance_m >= footprint_end:
                percent = 100
            else:
                relative = distance_m - footprint_start
                percent = (relative / footprint_width) * 100
            
            # Batasi percent antara 0-100
            percent = max(0, min(100, percent))
            
            self._update_distance_slider_color(percent)
            
        except Exception as e:
            print(f"⚠️ Error in _update_footprint_percentage: {e}")
    
    
    def _get_footprint_interpretation(self, percent):
        """Get RF engineering interpretation of percentage"""
        if percent < 20:
            return "Early footprint: Signal just starting to reach ground"
        elif percent < 50:
            return "Near edge: Building coverage"
        elif percent < 80:
            return "Optimal coverage: Best signal strength"
        elif percent < 100:
            return "Edge coverage: Signal weakening"
        else:
            return "Beyond main beam: Overshoot potential"
            
            
    def _refresh_profile_plot(self, *args):
        """
        Refresh terrain profile after splitter resize.
        Uses QTimer to debounce rapid resize events.
        """

        try:

            # cancel pending refresh if exists
            if hasattr(self, "_profile_refresh_timer"):
                self._profile_refresh_timer.stop()

            # create timer if not exist
            if not hasattr(self, "_profile_refresh_timer"):
                self._profile_refresh_timer = QTimer()
                self._profile_refresh_timer.setSingleShot(True)
                self._profile_refresh_timer.timeout.connect(self._apply_profile_refresh)

            # start timer (debounce 30ms)
            self._profile_refresh_timer.start(30)

        except Exception:  # nosec
            pass
            
            
    def _apply_profile_refresh(self):
        """
        Apply actual refresh for terrain profile.
        This is called after resize debounce.
        """
        # =====================================================
        # GUARD CLAUSE: Jangan eksekusi jika dialog sedang di-destroy
        # =====================================================
        if hasattr(self, '_is_destroying') and self._is_destroying:
            return

        try:
            if hasattr(self, "profile_widget") and self.profile_widget:
                # redraw plot
                if hasattr(self.profile_widget, "plot_item"):
                    self.profile_widget.plot_item.update()

                # rescale SVG tower
                if hasattr(self.profile_widget, "_update_tower_scale"):
                    self.profile_widget._update_tower_scale()
        except Exception:  # nosec
            pass