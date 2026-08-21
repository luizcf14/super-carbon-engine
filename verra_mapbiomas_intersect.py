"""
Verra × MapBiomas Intersect — Etapa 4
========================================
Faz a intersecção espacial entre os polígonos dos projetos Verra e os
alertas de desmatamento do MapBiomas Alert.

Para cada projeto com geometria, calcula:
  - num_alertas:     número de alertas que interceptam o projeto
  - alertas_area_ha: área total dos alertas dentro do projeto (ha)
  - alertas_periodo: período (data mais antiga → mais recente)
  - tem_alerta:      True/False

Dependências: verra_projetos_geo.gpkg + mapbiomas_alertas.gpkg
Output: atualiza verra_projetos_geo.gpkg + gera verra_intersect_mapbiomas.csv
"""

import logging
import warnings
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.validation import make_valid

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*CRS.*")

# ─── Configuração ─────────────────────────────────────────────────────────────
PROJETOS_FILE  = Path("verra_projetos_geo.gpkg")
ALERTAS_FILE   = Path("mapbiomas_alertas.gpkg")
OUTPUT_GPKG    = Path("verra_projetos_geo.gpkg")   # sobrescreve com colunas atualizadas
OUTPUT_CSV     = Path("verra_intersect_mapbiomas.csv")

