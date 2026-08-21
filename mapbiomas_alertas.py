"""
MapBiomas Alertas Reais — Etapa 3
==================================
Baixa e processa os dados OFICIAIS de alertas de desmatamento/uso do solo
do MapBiomas Alerta (Shapefile oficial completo do Google Cloud Storage).

URL Oficial: https://storage.googleapis.com/alerta-public/dashboard/downloads/dashboard_alerts-shapefile.zip
Output: mapbiomas_alertas.gpkg
"""

import os
import sys
import shutil
import zipfile
import logging
import tempfile
import requests
import geopandas as gpd
import pandas as pd
from pathlib import Path
from datetime import datetime

# ─── Configuração ─────────────────────────────────────────────────────────────
OUTPUT_FILE = Path("mapbiomas_alertas.gpkg")
CACHE_ZIP   = Path("mapbiomas_alerts_official.zip")
MAPBIOMAS_SHP_URL = "https://storage.googleapis.com/alerta-public/dashboard/downloads/dashboard_alerts-shapefile.zip"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def download_official_zip() -> Path:
    """Baixa o ZIP oficial de alertas do MapBiomas com streaming."""
    if CACHE_ZIP.exists() and CACHE_ZIP.stat().st_size > 100_000_000:
        log.info(f"Usando ZIP já baixado em cache: {CACHE_ZIP} ({CACHE_ZIP.stat().st_size / (1024*1024):.1f} MB)")
        return CACHE_ZIP

    log.info(f"Baixando Shapefile Oficial do MapBiomas Alerta...")
    log.info(f"URL: {MAPBIOMAS_SHP_URL}")

    resp = requests.get(MAPBIOMAS_SHP_URL, stream=True, timeout=120)
    resp.raise_for_status()

    total_bytes = int(resp.headers.get("content-length", 0))
    total_mb = total_bytes / (1024 * 1024) if total_bytes else 0
    log.info(f"Tamanho total: {total_mb:.1f} MB")

    downloaded = 0
    with open(CACHE_ZIP, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024 * 4): # 4MB chunks
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_mb > 0:
                    pct = (downloaded / total_bytes) * 100
                    sys.stdout.write(f"\r  Progresso: {downloaded / (1024*1024):.1f} / {total_mb:.1f} MB ({pct:.1f}%)")
                    sys.stdout.flush()

    sys.stdout.write("\n")
    log.info(f"[OK] Download concluído: {CACHE_ZIP}")
    return CACHE_ZIP


def process_shapefile(zip_path: Path) -> gpd.GeoDataFrame:
    """Extrai e normaliza o shapefile oficial de alertas."""
    extract_dir = Path(".mapbiomas_shp_raw")
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(exist_ok=True)

    log.info(f"Extraindo {zip_path.name}...")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract_dir)

    shp_files = list(extract_dir.glob("**/*.shp"))
    if not shp_files:
        raise FileNotFoundError("Nenhum arquivo .shp encontrado dentro do ZIP!")

    shp_target = shp_files[0]
    log.info(f"Lendo Shapefile: {shp_target.name} ({shp_target.stat().st_size / (1024*1024):.1f} MB)...")

    # Ler shapefile com geopandas
    gdf = gpd.read_file(shp_target)
    log.info(f"Shapefile carregado: {len(gdf):,} alertas!")
    log.info(f"Colunas originais: {gdf.columns.tolist()}")

    # Normalizar CRS para EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Mapear e padronizar colunas
    col_map = {}
    for col in gdf.columns:
        cl = col.lower()
        if "alerta" in cl or "alert_id" in cl or "alert_code" in cl or "id_alerta" in cl or cl == "id":
            if "alerta_id" not in col_map.values():
                col_map[col] = "alerta_id"
        elif "bioma" in cl or "biome" in cl:
            col_map[col] = "bioma"
        elif "uf" == cl or "estado" in cl or "state" in cl:
            col_map[col] = "estado"
        elif "municipio" in cl or "municip" in cl or "city" in cl:
            col_map[col] = "municipio"
        elif "area" in cl and ("ha" in cl or "hect" in cl):
            col_map[col] = "area_ha"
        elif "data" in cl or "date" in cl or "detec" in cl or "detect" in cl or "ano" in cl or "year" in cl:
            if "data_deteccao" not in col_map.values():
                col_map[col] = "data_deteccao"

    gdf = gdf.rename(columns=col_map)

    # Garantir colunas mínimas
    if "alerta_id" not in gdf.columns:
        gdf["alerta_id"] = [f"ALERT-{i+1}" for i in range(len(gdf))]
    if "area_ha" not in gdf.columns:
        # Calcular área se não existir na tabela
        log.info("Calculando área dos polígonos em hectares...")
        gdf["area_ha"] = gdf.to_crs("EPSG:5880").geometry.area / 10_000
    if "bioma" not in gdf.columns:
        gdf["bioma"] = "Não informado"
    if "estado" not in gdf.columns:
        gdf["estado"] = "BR"
    if "municipio" not in gdf.columns:
        gdf["municipio"] = "—"
    if "data_deteccao" not in gdf.columns:
        gdf["data_deteccao"] = "—"

    # Converter área para float
    gdf["area_ha"] = pd.to_numeric(gdf["area_ha"], errors="coerce").fillna(0).round(2)
    gdf["data_deteccao"] = gdf["data_deteccao"].astype(str)

    # Filtrar geometrias inválidas ou vazias
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    cols_final = ["alerta_id", "bioma", "estado", "municipio", "area_ha", "data_deteccao", "geometry"]
    gdf_final = gdf[[c for c in cols_final if c in gdf.columns]]

    # Limpar pasta temporária de extração
    shutil.rmtree(extract_dir, ignore_errors=True)

    return gdf_final


def main():
    log.info("=" * 60)
    log.info("MapBiomas Alertas Reais — Etapa 3")
    log.info("=" * 60)

    # 1. Download do ZIP oficial
    zip_path = download_official_zip()

    # 2. Processar Shapefile
    gdf = process_shapefile(zip_path)

    # 3. Salvar GeoPackage
    log.info(f"Salvando {len(gdf):,} alertas oficiais em {OUTPUT_FILE}...")
    gdf.to_file(OUTPUT_FILE, driver="GPKG", layer="alertas")

    log.info("=" * 60)
    log.info(f"[OK] {len(gdf):,} alertas salvos com sucesso em {OUTPUT_FILE}")
    log.info(f"     Área total de alertas: {gdf['area_ha'].sum():,.0f} ha")
    if "bioma" in gdf.columns:
        log.info("\nResumo por Bioma:")
        for bioma, grp in gdf.groupby("bioma"):
            log.info(f"  {bioma}: {len(grp):,} alertas ({grp['area_ha'].sum():,.0f} ha)")


if __name__ == "__main__":
    main()
