# -*- coding: utf-8 -*-
# ============================================================================
# tilt_core.py — 扇区一键 Tilt 分析 核心逻辑
#
# 扇区一键 Tilt 分析核心逻辑，
# （自动触发分析）：填充完垂直波瓣分析对话框控件后程序化触发分析，
# 实现「一键传参并出结果」。
#
# 设计要点：
#   - 数据源(工参层/覆盖层)全部自动发现，零硬编码 DB/表名/字段名
#   - 中英文 + 模糊字段匹配，适配华为/中兴/爱立信导出
#   - DEM 默认在线(Open-Meteo)
# ============================================================================

import re
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QInputDialog
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeatureRequest,
    QgsExpressionContextUtils
)

# ============================================================================
# 配置区（仅 扇区Tilt分析 固定设置，数据源全部自动发现）
# ============================================================================
CONFIG = {
    "dem_source_index": 1,            # 0=Local DEM, 1=Open-Meteo (Online) —— 默认在线
    "basemap_keyword": "sanwei",      # basemap 模糊匹配关键词
    "basemap_refresh_method": "_refresh_basemap_list",
}

# ============================================================================
# 字段名候选（中英文自动匹配，按优先级排列）
# ============================================================================
FIELD_CANDIDATES = {
    "longitude":   ["longitude", "lon", "lng", "经度", "Longitude", "经  度"],
    "latitude":    ["latitude", "lat", "纬度", "Latitude"],
    "azimuth":     ["azimuth", "方位角", "Azimuth", "方向角", "Az"],
    "mech_tilt":   ["mech_tilt", "mechanical_tilt", "机械下倾", "机械倾角",
                   "MTilt", "downtilt", "下倾角", "机械下倾角"],
    "elec_tilt":   ["elec_tilt", "electrical_tilt", "电子下倾", "电子倾角",
                   "ETilt", "电下倾", "RetTilt"],
    "height":      ["height", "天线挂高", "antenna_height", "挂高",
                   "TowerHeight", "站高", "AntHeight"],
    "v_beamwidth": ["vertical_beamwidth", "v_beamwidth", "垂直波束宽度", "VBW"],
    "h_beamwidth": ["horizontal_beamwidth", "h_beamwidth", "水平波束宽度", "HBW"],
    "cell_name":   ["cellname", "cell_name", "CellName", "小区名"],
}

CELL_ID_CANDIDATES = [
    "UniqueID", "unique_id", "uniqueid", "UNIQUEID",
    "cell_uid", "CellUID",
    "小区号", "小区标识", "小区ID", "cell_id", "cellid",
    "CELL_ID", "CELLID",
]


# ============================================================================
# 1. 解析小区号(UniqueID/gNodeBID-CellID)
# ============================================================================
def parse_cell_id(cell_id_str):
    """
    '3286202-202' / '3286202_202' / '3286202 202'
    → {'gnodeb_id':3286202, 'cell_id':202, 'cell_uid':'3286202_202', ...}

    兼容三段式 ID（站址号-gNodeBID-CellID）：
      '1234-3286202-202' / '1234：3286202-202_示例站-Ⅴ-ABC-1'
    → 取【后两段】为 (gNodeBID, CellID) = (3286202, 202)，cell_uid='3286202_202'
      （gNodeBID 通常 7 位，站址号 4 位；取后两段可同时覆盖两种格式）
    """
    s = str(cell_id_str).strip()
    parts = re.split(r"[-_\s]+", s)
    parts = [p for p in parts if p]
    if len(parts) < 2:
        raise ValueError(
            f"小区号解析失败: '{s}'（需要 gNodeBID-CellID 格式，如 3286202-202）"
        )

    # 三段式及以上：取后两段（gNodeBID-CellID），避免把"站址号"误当成 gNodeBID
    if len(parts) >= 3:
        tail = [p for p in parts if p[-1:].isdigit() or p.isdigit()]
        # 优先取「后两段纯数字」（真实 gNodeBID + CellID）
        numeric = [p for p in tail if p.isdigit()]
        if len(numeric) >= 2:
            gnodeb_id = int(numeric[-2])
            cell_id = int(numeric[-1])
        else:
            gnodeb_id = int(parts[-2])
            cell_id = int(parts[-1])
    else:
        gnodeb_id = int(parts[0])
        cell_id = int(parts[1])

    cell_uid = f"{gnodeb_id}_{cell_id}"
    return {
        "gnodeb_id": gnodeb_id,
        "cell_id": cell_id,
        "cell_uid": cell_uid,
        "like_pattern": f"%{cell_uid}%",
        "raw": s,
    }