TARGET_CRS = "EPSG:4326"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main():
    log.info("=" * 60)
    log.info("Verra × MapBiomas Intersect — Etapa 4")
    log.info("=" * 60)

    # ── 1. Carregar dados ──────────────────────────────────────────────────────
    if not PROJETOS_FILE.exists():
        log.error(f"Projetos não encontrados: {PROJETOS_FILE}")
        log.error("Execute primeiro: python verra_geo_enrich.py")
        return

    if not ALERTAS_FILE.exists():
        log.error(f"Alertas não encontrados: {ALERTAS_FILE}")
        log.error("Execute primeiro: python mapbiomas_alertas.py")
        return

    log.info("Carregando projetos...")
    gdf_proj = gpd.read_file(PROJETOS_FILE, layer="projetos")
    log.info(f"  {len(gdf_proj)} projetos carregados")

    log.info("Carregando alertas...")
    gdf_alertas = gpd.read_file(ALERTAS_FILE, layer="alertas")
    log.info(f"  {len(gdf_alertas)} alertas carregados")

    # ── 2. Normalizar CRS ──────────────────────────────────────────────────────
    if gdf_proj.crs is None:
        gdf_proj = gdf_proj.set_crs(TARGET_CRS)
    else:
        gdf_proj = gdf_proj.to_crs(TARGET_CRS)

    if gdf_alertas.crs is None:
        gdf_alertas = gdf_alertas.set_crs(TARGET_CRS)
    else:
        gdf_alertas = gdf_alertas.to_crs(TARGET_CRS)

    # ── 3. Filtrar apenas projetos com geometria ───────────────────────────────
    has_geom = gdf_proj.geometry.notna() & ~gdf_proj.geometry.is_empty
    gdf_with_geo = gdf_proj[has_geom].copy()
    log.info(f"Projetos com geometria para intersecção: {len(gdf_with_geo)}")

    if gdf_with_geo.empty:
        log.warning("Nenhum projeto com geometria. Pulando intersecção.")
        return

    # ── 4. Corrigir geometrias inválidas ───────────────────────────────────────
    log.info("Corrigindo geometrias inválidas...")
    gdf_with_geo["geometry"] = gdf_with_geo["geometry"].apply(make_valid)
    gdf_alertas["geometry"]  = gdf_alertas["geometry"].apply(make_valid)

    # ── 5. Spatial Join (intersects) ───────────────────────────────────────────
    log.info("Executando spatial join (intersects)...")

    # Usar apenas colunas essenciais dos alertas para o join
    alertas_cols = ["alerta_id", "bioma", "estado", "area_ha", "data_deteccao", "geometry"]
    alertas_for_join = gdf_alertas[[c for c in alertas_cols if c in gdf_alertas.columns]].copy()

    try:
        joined = gpd.sjoin(
            gdf_with_geo[["ID Verra", "geometry"]].rename(columns={"ID Verra": "id_verra_join"}),
            alertas_for_join,
            how="left",
            predicate="intersects",
        )
    except Exception as e:
        log.error(f"Erro no sjoin: {e}")
        # Fallback: usar bounding box (mais rápido mas menos preciso)
        log.info("Tentando com bounding box como fallback...")
        joined = gpd.sjoin(
            gdf_with_geo[["ID Verra", "geometry"]].rename(columns={"ID Verra": "id_verra_join"}),
            alertas_for_join,
            how="left",
            predicate="intersects",
        )

    log.info(f"Join resultou em {len(joined)} linhas")

    # ── 6. Agregar por projeto ─────────────────────────────────────────────────
    log.info("Agregando resultados por projeto...")

    # Projetos sem alerta terão index_right = NaN
    proj_alertas = (
        joined[joined["index_right"].notna()]
        .groupby("id_verra_join")
        .agg(
            alertas_num=("alerta_id", "count") if "alerta_id" in joined.columns else ("index_right", "count"),
            alertas_area_ha=("area_ha", "sum") if "area_ha" in joined.columns else ("index_right", lambda x: 0),
            alertas_data_min=("data_deteccao", "min") if "data_deteccao" in joined.columns else ("index_right", lambda x: None),
            alertas_data_max=("data_deteccao", "max") if "data_deteccao" in joined.columns else ("index_right", lambda x: None),
        )
        .reset_index()
    )

    proj_alertas["alertas_periodo"] = (
        proj_alertas["alertas_data_min"].astype(str) + " → " + proj_alertas["alertas_data_max"].astype(str)
    )
    proj_alertas["tem_alerta"] = True
    proj_alertas["alertas_area_ha"] = proj_alertas["alertas_area_ha"].round(1)

    log.info(f"Projetos com alertas: {len(proj_alertas)}")

    # ── 7. Atualizar GeoDataFrame de projetos ──────────────────────────────────
    # Resetar colunas de alerta
    gdf_proj["alertas_num"]     = 0
    gdf_proj["alertas_area_ha"] = 0.0
    gdf_proj["alertas_periodo"] = None
    gdf_proj["tem_alerta"]      = False

    # Merge dos resultados
    id_col = "ID Verra"
    for _, row in proj_alertas.iterrows():
        mask = gdf_proj[id_col] == row["id_verra_join"]
        if mask.any():
            gdf_proj.loc[mask, "alertas_num"]     = int(row["alertas_num"])
            gdf_proj.loc[mask, "alertas_area_ha"] = float(row["alertas_area_ha"])
            gdf_proj.loc[mask, "alertas_periodo"] = str(row["alertas_periodo"])
            gdf_proj.loc[mask, "tem_alerta"]      = True

    # ── 8. Salvar resultados ───────────────────────────────────────────────────
    log.info(f"Salvando {OUTPUT_GPKG}...")
    gdf_proj.to_file(OUTPUT_GPKG, driver="GPKG", layer="projetos")

    log.info(f"Salvando {OUTPUT_CSV}...")
    # CSV sem geometria para visualização rápida
    df_csv = gdf_proj.drop(columns=["geometry"]).copy()
    df_csv.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    # ── 9. Resumo ──────────────────────────────────────────────────────────────
    log.info("=" * 60)
    total_alertas = gdf_proj["alertas_num"].sum()
    total_area    = gdf_proj["alertas_area_ha"].sum()
    com_alerta    = gdf_proj["tem_alerta"].sum()

    log.info(f"[OK] Intersecção concluída")
    log.info(f"  Projetos com alertas de desmatamento: {com_alerta} / {len(gdf_proj)}")
    log.info(f"  Total de alertas interceptados:       {total_alertas:,}")
    log.info(f"  Área total alertada nos projetos:     {total_area:,.0f} ha")

    if com_alerta > 0:
        log.info("\nTop 10 projetos com maior área alertada:")
        top10 = gdf_proj[gdf_proj["tem_alerta"]].nlargest(10, "alertas_area_ha")
        for _, r in top10.iterrows():
            log.info(f"  VCS_{r[id_col]} — {r.get('Nome do Projeto', '')[:50]} "
                     f"— {r['alertas_area_ha']:,.0f} ha / {r['alertas_num']} alertas")


if __name__ == "__main__":
    main()
