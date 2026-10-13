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
layer_manager.py

Layer management untuk RF Vertical Analysis.
Mengelola lifecycle layer dan mencegah duplicate/ghost layers.
"""

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem
)


class LayerManager:
    """
    Manages RF analysis layers in QGIS project.
    Ensures single instance per layer type and proper cleanup.
    """

    def __init__(self):
        self.project = QgsProject.instance()
        self._layers = {}  # cache: name -> layer

    # ======================================================
    # GET OR CREATE LAYER
    # ======================================================

    # ======================================================
    # GET OR CREATE LAYER (FIXED - EMBEDDED ONLY)
    # ======================================================

    def get_or_create_vector_layer(
        self,
        name,
        geometry_type,
        crs="EPSG:4326",
        overwrite=False,
        add_to_project=False  # NEW: Default False untuk embedded canvas
    ):
        """
        Get existing layer by name or create new one.

        Parameters
        ----------
        name : str
            Layer name
        geometry_type : str
            "Point", "LineString", or "Polygon"
        crs : str
            EPSG code
        overwrite : bool
            If True, remove existing layer and create new
        add_to_project : bool
            If True, add to QGIS project (appears in layer panel)
            If False, memory layer only for embedded canvas

        Returns
        -------
        QgsVectorLayer or None
        """

        # ======================================================
        # CHECK CACHE
        # ======================================================

        if not overwrite and name in self._layers:
            layer = self._layers[name]
            if layer and layer.isValid():
                return layer

        # ======================================================
        # CHECK PROJECT LAYERS (ONLY IF ADD_TO_PROJECT)
        # ======================================================

        if add_to_project:
            existing_layers = self.project.mapLayersByName(name)

            if existing_layers and not overwrite:
                layer = existing_layers[0]
                self._layers[name] = layer
                return layer

            # ======================================================
            # REMOVE OLD IF OVERWRITE (PROJECT LAYERS)
            # ======================================================

            if overwrite and existing_layers:
                for old_layer in existing_layers:
                    self.project.removeMapLayer(old_layer.id())
                self._layers.pop(name, None)

        # ======================================================
        # CREATE NEW LAYER (MEMORY LAYER - NOT ADDED TO PROJECT)
        # ======================================================

        uri = f"{geometry_type}?crs={crs}"
        layer = QgsVectorLayer(uri, name, "memory")

        if not layer.isValid():
            return None

        # ONLY add to project if explicitly requested
        if add_to_project:
            self.project.addMapLayer(layer)

        # Always cache
        self._layers[name] = layer

        return layer

    # ======================================================
    # GET OR CREATE RASTER LAYER (for basemap)
    # ======================================================

    def get_or_create_raster_layer(
        self,
        name,
        uri,
        provider="wms",
        crs="EPSG:3857",
        overwrite=False
    ):
        """
        Get existing raster layer or create new.

        Parameters
        ----------
        name : str
            Layer name
        uri : str
            Raster URI/URL
        provider : str
            Provider type (wms, gdal, etc)
        crs : str
            EPSG code
        overwrite : bool
            If True, remove existing and create new

        Returns
        -------
        QgsRasterLayer or None
        """

        # ======================================================
        # CHECK CACHE
        # ======================================================

        if not overwrite and name in self._layers:
            layer = self._layers[name]
            if layer and layer.isValid():
                return layer

        # ======================================================
        # CHECK PROJECT LAYERS
        # ======================================================

        existing_layers = self.project.mapLayersByName(name)

        if existing_layers and not overwrite:
            layer = existing_layers[0]
            if layer.isValid():
                self._layers[name] = layer
                return layer

        # ======================================================
        # REMOVE OLD IF OVERWRITE
        # ======================================================

        if overwrite and existing_layers:
            for old_layer in existing_layers:
                self.project.removeMapLayer(old_layer.id())
            self._layers.pop(name, None)

        # ======================================================
        # CREATE NEW LAYER
        # ======================================================

        layer = QgsRasterLayer(uri, name, provider)

        if not layer.isValid():
            return None

        # Set CRS
        layer.setCrs(QgsCoordinateReferenceSystem(crs))

        self.project.addMapLayer(layer)
        self._layers[name] = layer

        return layer


    # ======================================================
    # CLEAR LAYER FEATURES (FIXED - DENGAN NULL CHECK)
    # ======================================================

    def clear_layer(self, name):
        """
        Remove all features from a vector layer.

        Parameters
        ----------
        name : str
            Layer name

        Returns
        -------
        bool
        """

        if name not in self._layers:
            # Try to find in project
            existing = self.project.mapLayersByName(name)
            if not existing:
                print(f"Layer {name} not found")
                return False
            layer = existing[0]
            self._layers[name] = layer
        else:
            layer = self._layers[name]

        # Check if layer exists and is valid
        if layer is None:
            print(f"Layer {name} is None")
            return False
            
        if not isinstance(layer, QgsVectorLayer):
            print(f"Layer {name} is not a vector layer")
            return False
            
        if not layer.isValid():
            print(f"Layer {name} is not valid")
            return False

        layer.startEditing()
        ids = [f.id() for f in layer.getFeatures()]
        if ids:
            layer.deleteFeatures(ids)
        layer.commitChanges()

        return True

    # ======================================================
    # REMOVE LAYER
    # ======================================================

    def remove_layer(self, name):
        """
        Remove layer from project and cache.

        Parameters
        ----------
        name : str
            Layer name

        Returns
        -------
        bool
        """

        if name in self._layers:
            layer = self._layers[name]
            self.project.removeMapLayer(layer.id())
            del self._layers[name]
            return True

        existing = self.project.mapLayersByName(name)
        if existing:
            self.project.removeMapLayer(existing[0].id())
            return True

        return False

    # ======================================================
    # CLEANUP ALL RF LAYERS
    # ======================================================

    def cleanup_rf_layers(self):
        """
        Remove all RF analysis layers from project.
        """

        rf_layer_names = [
            "RF_Antenna",
            "RF_Sector",
            "RF_Footprint",
            "RF_BeamEdges",
            "RF_LOS",
            "RF_CenterLine",
            "RF_Impact",
            "RF_Debug",
            "VerticalAnalysis_Site",
            "VerticalAnalysis_Sector",
            "VerticalAnalysis_LOS",
            "VerticalAnalysis_Impact",
            "VerticalAnalysis_Coverage",
            "VerticalAnalysis_Footprint",
            "VerticalAnalysis_RF_Coverage",
            "VerticalAnalysis_RF_2D_Coverage",
            "VerticalAnalysis_MultiSite_Coverage",
            "VerticalAnalysis_Coverage_Gap",
            "VerticalAnalysis_Coverage_Overlap",
            "VerticalAnalysis_Neighbor_Suggestion",
            "VerticalAnalysis_PCI_Collision",
            "VerticalAnalysis_PCI_Confusion"
        ]

        for name in rf_layer_names:
            self.remove_layer(name)

    # ======================================================
    # GET LAYER
    # ======================================================

    def get_layer(self, name):
        """
        Get layer by name.

        Parameters
        ----------
        name : str

        Returns
        -------
        QgsMapLayer or None
        """

        if name in self._layers:
            return self._layers[name]

        existing = self.project.mapLayersByName(name)
        if existing:
            self._layers[name] = existing[0]
            return existing[0]

        return None