# ============================================================================
# 2. 自动发现图层
# ============================================================================

def _get_project_var(name):
    """读取 QGIS 项目变量（Project → Properties → Variables 中设置）"""
    try:
        scope = QgsExpressionContextUtils.projectScope(QgsProject.instance())
        return scope.variable(name)
    except Exception:
        return None


def _match_field(fields, candidates):
    """在字段列表中查找候选字段名，返回第一个匹配的真实字段名"""
    lowered = {f.name().lower(): f.name() for f in fields}
    for cand in candidates:
        key = lowered.get(cand.lower())
        if key:
            return key
    # 模糊匹配：字段名包含候选词
    for cand in candidates:
        cl = cand.lower()
        for f in fields:
            if cl in f.name().lower():
                return f.name()
    return None


def _score_gongcan_layer(layer):
    """评估图层作为工参表的可能性 (score, matched_fields)"""
    if not isinstance(layer, QgsVectorLayer):
        return 0, {}

    fields = list(layer.fields())
    matched = {}
    score = 0

    # 必须有: 经度 + 纬度 (各 25 分)
    lon_f = _match_field(fields, FIELD_CANDIDATES["longitude"])
    lat_f = _match_field(fields, FIELD_CANDIDATES["latitude"])
    if lon_f:
        matched["longitude"] = lon_f
        score += 25
    if lat_f:
        matched["latitude"] = lat_f
        score += 25

    # 应该有: 方位角 (20 分)
    az_f = _match_field(fields, FIELD_CANDIDATES["azimuth"])
    if az_f:
        matched["azimuth"] = az_f
        score += 20

    # 加分项
    for key, weight in [("mech_tilt", 10), ("elec_tilt", 10),
                         ("height", 10), ("v_beamwidth", 5),
                         ("h_beamwidth", 5), ("cell_name", 5)]:
        f = _match_field(fields, FIELD_CANDIDATES[key])
        if f:
            matched[key] = f
            score += weight

    return score, matched


def discover_gongcan_layer(clicked_layer=None):
    """
    自动发现工参图层。
    优先级:
      1. QGIS 项目变量 @gongcan_layer
      2. 点击的图层本身（如果有 lat+lon 字段）
      3. 扫描所有已加载图层，选得分最高的
    """
    # 1. 项目变量覆盖
    var_name = _get_project_var("gongcan_layer")
    if var_name:
        layers = QgsProject.instance().mapLayersByName(var_name)
        if layers:
            layer = layers[0]
            _, matched = _score_gongcan_layer(layer)
            if matched:
                return layer, matched

    # 2. 点击图层本身是否有 RF 参数
    if clicked_layer is not None:
        score, matched = _score_gongcan_layer(clicked_layer)
        if score >= 50:
            return clicked_layer, matched

    # 3. 扫描所有图层
    candidates = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        score, matched = _score_gongcan_layer(layer)
        if score >= 50:
            candidates.append((layer, matched, score))

    if not candidates:
        return None, {}

    candidates.sort(key=lambda x: x[2], reverse=True)

    # 只有一个候选 → 直接用
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1]

    # 最高分远超第二名 → 自动选
    if candidates[0][2] >= candidates[1][2] + 20:
        return candidates[0][0], candidates[0][1]

    # 多个候选 → 让用户选
    names = [f"{lyr.name()} (得分:{sc})" for lyr, _, sc in candidates]
    choice, ok = QInputDialog.getItem(
        None, "选择工参图层",
        "找到多个可能的工参图层，请选择：",
        names, 0, False
    )
    if ok and choice:
        idx = names.index(choice)
        return candidates[idx][0], candidates[idx][1]

    return candidates[0][0], candidates[0][1]


