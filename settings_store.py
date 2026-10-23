# -*- coding: utf-8 -*-
"""统一管理用户偏好持久化（DEM 数据源 / 底图 / Tab2 地形源）。

存到 QGIS 全局设置（Windows 注册表 HKCU\\Software\\QGIS\\QGIS3 或 ini），
跨工程、跨 QGIS 会话保留。这样用户「设为默认」后不必每次重开都再切一遍。
"""
from qgis.core import QgsSettings

GROUP = "sector_tiltm_auto"

K_DEM_SOURCE = "dem_source_index"      # 0=本地DEM  1=Open-Meteo 在线
K_BASEMAP    = "basemap_name"          # 底图图层名（精确匹配优先）
K_RING_SRC   = "ring_source_index"     # Tab2 地形源 0=本地 1=在线


def _s():
    return QgsSettings()


def _get(key, default=None):
    try:
        s = _s()
        s.beginGroup(GROUP)
        v = s.value(key, None)
        s.endGroup()
        return v if v is not None else default
    except Exception:  # nosec
        return default


def _set(key, value):
    try:
        s = _s()
        s.beginGroup(GROUP)
        s.setValue(key, value)
        s.endGroup()
        s.sync()
        return True
    except Exception:  # nosec
        return False


# ------------------------------------------------------------------ Tab1 DEM 源
def get_dem_source(default=None):
    v = _get(K_DEM_SOURCE, None)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def set_dem_source(idx):
    return _set(K_DEM_SOURCE, int(idx))


# ------------------------------------------------------------------ Tab1 底图
def get_basemap(default=None):
    v = _get(K_BASEMAP, None)
    return str(v) if v is not None else default


def set_basemap(name):
    return _set(K_BASEMAP, str(name))


# ------------------------------------------------------------------ Tab2 地形源
def get_ring_source(default=None):
    v = _get(K_RING_SRC, None)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def set_ring_source(idx):
    return _set(K_RING_SRC, int(idx))


# ------------------------------------------------------------------ 工具
def clear_all():
    try:
        s = _s()
        s.beginGroup(GROUP)
        s.remove("")
        s.endGroup()
        s.sync()
        return True
    except Exception:  # nosec
        return False


def dump():
    return {
        "dem_source_index": get_dem_source(),
        "basemap_name": get_basemap(),
        "ring_source_index": get_ring_source(),
    }
