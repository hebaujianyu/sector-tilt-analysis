# -*- coding: utf-8 -*-
def classFactory(iface):
    from .plugin import SectorTiltMAuto
    return SectorTiltMAuto(iface)