def _find_cell_field(layer, like_pattern):
    """在图层中查找包含 cell_uid 模式的字段（轻量版：只查前 10 个字符串字段，LIMIT 1）"""
    priority_kws = ['cell', 'gnodeb', 'nodeb', 'enb', 'ci', 'id', 'name']
    fields = list(layer.fields())

    def sort_key(field):
        fname = field.name().lower()
        for i, kw in enumerate(priority_kws):
            if kw in fname:
                return i
        return len(priority_kws)

    fields.sort(key=sort_key)

    checked = 0
    for field in fields:
        # 只查前 10 个字段，避免大表卡死
        checked += 1
        if checked > 10:
            break
        try:
            expr = f'"{field.name()}" LIKE \'{like_pattern}\''
            request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
            request.setTimeout(5000)  # 5秒超时
            feat = next(layer.getFeatures(request), None)
            if feat:
                return field.name()
        except Exception:  # nosec
            continue

    return None


# ============================================================================
# 3. 查询与提取
# ============================================================================

def query_gongcan_layer(layer, field_map, cell_uid, like_pattern):
    """在工参图层中查找匹配的小区，返回特征字典"""
    # 0) 若命中层就是工参层本身，直接返回（由调用方处理 feature）
    #    这里优先用 gNodeBID-CellID 组合字段精确匹配（Cnum/UniqueID/唯一标识）
    #    避免 LIKE 通配符 `_` 把同站多个扇区全部命中后 setLimit(1) 取错行。
    cell_field = field_map.get("cell_name")
    # gNodeBID/CellID 复合字段候选（两段式 `3286202-202`）
    composite_candidates = [
        "Cnum", "UniqueID", "unique_id", "uniqueid", "UNIQUEID",
        "唯一标识", "小区标识", "小区ID", "cell_id", "cellid",
        "CELL_ID", "CELLID", "CellID",
    ]
    composite_field = None
    for cand in composite_candidates:
        if cand in [f.name() for f in layer.fields()]:
            composite_field = cand
            break

    # 0.1) 用复合字段精确匹配 cell_uid（'3286202_202' → 归一化比较）
    if composite_field:
        # 精确：cell_uid 下划线形式（'3286202_202'）
        for sep in ("_", "-"):
            alt_uid = cell_uid.replace("_", sep)
            expr = f'"{composite_field}" = \'{alt_uid}\''
            try:
                request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
                feat = next(layer.getFeatures(request), None)
                if feat:
                    return {f.name(): feat[f.name()] for f in layer.fields()}
            except Exception:  # nosec
                continue

    # 优先用 cell_name 字段匹配
    if cell_field:
        # 精确匹配
        expr = f'"{cell_field}" = \'{cell_uid}\''
        request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
        feat = next(layer.getFeatures(request), None)

        if not feat:
            # 模糊匹配兜底（转义 _ 通配符，避免同站误命中）
            escaped = like_pattern.replace("_", r"\_")
            expr = f'"{cell_field}" LIKE \'{escaped}\' ESCAPE \'\\\''
            try:
                request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
                feat = next(layer.getFeatures(request), None)
            except Exception:
                # 某些数据源不支持 ESCAPE，退回原始 LIKE
                expr = f'"{cell_field}" LIKE \'{like_pattern}\''
                request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
                feat = next(layer.getFeatures(request), None)

        if feat:
            return {f.name(): feat[f.name()] for f in layer.fields()}

    # 没有 cell_name 字段 → 扫描所有字符串字段
    for field in layer.fields():
        if field.type() not in (10, QVariant.String):  # 10 = QString
            continue
        try:
            escaped = like_pattern.replace("_", r"\_")
            expr = f'"{field.name()}" LIKE \'{escaped}\' ESCAPE \'\\\''
            request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
            feat = next(layer.getFeatures(request), None)
            if not feat:
                expr = f'"{field.name()}" LIKE \'{like_pattern}\''
                request = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
                feat = next(layer.getFeatures(request), None)
            if feat:
                return {f.name(): feat[f.name()] for f in layer.fields()}
        except Exception:  # nosec
            continue

    return None


