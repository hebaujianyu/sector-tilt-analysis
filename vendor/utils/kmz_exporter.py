# -*- coding: utf-8 -*-
"""
TiltMaster - RF Vertical Analysis for QGIS
Full Patched Version - KMZ Export with PNG Legend
"""

import math
import os
import tempfile
import zipfile
import shutil
from xml.etree import ElementTree as ET
from xml.dom import minidom
from qgis.core import QgsPointXY
from PyQt5.QtWidgets import QFileDialog


class KMZExporter:
    def __init__(self, iface):
        self.iface = iface
    
    def get_plugin_path(self):
        """Dapatkan path folder plugin secara dinamis"""
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return plugin_dir
    
    def get_legend_path(self):
        """Dapatkan path legend PNG dari plugin"""
        plugin_dir = self.get_plugin_path()
        legend_path = os.path.join(plugin_dir, "resources", "legend", "legend.png")
        return legend_path
    
    def export_sector(self, site_point, azimuth, h_beamwidth, footprint_start, footprint_end,
                 impact_point=None, upper_intersection_point=None, lower_intersection_point=None,
                 beam_end_point=None, center_line_points=None, beam_edges_points=None,
                 sector_radius=None, filename=None):

        """
        Pure export function (NO UI)
        Returns:
            str  -> filename (success)
            None -> cancelled
        """

        # ======================================================
        # VALIDASI FILENAME (NO UI)
        # ======================================================
        if not filename:
            # Caller harus handle dialog
            print("⚠️ No filename provided, export cancelled")
            return None

        # ======================================================
        # DEFAULT SECTOR RADIUS
        # ======================================================
        if sector_radius is None or sector_radius <= 0:
            sector_radius = 5000
            print(f"📡 Sector radius defaulted to {sector_radius}m")

        try:
            # ======================================================
            # CHECK LEGEND
            # ======================================================
            legend_path = self.get_legend_path()
            use_png_legend = os.path.exists(legend_path)

            if not use_png_legend:
                print(f"⚠️ Legend PNG not found → fallback HTML")

            # ======================================================
            # TEMP DIR
            # ======================================================
            temp_dir = tempfile.mkdtemp()
            kml_path = os.path.join(temp_dir, "doc.kml")

            # ======================================================
            # GENERATE KML
            # ======================================================
            kml_content = self._generate_kml(
                site_point, azimuth, h_beamwidth,
                footprint_start, footprint_end,
                impact_point, upper_intersection_point, lower_intersection_point,
                beam_end_point, center_line_points, beam_edges_points,
                sector_radius,
                use_png_legend=use_png_legend
            )

            # Write file
            with open(kml_path, 'w', encoding='utf-8') as f:
                f.write(kml_content)

            # ======================================================
            # CREATE KMZ
            # ======================================================
            with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as kmz:
                kmz.write(kml_path, "doc.kml")

                if use_png_legend:
                    kmz.write(legend_path, "legend.png")

            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

            print(f"✅ KMZ exported: {filename}")

            return filename  # ← IMPORTANT

        except Exception as e:
            print(f"❌ KMZ export error: {e}")
            return False

    
    def _open_kmz_in_google_earth(self, kmz_path):
        """
        Open KMZ file in Google Earth if installed
        """
        import subprocess
        import os

        possible_paths = [
            r"C:\Program Files\Google\Google Earth Pro\client\googleearth.exe",
            r"C:\Program Files (x86)\Google\Google Earth Pro\client\googleearth.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    subprocess.Popen([path, kmz_path])
                    print("🌍 Opened in Google Earth")
                    return True
                except Exception as e:
                    print(f"⚠️ Failed to open Google Earth: {e}")
                    return False

        print("⚠️ Google Earth not found")
        return False
    
    def _generate_kml(self, site_point, azimuth, h_beamwidth, footprint_start, footprint_end,
                      impact_point, upper_intersection_point, lower_intersection_point,
                      beam_end_point, center_line_points, beam_edges_points, sector_radius,
                      use_png_legend=False):
        
        kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        document = ET.SubElement(kml, "Document")
        
        # Camera LookAt
        look_at = ET.SubElement(document, "LookAt")
        ET.SubElement(look_at, "longitude").text = str(site_point.x())
        ET.SubElement(look_at, "latitude").text = str(site_point.y())
        ET.SubElement(look_at, "range").text = "2500"
        ET.SubElement(look_at, "tilt").text = "45"
        
        self._add_all_styles(document)
        
        # Add legend (PNG or HTML fallback)
        if use_png_legend:
            self._add_legend_overlay_png(document)
        else:
            self._add_legend_overlay_html(document)
        
        # Elements
        self._add_point(document, "Antenna", "#sn_site", site_point)
        
        if sector_radius and sector_radius > 0:
            self._add_sector_polygon(document, site_point, azimuth, h_beamwidth, sector_radius)
        
        self._add_footprint(document, site_point, azimuth, h_beamwidth, footprint_start, footprint_end)
        
        if center_line_points:
            self._add_center_line(document, center_line_points)
        
        if impact_point:
            self._add_point(document, "Impact Point", "#sn_impact", impact_point)
        
        if upper_intersection_point:
            self._add_point(document, "Upper Beam", "#sn_upper", upper_intersection_point)
        
        if lower_intersection_point:
            self._add_point(document, "Lower Beam", "#sn_lower", lower_intersection_point)
        
        if beam_end_point:
            self._add_point(document, "Beam End", "#sn_bend", beam_end_point)
        
        if beam_edges_points:
            self._add_beam_edges(document, beam_edges_points)
        
        # =====================================================
        # SECURE XML PRETTY PRINT (FIX BANDIT ISSUE)
        # =====================================================
        rough_string = ET.tostring(kml, encoding='utf-8')
        
        try:
            # Use defusedxml (secure)
            from defusedxml.minidom import parseString
            reparsed = parseString(rough_string)
            return reparsed.toprettyxml(indent="  ")
        
        except ImportError:
            # Fallback (safe enough because XML is internally generated)
            return rough_string.decode('utf-8')

    def _add_legend_overlay_png(self, document):
        """Legend Overlay menggunakan PNG - Ukuran Asli 100%"""
        so = ET.SubElement(document, "ScreenOverlay")
        ET.SubElement(so, "name").text = "RF Legend"
        ET.SubElement(so, "visibility").text = "1"
        
        # Icon harus didefinisikan di awal untuk kompatibilitas
        icon = ET.SubElement(so, "Icon")
        ET.SubElement(icon, "href").text = "legend.png"
        
        # Overlay XY: Titik jangkar pada GAMBAR (Kiri Atas)
        overlay_xy = ET.SubElement(so, "overlayXY", 
                                   x="0", y="1", 
                                   xunits="fraction", yunits="fraction")
        
        # Screen XY: Titik penempatan pada LAYAR (Kiri Atas)
        screen_xy = ET.SubElement(so, "screenXY", 
                                  x="0.01", y="0.98", 
                                  xunits="fraction", yunits="fraction")
        
        # SIZE: Set x dan y ke 0 untuk menggunakan ukuran asli gambar (100%)
        size = ET.SubElement(so, "size", 
                             x="0", y="0", 
                             xunits="fraction", yunits="fraction")
        
        ET.SubElement(so, "drawOrder").text = "99"

    def _add_legend_overlay_html(self, document):
        """Legend Overlay HTML (fallback jika PNG tidak tersedia)"""
        so = ET.SubElement(document, "ScreenOverlay")
        ET.SubElement(so, "name").text = "RF Legend"
        ET.SubElement(so, "visibility").text = "1"
        
        overlay_xy = ET.SubElement(so, "overlayXY")
        ET.SubElement(overlay_xy, "x").text = "0"
        ET.SubElement(overlay_xy, "y").text = "0"
        ET.SubElement(overlay_xy, "xunits").text = "fraction"
        ET.SubElement(overlay_xy, "yunits").text = "fraction"
        
        screen_xy = ET.SubElement(so, "screenXY")
        ET.SubElement(screen_xy, "x").text = "0.02"
        ET.SubElement(screen_xy, "y").text = "0.05"
        ET.SubElement(screen_xy, "xunits").text = "fraction"
        ET.SubElement(screen_xy, "yunits").text = "fraction"
        
        size = ET.SubElement(so, "size")
        ET.SubElement(size, "x").text = "0"
        ET.SubElement(size, "y").text = "0"
        ET.SubElement(size, "xunits").text = "fraction"
        ET.SubElement(size, "yunits").text = "fraction"

        desc = ET.SubElement(so, "description")
        desc.text = """<![CDATA[
        <table style="background-color: white; padding: 10px; border: 2px solid #333333; font-family: Arial, sans-serif; min-width: 150px;">
            <tr><td colspan="2" style="text-align: center; border-bottom: 1px solid #ccc;"><b>RF LEGEND</b></td></tr>
            <tr><td style="color: black; font-size: 18px;">▲</td><td>Antenna</td></tr>
            <tr><td style="color: #00A000; font-size: 20px;">●</td><td>Impact (Main Beam)</td></tr>
            <tr><td style="color: #00FF00; font-size: 20px;">●</td><td>Beam End</td></tr>
            <tr><td style="color: #0000E1; font-size: 20px;">●</td><td>Upper Intersection</td></tr>
            <tr><td style="color: #FF0000; font-size: 20px;">●</td><td>Lower Intersection</td></tr>
            <tr><td style="background-color: #06FAFA; border: 1px solid black; width: 15px;"> </td><td>Coverage Footprint</td></tr>
            <tr><td style="background-color: #FFFF00; border: 1px solid black; width: 15px;"> </td><td>Sector</td></tr>
            <tr><td style="color: red; font-weight: bold;">---</td><td>Center Line</td></tr>
        </table>
        ]]>"""

    def _add_all_styles(self, document):
        TRIANGLE = "http://maps.google.com/mapfiles/kml/shapes/triangle.png"
        CIRCLE = "http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png"

        # (ID, IconColor AABBGGRR, IconURL, Scale)
        styles = [
            ("sn_site", "ff000000", TRIANGLE, "1.3"),
            ("sn_impact", "ff00a000", CIRCLE, "1.1"),
            ("sn_bend", "ff00ff00", CIRCLE, "0.9"),
            ("sn_upper", "ffe10000", CIRCLE, "0.9"),
            ("sn_lower", "ff0000ff", CIRCLE, "0.9"),
        ]

        for s_id, s_col, s_href, s_scale in styles:
            style = ET.SubElement(document, "Style", id=s_id)
            # Icon Style
            istyle = ET.SubElement(style, "IconStyle")
            ET.SubElement(istyle, "color").text = s_col
            ET.SubElement(istyle, "scale").text = s_scale
            ET.SubElement(ET.SubElement(istyle, "Icon"), "href").text = s_href
            
            # Label Style: Scale 0 menyembunyikan teks di peta, tapi tetap muncul di list kiri
            lstyle = ET.SubElement(style, "LabelStyle")
            ET.SubElement(lstyle, "scale").text = "0"

        # Styles untuk Poligon dan Garis
        s_foot = ET.SubElement(document, "Style", id="footprintStyle")
        ET.SubElement(ET.SubElement(s_foot, "PolyStyle"), "color").text = "88fafa06"
        ET.SubElement(ET.SubElement(s_foot, "LabelStyle"), "scale").text = "0"
        
        s_sector = ET.SubElement(document, "Style", id="sectorStyle")
        ET.SubElement(ET.SubElement(s_sector, "PolyStyle"), "color").text = "6600ffff"
        ET.SubElement(ET.SubElement(s_sector, "LabelStyle"), "scale").text = "0"
        
        s_line = ET.SubElement(document, "Style", id="centerLineStyle")
        ls_line = ET.SubElement(s_line, "LineStyle")
        ET.SubElement(ls_line, "color").text = "ff0000ff"
        ET.SubElement(ls_line, "width").text = "2.5"
        ET.SubElement(ET.SubElement(s_line, "LabelStyle"), "scale").text = "0"
        
        s_edge = ET.SubElement(document, "Style", id="beamEdgeStyle")
        ls_edge = ET.SubElement(s_edge, "LineStyle")
        ET.SubElement(ls_edge, "color").text = "ff00ffff"
        ET.SubElement(ls_edge, "width").text = "1.5"
        ET.SubElement(ET.SubElement(s_edge, "LabelStyle"), "scale").text = "0"

    def _add_point(self, parent, name, style, pt):
        pm = ET.SubElement(parent, "Placemark")
        ET.SubElement(pm, "name").text = name
        ET.SubElement(pm, "styleUrl").text = style
        ET.SubElement(ET.SubElement(pm, "Point"), "coordinates").text = f"{pt.x()},{pt.y()},0"

    def _add_footprint(self, doc, center, azimuth, bw, start, end):
        pts = self._generate_sector_polygon(center, azimuth, bw, start, end)
        pm = ET.SubElement(doc, "Placemark")
        ET.SubElement(pm, "name").text = "Coverage Footprint"
        ET.SubElement(pm, "styleUrl").text = "#footprintStyle"
        poly = ET.SubElement(pm, "Polygon")
        ring = ET.SubElement(ET.SubElement(poly, "outerBoundaryIs"), "LinearRing")
        ET.SubElement(ring, "coordinates").text = " ".join([f"{p.x()},{p.y()},0" for p in pts])

    def _add_sector_polygon(self, doc, center, azimuth, bw, rad):
        pts = self._generate_sector_polygon(center, azimuth, bw, 0, rad)
        pm = ET.SubElement(doc, "Placemark")
        ET.SubElement(pm, "name").text = "Sector"
        ET.SubElement(pm, "styleUrl").text = "#sectorStyle"
        poly = ET.SubElement(pm, "Polygon")
        ring = ET.SubElement(ET.SubElement(poly, "outerBoundaryIs"), "LinearRing")
        ET.SubElement(ring, "coordinates").text = " ".join([f"{p.x()},{p.y()},0" for p in pts])

    def _add_center_line(self, doc, points):
        """Add center line as a dashed line by segmenting it"""
        if not points or len(points) < 2:
            return

        # Folder untuk mengelompokkan segmen garis agar tidak berantakan di list
        folder = ET.SubElement(doc, "Folder")
        ET.SubElement(folder, "name").text = "Center Line (Dashed)"
        
        # Parameter dash (dalam meter atau proporsi)
        # Kita hitung total titik dan bagi menjadi segmen
        all_segments = []
        
        # Interpolasi sederhana untuk membuat efek dash
        # Kita akan menggambar garis setiap 50 meter (misalnya)
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            
            # Buat segmen-segmen kecil antara dua titik
            # Di sini kita bagi garis menjadi potongan 20 meteran
            dist = math.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
            num_steps = 40 # Sesuaikan jumlah potongan untuk kerapatan dash
            
            for j in range(num_steps):
                if j % 2 == 0: # Hanya gambar segmen genap (selang-seling)
                    curr_p1_x = p1.x() + (p2.x() - p1.x()) * (j / num_steps)
                    curr_p1_y = p1.y() + (p2.y() - p1.y()) * (j / num_steps)
                    
                    # Titik akhir segmen (Ubah 0.5 menjadi 0.9 agar garis sedikit lebih panjang dari celahnya)
                    dash_length = 0.9 
                    curr_p2_x = p1.x() + (p2.x() - p1.x()) * ((j + dash_length) / num_steps)
                    curr_p2_y = p1.y() + (p2.y() - p1.y()) * ((j + dash_length) / num_steps)
                    
                    pm = ET.SubElement(folder, "Placemark")
                    ET.SubElement(pm, "name").text = "Center Line Segment"
                    ET.SubElement(pm, "styleUrl").text = "#centerLineStyle"
                    # Sembunyikan nama segmen di peta (agar tidak penuh teks)
                    ls_style = ET.SubElement(pm, "Style")
                    ET.SubElement(ET.SubElement(ls_style, "LabelStyle"), "scale").text = "0"
                    
                    ls = ET.SubElement(pm, "LineString")
                    ET.SubElement(ls, "coordinates").text = f"{curr_p1_x},{curr_p1_y},0 {curr_p2_x},{curr_p2_y},0"
    
    def _add_beam_edges(self, doc, edges):
        """Add beam edges as lines"""
        for i, edge in enumerate(edges):
            pm = ET.SubElement(doc, "Placemark")
            ET.SubElement(pm, "name").text = f"Beam Edge {i+1}"
            ET.SubElement(pm, "styleUrl").text = "#beamEdgeStyle"
            ET.SubElement(ET.SubElement(pm, "LineString"), "coordinates").text = " ".join([f"{p.x()},{p.y()},0" for p in edge])

    def _generate_sector_polygon(self, center, azimuth, bw, d1, d2, steps=30):
        R = 6378137.0
        lat1, lon1 = math.radians(center.y()), math.radians(center.x())
        pts = []
        start_angle = azimuth - bw/2
        end_angle = azimuth + bw/2
        
        # Outer arc
        for i in range(steps + 1):
            ang = math.radians(start_angle + (bw * i / steps))
            lat2 = math.asin(math.sin(lat1)*math.cos(d2/R) + math.cos(lat1)*math.sin(d2/R)*math.cos(ang))
            lon2 = lon1 + math.atan2(math.sin(ang)*math.sin(d2/R)*math.cos(lat1), math.cos(d2/R)-math.sin(lat1)*math.sin(lat2))
            pts.append(QgsPointXY(math.degrees(lon2), math.degrees(lat2)))
        
        # Inner arc (reverse direction)
        for i in range(steps, -1, -1):
            ang = math.radians(start_angle + (bw * i / steps))
            lat2 = math.asin(math.sin(lat1)*math.cos(d1/R) + math.cos(lat1)*math.sin(d1/R)*math.cos(ang))
            lon2 = lon1 + math.atan2(math.sin(ang)*math.sin(d1/R)*math.cos(lat1), math.cos(d1/R)-math.sin(lat1)*math.sin(lat2))
            pts.append(QgsPointXY(math.degrees(lon2), math.degrees(lat2)))
        
        return pts