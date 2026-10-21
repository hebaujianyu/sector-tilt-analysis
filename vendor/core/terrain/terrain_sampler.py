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
terrain_sampler.py - dengan threading support
"""

import math
import threading
import queue
import requests
import json
import time
from PyQt5.QtCore import QTimer
from qgis.core import QgsNetworkAccessManager, QgsBlockingNetworkRequest
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtCore import QUrl, QCoreApplication
from typing import List, Dict, Any
from qgis.core import (
    QgsPointXY,
    QgsRaster,
    QgsRasterLayer,
    QgsCoordinateTransform,
    QgsProject,
)
from ...ui.dialogs.defaults import RFDefaults

EARTH_RADIUS = 6378137.0


class TerrainSampler:
    """
    Terrain sampling engine dengan threading support.
    """

    MAX_CACHE_SIZE = RFDefaults.TERRAIN_CACHE_SIZE
    
    def __init__(self, dem_layer: QgsRasterLayer):
        if not isinstance(dem_layer, QgsRasterLayer):
            raise ValueError(
                "Invalid DEM layer type.\n\n"
                "The selected layer must be a raster layer containing elevation data. "
                "Please load a valid DEM raster layer."
            )

        self.dem = dem_layer
        self._cache = {}  # Cache untuk hasil sampling
        self._cache_lock = threading.Lock()
        self._cache_access_time = {}  # Track akses untuk LRU
    
    
    def _add_to_cache(self, key, value):
        """
        Add item to cache dengan LRU tracking - THREAD SAFE
        """
        with self._cache_lock:
            # Jika cache sudah penuh, hapus yang paling lama tidak diakses
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                # Cari item dengan access time paling lama
                if self._cache_access_time:
                    oldest_key = min(self._cache_access_time.keys(), 
                                    key=lambda k: self._cache_access_time[k])
                    del self._cache[oldest_key]
                    del self._cache_access_time[oldest_key]
                    print(f"🧹 Cache LRU: removed oldest entry")
            
            # Tambahkan item baru
            self._cache[key] = value
            self._cache_access_time[key] = time.time()
    
    def _get_from_cache(self, key):
        """
        Get item from cache and update access time - THREAD SAFE
        """
        with self._cache_lock:
            if key in self._cache:
                # Update access time
                self._cache_access_time[key] = time.time()
                return self._cache[key]
        return None
    
    def clear_cache(self):
        """Clear all cached terrain samples - THREAD SAFE"""
        with self._cache_lock:
            cache_size = len(self._cache)
            self._cache.clear()
            self._cache_access_time.clear()
            print(f"🧹 Cleared {cache_size} entries from terrain cache")
    
    # ======================================================
    # TAMBAHKAN method ini ke class TerrainSampler
    # ======================================================
    def cleanup(self):
        """
        Cleanup final untuk sampler, membersihkan cache.
        Dipanggil saat analisis selesai atau dialog ditutup.
        """
        self.clear_cache()
        print("🧹 TerrainSampler cache cleared.")
    
    def get_cache_stats(self):
        """Get cache statistics - THREAD SAFE"""
        with self._cache_lock:
            return {
                'size': len(self._cache),
                'max_size': self.MAX_CACHE_SIZE,
                'utilization': f"{len(self._cache)}/{self.MAX_CACHE_SIZE}"
            }
            

    # ======================================================
    # PUBLIC API - SYNCHRONOUS (UNTUK UI)
    # ======================================================

    def sample_profile(
        self,
        site_point,
        azimuth,
        max_distance,
        step,
        source="local",
        timeout=30
    ):
        """
        Sample terrain elevation sepanjang azimuth sektor
        """
        # =====================================================
        # VALIDASI INPUT
        # =====================================================
        if max_distance <= 0:
            raise ValueError(f"Max distance must be positive: {max_distance}")
        
        if step <= 0:
            raise ValueError(f"Sampling step must be positive: {step}")
        
        if step > max_distance:
            step = max_distance / 10
            print(f"⚠️ Step too large, adjusted to {step:.0f}m")
        
        if timeout <= 0:
            timeout = 30
            print(f"⚠️ Invalid timeout, using default: {timeout}s")
        
        # Buat cache key
        cache_key = (
            round(site_point.x(), 6),
            round(site_point.y(), 6),
            round(azimuth, 2),
            int(max_distance),
            int(step),
            source
        )
        
        # Cek cache menggunakan method baru
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            print(f"✅ Using cached terrain data for {cache_key}")
            return cached_result
        
        # Sampling based on source
        try:
            if source == "online":
                # =====================================================
                # FIXED: THREAD SAFE ONLINE SAMPLING DENGAN CLEANUP
                # =====================================================
                import threading
                import queue
                import time
                
                result_queue = queue.Queue()
                thread = None
                
                try:
                    def worker():
                        try:
                            result = self.sample_profile_online(site_point, azimuth, max_distance, step)
                            result_queue.put(("success", result))
                        except Exception as e:
                            result_queue.put(("error", str(e)))
                    
                    thread = threading.Thread(target=worker)
                    thread.daemon = True
                    thread.start()
                    
                    # Wait with timeout
                    thread.join(timeout)
                    
                    if thread.is_alive():
                        # Thread still running after timeout - force cleanup
                        print(f"⚠️ Thread still alive after {timeout}s, marking for cleanup...")
                        # Cannot force kill thread in Python, but we can abandon it
                        # The daemon flag will ensure it dies when main thread exits
                        raise Exception(f"Open-Meteo request timed out after {timeout} seconds")
                    
                    # Get result with timeout to prevent blocking
                    try:
                        status, data = result_queue.get(timeout=5)
                    except queue.Empty:
                        raise Exception("No response from worker thread")
                    
                    if status == "error":
                        raise Exception(data)
                    result = data
                    
                except Exception as e:
                    # Clean up thread reference
                    thread = None
                    raise
                finally:
                    # Clear queue to free memory
                    while not result_queue.empty():
                        try:
                            result_queue.get_nowait()
                        except queue.Empty:
                            break
            else:
                result = self._sample_sync(site_point, azimuth, max_distance, step)
            
            # Simpan ke cache menggunakan method baru
            self._add_to_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            print(f"❌ Terrain sampling failed: {e}")
            # Re-raise dengan pesan yang lebih jelas
            raise Exception(f"Failed to sample terrain from {source}: {str(e)}")

    # ======================================================
    # ASYNCHRONOUS SAMPLING (UNTUK BACKGROUND)
    # ======================================================

    def sample_profile_async(
        self,
        site_point,
        azimuth,
        max_distance,
        step,
        callback=None
    ):
        """
        Sample terrain secara asynchronous
        """
        
        # Buat queue untuk result
        result_queue = queue.Queue()
        
        def worker():
            try:
                result = self._sample_sync(site_point, azimuth, max_distance, step)
                result_queue.put(result)
            except Exception as e:
                result_queue.put(e)
        
        # Start thread
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()
        
        if callback:
            # Polling untuk result
            def check_result():
                try:
                    result = result_queue.get_nowait()
                    if isinstance(result, Exception):
                        callback(None, result)
                    else:
                        callback(result, None)
                except queue.Empty:
                    # Schedule again
                    QTimer.singleShot(100, check_result)
            
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, check_result)
        
        return thread

    # ======================================================
    # INTERNAL METHODS
    # ======================================================

    def _sample_sync(self, site_point, azimuth, max_distance, step):
        """
        Internal synchronous sampling
        """
        
        provider = self.dem.dataProvider()
        distances = []
        elevations = []
        
        lat1 = math.radians(site_point.y())
        lon1 = math.radians(site_point.x())
        az = math.radians(azimuth)
        
        d = 0
        while d <= max_distance:
            lat2 = lat1 + (d / EARTH_RADIUS) * math.cos(az)
            lon2 = lon1 + (d / EARTH_RADIUS) * math.sin(az) / math.cos(lat1)
            
            point = QgsPointXY(
                math.degrees(lon2),
                math.degrees(lat2)
            )
            
            # Sample raster
            result = provider.identify(
                point,
                QgsRaster.IdentifyFormatValue
            )
            
            elevation = 0
            if result.isValid():
                values = result.results()
                if 1 in values:
                    elevation = float(values[1])
            
            distances.append(d)
            elevations.append(elevation)
            d += step
        
        return {
            "distances": distances,
            "elevations": elevations
        }
        
    
    # ======================================================
    # OPEN-METEO API METHODS
    # ======================================================
    
    def sample_profile_online(self, site_point, azimuth, max_distance, step):
        """
        Sample terrain elevation using Open-Meteo API
        
        Parameters
        ----------
        site_point : QgsPointXY
            Site location in WGS84
        azimuth : float
            Azimuth angle in degrees
        max_distance : float
            Maximum distance in meters
        step : float
            Sampling step in meters
            
        Returns
        -------
        dict
            {"distances": [...], "elevations": [...]}
        """
        
        # Hitung jumlah titik yang akan dihasilkan
        n_points = int(max_distance / step) + 1
        
        # Open-Meteo API max 100 points per request
        # Kita pakai 98 untuk safety (buffer 2)
        MAX_POINTS = 98
        
        # Jika terlalu banyak untuk Open-Meteo, sesuaikan step
        if n_points > MAX_POINTS:
            # Hitung step baru agar total titik <= MAX_POINTS
            # Rumus: max_distance / (MAX_POINTS - 1) = step baru
            new_step = max_distance / (MAX_POINTS - 1)
            print(f"⚠️ Too many points ({n_points}) for Open-Meteo API (max {MAX_POINTS})")
            print(f"   Adjusting step from {step}m to {new_step:.0f}m")
            step = new_step
            n_points = int(max_distance / step) + 1
            print(f"   New point count: {n_points}")
        
        # Generate route points dengan step yang sudah disesuaikan
        route_points = self._generate_route_points(site_point, azimuth, max_distance, step)
        
        # Fetch from Open-Meteo
        elevations = self._fetch_from_open_meteo(route_points)
        
        if elevations is None:
            # Coba dengan chunking sebagai fallback
            print("⚠️ Direct fetch failed, trying chunked mode...")
            elevations = self._fetch_open_meteo_chunked(route_points, max_retries=3)
            
        if elevations is None:
            raise Exception(
                "Failed to retrieve elevation data from Open-Meteo service.\n\n"
                "This could be due to:\n"
                "• No internet connection\n"
                "• Open-Meteo service temporarily unavailable\n"
                "• Too many points requested\n\n"
                "Please check your connection or try again later."
            )
        
        # Build result
        distances = [p["distance"] for p in route_points]
        
        result = {
            "distances": distances,
            "elevations": elevations
        }
        
        return result
        
        
    
    def _generate_route_points(self, site_point, azimuth, max_distance, step):
        """
        Generate points along azimuth for sampling
        
        Returns
        -------
        list of dict
            [{"lat": lat, "lon": lon, "distance": distance}, ...]
        """
        import math
        
        EARTH_RADIUS = 6378137.0
        points = []
        
        lat1 = math.radians(site_point.y())
        lon1 = math.radians(site_point.x())
        az = math.radians(azimuth)
        
        d = 0
        while d <= max_distance:
            lat2 = lat1 + (d / EARTH_RADIUS) * math.cos(az)
            lon2 = lon1 + (d / EARTH_RADIUS) * math.sin(az) / math.cos(lat1)
            
            points.append({
                "lat": math.degrees(lat2),
                "lon": math.degrees(lon2),
                "distance": d
            })
            
            d += step
        
        return points
    
    def _fetch_from_open_meteo(self, route_points, max_retries=3):
        """
        Fetch elevation data from Open-Meteo API dengan NON-BLOCKING request
        """
        
        # Prepare coordinates with HIGH precision (not rounded)
        latitudes = [str(p["lat"]) for p in route_points]
        longitudes = [str(p["lon"]) for p in route_points]
        
        # Join with commas
        lat_str = ",".join(latitudes)
        lon_str = ",".join(longitudes)
        
        # Build URL
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lat_str}&longitude={lon_str}"
        
        print(f"📡 Fetching Open-Meteo data for {len(route_points)} points...")
        print(f"URL length: {len(url)} characters")
        
        # Check if URL is too long (browser limit ~2000 chars)
        if len(url) > 1800:
            print(f"⚠️ URL too long ({len(url)} chars), splitting into chunks...")
            return self._fetch_open_meteo_chunked(route_points, max_retries)
        
        # =====================================================
        # GUNAKAN REQUEST DENGAN THREAD AGAR TIDAK BLOCKING
        # =====================================================
        for attempt in range(max_retries):
            try:
                # Gunakan requests dengan timeout - ini akan block di thread,
                # tapi kita sudah di background thread, jadi aman
                import requests
                
                # Set smaller timeout untuk memastikan tidak hang terlalu lama
                response = requests.get(
                    url, 
                    timeout=30,
                    headers={"User-Agent": "SectorTiltAnalysis-QGIS-Plugin"}
                )
                
                if response.status_code != 200:
                    print(f"❌ HTTP error: {response.status_code}")
                    
                    # Exponential backoff
                    if response.status_code == 429:  # Rate limited
                        wait_time = 5 * (attempt + 1)
                        print(f"⏳ Rate limited. Waiting {wait_time}s...")
                    else:
                        wait_time = 2 ** attempt
                        print(f"⏳ Retrying in {wait_time}s...")
                    
                    import time
                    time.sleep(wait_time)
                    continue
                
                data = response.json()
                
                if "elevation" not in data:
                    print(f"❌ Invalid response: missing 'elevation' field")
                    return None
                
                elevations = data["elevation"]
                
                if len(elevations) != len(route_points):
                    print(f"❌ Mismatch: got {len(elevations)} elevations for {len(route_points)} points")
                    return None
                
                print(f"✅ Fetched {len(elevations)} elevation points from Open-Meteo")
                return elevations
                
            except Exception as e:
                print(f"❌ Attempt {attempt + 1} failed: {e}")
                import traceback
                traceback.print_exc()
                
                if attempt == max_retries - 1:
                    return None
                
                # Exponential backoff
                import time
                wait_time = 2 ** attempt
                print(f"⏳ Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        return None
    
    
    def _fetch_open_meteo_chunked(self, route_points, max_retries=3):
        """
        Fetch elevation data in chunks dengan NON-BLOCKING request
        """
        import requests
        import time
        
        MAX_POINTS_PER_CHUNK = 98
        
        chunk_size = MAX_POINTS_PER_CHUNK
        all_elevations = []
        total_chunks = (len(route_points) + chunk_size - 1) // chunk_size
        
        print(f"📡 Fetching {len(route_points)} points in {total_chunks} chunks...")
        
        for i in range(0, len(route_points), chunk_size):
            chunk = route_points[i:i+chunk_size]
            chunk_num = i//chunk_size + 1
            
            # Prepare coordinates for this chunk
            latitudes = [str(p["lat"]) for p in chunk]
            longitudes = [str(p["lon"]) for p in chunk]
            
            lat_str = ",".join(latitudes)
            lon_str = ",".join(longitudes)
            
            url = f"https://api.open-meteo.com/v1/elevation?latitude={lat_str}&longitude={lon_str}"
            
            print(f"📡 Fetching chunk {chunk_num}/{total_chunks} ({len(chunk)} points)...")
            
            # Retry for this chunk
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        url, 
                        timeout=30,
                        headers={"User-Agent": "SectorTiltAnalysis-QGIS-Plugin"}
                    )
                    
                    if response.status_code != 200:
                        print(f"❌ Chunk {chunk_num} HTTP error: {response.status_code}")
                        
                        if response.status_code == 429:  # Rate limited
                            wait_time = 5 * (attempt + 1)
                            print(f"⏳ Rate limited. Waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            return None
                    
                    data = response.json()
                    
                    if "elevation" not in data:
                        print(f"❌ Chunk {chunk_num} invalid response")
                        return None
                    
                    chunk_elevations = data["elevation"]
                    
                    if len(chunk_elevations) != len(chunk):
                        print(f"❌ Chunk {chunk_num} mismatch")
                        return None
                    
                    all_elevations.extend(chunk_elevations)
                    print(f"✅ Chunk {chunk_num} complete")
                    break
                    
                except Exception as e:
                    print(f"❌ Chunk {chunk_num} attempt {attempt + 1} failed: {e}")
                    
                    if attempt == max_retries - 1:
                        return None
                    time.sleep(2 * (attempt + 1))
            
            # Small delay between chunks
            if chunk_num < total_chunks:
                time.sleep(1)
        
        if len(all_elevations) != len(route_points):
            return None
        
        return all_elevations
    
    
        
    def _generate_route_points(self, site_point, azimuth, max_distance, step):
        """
        Generate points along azimuth for sampling
        
        Returns
        -------
        list of dict
            [{"lat": lat, "lon": lon, "distance": distance}, ...]
        """
        import math
        
        EARTH_RADIUS = 6378137.0
        points = []
        
        lat1 = math.radians(site_point.y())
        lon1 = math.radians(site_point.x())
        az = math.radians(azimuth)
        
        d = 0
        while d <= max_distance:
            lat2 = lat1 + (d / EARTH_RADIUS) * math.cos(az)
            lon2 = lon1 + (d / EARTH_RADIUS) * math.sin(az) / math.cos(lat1)
            
            lat_deg = math.degrees(lat2)
            lon_deg = math.degrees(lon2)
            
            points.append({
                "lat": lat_deg,
                "lon": lon_deg,
                "distance": d
            })
            
            d += step
        
        # Debug: print first few points
        print(f"📍 Generated {len(points)} route points")
        print(f"   First point: lat={points[0]['lat']:.6f}, lon={points[0]['lon']:.6f}")
        if len(points) > 1:
            print(f"   Last point: lat={points[-1]['lat']:.6f}, lon={points[-1]['lon']:.6f}")
        
        return points
        