def extract_site_values(feature_dict, field_map):
    """从特征字典中提取 扇区Tilt分析 所需字段值"""
    result = {}

    # 优先用 field_map 中的精确匹配
    for target, source_field in field_map.items():
        val = feature_dict.get(source_field)
        if val is not None and val != "":
            result[target] = val

    # 补充：用候选名列表兜底
    lowered = {str(k).lower(): k for k in feature_dict.keys()}
    for target, candidates in FIELD_CANDIDATES.items():
        if target in result:
            continue
        for cand in candidates:
            key = lowered.get(cand.lower())
            if key:
                val = feature_dict[key]
                if val is not None and val != "":
                    result[target] = val
                    break

    return result


# ============================================================================
# 4. 扇区Tilt分析 对话框（基于源码分析）
# ============================================================================

def _ensure_controller(dialog):
    """确保 vertical_dialog 已绑定垂直分析引擎 controller。

    已绑定则跳过（仅刷新 basemap 列表，因为项目图层可能变化）；
    未绑定则查找 DEM 栅格 → 创建 VerticalAnalysisModule → 赋值 controller
    → 刷新 basemap 列表。缺 DEM 时抛 RuntimeError（沿用原硬约束）。
    """
    if getattr(dialog, "controller", None) is not None:
        refresh = getattr(dialog, CONFIG["basemap_refresh_method"], None)
        if callable(refresh):
            try:
                refresh()
                QApplication.processEvents()
            except Exception as e:
                print(f"[扇区Tilt分析] basemap 刷新: {e}")
        return

    dem_layer = _find_dem_layer()
    if dem_layer is None:
        raise RuntimeError(
            "当前项目中没有栅格图层。\n"
            "扇区Tilt分析 需要至少一个栅格图层（即使使用 Open-Meteo 在线 DEM）。\n"
            "请先加载一个 DEM 栅格或任意栅格底图。"
        )

    from .vendor.modules.vertical_analysis.module import VerticalAnalysisModule
    module = VerticalAnalysisModule(dem_layer)
    dialog.controller = module.controller

    QApplication.processEvents()
    refresh = getattr(dialog, CONFIG["basemap_refresh_method"], None)
    if callable(refresh):
        try:
            refresh()
            QApplication.processEvents()
        except Exception as e:
            print(f"[扇区Tilt分析] basemap 刷新: {e}")


def find_or_launch_dialog():
    """查找或启动 扇区Tilt分析 对话框（多标签工具箱模式）。

    优先复用工具箱主界面(MainToolDialog)内的 tilt_dialog 子实例；
    若工具箱未打开，自动创建并打开（DEM 检查仍走 _ensure_controller）。
    """
    from .main_dialog import MainToolDialog, get_or_create_main

    main = MainToolDialog._instance
    opened = False
    if main is None or not isinstance(main, MainToolDialog):
        main = get_or_create_main()
        opened = True

    vd = main.tilt_dialog
    _ensure_controller(vd)          # DEM 检查 + 创建 module + 刷新 basemap
    main.activate_tilt_tab()
    main.raise_()
    main.activateWindow()
    return vd, ("created" if opened else "reused")


