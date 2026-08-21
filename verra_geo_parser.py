"""
Verra Geo Parser — Etapa 1
============================
Lê os arquivos geoespaciais de cada projeto (KML, KMZ, GeoJSON, SHP, GPKG)
usando as classificações da Etapa 0, e produz um GeoDataFrame com apenas
os polígonos de 'project_boundary' de cada projeto.

Dependência: verra_geo_classification.json (gerado pela Etapa 0)
Output: verra_geometrias.gpkg
"""

import os
import re
import json
import logging
import zipfile
import tempfile
import warnings
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*CRS.*")

# ─── Configuração ─────────────────────────────────────────────────────────────
DOWNLOADS_DIR       = Path("downloads")
CLASSIFICATION_FILE = Path("verra_geo_classification.json")
OUTPUT_FILE         = Path("verra_geometrias.gpkg")

# CRS padrão de saída
TARGET_CRS = "EPSG:4326"

# CRS métrico para o Brasil (para calcular área em km²)
BRAZIL_METRIC_CRS = "EPSG:5880"  # SIRGAS 2000 / Brazil Polyconic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Utilitários ──────────────────────────────────────────────────────────────

def win_path(path: Path) -> Path:
    """Aplica prefixo \\?\\ para suportar caminhos longos no Windows."""
    if os.name == "nt":
        resolved = str(path.resolve())
        if not resolved.startswith("\\\\?\\"):
            return Path("\\\\?\\" + resolved)
    return path.resolve()


def read_kmz(kmz_path: Path) -> Optional[gpd.GeoDataFrame]:
    """Extrai o KML de dentro de um KMZ e lê como GeoDataFrame."""
    try:
        with zipfile.ZipFile(kmz_path) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                log.warning(f"  KMZ sem KML interno: {kmz_path.name}")
                return None
            # Preferir doc.kml ou o maior
            kml_name = next((n for n in kml_names if "doc.kml" in n.lower()), kml_names[0])
            with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
                tmp.write(z.read(kml_name))
                tmp_path = Path(tmp.name)
        gdf = read_geo_file(tmp_path)
        tmp_path.unlink(missing_ok=True)
        return gdf
    except Exception as e:
        log.error(f"  Erro ao ler KMZ {kmz_path.name}: {e}")
        return None



def read_geo_file(path: Path) -> Optional[gpd.GeoDataFrame]:
    """
    Lê um arquivo geoespacial (KML, KMZ, GeoJSON, SHP, GPKG) e retorna GeoDataFrame.
    Para KMLs com múltiplas camadas: lê todas as camadas e combina as que têm polígonos.
    """
    import fiona
    ext = path.suffix.lower()

    if ext == ".kmz":
        return read_kmz(path)

    safe_path = win_path(path)
    os.environ["GDAL_ENABLE_DRIVER_KML"] = "YES"

    # ── Listar camadas disponíveis ────────────────────────────────────────────
    try:
        layers = fiona.listlayers(str(safe_path))
    except Exception:
        layers = [None]  # sem informação de camadas → tentar direto

    if not layers:
        layers = [None]

    # ── Ler cada camada e combinar ────────────────────────────────────────────
    gdfs = []
    for layer in layers:
        try:
            kwargs = {}
            if layer is not None:
                kwargs["layer"] = layer
            gdf = gpd.read_file(str(safe_path), **kwargs)
            if gdf is None or gdf.empty:
                continue
            # Filtrar geometrias nulas
            gdf = gdf[~gdf.geometry.isna()].copy()
            if gdf.empty:
                continue
            gdfs.append(gdf)
        except Exception as e:
            log.debug(f"    Camada '{layer}' ignorada: {e}")
            continue

    if not gdfs:
        log.warning(f"  Sem geometria válida em {path.name}")
        return None

    if len(gdfs) == 1:
        return gdfs[0]

    # Combinar múltiplas camadas
    try:
        combined = gpd.GeoDataFrame(
            pd.concat(gdfs, ignore_index=True),
            crs=gdfs[0].crs
        )
        return combined
    except Exception as e:
        log.error(f"  Erro ao combinar camadas de {path.name}: {e}")
        return gdfs[0]  # fallback: primeira camada


def extract_polygons(gdf: gpd.GeoDataFrame) -> Optional[gpd.GeoDataFrame]:
    """
    Filtra apenas geometrias poligonais (Polygon / MultiPolygon).
    Tenta converter linhas/pontos apenas se não houver polígonos.
    """
    if gdf is None or gdf.empty:
        return None

    # Garantir CRS
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")

    # Remover geometrias nulas
    gdf = gdf[~gdf.geometry.isna()].copy()
    if gdf.empty:
        return None

    # Corrigir geometrias inválidas
    gdf["geometry"] = gdf["geometry"].apply(make_valid)

    # Filtrar polígonos
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    poly_gdf = gdf[poly_mask].copy()

    if poly_gdf.empty:
        log.debug("  Sem polígonos — tentando buffer em pontos/linhas")
        # Fallback: buffer pequeno em pontos (0.001° ≈ 111m)
        non_poly = gdf[~poly_mask].copy()
        if not non_poly.empty:
            non_poly["geometry"] = non_poly.geometry.buffer(0.001)
            return non_poly
        return None

    return poly_gdf


