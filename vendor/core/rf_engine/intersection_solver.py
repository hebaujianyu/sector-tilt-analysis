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
intersection_solver.py

RF Beam vs Terrain Intersection Solver.

Engine ini menentukan apakah beam antena
menabrak terrain atau mencapai ground bebas.

Digunakan untuk:
- coverage limit detection
- RF vertical obstruction analysis
"""

import math


class IntersectionSolver:

    """
    Menyelesaikan intersection antara beam dan terrain.
    """

    def __init__(
        self,
        distances,
        elevations,
        antenna_height
    ):
        """
        Parameters
        ----------
        distances : list
            Jarak dari site dalam meter
        elevations : list
            Elevasi terrain dalam meter
        antenna_height : float
            Tinggi antenna di atas ground dalam meter
        """

        if len(distances) != len(elevations):
            raise ValueError("distances and elevations length mismatch")

        self.distances = distances
        self.elevations = elevations
        self.antenna_height = antenna_height
        self.antenna_abs = elevations[0] + antenna_height

    # ======================================================
    # MAIN INTERSECTION SOLVER
    # ======================================================

    def solve(self, beam_angle):
        """
        Mencari titik pertama beam menabrak terrain.
        Menggunakan cache untuk memastikan total tilt yang sama = hasil sama
        
        Parameters
        ----------
        beam_angle : float
            Sudut beam dalam derajat (positif = ke bawah)
            
        Returns
        -------
        dict
        """
        # ======================================================
        # CEK CACHE DULU
        # ======================================================
        # Buat cache key yang unik
        cache_key = (
            tuple(self.distances),
            tuple(self.elevations),
            self.antenna_height,
            round(beam_angle, 2)  # Bulatkan ke 2 desimal untuk konsistensi
        )
        
        # Gunakan cache singleton
        cache = IntersectionCache()
        cached_result = cache.get(cache_key)
        
        if cached_result is not None:
            print(f"  📦 INTERSECTION CACHE HIT: beam_angle={beam_angle:.2f}°")
            return cached_result
        
        # ======================================================
        # HITUNG INTERSECTION (KODE ORIGINAL)
        # ======================================================
        prev_d = None
        prev_elev = None
        prev_beam_h = None

        print(f"\n🔍 SOLVING for beam angle: {beam_angle:.2f}°")

        # Hitung absolute antenna height
        antenna_abs = self.elevations[0] + self.antenna_height

        for i, (d, elev) in enumerate(zip(self.distances, self.elevations)):

            # Hitung tinggi beam pada jarak d
            beam_h = antenna_abs - d * math.tan(math.radians(beam_angle))

            if d == 0:
                prev_d = d
                prev_elev = elev
                prev_beam_h = beam_h
                continue

            print(f"  d={d:.0f}m, terrain={elev:.1f}m, beam={beam_h:.1f}m")

            # Intersection terjadi ketika beam_height <= terrain_height
            if beam_h <= elev:
                print(f"    ✅ INTERSECTION at d={d:.0f}m")
                
                if prev_d is None:
                    result = {
                        "blocked": True,
                        "distance": d,
                        "terrain_height": elev,
                        "beam_height": beam_h,
                        "beam_angle": beam_angle
                    }
                    # Simpan ke cache
                    cache.set(cache_key, result)
                    return result

                # Linear interpolation antara prev_d dan d
                prev_beam = prev_beam_h
                prev_terrain = prev_elev
                
                # Cari titik di mana beam = terrain
                if beam_h == prev_beam:
                    interp_d = d
                else:
                    ratio = (prev_terrain - prev_beam) / ((beam_h - prev_beam) - (elev - prev_terrain))
                    interp_d = prev_d + ratio * (d - prev_d)
                
                print(f"    interpolated distance: {interp_d:.0f}m")

                result = {
                    "blocked": True,
                    "distance": interp_d,
                    "terrain_height": elev,
                    "beam_height": beam_h,
                    "beam_angle": beam_angle
                }
                # Simpan ke cache
                cache.set(cache_key, result)
                return result

            prev_d = d
            prev_elev = elev
            prev_beam_h = beam_h

        print(f"  ⚠️ NO INTERSECTION found for beam {beam_angle:.1f}°")
        result = {
            "blocked": False,
            "distance": None,
            "terrain_height": None,
            "beam_height": None,
            "beam_angle": beam_angle
        }
        # Simpan ke cache (negative result juga perlu dicache)
        cache.set(cache_key, result)
        return result

    # ======================================================
    # MULTI BEAM SOLVER
    # ======================================================

    def solve_beam_set(
        self,
        upper_beam,
        main_beam,
        lower_beam
    ):
        """
        Solve intersection untuk semua beam.

        Returns
        -------
        dict
        """

        upper = self.solve(upper_beam)
        main = self.solve(main_beam)
        lower = self.solve(lower_beam)

        return {
            "upper_beam": upper,
            "main_beam": main,
            "lower_beam": lower
        }

    # ======================================================
    # TERRAIN CLEARANCE CHECK
    # ======================================================

    def is_line_of_sight(self, beam_angle):
        """
        Check apakah beam LOS (tidak terhalang terrain).

        Returns
        -------
        bool
        """

        result = self.solve(beam_angle)

        return not result["blocked"]

    # ======================================================
    # FIRST OBSTRUCTION
    # ======================================================

    def first_obstruction(self):
        """
        Mengembalikan obstruction terrain tertinggi.

        Returns
        -------
        dict
        """

        max_angle = -999
        max_distance = None

        for d, angle in zip(self.distances, self.terrain_angles):

            if angle > max_angle:
                max_angle = angle
                max_distance = d

        return {
            "distance": max_distance,
            "terrain_angle": max_angle
        }



# ======================================================
# INTERSECTION CACHE WITH LRU (FIXED - MEMORY SAFE)
# ======================================================

from collections import OrderedDict

class IntersectionCache:
    """
    Cache untuk hasil intersection dengan LRU eviction policy
    Mencegah memory leak pada sesi panjang
    """
    _instance = None
    _cache = None
    _maxsize = 200  # Batas maksimum entries
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = OrderedDict()
        return cls._instance
    
    def get(self, key):
        """
        Get cached intersection result dengan LRU update
        """
        if key in self._cache:
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return self._cache[key]
        return None
    
    def set(self, key, value):
        """
        Set cached intersection result dengan LRU eviction
        """
        self._cache[key] = value
        self._cache.move_to_end(key)
        
        # Evict oldest if exceeds maxsize
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)
            print(f"🧹 LRU Cache: evicted oldest entry, size now {len(self._cache)}")
    
    def clear(self):
        """Clear cache"""
        self._cache.clear()
        print("🧹 Intersection cache cleared")
    
    def get_stats(self):
        """Get cache statistics"""
        return {
            'size': len(self._cache),
            'maxsize': self._maxsize
        }
    
    # ======================================================
    # TAMBAHKAN method ini ke class IntersectionCache
    # ======================================================
    def cleanup(self):
        """
        Force clear cache dan release memory.
        """
        self.clear()
        print("🧹 IntersectionCache fully cleared.")