def _find_dem_layer():
    """查找 DEM 栅格图层（跳过底图类）"""
    skip_kws = [
        'bing', 'osm', 'openstreetmap', 'google', 'map',
        'satellite', 'imagery', 'basemap', 'sanwei'
    ]
    layers = list(QgsProject.instance().mapLayers().values())

    # 第一轮：非底图栅格
    for lyr in layers:
        if lyr.type() == lyr.RasterLayer:
            name = lyr.name().lower()
            if not any(k in name for k in skip_kws):
                return lyr

    # 第二轮兜底：任意栅格
    for lyr in layers:
        if lyr.type() == lyr.RasterLayer:
            return lyr

    return None


def fill_dialog(dialog, values):
    """精确填充 扇区Tilt分析 控件（控件名来自源码确认）"""
    filled = []

    def _set_le(attr, val):
        w = getattr(dialog, attr, None)
        if w is not None and val is not None and val != "":
            w.setText(str(val))
            filled.append((attr, str(val)))

    def _set_sb(attr, val, clamp_min=None, clamp_max=None):
        w = getattr(dialog, attr, None)
        if w is not None and val is not None and val != "":
            try:
                v = float(val)
            except (ValueError, TypeError):
                return
            if clamp_min is not None:
                v = max(w.minimum(), v)
            if clamp_max is not None:
                v = min(w.maximum(), v)
            w.setValue(v)
            filled.append((attr, v))

    # 基础参数
    _set_le("latitude_input",  values.get("latitude"))
    _set_le("longitude_input", values.get("longitude"))
    _set_sb("azimuth_spin",     values.get("azimuth"), 0, 359.99)

    # RF 参数
    _set_sb("height_spin",      values.get("height"), 0, 200)
    _set_sb("mech_tilt_spin",   values.get("mech_tilt"), -5, 20)
    _set_sb("elec_tilt_spin",   values.get("elec_tilt"), 0, 12)
    # total_tilt_label 由 valueChanged 信号自动更新

    # 波束宽度（工参里通常没有，有就填）
    _set_sb("beamwidth_spin",   values.get("v_beamwidth"), 0, 30)
    _set_sb("h_beamwidth_spin", values.get("h_beamwidth"), 0, 120)

    # 最大分析距离（固定 2000m）
    _set_sb("distance_spin",  2000, 0, 10000)

    # DEM Source（固定 Open-Meteo Online）
    dem_combo = getattr(dialog, "dem_source_combo", None)
    if dem_combo is not None:
        dem_combo.setCurrentIndex(CONFIG["dem_source_index"])
        filled.append(("dem_source_combo", dem_combo.currentText()))

    # Basemap（模糊匹配）
    bm_combo = getattr(dialog, "basemap_combo", None)
    if bm_combo is not None:
        kw = CONFIG["basemap_keyword"].lower()
        var_kw = _get_project_var("basemap_keyword")
        if var_kw:
            kw = var_kw.lower()

        idx = -1
        # 精确匹配优先
        for i in range(bm_combo.count()):
            if bm_combo.itemText(i).lower() == kw:
                idx = i
                break
        # 模糊匹配兜底
        if idx < 0:
            for i in range(bm_combo.count()):
                if kw in bm_combo.itemText(i).lower():
                    idx = i
                    break
        if idx >= 0:
            bm_combo.setCurrentIndex(idx)
            filled.append(("basemap_combo", bm_combo.currentText()))
        else:
            filled.append(("basemap_combo",
                           f"NOT FOUND (kw='{kw}', items={bm_combo.count()})"))

    return filled


# ============================================================================
# 5. 主入口：一键传参并出结果
# ============================================================================

