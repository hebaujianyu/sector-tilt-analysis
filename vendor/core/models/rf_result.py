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
RF Analysis Result data model.
"""

class RFAnalysisResult:
    """
    Data model for RF Vertical Analysis results.
    """
    
    def __init__(self, 
                 distances=None,
                 elevations=None,
                 main_beam=None,
                 upper_beam=None,
                 lower_beam=None,
                 impact_distance=None,
                 impact_point=None,
                 footprint_start=None,
                 footprint_end=None,
                 **kwargs):
        
        self.distances = distances or []
        self.elevations = elevations or []
        self.main_beam = main_beam
        self.upper_beam = upper_beam
        self.lower_beam = lower_beam
        self.impact_distance = impact_distance
        self.impact_point = impact_point
        self.footprint_start = footprint_start
        self.footprint_end = footprint_end
        
        # Store additional attributes
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def to_dict(self):
        """Convert to dictionary for serialization"""
        return {
            "distances": self.distances,
            "elevations": self.elevations,
            "main_beam": self.main_beam,
            "upper_beam": self.upper_beam,
            "lower_beam": self.lower_beam,
            "impact_distance": self.impact_distance,
            "impact_point": self.impact_point,
            "footprint_start": self.footprint_start,
            "footprint_end": self.footprint_end,
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create instance from dictionary"""
        return cls(**data)