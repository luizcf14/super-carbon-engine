"""
Verra Mapa Interativo — Otimizado e Fluido
============================================
Gera o mapa Folium ultraleve com sanitização rigorosa de strings
para evitar qualquer erro de sintaxe JS no navegador.
"""

import json
import logging
import warnings
from pathlib import Path
from datetime import datetime

import pandas as pd
import geopandas as gpd
import folium
from folium import plugins

warnings.filterwarnings("ignore")

# ─── Configuração ─────────────────────────────────────────────────────────────
PROJETOS_FILE = Path("verra_projetos_geo.gpkg")
ALERTAS_FILE  = Path("mapbiomas_alertas.gpkg")
OUTPUT_FILE   = Path("mapa_verra_brasil.html")

BRAZIL_CENTER = [-14.235, -51.925]
INITIAL_ZOOM  = 4

STATUS_COLORS = {
    "Registered":                                               "#22c55e",
    "Late to verify":                                          "#f59e0b",
    "Under validation":                                        "#3b82f6",
    "Under development":                                       "#8b5cf6",
    "Withdrawn":                                               "#6b7280",
    "Verification approval requested":                         "#06b6d4",
    "Registration and verification approval requested":        "#0ea5e9",
    "Registration requested":                                  "#60a5fa",
    "On Hold - see notification letter":                       "#ef4444",
    "Units Transferred from Approved GHG Program":             "#a855f7",
    "Rejected by Administrator":                               "#dc2626",
    "Inactive":                                                "#9ca3af",
}
DEFAULT_COLOR = "#94a3b8"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def clean_str(s) -> str:
    """Remove crases (backticks), barras invertidas e caracteres que quebram JavaScript."""
    if s is None or pd.isna(s):
        return ""
    return str(s).replace("`", "'").replace("\\", "/").replace('"', "'").strip()


def fmt_num(val, suffix="", decimals=0) -> str:
    try:
        v = float(val)
        if decimals == 0:
            return f"{int(v):,}".replace(",", ".") + suffix
        return f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suffix
    except (TypeError, ValueError):
        return "—"


def build_legend_html() -> str:
    items = [
        (STATUS_COLORS.get(s, DEFAULT_COLOR), s)
        for s in ["Registered", "Late to verify", "Under validation",
                  "Under development", "Withdrawn", "On Hold - see notification letter"]
    ]
    items_html = "".join(
        f'<div style="display:flex;align-items:center;margin:3px 0;">'
        f'<div style="width:13px;height:13px;background:{c};border-radius:3px;margin-right:7px;flex-shrink:0;"></div>'
        f'<span style="font-size:11px;color:#cbd5e1;">{s}</span></div>'
        for c, s in items
    )
    return f"""
    <div style="position:fixed;bottom:25px;left:15px;z-index:1000;background:rgba(15,23,42,0.92);
                padding:12px 14px;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.5);
                border:1px solid rgba(255,255,255,0.1);backdrop-filter:blur(8px);
                font-family:'Segoe UI',Arial,sans-serif;min-width:230px;">
      <div style="font-weight:700;font-size:12px;margin-bottom:8px;color:#f8fafc;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:4px;">
        🌿 Status dos Projetos Verra
      </div>
      {items_html}
      <div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);">
        <div style="display:flex;align-items:center;margin:3px 0;">
          <div style="width:13px;height:13px;background:#f97316;border-radius:3px;margin-right:7px;flex-shrink:0;"></div>
          <span style="font-size:11px;font-weight:600;color:#fb923c;">⚠️ Com alertas MapBiomas (< 1.000 ha)</span>
        </div>
        <div style="display:flex;align-items:center;margin:3px 0;">
          <div style="width:13px;height:13px;background:#dc2626;border-radius:3px;margin-right:7px;flex-shrink:0;"></div>
          <span style="font-size:11px;font-weight:700;color:#f87171;">🚨 Alta pressão de alertas (> 1.000 ha)</span>
        </div>
      </div>
    </div>"""