def run_from_feature(feature, layer, auto_run=True):
    """
    点击/选中要素后的主流程：
      解析 UniqueID → 自动发现工参层 → 查小区 → 提取 RF 参数
      → 启动 扇区Tilt分析 对话框 → 填充控件 → (auto_run) 自动执行分析

    auto_run=True：填充完成后程序化触发 扇区Tilt分析 的 Run Analysis，
                  实现「一键传参并出结果」。
    """
    # 5.1 获取小区号（自动检测字段名）
    field_names = [f.name() for f in layer.fields()]
    unique_id = None

    # 精确匹配候选字段名
    for candidate in CELL_ID_CANDIDATES:
        if candidate in field_names:
            v = feature[candidate]
            if v not in (None, "", QVariant()):
                unique_id = v
                break

    # 兜底: 基站ID_小区ID 拼接 (gNodeBID + CellID)
    if unique_id is None:
        gnb_candidates = ['gNodeBID', 'gnodebid', 'gNodeB_ID', 'gNodeB', 'eNodeBID', 'site_id', '基站ID', '站号']
        cell_candidates = ['CellID', 'cellid', 'cell_id', 'Cell_ID', 'sector_id', 'CI', '小区ID', 'Cnum']
        gnb_field = cell_field = None
        for f in layer.fields():
            fn = f.name().lower()
            for c in gnb_candidates:
                if c.lower() == fn:
                    gnb_field = f.name()
                    break
            for c in cell_candidates:
                if c.lower() == fn:
                    cell_field = f.name()
                    break
        if gnb_field and cell_field:
            gnb_v = feature[gnb_field]
            cell_v = feature[cell_field]
            if gnb_v not in (None, "", QVariant()) and cell_v not in (None, "", QVariant()):
                try:
                    # Cnum 常为两段式 gNB-Cell（如 3286202-202），直接用即可
                    cv_str = str(cell_v).strip()
                    if re.match(r"^\d+[-_]\d+$", cv_str):
                        unique_id = cv_str
                    else:
                        unique_id = f"{int(float(str(gnb_v)))}_{int(float(cv_str))}"
                except (ValueError, TypeError):
                    unique_id = f"{str(gnb_v).strip()}_{str(cell_v).strip()}"

    # 兜底：字段名含 unique / cell / uid
    if unique_id is None:
        for f in layer.fields():
            fname = f.name().lower()
            if 'unique' in fname or 'cell' in fname or 'uid' in fname:
                v = feature[f.name()]
                if v not in (None, "", QVariant()):
                    unique_id = v
                    break

    # 最后兜底：第一个非空字符串字段（排除"小区"这类三段式展示字段，
    # 优先 Cnum / UniqueID 两段式 gNB-Cell 格式字段）
    if unique_id is None:
        for f in layer.fields():
            fname = f.name()
            if f.type() not in (10, QVariant.String):
                continue
            v = feature[f.name()]
            if v in (None, "", QVariant()):
                continue
            # 优先取两段式/短值字段（gNB-Cell），避免取到"站址号:gNB-小区_站名"长展示字段
            sv = str(v).strip()
            if fname in ("Cnum", "UniqueID", "unique_id", "uniqueid", "唯一标识"):
                unique_id = sv
                break
            # 含全角冒号/下划线+站名 → 三段式展示字段，跳过（改用组合还原）
            if "：" in sv or ":" in sv or len(sv) > 20:
                continue
            unique_id = sv
            break

    # 若最终取到的是三段式展示值（站址号-gNB-Cell_站名），尝试用 基站ID+Cnum 还原 gNB-Cell
    if unique_id is not None and ("：" in str(unique_id) or ":" in str(unique_id)):
        try:
            gnb_f = cell_f = None
            for f in layer.fields():
                fn = f.name().lower()
                if gnb_f is None and fn in ("基站id", "gnodebid", "gnodeb", "站号"):
                    gnb_f = f.name()
                if cell_f is None and fn in ("cnum", "uniqueid", "unique_id", "小区id", "cellid", "小区标识"):
                    cell_f = f.name()
            if gnb_f and cell_f:
                g = feature[gnb_f]
                c = feature[cell_f]
                if g not in (None, "", QVariant()) and c not in (None, "", QVariant()):
                    unique_id = f"{int(float(str(g)))}_{int(float(str(c)))}"
        except (ValueError, TypeError):
            pass

    if unique_id is None:
        QMessageBox.warning(None, "扇区Tilt分析", "未在要素中找到小区号(UniqueID)字段！")
        return

    # 5.2 解析小区号；解析失败(如字段值是 '2' 这类非 gNB-Cell 格式)时，
    #     不再致命报错，回退为「要素直取」模式（直接用当前要素的经纬度+RF 参数）
    try:
        parsed = parse_cell_id(unique_id)
    except ValueError as e:
        print(f"[扇区Tilt分析] {e} → 回退为要素直取模式(run_from_selection)")
        run_from_selection(feature, layer, auto_run=True)
        return

    print(f"[扇区Tilt分析] 小区号={unique_id} → cell_uid={parsed['cell_uid']}")

    # 5.3 自动发现工参图层
    gongcan_layer, field_map = discover_gongcan_layer(layer)

    if gongcan_layer is None:
        QMessageBox.warning(
            None, "扇区Tilt分析",
            f"未找到工参图层！\n\n"
            f"请在 QGIS 中加载包含经纬度/方位角/倾角等字段的工参表图层。\n"
            f"或通过 项目属性 → 变量 设置 @gongcan_layer"
        )
        return

    print(f"[扇区Tilt分析] 工参图层: {gongcan_layer.name()}")
    print(f"[扇区Tilt分析] 字段映射: {field_map}")

    # 5.4 查询工参数据
    site_dict = query_gongcan_layer(
        gongcan_layer, field_map,
        parsed["cell_uid"], parsed["like_pattern"]
    )

    # 如果点击的图层就是工参图层，直接用当前 feature
    if site_dict is None and layer == gongcan_layer:
        site_dict = {f.name(): feature[f.name()] for f in layer.fields()}

    if site_dict is None:
        QMessageBox.warning(
            None, "扇区Tilt分析",
            f"工参图层 [{gongcan_layer.name()}] 中未找到:\n"
            f"  cellname = '{parsed['cell_uid']}'\n"
            f"  或 LIKE '{parsed['like_pattern']}'"
        )
        return

    # 5.5 提取 RF 参数
    values = extract_site_values(site_dict, field_map)

    # 5.6~5.9 启动对话框 → 填充 → 自动运行
    _apply_and_run(values, values.get("cell_name"), parsed["cell_uid"])