def dissolve_project(gdf: gpd.GeoDataFrame, proj_id: int) -> Optional[dict]:
    """
    Dissolve todas as geometrias de um projeto em um único MultiPolygon.
    Retorna dicionário com campos para o GeoDataFrame final.
    """
    poly_gdf = extract_polygons(gdf)
    if poly_gdf is None or poly_gdf.empty:
        return None

    # União de todos os polígonos
    try:
        union_geom = make_valid(unary_union(poly_gdf.geometry))
    except Exception as e:
        log.error(f"  VCS_{proj_id}: erro na união de geometrias: {e}")
        return None

    if union_geom is None or union_geom.is_empty:
        return None

    # Calcular área em km²
    try:
        import pyproj
        from shapely.ops import transform
        from functools import partial

        proj = pyproj.Transformer.from_crs(
            "EPSG:4326", BRAZIL_METRIC_CRS, always_xy=True
        ).transform
        geom_metric = transform(proj, union_geom)
        area_km2 = geom_metric.area / 1_000_000
    except Exception:
        # Fallback: estimativa planar em graus (imprecisa para áreas grandes)
        area_km2 = union_geom.area * 12321  # aprox. 111km/grau²

    # Sanity check: Brasil tem ~8.5M km², nenhum projeto individual deveria ter mais de 2M km²
    area_flag = None
    if area_km2 > 2_000_000:
        area_flag = "area_suspeita_grande"
        log.warning(f"  VCS_{proj_id}: área suspeita ({area_km2:,.0f} km²) — KML pode ser regional/nacional")

    return {
        "id_verra": proj_id,
        "geometry": union_geom,
        "area_km2": round(area_km2, 2),
        "num_features": len(poly_gdf),
        "area_flag":  area_flag,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Verra Geo Parser — Etapa 1")
    log.info("=" * 60)

    if not CLASSIFICATION_FILE.exists():
        log.error(f"Arquivo de classificação não encontrado: {CLASSIFICATION_FILE}")
        log.error("Execute primeiro: python verra_geo_classifier.py")
        return

    with open(CLASSIFICATION_FILE, encoding="utf-8") as fh:
        classification = json.load(fh)

    log.info(f"Projetos classificados: {len(classification)}")

    records = []
    errors  = []

    for str_id, entry in sorted(classification.items(), key=lambda x: int(x[0])):
        proj_id  = int(str_id)
        files_cl = entry.get("files", {})

        # Selecionar apenas os arquivos de project_boundary
        boundary_files = {
            fname: cat
            for fname, cat in files_cl.items()
            if cat == "project_boundary"
        }

        if not boundary_files:
            # Nenhum arquivo classificado como boundary — usar todos
            log.warning(f"VCS_{proj_id}: nenhum project_boundary → usando todos os arquivos geo")
            boundary_files = files_cl

        # Localizar a pasta do projeto
        project_folder = None
        for folder in DOWNLOADS_DIR.iterdir():
            if folder.is_dir() and folder.name.startswith(f"VCS_{proj_id}_"):
                project_folder = folder
                break

        if project_folder is None:
            log.warning(f"VCS_{proj_id}: pasta não encontrada")
            errors.append(proj_id)
            continue

        # Ler e combinar todos os arquivos de boundary
        gdfs = []
        for fname, cat in boundary_files.items():
            # Buscar o arquivo recursivamente na pasta do projeto
            found = list(project_folder.rglob(fname))
            if not found:
                log.warning(f"  VCS_{proj_id}: arquivo não encontrado: {fname}")
                continue
            file_path = found[0]
            log.info(f"VCS_{proj_id}: lendo {fname} ({file_path.stat().st_size // 1024} KB)")
            gdf = read_geo_file(file_path)
            if gdf is not None:
                gdfs.append(gdf)

        if not gdfs:
            log.warning(f"VCS_{proj_id}: nenhum arquivo lido com sucesso")
            errors.append(proj_id)
            continue

        # Combinar todos os GDFs do projeto
        combined = gpd.GeoDataFrame(
            pd.concat(gdfs, ignore_index=True),
            crs="EPSG:4326"
        )

        result = dissolve_project(combined, proj_id)
        if result is None:
            log.warning(f"VCS_{proj_id}: sem polígonos válidos após processamento")
            errors.append(proj_id)
            continue

        # Adicionar informações de classificação
        result["arquivo_geo"]           = "; ".join(boundary_files.keys())
        result["classification_source"] = entry.get("classified_by", "unknown")
        records.append(result)
        log.info(f"  ✓ VCS_{proj_id}: {result['num_features']} feature(s), {result['area_km2']:,.1f} km²")

    # Criar GeoDataFrame final
    if not records:
        log.error("Nenhuma geometria válida extraída.")
        return

    gdf_final = gpd.GeoDataFrame(records, crs=TARGET_CRS)
    gdf_final = gdf_final.set_index("id_verra")

    # Salvar
    gdf_final.reset_index().to_file(OUTPUT_FILE, driver="GPKG", layer="geometrias")

    log.info("=" * 60)
    log.info(f"[OK] {len(gdf_final)} projetos com geometria salvo em {OUTPUT_FILE}")
    log.info(f"     Erros: {len(errors)} projetos sem geometria válida")
    if errors:
        log.info(f"     IDs com erro: {errors[:20]}")
    log.info(f"     Área total dos projetos: {gdf_final['area_km2'].sum():,.0f} km²")


if __name__ == "__main__":
    main()