def main():
    log.info("=" * 60)
    log.info("Verra Mapa Interativo — Otimizado e Fluido")
    log.info("=" * 60)

    if not PROJETOS_FILE.exists():
        log.error(f"Projetos não encontrados: {PROJETOS_FILE}")
        return

    # ── 1. Carregar e preparar dados (Apenas 'Registered') ───────────────────
    gdf = gpd.read_file(PROJETOS_FILE, layer="projetos")
    gdf = gdf.to_crs("EPSG:4326")

    # Filtrar EXCLUSIVAMENTE projetos no estágio 'Registered'
    gdf = gdf[gdf["Status"] == "Registered"].copy()
    log.info(f"Projetos 'Registered' no Brasil: {len(gdf)} projetos")

    gdf_alertas = None
    if ALERTAS_FILE.exists():
        gdf_alertas = gpd.read_file(ALERTAS_FILE, layer="alertas")
        gdf_alertas = gdf_alertas.to_crs("EPSG:4326")

    # Separar projetos com geometria e simplificar para render web rápida
    has_geom = gdf.geometry.notna() & ~gdf.geometry.is_empty
    gdf_poly = gdf[has_geom].copy()
    log.info(f"Projetos 'Registered' com polígono vetorial: {len(gdf_poly)}")

    # Simplificação de tolerância (~100m)
    log.info(f"Simplificando geometrias de {len(gdf_poly)} projetos Registered...")
    gdf_poly["geometry"] = gdf_poly["geometry"].simplify(0.002, preserve_topology=True)

    # Preparar e sanitizar colunas textuais para exibição (sem crases/backticks)
    gdf_poly["id_str"] = gdf_poly["ID Verra"].apply(clean_str)
    gdf_poly["nome_curto"] = gdf_poly["Nome do Projeto"].apply(lambda x: clean_str(x)[:45])
    gdf_poly["status_str"] = gdf_poly["Status"].apply(clean_str)
    gdf_poly["proponente_str"] = gdf_poly["Proponente"].apply(lambda x: clean_str(x)[:35])
    gdf_poly["metodologia_str"] = gdf_poly["Metodologia(s)"].apply(clean_str)
    gdf_poly["reducao_str"] = gdf_poly["Redução Anual Estimada (tCO2e)"].apply(lambda x: fmt_num(x, " tCO2e/ano"))
    gdf_poly["area_km2_str"] = gdf_poly["area_km2"].apply(lambda x: fmt_num(x, " km²", decimals=1))
    gdf_poly["alertas_info"] = gdf_poly.apply(
        lambda r: f"🚨 {int(r['alertas_num'])} alertas ({fmt_num(r['alertas_area_ha'], decimals=1)} ha)" if r.get("tem_alerta") else "✅ Sem alertas",
        axis=1
    )

    # ── 2. Inicializar Mapa Folium ────────────────────────────────────────────
    m = folium.Map(
        location=BRAZIL_CENTER,
        zoom_start=INITIAL_ZOOM,
        tiles="CartoDB dark_matter",
        prefer_canvas=True,
    )

    # Adicionar tiles alternativos
    folium.TileLayer(
        tiles="CartoDB positron",
        name="☀️ Mapa Claro (CartoDB)",
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="🛰️ Imagem de Satélite (Esri)",
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="🗺️ OpenStreetMap",
        control=True,
    ).add_to(m)

    # ── 3. Estilo e GeoJSON dos Projetos ──────────────────────────────────────
    def style_function(feature):
        props = feature["properties"]
        tem_alerta = props.get("tem_alerta", False)
        area_ha = float(props.get("alertas_area_ha") or 0)
        status = props.get("status_str", "")

        if tem_alerta:
            fill_color = "#dc2626" if area_ha > 1000 else "#f97316"
            line_color = "#ef4444" if area_ha > 1000 else "#ea580c"
            fill_opacity = 0.50
            weight = 2.5
        else:
            fill_color = STATUS_COLORS.get(status, DEFAULT_COLOR)
            line_color = fill_color
            fill_opacity = 0.35
            weight = 1.6

        return {
            "fillColor": fill_color,
            "color": line_color,
            "weight": weight,
            "fillOpacity": fill_opacity,
            "opacity": 0.9,
        }

    # Criar camada única e eficiente de GeoJSON com tooltip e popup
    fields_popup = ["id_str", "nome_curto", "status_str", "proponente_str", "metodologia_str", "reducao_str", "area_km2_str", "alertas_info"]
    aliases_popup = ["ID Verra:", "Projeto:", "Status:", "Proponente:", "Metodologia:", "Redução Anual:", "Área Projeto:", "MapBiomas:"]

    fg_projetos = folium.FeatureGroup(name="🌿 Projetos Verra Brasil (Polígonos)", show=True)

    geojson_layer = folium.GeoJson(
        gdf_poly,
        name="Polígonos dos Projetos",
        style_function=style_function,
        highlight_function=lambda x: {"weight": 4, "fillOpacity": 0.75, "color": "#38bdf8"},
        tooltip=folium.GeoJsonTooltip(
            fields=["id_str", "nome_curto", "status_str", "alertas_info"],
            aliases=["VCS ID:", "Nome:", "Status:", "Alertas:"],
            style="background:rgba(15,23,42,0.9);color:white;padding:8px;border-radius:6px;border:1px solid rgba(255,255,255,0.2);font-family:sans-serif;font-size:11px;"
        ),
        popup=folium.GeoJsonPopup(
            fields=fields_popup,
            aliases=aliases_popup,
            style="font-family:sans-serif;font-size:12px;min-width:250px;"
        )
    )
    geojson_layer.add_to(fg_projetos)
    fg_projetos.add_to(m)

    # ── 4. Camada Heatmap de Alertas ──────────────────────────────────────────
    if gdf_alertas is not None and not gdf_alertas.empty:
        fg_heat = folium.FeatureGroup(name="🔥 Alertas MapBiomas (Heatmap)", show=True)
        heat_data = []
        for _, row in gdf_alertas.iterrows():
            geom = row.get("geometry")
            if geom is None:
                continue
            try:
                c = geom.centroid
                area = float(row.get("area_ha", 1) or 1)
                weight = min(1.0, area / 1000)
                heat_data.append([c.y, c.x, weight])
            except Exception:
                pass

        if heat_data:
            plugins.HeatMap(
                heat_data,
                name="Heatmap",
                min_opacity=0.35,
                max_zoom=18,
                radius=14,
                blur=16,
                gradient={0.2: "#fef08a", 0.5: "#f97316", 0.8: "#dc2626", 1.0: "#7f1d1d"},
            ).add_to(fg_heat)
            fg_heat.add_to(m)

    # ── 5. Marcadores pontuais para projetos sem polígono ─────────────────────
    gdf_nogeom = gdf[~has_geom].copy()
    if not gdf_nogeom.empty:
        fg_nogeom = folium.FeatureGroup(name="⚪ Projetos sem geometria (Ponto)", show=False)
        for _, row in gdf_nogeom.iterrows():
            lat = row.get("lat_centroid") or BRAZIL_CENTER[0]
            lon = row.get("lon_centroid") or BRAZIL_CENTER[1]
            try:
                lat, lon = float(lat), float(lon)
            except Exception:
                lat, lon = BRAZIL_CENTER
            
            status = clean_str(row.get("Status", ""))
            nome = clean_str(row.get("Nome do Projeto", ""))[:45]
            proj_id = clean_str(row.get("ID Verra", ""))

            folium.CircleMarker(
                location=[lat, lon],
                radius=5,
                color=STATUS_COLORS.get(status, DEFAULT_COLOR),
                fill=True,
                fill_opacity=0.7,
                tooltip=f"⚪ [VCS {proj_id}] {nome} (Sem polígono)",
                popup=f"<b>[{proj_id}] {nome}</b><br>Status: {status}<br><i>(Geometria vetorial não disponível)</i>"
            ).add_to(fg_nogeom)
        fg_nogeom.add_to(m)

    # ── 6. Controles e Elementos de Interface ─────────────────────────────────
    plugins.Fullscreen(position="topright").add_to(m)
    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # Legenda
    m.get_root().html.add_child(folium.Element(build_legend_html()))

    # Banner Flutuante de Indicadores
    com_alerta_cnt = gdf_poly["tem_alerta"].sum() if "tem_alerta" in gdf_poly.columns else 0
    total_alt_ha = gdf_poly["alertas_area_ha"].sum() if "alertas_area_ha" in gdf_poly.columns else 0

    title_html = f"""
    <div style="position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:1000;
                background:rgba(15,23,42,0.94);color:white;padding:8px 24px;border-radius:10px;
                box-shadow:0 4px 20px rgba(0,0,0,0.5);border:1px solid rgba(255,255,255,0.12);
                backdrop-filter:blur(8px);font-family:'Segoe UI',Arial,sans-serif;text-align:center;pointer-events:none;">
      <div style="font-weight:800;font-size:13px;letter-spacing:0.02em;">
        🌿 PROJETOS VCS BRASIL × MAPBIOMAS ALERTA
      </div>
      <div style="font-size:11px;color:#94a3b8;margin-top:2px;">
        <b>{len(gdf_poly)}</b> projetos com polígono · <span style="color:#fb923c;font-weight:700;">{com_alerta_cnt} com alertas</span> · 
        <span style="color:#f87171;font-weight:700;">{total_alt_ha:,.0f} ha sob alerta</span>
      </div>
    </div>"""
    m.get_root().html.add_child(folium.Element(title_html))

    # ── 7. Salvar ──────────────────────────────────────────────────────────────
    m.save(str(OUTPUT_FILE))
    file_size_kb = OUTPUT_FILE.stat().st_size / 1024
    log.info(f"[OK] Mapa otimizado salvo em: {OUTPUT_FILE} ({file_size_kb:,.1f} KB)")


if __name__ == "__main__":
    main()