# ============================================================================
# 5b. 公共：启动对话框 → 填充控件 → (自动)运行分析
# ============================================================================

def _apply_and_run(values, cell_name, unique_id=None):
    """
    run_from_feature / run_from_selection 共用的「尾段」：
      启动(或复用) 扇区Tilt分析 对话框 → 填充控件 → (auto_run) 自动执行分析。
    """
    # 启动对话框
    try:
        dialog, status = find_or_launch_dialog()
    except Exception as e:
        QMessageBox.critical(None, "扇区Tilt分析", f"启动垂直分析失败:\n{e}")
        return

    # 在窗口标题栏显示当前小区号 + 小区名称（即时同步，不进分析链路）
    try:
        _status_txt = {"created": "新开", "reused": "复用"}.get(status, str(status))
        dialog.set_cell_info(unique_id or "选中/手动", extra=_status_txt,
                             cell_name=cell_name)
        print(f"[扇区Tilt分析] 标题已更新 → {unique_id}（{_status_txt}） 名称={cell_name}")
    except Exception:
        import traceback
        traceback.print_exc()

    # 填充控件
    filled = fill_dialog(dialog, values)

    # 自动出结果：填充后程序化触发 Run Analysis
    try:
        QApplication.processEvents()   # 让 fill_dialog 的 valueChanged 落定
        dialog.run_analysis()          # 等价手动点击 Run Analysis
    except Exception as e:
        QMessageBox.warning(
            None, "扇区Tilt分析",
            f"参数已自动填充，但自动分析失败，请手动点 Run Analysis：\n{e}"
        )

    # 完成提示
    try:
        from qgis.utils import iface
        iface.messageBar().pushInfo(
            "扇区Tilt分析",
            f"已自动填充并启动分析: {unique_id or cell_name or '选中要素'}（{len(filled)} 字段）"
        )
    except Exception:  # nosec
        pass
    print(f"[扇区Tilt分析] 完成: cell={unique_id}, 已填充 {len(filled)} 个字段")


