"""
Verra Geo Enrich — Etapa 2
============================
Une as geometrias dos projetos (verra_geometrias.gpkg) com os metadados
do CSV Verra (verra_projetos_brasil.csv) para produzir um GeoDataFrame
completo com todos os 337 projetos.

Projetos sem geometria mantêm geometry=None (aparecem como marcadores
pontuais no mapa usando o centróide do Brasil como fallback visual).

Dependências: verra_geometrias.gpkg + verra_projetos_brasil.csv
Output: verra_projetos_geo.gpkg
"""

import logging
import warnings
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

warnings.filterwarnings("ignore", category=FutureWarning)

# ─── Configuração ─────────────────────────────────────────────────────────────
GEOMETRIAS_FILE = Path("verra_geometrias.gpkg")
CSV_FILE        = Path("verra_projetos_brasil.csv")
OUTPUT_FILE     = Path("verra_projetos_geo.gpkg")

TARGET_CRS = "EPSG:4326"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main():
    log.info("=" * 60)
    log.info("Verra Geo Enrich — Etapa 2")
    log.info("=" * 60)

    # ── 1. Carregar metadados CSV ──────────────────────────────────────────────
    if not CSV_FILE.exists():
        log.error(f"CSV não encontrado: {CSV_FILE}")
        return

    df_meta = pd.read_csv(CSV_FILE, encoding="utf-8-sig")

    # Normalizar o ID (garantir inteiro)
    id_col = "ID Verra"
    df_meta[id_col] = pd.to_numeric(df_meta[id_col], errors="coerce").astype("Int64")
    df_meta = df_meta.dropna(subset=[id_col])
    log.info(f"Metadados carregados: {len(df_meta)} projetos")

    # ── 2. Carregar geometrias ─────────────────────────────────────────────────
    if not GEOMETRIAS_FILE.exists():
        log.error(f"Geometrias não encontradas: {GEOMETRIAS_FILE}")
        log.error("Execute primeiro: python verra_geo_parser.py")
        return

    gdf_geo = gpd.read_file(GEOMETRIAS_FILE, layer="geometrias")
    gdf_geo["id_verra"] = pd.to_numeric(gdf_geo["id_verra"], errors="coerce").astype("Int64")
    log.info(f"Geometrias carregadas: {len(gdf_geo)} projetos com polígono")

    # ── 3. Left join: todos os projetos + geometrias disponíveis ──────────────
    df_joined = df_meta.merge(
        gdf_geo[["id_verra", "geometry", "area_km2", "num_features",
                 "arquivo_geo", "classification_source"]],
        left_on=id_col,
        right_on="id_verra",
        how="left",
    )

    # ── 4. Criar GeoDataFrame ──────────────────────────────────────────────────
    gdf = gpd.GeoDataFrame(df_joined, geometry="geometry", crs=TARGET_CRS)

    # ── 5. Calcular centróide para projetos com geometria ─────────────────────
    has_geom = ~gdf.geometry.isna()
    log.info(f"Projetos com geometria: {has_geom.sum()} / {len(gdf)}")
    log.info(f"Projetos sem geometria: {(~has_geom).sum()}")

    # Centróide para posicionamento de marcadores pontuais e tooltips
    gdf["lat_centroid"] = None
    gdf["lon_centroid"] = None

    if has_geom.any():
        centroids = gdf.loc[has_geom, "geometry"].centroid
        gdf.loc[has_geom, "lat_centroid"] = centroids.y.round(6)
        gdf.loc[has_geom, "lon_centroid"] = centroids.x.round(6)

    # ── 6. Normalizar e limpar colunas de data ─────────────────────────────────
    date_cols = [
        "Início Credenciamento", "Fim Credenciamento",
        "Data Registro", "Data Criação (sistema)",
    ]
    for col in date_cols:
        if col in gdf.columns:
            gdf[col] = pd.to_datetime(gdf[col], errors="coerce").dt.strftime("%Y-%m-%d")

    # ── 7. Adicionar colunas de alertas MapBiomas (serão preenchidas na Etapa 4) ──
    gdf["alertas_num"]      = 0
    gdf["alertas_area_ha"]  = 0.0
    gdf["alertas_periodo"]  = None
    gdf["tem_alerta"]       = False

    # ── 8. Salvar ──────────────────────────────────────────────────────────────
    gdf.to_file(OUTPUT_FILE, driver="GPKG", layer="projetos")

    log.info("=" * 60)
    log.info(f"[OK] {len(gdf)} projetos salvos em {OUTPUT_FILE}")

    # Resumo por status
    log.info("\nResumo por Status:")
    for status, grp in gdf.groupby("Status"):
        com_geo = grp["geometry"].notna().sum()
        log.info(f"  {status}: {len(grp)} projetos ({com_geo} com geometria)")

    log.info(f"\nCobertura geo: {has_geom.sum() / len(gdf) * 100:.1f}%")
    log.info(f"Área total dos projetos: {gdf['area_km2'].sum():,.0f} km²")


if __name__ == "__main__":
    main()
