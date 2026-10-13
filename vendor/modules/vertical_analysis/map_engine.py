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

import math

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform
)

from .utils import build_sector_polygon_planar


class VerticalAnalysisMapEngine:

    def __init__(self, iface):

        self.iface = iface
        self.project = QgsProject.instance()

        self.site_layer = None
        self.sector_layer = None
        self.los_layer = None
        self.impact_layer = None

    # ======================================================
    # PUBLIC API
    # ======================================================

    def render_analysis(
        self,
        site_lat,
        site_lon,
        azimuth,
        beamwidth,
        impact_distance
    ):

        self._ensure_layers()

        site_point = QgsPointXY(site_lon, site_lat)

        impact_point = self._calculate_impact_point(
            site_lat,
            site_lon,
            azimuth,
            impact_distance
        )

        self._draw_site(site_point)

        self._draw_sector(
            site_point,
            azimuth,
            beamwidth,
            impact_distance
        )

        self._draw_los(
            site_point,
            impact_point
        )

        self._draw_impact(
            impact_point
        )

        # ======================================================
        # AUTO ZOOM TO SITE
        # ======================================================

        canvas = self.iface.mapCanvas()

        canvas.setCenter(site_point)
        canvas.zoomScale(5000)


    # ======================================================
    # LAYER INITIALIZATION (ORIGINAL - FOR MAIN QGIS CANVAS)
    # ======================================================

    def _ensure_layers(self):
        """
        Initialize layers in main QGIS canvas.
        These SHOULD appear in layer panel.
        """

        # SITE
        if self.site_layer is None:

            existing = QgsProject.instance().mapLayersByName(
                "VerticalAnalysis_Site"
            )

            if existing:
                self.site_layer = existing[0]

            else:

                self.site_layer = QgsVectorLayer(
                    "Point?crs=EPSG:4326",
                    "VerticalAnalysis_Site",
                    "memory"
                )

                QgsProject.instance().addMapLayer(self.site_layer)

        # SECTOR
        if self.sector_layer is None:

            existing = QgsProject.instance().mapLayersByName(
                "VerticalAnalysis_Sector"
            )

            if existing:
                self.sector_layer = existing[0]

            else:

                self.sector_layer = QgsVectorLayer(
                    "Polygon?crs=EPSG:4326",
                    "VerticalAnalysis_Sector",
                    "memory"
                )

                QgsProject.instance().addMapLayer(self.sector_layer)

        # LOS
        if self.los_layer is None:

            existing = QgsProject.instance().mapLayersByName(
                "VerticalAnalysis_LOS"
            )

            if existing:
                self.los_layer = existing[0]

            else:

                self.los_layer = QgsVectorLayer(
                    "LineString?crs=EPSG:4326",
                    "VerticalAnalysis_LOS",
                    "memory"
                )

                QgsProject.instance().addMapLayer(self.los_layer)

        # IMPACT
        if self.impact_layer is None:

            existing = QgsProject.instance().mapLayersByName(
                "VerticalAnalysis_Impact"
            )

            if existing:
                self.impact_layer = existing[0]

            else:

                self.impact_layer = QgsVectorLayer(
                    "Point?crs=EPSG:4326",
                    "VerticalAnalysis_Impact",
                    "memory"
                )

                QgsProject.instance().addMapLayer(self.impact_layer)

    # ======================================================
    # DRAW SITE
    # ======================================================

    def _draw_site(self, site_point):

        layer = self.site_layer

        layer.startEditing()

        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(site_point))

        layer.addFeature(feat)

        layer.commitChanges()

    # ======================================================
    # DRAW SECTOR
    # ======================================================

    def _draw_sector(
        self,
        site_point,
        azimuth,
        beamwidth,
        radius
    ):

        layer = self.sector_layer

        layer.startEditing()

        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)

        utm_crs = self._get_utm_crs(site_point)

        to_utm = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            utm_crs,
            QgsProject.instance()
        )

        to_wgs = QgsCoordinateTransform(
            utm_crs,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )

        center_utm = to_utm.transform(site_point)

        cx = center_utm.x()
        cy = center_utm.y()

        pts = build_sector_polygon_planar(
            cx,
            cy,
            azimuth,
            beamwidth,
            radius
        )

        pts_wgs = []

        for p in pts:

            w = to_wgs.transform(p)
            pts_wgs.append(w)

        geom = QgsGeometry.fromPolygonXY([pts_wgs])

        feat = QgsFeature()
        feat.setGeometry(geom)

        layer.addFeature(feat)

        layer.commitChanges()
        
    
    # ======================================================
    # DRAW FOOTPRINT SECTOR
    # ======================================================

    def draw_sector_footprint(
        self,
        site_point,
        azimuth,
        start_distance,
        end_distance,
        beamwidth=65
    ):

        self._ensure_layers()

        layer = self.sector_layer

        layer.startEditing()

        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)

        utm_crs = self._get_utm_crs(site_point)

        to_utm = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            utm_crs,
            QgsProject.instance()
        )

        to_wgs = QgsCoordinateTransform(
            utm_crs,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )

        center_utm = to_utm.transform(site_point)

        cx = center_utm.x()
        cy = center_utm.y()

        outer_pts = build_sector_polygon_planar(
            cx,
            cy,
            azimuth,
            beamwidth,
            end_distance
        )

        inner_pts = build_sector_polygon_planar(
            cx,
            cy,
            azimuth,
            beamwidth,
            start_distance
        )

        inner_pts.reverse()

        ring = outer_pts + inner_pts

        pts_wgs = []

        for p in ring:

            w = to_wgs.transform(p)
            pts_wgs.append(w)

        geom = QgsGeometry.fromPolygonXY([pts_wgs])

        feat = QgsFeature()
        feat.setGeometry(geom)

        layer.addFeature(feat)

        layer.commitChanges()

    # ======================================================
    # DRAW LOS
    # ======================================================

    def _draw_los(self, site_point, impact_point):

        layer = self.los_layer

        layer.startEditing()

        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)

        geom = QgsGeometry.fromPolylineXY(
            [site_point, impact_point]
        )

        feat = QgsFeature()
        feat.setGeometry(geom)

        layer.addFeature(feat)

        layer.commitChanges()

    # ======================================================
    # DRAW IMPACT
    # ======================================================

    def _draw_impact(self, impact_point):

        layer = self.impact_layer

        layer.startEditing()

        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)

        feat = QgsFeature()
        feat.setGeometry(
            QgsGeometry.fromPointXY(impact_point)
        )

        layer.addFeature(feat)

        layer.commitChanges()

    # ======================================================
    # IMPACT POINT CALCULATION (FIXED CRS)
    # ======================================================

    def _calculate_impact_point(
        self,
        lat,
        lon,
        azimuth,
        distance
    ):
        """
        Calculate impact point using proper geodesic formula.
        All calculations in WGS84.
        """

        import math

        # Earth radius in meters
        R = 6378137.0

        lat1 = math.radians(lat)
        lon1 = math.radians(lon)

        az = math.radians(azimuth)

        # Angular distance
        delta = distance / R

        # Haversine formula
        lat2 = math.asin(
            math.sin(lat1) * math.cos(delta) +
            math.cos(lat1) * math.sin(delta) * math.cos(az)
        )

        lon2 = lon1 + math.atan2(
            math.sin(az) * math.sin(delta) * math.cos(lat1),
            math.cos(delta) - math.sin(lat1) * math.sin(lat2)
        )

        return QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )

    # ======================================================
    # UTM CRS
    # ======================================================

    def _get_utm_crs(self, point):

        lon = point.x()

        zone = int((lon + 180) / 6) + 1

        epsg = 32600 + zone

        return QgsCoordinateReferenceSystem(
            f"EPSG:{epsg}"
        )