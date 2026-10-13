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
defaults.py

Centralized default values for RF Vertical Analysis
Single source of truth for all default parameters
"""

class RFDefaults:
    # =====================================================
    # ANTENNA PARAMETERS
    # =====================================================
    ANTENNA_HEIGHT = 40  # meters
    MECHANICAL_TILT = 4  # degrees
    ELECTRICAL_TILT = 2  # degrees
    VERTICAL_BEAMWIDTH = 6  # degrees
    HORIZONTAL_BEAMWIDTH = 65  # degrees
    
    # =====================================================
    # ANALYSIS PARAMETERS
    # =====================================================
    MAX_DISTANCE = 5000  # meters
    SAMPLING_STEP = 30  # meters
    DEFAULT_AZIMUTH = 90  # degrees
    
    # =====================================================
    # OPTIMIZATION DEFAULTS - UPDATED WITH RF REALISTIC VALUES
    # =====================================================
    TARGET_DISTANCE = 800  # meters (typical urban cell radius)
    BALANCED_MIN = 300  # meters (minimum useful coverage)
    BALANCED_MAX = 2000  # meters (maximum before overshoot)
    
    # =====================================================
    # OPTIMIZATION WEIGHTS - RF ENGINEERING BASED
    # =====================================================
    BALANCED_BASE_BONUS = 200  # Minimum bonus for being in range
    BALANCED_OPTIMAL_BONUS = 800  # Maximum bonus at sweet spot (mid-cell)
    BALANCED_PENALTY_FACTOR = 5  # Penalty factor for outside range
    
    # =====================================================
    # CACHE LIMITS
    # =====================================================
    TERRAIN_CACHE_SIZE = 100  # Maximum number of terrain profiles to cache
    
    # =====================================================
    # THREADING & TIMEOUT
    # =====================================================
    THREAD_TIMEOUT = 300  # seconds (5 minutes)
    ONLINE_TIMEOUT = 45  # seconds for online requests
    
    # =====================================================
    # FALLBACK VALUES
    # =====================================================
    BEAMWIDTH_FALLBACK = 7.0  # degrees (when field not found)