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
controller.py

Vertical Analysis Controller

Bridge antara QGIS feature layer dan RF core engine.
"""

from qgis.core import QgsPointXY

from ...core.rf_engine import VerticalAnalysisEngine
from ...ui.dialogs.defaults import RFDefaults  # Naik 3 level
from .map_engine import VerticalAnalysisMapEngine
from qgis.utils import iface

class VerticalAnalysisController:
    """
    Controller untuk menjalankan RF Vertical Analysis
    dari sektor yang dipilih di map.
    """

    def __init__(self, dem_layer):
        # =====================================================
        # VALIDASI: Pastikan dem_layer adalah DEM, bukan basemap
        # =====================================================
        if dem_layer is not None:
            layer_name = dem_layer.name().lower()
            skip_keywords = ['bing', 'osm', 'openstreetmap', 'google', 'map', 'satellite', 'imagery', 'basemap']
            is_basemap = any(keyword in layer_name for keyword in skip_keywords)
            
            if is_basemap:
                raise ValueError(
                    f"'{dem_layer.name()}' appears to be a basemap, not a DEM.\n\n"
                    "Please load a valid DEM raster layer (e.g., SRTM, ASTER, or local elevation data)."
                )
        
        self.dem_layer = dem_layer
        self.engine = VerticalAnalysisEngine(dem_layer)

    # ======================================================
    # RUN ANALYSIS FROM FEATURE
    # ======================================================

    def analyze_feature(self, feature):
        """
        Run vertical analysis dari feature sektor.

        Parameters
        ----------
        feature : QgsFeature

        Returns
        -------
        dict
        """

        geom = feature.geometry()

        if geom.isEmpty():
            raise ValueError(
                "Selected feature has no geometry.\n\n"
                "Please select a valid sector feature with point, line, or polygon geometry."
            )

        # ======================================================
        # VALIDASI DEM LAYER
        # ======================================================
        if not self.dem_layer or not self.dem_layer.isValid():
            raise ValueError(
                "Tidak ada DEM layer yang valid di project.\n\n"
                "Pastikan DEM raster layer sudah dimuat dan dapat diakses."
            )
            
            
        # ======================================================
        # GET SITE POINT
        # ======================================================

        geom_type = geom.type()

        # 0 = Point
        # 1 = Line
        # 2 = Polygon

        if geom_type == 0:

            if geom.isMultipart():
                point = geom.asMultiPoint()[0]
            else:
                point = geom.asPoint()

        else:

            # gunakan centroid untuk Line / Polygon
            centroid = geom.centroid()

            if centroid.isEmpty():
                raise ValueError(
                    "Cannot calculate center point from the selected feature's geometry.\n\n"
                    "The geometry may be invalid or too complex. Try selecting a different feature."
                )

            point = centroid.asPoint()

        site_point = QgsPointXY(
            point.x(),
            point.y()
        )



        # ======================================================
        # GET RF PARAMETERS (Sector Polygon Standard v1)
        # =====================================================

        fields = feature.fields().names()
        
        # ---- ANTENNA HEIGHT ----
        if "HEIGHT_ANT" in fields:
            antenna_height = float(feature["HEIGHT_ANT"])
            if antenna_height <= 0:
                raise ValueError(f"Invalid antenna height: {antenna_height}. Must be positive.")
        else:
            raise ValueError("Field HEIGHT_ANT not found in sector layer")
        
        # ---- MECHANICAL TILT ----
        if "ANTENNA_ME" in fields:
            mech_tilt = float(feature["ANTENNA_ME"])
            # Validasi range realistic
            if mech_tilt < -10 or mech_tilt > 30:
                print(f"⚠️ Warning: Mechanical tilt {mech_tilt}° outside typical range (-10° to 30°)")
        else:
            raise ValueError("Field ANTENNA_ME not found in sector layer")
        
        # ---- ELECTRICAL TILT ----
        if "ANTENNA_EL" in fields:
            elec_tilt = float(feature["ANTENNA_EL"])
            if elec_tilt < 0 or elec_tilt > 15:
                print(f"⚠️ Warning: Electrical tilt {elec_tilt}° outside typical range (0° to 15°)")
        else:
            raise ValueError("Field ANTENNA_EL not found in sector layer")
        
        # ---- AZIMUTH ----
        if "ANTENNA_AZ" in fields:
            azimuth = float(feature["ANTENNA_AZ"])
            if azimuth < 0 or azimuth > 360:
                raise ValueError(f"Invalid azimuth: {azimuth}°. Must be between 0° and 360°.")
        else:
            raise ValueError("Field ANTENNA_AZ not found in sector layer")
        
        # ---- VERTICAL BEAMWIDTH ----
        beamwidth = RFDefaults.BEAMWIDTH_FALLBACK
        
        if "VERTICAL_B" in fields:
            beamwidth = float(feature["VERTICAL_B"])
            if beamwidth <= 0:
                raise ValueError(f"Invalid vertical beamwidth: {beamwidth}°. Must be positive.")
        elif "V_BEAMWIDTH" in fields:
            beamwidth = float(feature["V_BEAMWIDTH"])
            if beamwidth <= 0:
                raise ValueError(f"Invalid vertical beamwidth: {beamwidth}°. Must be positive.")
        
        # =====================================================
        # ======================================================
        # RUN CORE ENGINE
        # ======================================================

        result = self.engine.run(
            site_point=site_point,
            azimuth=azimuth,
            antenna_height=antenna_height,
            mech_tilt=mech_tilt,
            elec_tilt=elec_tilt,
            beamwidth=beamwidth
        )

        # attach metadata jika ada
        if "SITE_ID" in feature.fields().names():
            result["site_id"] = feature["SITE_ID"]

        if "SECTOR_ID" in feature.fields().names():
            result["sector_id"] = feature["SECTOR_ID"]

        return result
        
    
    # ======================================================
    # RUN ANALYSIS FROM UI PARAMETERS
    # ======================================================

    def run_analysis(self, params):
        """
        Run RF analysis with parameters from UI
        
        Parameters
        ----------
        params : dict
            Dictionary containing:
            - height: antenna height in meters
            - mech: mechanical tilt in degrees
            - elec: electrical tilt in degrees
            - beamwidth: vertical beamwidth in degrees
            - azimuth: azimuth in degrees
            - distance: max distance in meters
            - lat: latitude (optional, uses map center if None)
            - lon: longitude (optional, uses map center if None)
            - dem_source: 0=local, 1=online
            
        Returns
        -------
        dict
            Analysis results from engine
        """
        from qgis.core import QgsPointXY
        import time

        # ======================================================
        # GET PARAMETERS
        # ======================================================

        antenna_height = params.get("height")
        mech_tilt = params.get("mech")
        elec_tilt = params.get("elec")
        beamwidth = params.get("beamwidth")
        azimuth = params.get("azimuth")
        max_distance = params.get("distance", 5000)

        # Validasi parameter kritis
        if antenna_height is None or antenna_height <= 0:
            raise ValueError("Antenna height must be positive")
        
        if mech_tilt is None:
            raise ValueError("Mechanical tilt is required")
            
        if elec_tilt is None:
            raise ValueError("Electrical tilt is required")

        # ======================================================
        # CEK DEM SOURCE DAN SET TIMEOUT
        # ======================================================
        dem_source = params.get("dem_source", 0)
        source = "online" if dem_source == 1 else "local"
        
        # Set timeout berbeda untuk online vs local
        if source == "online":
            print("🌐 Using Open-Meteo online source - this may take a few seconds...")
            timeout = 45  # 45 detik untuk online
        else:
            timeout = 30  # 30 detik untuk local

        # ======================================================
        # GET SITE FROM PARAMS (UI)
        # ======================================================

        lat = params.get("lat")
        lon = params.get("lon")

        if lat is None or lon is None:
            from qgis.utils import iface
            canvas = iface.mapCanvas()
            center = canvas.extent().center()
            site_point = QgsPointXY(center.x(), center.y())
            print(f"📍 Using map center: ({center.y():.6f}, {center.x():.6f})")
        else:
            site_point = QgsPointXY(lon, lat)
            print(f"📍 Using provided coordinates: ({lat:.6f}, {lon:.6f})")

        # ======================================================
        # RUN ENGINE DENGAN TIMEOUT
        # ======================================================
        
        start_time = time.time()
        print(f"⏱️ Starting engine run at {time.strftime('%H:%M:%S')}")
        
        try:
            result = self.engine.run(
                site_point=site_point,
                azimuth=azimuth,
                antenna_height=antenna_height,
                mech_tilt=mech_tilt,
                elec_tilt=elec_tilt,
                beamwidth=beamwidth,
                max_distance=max_distance,
                dem_source=source,
                timeout=timeout  # PARAMETER TIMEOUT
            )
            
            elapsed = time.time() - start_time
            print(f"⏱️ Engine run completed in {elapsed:.1f} seconds")
            
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Engine run failed after {elapsed:.1f} seconds: {e}")
            import traceback
            traceback.print_exc()
            
            # Return error object instead of raising
            return {
                "error": True,
                "error_message": str(e),
                "source": source,
                "distances": [],
                "elevations": [],
                "main_beam": None,
                "upper_beam": None,
                "lower_beam": None,
                "impact_distance": None,
                "impact_point": None,
                "footprint_start_distance": None,
                "footprint_end_distance": None
            }

        # ======================================================
        # MAP RENDERING DISABLED (Handled by UI widget)
        # ======================================================
        # Rendering sector footprint dilakukan oleh SectorMapWidget
        # di vertical_analysis_dialog.py agar layer hanya muncul
        # di embedded plugin canvas, bukan di main QGIS canvas.
        
        return result