# ============================================================================
# 5c. 选中小区自动展现：从选中要素直接取 经纬度 + RF 参数
# ============================================================================

def run_from_selection(feature, layer, auto_run=True):
    """
    选中要素后自动展现：不依赖小区号/工参层查找，直接从选中要素取
      经纬度（字段优先，否则几何质心重投影到 WGS84）+ RF 参数（字段匹配），
      启动 扇区Tilt分析 对话框并自动运行。
    """
    if feature is None or not feature.isValid():
        return

    fields = list(layer.fields())

    # 1) 经纬度：优先字段，否则几何质心(重投影到 EPSG:4326)
    lat = lon = None
    lon_f = _match_field(fields, FIELD_CANDIDATES["longitude"])
    lat_f = _match_field(fields, FIELD_CANDIDATES["latitude"])
    if lon_f and lat_f:
        try:
            lon = float(feature[lon_f])
            lat = float(feature[lat_f])
        except (ValueError, TypeError, KeyError):
            lon = lat = None

    if lat is None or lon is None:
        try:
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty():
                centroid = geom.centroid().asPoint()
                src_crs = layer.crs()
                if src_crs is not None and src_crs.authid() != "EPSG:4326":
                    from qgis.core import QgsCoordinateTransform, QgsProject
                    xform = QgsCoordinateTransform(
                        src_crs,
                        QgsProject.instance().crsFromAuthId("EPSG:4326"),
                        QgsProject.instance()
                    )
                    pt = xform.transform(centroid)
                else:
                    pt = centroid
                lon, lat = pt.x(), pt.y()
        except Exception:  # nosec
            pass

    if lat is None or lon is None:
        QMessageBox.warning(
            None, "扇区Tilt分析",
            "选中要素无法获取经纬度（既没有经纬度字段，几何质心计算也失败）。"
        )
        return

    # 2) RF 参数：直接用要素字段做候选名匹配
    feat_dict = {f.name(): feature[f.name()] for f in fields}
    values = extract_site_values(feat_dict, {})
    values["latitude"] = lat
    values["longitude"] = lon

    # 小区名称兜底
    cell_name = values.get("cell_name")
    if not cell_name:
        for key in ("cellname", "小区名", "name", "Name", "CellName"):
            if key in feat_dict and feat_dict[key] not in (None, ""):
                cell_name = str(feat_dict[key])
                break

    _apply_and_run(values, cell_name, cell_name or f"选中({layer.name()})")


def run_from_primary(layer_id, feature_id):
    """兼容旧 Action 入口：按图层 ID + 要素 ID 触发。"""
    from qgis.core import QgsProject
    layer = QgsProject.instance().mapLayer(layer_id)
    if layer is None:
        QMessageBox.warning(None, "扇区Tilt分析", f"未找到图层 (ID={layer_id})")
        return
    try:
        feat = layer.getFeature(int(feature_id))
    except (ValueError, TypeError):
        feat = None
    if feat is None or not feat.isValid():
        QMessageBox.warning(None, "扇区Tilt分析", f"未找到要素 (ID={feature_id})")
        return
    run_from_feature(feat, layer, auto_run=True)


# ============================================================================
# 6. 独立测试（命令行，不依赖 QGIS）
# ============================================================================

if __name__ == "__main__":
    for test in ["3286202-202", "3286202_202", "3286202 202"]:
        try:
            print(f"'{test}' → {parse_cell_id(test)}")
        except ValueError as e:
            print(f"'{test}' → ERROR: {e}")
