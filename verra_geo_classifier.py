"""
Verra Geo Classifier — Etapa 0
================================
Usa o sistema RAG (Gemini via Agno) para classificar o papel de cada arquivo
geoespacial (KML/KMZ/GeoJSON/SHP) de cada projeto Verra.

Lógica:
  - Projetos com 1 único arquivo geo → classificado automaticamente como
    'project_boundary' sem chamar a LLM.
  - Projetos com múltiplos arquivos geo → RAG lê o PDD do projeto e
    identifica o papel de cada arquivo.

Output: verra_geo_classification.json
"""

import os
import re
import json
import time
import zipfile
import logging
from pathlib import Path
from typing import Optional

# Carrega variáveis de ambiente do .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from verra_rag import VerraRAG

# ─── Configuração ─────────────────────────────────────────────────────────────
DOWNLOADS_DIR   = Path("downloads")
OUTPUT_FILE     = Path("verra_geo_classification.json")
GEO_EXTENSIONS  = {".kml", ".kmz", ".geojson", ".shp", ".gpkg"}
DELAY_BETWEEN_LLM_CALLS = 2.0   # segundos entre chamadas à LLM

# Categorias válidas de classificação
VALID_CATEGORIES = {
    "project_boundary",
    "leakage_belt",
    "reference_region",
    "buffer_zone",
    "project_area_individual",
    "other",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Utilitários ──────────────────────────────────────────────────────────────

def find_geo_files(project_folder: Path) -> list[Path]:
    """Retorna todos os arquivos geoespaciais de uma pasta de projeto."""
    geo_files = []
    for f in project_folder.rglob("*"):
        if f.is_file() and f.suffix.lower() in GEO_EXTENSIONS:
            geo_files.append(f)
    return sorted(geo_files)


def find_pdd(project_folder: Path) -> Optional[Path]:
    """
    Localiza o PDD (Project Description Document) mais relevante do projeto.
    Prioridade: VCS Registration Documents > VCS Other Documents > qualquer PDF.
    Prefere PDFs com 'proj_desc' ou 'PD' no nome, e depois o maior PDF.
    """
    priority_dirs = [
        project_folder / "VCS Registration Documents",
        project_folder / "VCS Other Documents",
    ]

    candidates = []
    for d in priority_dirs:
        if d.exists():
            for f in d.glob("*.pdf"):
                candidates.append(f)

    # Fallback: qualquer PDF no projeto
    if not candidates:
        candidates = list(project_folder.rglob("*.pdf"))

    if not candidates:
        return None

    # Priorizar por nome (PD = Project Description)
    def score(p: Path) -> tuple:
        name_lower = p.name.lower()
        name_score = 0
        if any(kw in name_lower for kw in ["proj_desc", "project_desc", "_pd_", "project description"]):
            name_score = 2
        elif "pdd" in name_lower:
            name_score = 1
        return (name_score, p.stat().st_size)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def infer_category_from_name(filename: str) -> Optional[str]:
    """
    Tenta inferir a categoria do arquivo pelo nome (heurística simples).
    Retorna None se não conseguir inferir com confiança.
    """
    name = filename.lower()
    if any(k in name for k in ["leakage_belt", "leakage belt", "leakage-belt", "vazamento"]):
        return "leakage_belt"
    if any(k in name for k in ["reference_region", "reference region", "referencia", "ref_reg", "ref_area"]):
        return "reference_region"
    if any(k in name for k in ["buffer", "zona_buffer", "buffer_zone"]):
        return "buffer_zone"
    if any(k in name for k in ["project_area", "project area", "project_boundary",
                                 "project boundary", "pa_", "_pa.", "limite", "boundary",
                                 "area_projeto", "proj_area"]):
        return "project_boundary"
    return None


def classify_with_llm(
    rag: VerraRAG,
    project_id: int,
    geo_files: list[Path],
    pdd_path: Optional[Path],
) -> dict[str, str]:
    """
    Usa o RAG para classificar os arquivos geo de um projeto com múltiplos arquivos.
    Retorna dict: {filename: category}
    """
    geo_names = [f.name for f in geo_files]

    # Primeiro tentar heurística por nome — se funcionar para todos, evita a LLM
    heuristic_result = {}
    for name in geo_names:
        cat = infer_category_from_name(name)
        if cat:
            heuristic_result[name] = cat

    all_inferred = len(heuristic_result) == len(geo_names)
    if all_inferred:
        log.info(f"  VCS_{project_id}: todos {len(geo_names)} arquivos classificados por heurística de nome")
        return heuristic_result

    # Ainda há arquivos não classificados → chamar LLM
    unclassified = [n for n in geo_names if n not in heuristic_result]
    log.info(f"  VCS_{project_id}: {len(unclassified)} arquivo(s) precisam de LLM: {unclassified}")

    if pdd_path is None:
        log.warning(f"  VCS_{project_id}: sem PDD encontrado, usando heurística padrão")
        # Fallback: o de nome mais curto é geralmente o project_boundary
        result = dict(heuristic_result)
        for name in unclassified:
            result[name] = "project_boundary" if not result else "other"
        return result

    # Preparar contexto para a LLM
    doc_paths = [str(pdd_path)]

    prompt = f"""O projeto VCS {project_id} possui os seguintes arquivos geoespaciais:

{chr(10).join(f"  - {name}" for name in geo_names)}

Com base nos documentos do projeto, identifique o papel de CADA arquivo geoespacial listado.

Responda EXCLUSIVAMENTE em JSON válido, sem texto adicional, sem markdown, sem explicações.
Use exatamente os nomes dos arquivos como chaves.
Categorias válidas: project_boundary, leakage_belt, reference_region, buffer_zone, project_area_individual, other

Exemplo de resposta esperada:
{{"arquivo1.kml": "project_boundary", "arquivo2.kml": "leakage_belt"}}

Responda agora com o JSON:"""

    try:
        agent = rag.criar_agente_contexto_direto(doc_paths)
        response = agent.run(prompt)

        # Extrair o texto da resposta
        resp_text = ""
        if hasattr(response, "content"):
            resp_text = str(response.content)
        elif hasattr(response, "messages") and response.messages:
            resp_text = str(response.messages[-1].content)
        else:
            resp_text = str(response)

        # Limpar markdown se houver
        resp_text = resp_text.strip()
        if resp_text.startswith("```"):
            lines = resp_text.split("\n")
            resp_text = "\n".join(lines[1:-1]) if len(lines) > 2 else resp_text

        parsed = json.loads(resp_text)

        # Validar e sanitizar
        result = dict(heuristic_result)
        for name in geo_names:
            if name in parsed and parsed[name] in VALID_CATEGORIES:
                result[name] = parsed[name]
            elif name not in result:
                result[name] = "other"

        return result

    except Exception as e:
        log.error(f"  VCS_{project_id}: erro na LLM: {e}")
        # Fallback seguro
        result = dict(heuristic_result)
        for name in unclassified:
            result[name] = "project_boundary" if not result else "other"
        return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Verra Geo Classifier — Etapa 0")
    log.info("=" * 60)

    # Carregar classificações já existentes (cache)
    existing: dict = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as fh:
            existing = json.load(fh)
        log.info(f"Cache carregado: {len(existing)} projetos já classificados")

    rag = VerraRAG()

    # Varrer a pasta downloads e mapear projeto → arquivos geo
    project_geo_map: dict[int, list[Path]] = {}
    project_folder_map: dict[int, Path] = {}

    for folder in sorted(DOWNLOADS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        m = re.match(r"VCS_(\d+)_", folder.name)
        if not m:
            continue
        proj_id = int(m.group(1))
        geo_files = find_geo_files(folder)
        if geo_files:
            project_geo_map[proj_id] = geo_files
            project_folder_map[proj_id] = folder

    log.info(f"Projetos com arquivos geo: {len(project_geo_map)}")
    single = sum(1 for fs in project_geo_map.values() if len(fs) == 1)
    multi  = sum(1 for fs in project_geo_map.values() if len(fs) > 1)
    log.info(f"  Com 1 arquivo (auto): {single}")
    log.info(f"  Com múltiplos (LLM):  {multi}")

    results = dict(existing)
    llm_calls = 0

    for proj_id, geo_files in sorted(project_geo_map.items()):
        str_id = str(proj_id)

        # Pular se já classificado
        if str_id in results:
            log.info(f"VCS_{proj_id}: já classificado (cache)")
            continue

        geo_names = [f.name for f in geo_files]

        if len(geo_files) == 1:
            # ── Caso simples: 1 arquivo → auto project_boundary ────────────
            log.info(f"VCS_{proj_id}: auto → project_boundary ({geo_names[0]})")
            results[str_id] = {
                "classified_by": "auto_single",
                "pdd_used": None,
                "files": {geo_names[0]: "project_boundary"},
            }
        else:
            # ── Múltiplos arquivos → RAG + heurística ──────────────────────
            log.info(f"VCS_{proj_id}: {len(geo_files)} arquivos geo → classificando...")
            pdd = find_pdd(project_folder_map[proj_id])
            pdd_name = pdd.name if pdd else None
            if pdd:
                log.info(f"  PDD: {pdd_name} ({pdd.stat().st_size // 1024} KB)")

            classification = classify_with_llm(rag, proj_id, geo_files, pdd)

            results[str_id] = {
                "classified_by": "llm" if pdd else "heuristic",
                "pdd_used": pdd_name,
                "files": classification,
            }

            llm_calls += 1
            # Salvar progresso após cada LLM call (tolerante a falhas)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2)

            time.sleep(DELAY_BETWEEN_LLM_CALLS)

    # Salvar resultado final
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    log.info("=" * 60)
    log.info(f"Classificação concluída: {len(results)} projetos")
    log.info(f"  Chamadas LLM realizadas: {llm_calls}")

    # Resumo das categorias encontradas
    from collections import Counter
    cat_counter: Counter = Counter()
    for entry in results.values():
        for cat in entry["files"].values():
            cat_counter[cat] += 1
    log.info("Categorias encontradas:")
    for cat, cnt in cat_counter.most_common():
        log.info(f"  {cnt:>4}  {cat}")

    log.info(f"[OK] Salvo em: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
