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
map_renderer.py

Map Renderer untuk Vertical RF Analysis.

Menampilkan hasil analisis di map QGIS:
- Site point
- Impact point
- Coverage line
"""

import math

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject
)

from ..geometry import SectorGeometry
from PyQt5.QtCore import QVariant




class MapRenderer:
    """
    Renderer untuk menampilkan hasil RF Vertical Analysis.
    """

    def __init__(self):
        self.project = QgsProject.instance()

    # ======================================================
    # CLEAR EXISTING LAYERS
    # ======================================================

    def clear_previous(self):

        remove_list = []

        for layer in self.project.mapLayers().values():

            if layer.name().startswith("VerticalAnalysis"):

                remove_list.append(layer.id())

        for lid in remove_list:
            self.project.removeMapLayer(lid)

    # ======================================================
    # RENDER FULL RESULT
    # ======================================================

    def render(
        self,
        site_point,
        impact_point,
        azimuth=None,
        beamwidth=65,
        lower_distance=None,
        upper_distance=None
    ):

        self.clear_previous()

        self._draw_site(site_point)

        if impact_point:

            self._draw_impact(impact_point)

            self._draw_coverage_line(site_point, impact_point)

        # ======================================================
        # DRAW COVERAGE FOOTPRINT
        # ======================================================

        if azimuth is not None and upper_distance is not None:

            footprint = SectorGeometry.footprint_from_beams(
                center=site_point,
                azimuth=azimuth,
                horizontal_beamwidth=beamwidth,
                lower_distance=lower_distance,
                upper_distance=upper_distance
            )

            if footprint:

                self._draw_footprint(footprint)

    # ======================================================
    # DRAW SITE
    # ======================================================

    def _draw_site(self, point):

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            "VerticalAnalysis_Site",
            "memory"
        )

        provider = layer.dataProvider()

        feat = QgsFeature()

        feat.setGeometry(
            QgsGeometry.fromPointXY(point)
        )

        provider.addFeature(feat)

        layer.updateExtents()

        self.project.addMapLayer(layer)

    # ======================================================
    # DRAW IMPACT
    # ======================================================

    def _draw_impact(self, point):

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            "VerticalAnalysis_Impact",
            "memory"
        )

        provider = layer.dataProvider()

        feat = QgsFeature()

        feat.setGeometry(
            QgsGeometry.fromPointXY(point)
        )

        provider.addFeature(feat)

        layer.updateExtents()

        self.project.addMapLayer(layer)

    # ======================================================
    # DRAW COVERAGE LINE
    # ======================================================

    def _draw_coverage_line(self, site, impact):

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            "VerticalAnalysis_Coverage",
            "memory"
        )

        provider = layer.dataProvider()

        feat = QgsFeature()

        feat.setGeometry(
            QgsGeometry.fromPolylineXY(
                [site, impact]
            )
        )

        provider.addFeature(feat)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
        
    
    # ======================================================
    # DRAW COVERAGE FOOTPRINT
    # ======================================================

    def _draw_footprint(self, geometry):

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_Footprint",
            "memory"
        )

        provider = layer.dataProvider()

        feat = QgsFeature()

        feat.setGeometry(geometry)

        provider.addFeature(feat)

        layer.updateExtents()

        self.project.addMapLayer(layer)
    
    
    
    # ======================================================
    # DESTINATION POINT
    # ======================================================

    def _destination_point(self, origin, azimuth_deg, distance_m):

        R = 6378137.0

        lat1 = math.radians(origin.y())
        lon1 = math.radians(origin.x())

        az = math.radians(azimuth_deg)

        lat2 = lat1 + (distance_m / R) * math.cos(az)
        lon2 = lon1 + (distance_m / R) * math.sin(az) / math.cos(lat1)

        return QgsPointXY(
            math.degrees(lon2),
            math.degrees(lat2)
        )
    
    


    # ======================================================
    # RF COVERAGE QUALITY MAP
    # ======================================================

    def draw_rf_quality_map(
        self,
        site_point,
        azimuth,
        distances,
        terrain,
        beam
    ):

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            "VerticalAnalysis_RF_Coverage",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("distance", QVariant.Double))
        fields.append(QgsField("clearance", QVariant.Double))
        fields.append(QgsField("quality", QVariant.String))

        provider.addAttributes(fields)

        layer.updateFields()

        feats = []

        for d, t, b in zip(distances, terrain, beam):

            clearance = b - t

            if clearance > 10:
                quality = "excellent"

            elif clearance > 5:
                quality = "good"

            elif clearance > 0:
                quality = "weak"

            else:
                quality = "blocked"

            # project radial point

            pt = self._destination_point(
                site_point,
                azimuth,
                d
            )

            feat = QgsFeature()

            feat.setGeometry(
                QgsGeometry.fromPointXY(pt)
            )

            feat.setAttributes([
                d,
                clearance,
                quality
            ])

            feats.append(feat)

        provider.addFeatures(feats)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
        
    # ======================================================
    # 2D RF COVERAGE SECTOR MAP
    # ======================================================

    def draw_rf_sector_map(
        self,
        site_point,
        azimuth,
        beamwidth,
        distances,
        terrain,
        beam
    ):

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_RF_2D_Coverage",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("distance", QVariant.Double))
        fields.append(QgsField("clearance", QVariant.Double))
        fields.append(QgsField("quality", QVariant.String))

        provider.addAttributes(fields)

        layer.updateFields()

        feats = []

        start_angle = azimuth - beamwidth / 2
        end_angle = azimuth + beamwidth / 2

        angle_step = beamwidth / 20

        for angle in [start_angle + i * angle_step for i in range(int(beamwidth / angle_step))]:

            for d, t, b in zip(distances, terrain, beam):

                clearance = b - t

                if clearance > 10:
                    quality = "excellent"

                elif clearance > 5:
                    quality = "good"

                elif clearance > 0:
                    quality = "weak"

                else:
                    quality = "blocked"

                p1 = self._destination_point(site_point, angle, d)
                p2 = self._destination_point(site_point, angle + angle_step, d)
                p3 = self._destination_point(site_point, angle + angle_step, d + 50)
                p4 = self._destination_point(site_point, angle, d + 50)

                geom = QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])

                feat = QgsFeature()

                feat.setGeometry(geom)

                feat.setAttributes([
                    d,
                    clearance,
                    quality
                ])

                feats.append(feat)

        provider.addFeatures(feats)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
        
        
    # ======================================================
    # MULTI SITE COVERAGE SIMULATION
    # ======================================================

    def draw_multi_site_coverage(
        self,
        sector_layer,
        engine
    ):

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_MultiSite_Coverage",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("site", QVariant.String))
        fields.append(QgsField("distance", QVariant.Double))
        fields.append(QgsField("quality", QVariant.String))

        provider.addAttributes(fields)

        layer.updateFields()

        feats = []

        for f in sector_layer.getFeatures():

            geom = f.geometry()

            site_point = geom.centroid().asPoint()

            azimuth = f["ANTENNA_AZ"]

            mech = f["ANTENNA_ME"]

            elec = f["ANTENNA_EL"]

            height = f["HEIGHT_ANT"]

            beamwidth = f["VERTICAL_B"]

            try:

                result = engine.run(
                    site_point=site_point,
                    azimuth=azimuth,
                    antenna_height=height,
                    mech_tilt=mech,
                    elec_tilt=elec,
                    beamwidth=beamwidth
                )

            except Exception:
                continue

            if not result:
                continue

            distances = result["distances"]

            terrain = result["elevations"]

            beam = result["main_beam_line"]

            start_angle = azimuth - 30
            end_angle = azimuth + 30

            angle_step = 3

            for angle in range(int(start_angle), int(end_angle), angle_step):

                for d, t, b in zip(distances, terrain, beam):

                    clearance = b - t

                    if clearance > 10:
                        quality = "excellent"

                    elif clearance > 5:
                        quality = "good"

                    elif clearance > 0:
                        quality = "weak"

                    else:
                        quality = "blocked"

                    p1 = self._destination_point(site_point, angle, d)
                    p2 = self._destination_point(site_point, angle + angle_step, d)
                    p3 = self._destination_point(site_point, angle + angle_step, d + 50)
                    p4 = self._destination_point(site_point, angle, d + 50)

                    geom = QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])

                    feat = QgsFeature()

                    feat.setGeometry(geom)

                    feat.setAttributes([
                        str(f["CELL_NAME"]) if "CELL_NAME" in f.fields().names() else "site",
                        d,
                        quality
                    ])

                    feats.append(feat)

        provider.addFeatures(feats)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
    
    
    # ======================================================
    # COVERAGE GAP DETECTION
    # ======================================================

    def detect_coverage_gap(
        self,
        coverage_layer,
        site_point,
        azimuth,
        beamwidth,
        max_distance
    ):

        # union coverage geometry

        union_geom = None

        for f in coverage_layer.getFeatures():

            g = f.geometry()

            if union_geom is None:
                union_geom = g

            else:
                union_geom = union_geom.combine(g)

        if union_geom is None:
            return

        # build sector boundary

        start_angle = azimuth - beamwidth / 2
        end_angle = azimuth + beamwidth / 2

        pts = [site_point]

        step = beamwidth / 40

        angle = start_angle

        while angle <= end_angle:

            p = self._destination_point(site_point, angle, max_distance)

            pts.append(p)

            angle += step

        pts.append(site_point)

        sector_geom = QgsGeometry.fromPolygonXY([pts])

        # difference = gap

        gap_geom = sector_geom.difference(union_geom)

        if gap_geom.isEmpty():
            return

        # create layer

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_Coverage_Gap",
            "memory"
        )

        provider = layer.dataProvider()

        feat = QgsFeature()

        feat.setGeometry(gap_geom)

        provider.addFeature(feat)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
    
    
    # ======================================================
    # COVERAGE OVERLAP / INTERFERENCE DETECTION
    # ======================================================

    def detect_coverage_overlap(
        self,
        coverage_layer
    ):

        feats = list(coverage_layer.getFeatures())

        if len(feats) < 2:
            return

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_Coverage_Overlap",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("siteA", QVariant.String))
        fields.append(QgsField("siteB", QVariant.String))

        provider.addAttributes(fields)

        layer.updateFields()

        overlap_feats = []

        for i in range(len(feats)):

            geomA = feats[i].geometry()

            siteA = feats[i]["site"] if "site" in feats[i].fields().names() else "A"

            for j in range(i + 1, len(feats)):

                geomB = feats[j].geometry()

                siteB = feats[j]["site"] if "site" in feats[j].fields().names() else "B"

                inter = geomA.intersection(geomB)

                if inter.isEmpty():
                    continue

                feat = QgsFeature()

                feat.setGeometry(inter)

                feat.setAttributes([
                    siteA,
                    siteB
                ])

                overlap_feats.append(feat)

        if not overlap_feats:
            return

        provider.addFeatures(overlap_feats)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
    
    
    # ======================================================
    # AUTOMATIC NEIGHBOR SUGGESTION ENGINE
    # ======================================================

    def suggest_neighbors(
        self,
        overlap_layer
    ):

        feats = list(overlap_layer.getFeatures())

        if not feats:
            return

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            "VerticalAnalysis_Neighbor_Suggestion",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("sector_A", QVariant.String))
        fields.append(QgsField("sector_B", QVariant.String))
        fields.append(QgsField("overlap_area", QVariant.Double))

        provider.addAttributes(fields)

        layer.updateFields()

        feats_out = []

        for f in feats:

            geom = f.geometry()

            siteA = f["siteA"] if "siteA" in f.fields().names() else "A"
            siteB = f["siteB"] if "siteB" in f.fields().names() else "B"

            area = geom.area()

            centroid = geom.centroid().asPoint()

            feat = QgsFeature()

            # represent relation as point-to-point small line

            line = QgsGeometry.fromPolylineXY([
                centroid,
                centroid
            ])

            feat.setGeometry(line)

            feat.setAttributes([
                siteA,
                siteB,
                area
            ])

            feats_out.append(feat)

        if not feats_out:
            return

        provider.addFeatures(feats_out)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
        
        
    # ======================================================
    # PCI COLLISION DETECTOR
    # ======================================================

    def detect_pci_collision(
        self,
        overlap_layer,
        sector_layer,
        pci_field="PCI"
    ):

        # build sector PCI lookup

        pci_lookup = {}

        for f in sector_layer.getFeatures():

            name = f["CELL_NAME"] if "CELL_NAME" in f.fields().names() else None

            if name is None:
                continue

            pci_lookup[name] = f[pci_field]

        feats = list(overlap_layer.getFeatures())

        if not feats:
            return

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_PCI_Collision",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("sector_A", QVariant.String))
        fields.append(QgsField("sector_B", QVariant.String))
        fields.append(QgsField("PCI", QVariant.Int))
        fields.append(QgsField("overlap_area", QVariant.Double))

        provider.addAttributes(fields)

        layer.updateFields()

        out_feats = []

        for f in feats:

            geom = f.geometry()

            siteA = f["siteA"] if "siteA" in f.fields().names() else None
            siteB = f["siteB"] if "siteB" in f.fields().names() else None

            if siteA not in pci_lookup or siteB not in pci_lookup:
                continue

            pciA = pci_lookup[siteA]
            pciB = pci_lookup[siteB]

            if pciA != pciB:
                continue

            feat = QgsFeature()

            feat.setGeometry(geom)

            feat.setAttributes([
                siteA,
                siteB,
                pciA,
                geom.area()
            ])

            out_feats.append(feat)

        if not out_feats:
            return

        provider.addFeatures(out_feats)

        layer.updateExtents()

        self.project.addMapLayer(layer)
        
        
    
    # ======================================================
    # PCI CONFUSION DETECTOR
    # ======================================================

    def detect_pci_confusion(
        self,
        overlap_layer,
        sector_layer,
        pci_field="PCI"
    ):

        # build sector PCI lookup

        pci_lookup = {}

        for f in sector_layer.getFeatures():

            name = f["CELL_NAME"] if "CELL_NAME" in f.fields().names() else None

            if name is None:
                continue

            pci_lookup[name] = f[pci_field]

        feats = list(overlap_layer.getFeatures())

        if not feats:
            return

        pci_groups = {}

        for f in feats:

            geom = f.geometry()

            siteA = f["siteA"] if "siteA" in f.fields().names() else None
            siteB = f["siteB"] if "siteB" in f.fields().names() else None

            if siteA not in pci_lookup or siteB not in pci_lookup:
                continue

            pciA = pci_lookup[siteA]
            pciB = pci_lookup[siteB]

            if pciA != pciB:
                continue

            pci = pciA

            if pci not in pci_groups:
                pci_groups[pci] = []

            pci_groups[pci].append((geom, siteA, siteB))

        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "VerticalAnalysis_PCI_Confusion",
            "memory"
        )

        provider = layer.dataProvider()

        fields = QgsFields()

        fields.append(QgsField("PCI", QVariant.Int))
        fields.append(QgsField("sector_count", QVariant.Int))
        fields.append(QgsField("area", QVariant.Double))

        provider.addAttributes(fields)

        layer.updateFields()

        feats_out = []

        for pci, items in pci_groups.items():

            sectors = set()

            geom_union = None

            for geom, a, b in items:

                sectors.add(a)
                sectors.add(b)

                if geom_union is None:
                    geom_union = geom
                else:
                    geom_union = geom_union.combine(geom)

            if len(sectors) < 3:
                continue

            feat = QgsFeature()

            feat.setGeometry(geom_union)

            feat.setAttributes([
                pci,
                len(sectors),
                geom_union.area()
            ])

            feats_out.append(feat)

        if not feats_out:
            return

        provider.addFeatures(feats_out)

        layer.updateExtents()

        self.project.addMapLayer(layer)