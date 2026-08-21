"""
Verra Registry — Download de Anexos por Projeto
================================================
Para cada projeto do Brasil (do CSV gerado pelo verra_scraper.py),
busca a lista de documentos via resourceSummary e baixa os arquivos
dos tipos: pdf, doc, docx, geojson, shp, kml, kmz, zip, xlsx, xls.

Estrutura de saída:
  downloads/
    VCS_{id}_{nome_projeto}/
      {grupo}/
        {nome_do_arquivo}

Requer:
  - verra_projetos_brasil.csv (gerado pelo verra_scraper.py)
  - pip install requests pandas tqdm
"""

import requests
import pandas as pd
import os
import re
import time
import json
from pathlib import Path
from datetime import datetime

# ─── Configuração ─────────────────────────────────────────────────────────────
CSV_INPUT      = "verra_projetos_brasil.csv"
DOWNLOAD_DIR   = Path("downloads")
LOG_FILE       = "download_log.csv"
DELAY_SUMMARY  = 0.5   # delay entre chamadas ao resourceSummary (segundos)
DELAY_DOWNLOAD = 1.0   # delay entre downloads (segundos)
MAX_RETRIES    = 3

# Tipos de arquivo alvo (extensões)
TARGET_EXTENSIONS = {".pdf", ".doc", ".docx", ".geojson", ".shp",
                     ".kml", ".kmz", ".zip", ".xlsx", ".xls", ".shx",
                     ".dbf", ".prj", ".cpg", ".json"}

BASE_URL = "https://registry.verra.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/app/search/VCS/All%20Projects",
}


# ─── Funções auxiliares ────────────────────────────────────────────────────────

def safe_dirname(name: str, max_len: int = 60) -> str:
    """Converte um nome para ser seguro como nome de diretório no Windows."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')   # strip antes de truncar
    name = name[:max_len]
    name = name.rstrip('. ')  # strip APÓS truncar (evita espaço/ponto no fim)
    return name or "_"


def get_document_groups(session: requests.Session, project_id: str) -> list:
    """Busca os grupos de documentos de um projeto via resourceSummary."""
    url = f"{BASE_URL}/uiapi/resource/resourceSummary/{project_id}"
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            return data.get("documentGroups", [])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return []
            print(f"    [HTTP {e.response.status_code}] Tentativa {attempt+1}/{MAX_RETRIES}")
        except Exception as e:
            print(f"    [Erro] {e} — Tentativa {attempt+1}/{MAX_RETRIES}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(5)
    return []


def is_target_file(filename: str) -> bool:
    """Verifica se a extensão do arquivo é um dos tipos alvo."""
    ext = Path(filename).suffix.lower()
    return ext in TARGET_EXTENSIONS


def win_path(p: Path) -> str:
    """Retorna path com prefixo \\?\ para suportar caminhos longos no Windows."""
    resolved = str(p.resolve())
    # Evitar duplicar o prefixo caso resolve() ja retorne \\?\
    if resolved.startswith("\\\\?\\"):
        return resolved
    return "\\\\?\\" + resolved


def download_file(session: requests.Session, uri: str, dest_path: Path) -> dict:
    """Baixa um arquivo e salva em dest_path. Retorna info do resultado."""
    # Usar prefixo Windows para caminhos longos
    dest_str = win_path(dest_path)

    if Path(dest_str).exists():
        return {"status": "skipped", "size_bytes": Path(dest_str).stat().st_size}

    try:
        Path(dest_str).parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"status": "error", "message": f"Erro ao criar diretório: {e}"}

    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(uri, headers=HEADERS, timeout=60, stream=True)
            r.raise_for_status()

            # Verificar Content-Type (evitar HTML de erro)
            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct and dest_path.suffix.lower() not in {".html", ".htm"}:
                return {"status": "error", "message": f"Retornou HTML (possível página de erro)"}

            total = 0
            with open(dest_str, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)

            return {"status": "ok", "size_bytes": total}

        except requests.exceptions.HTTPError as e:
            msg = f"HTTP {e.response.status_code}"
            if e.response.status_code in {403, 404}:
                return {"status": "error", "message": msg}
            print(f"    [Tentativa {attempt+1}] {msg}")
        except Exception as e:
            print(f"    [Tentativa {attempt+1}] {e}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(5)

    return {"status": "error", "message": "Max retries exceeded"}


# ─── Programa principal ────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Verra Registry — Download de Anexos (Brasil)")
    print("=" * 65)
    print(f"  Iniciado em: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print()

    # Carregar lista de projetos
    if not Path(CSV_INPUT).exists():
        print(f"[ERRO] Arquivo '{CSV_INPUT}' não encontrado.")
        print("       Execute primeiro o verra_scraper.py")
        return

    df = pd.read_csv(CSV_INPUT, encoding="utf-8-sig")
    print(f"  Projetos carregados: {len(df)}")
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    session = requests.Session()

    # Retomada: carregar log existente para pular projetos já processados
    log_records = []
    done_project_ids = set()
    if Path(LOG_FILE).exists():
        existing_log = pd.read_csv(LOG_FILE, encoding="utf-8-sig")
        log_records = existing_log.to_dict("records")
        # Considerar como concluído apenas se TODOS os docs do projeto foram processados
        # (status ok ou error, não interrompido no meio)
        done_project_ids = set(existing_log["project_id"].astype(str).unique())
        print(f"  Retomando: {len(done_project_ids)} projetos ja no log")

    stats = {
        "projetos_processados": 0,
        "documentos_encontrados": 0,
        "downloads_ok": 0,
        "downloads_skipped": 0,
        "downloads_erro": 0,
        "bytes_total": 0,
    }

    for idx, row in df.iterrows():
        project_id   = str(row.get("ID Verra", "")).strip()
        project_name = str(row.get("Nome do Projeto", "")).strip()
        status       = str(row.get("Status", "")).strip()

        if not project_id:
            continue

        # Pular projetos já processados (retomada)
        if project_id in done_project_ids:
            print(f"\n[{idx+1:>3}/{len(df)}] ID={project_id} | {project_name[:45]} [JA PROCESSADO]")
            stats["projetos_processados"] += 1
            continue

        safe_name = safe_dirname(f"VCS_{project_id}_{project_name}")
        project_dir = DOWNLOAD_DIR / safe_name

        print(f"\n[{idx+1:>3}/{len(df)}] ID={project_id} | {project_name[:45]}")
        print(f"         Status: {status}")

        # Buscar documentos via API
        time.sleep(DELAY_SUMMARY)
        doc_groups = get_document_groups(session, project_id)

        if not doc_groups:
            print("         Sem documentos encontrados.")
            stats["projetos_processados"] += 1
            continue

        # Coletar todos os docs de todos os grupos
        all_docs = []
        seen_uris = set()
        for group in doc_groups:
            group_code = group.get("code", "OTHER")
            group_desc = group.get("description", group_code)
            for doc in group.get("documents", []):
                uri      = doc.get("uri", "")
                doc_name = doc.get("documentName", "")
                doc_type = doc.get("documentType", "")
                upload   = doc.get("uploadDate", "")

                if not uri or uri in seen_uris:
                    continue
                seen_uris.add(uri)

                if not is_target_file(doc_name):
                    print(f"         [SKIP tipo] {doc_name}")
                    continue

                all_docs.append({
                    "uri": uri,
                    "doc_name": doc_name,
                    "doc_type": doc_type,
                    "group_code": group_code,
                    "group_desc": group_desc,
                    "upload_date": upload,
                })

        stats["documentos_encontrados"] += len(all_docs)
        print(f"         Documentos alvo: {len(all_docs)}")

        for doc in all_docs:
            safe_fname = safe_dirname(doc["doc_name"], max_len=200)
            safe_group = safe_dirname(doc["group_desc"], max_len=50)
            dest_path  = project_dir / safe_group / safe_fname

            print(f"         -> [{doc['doc_type']}] {doc['doc_name']}")

            time.sleep(DELAY_DOWNLOAD)
            result = download_file(session, doc["uri"], dest_path)

            log_records.append({
                "project_id":   project_id,
                "project_name": project_name,
                "group":        doc["group_desc"],
                "doc_type":     doc["doc_type"],
                "doc_name":     doc["doc_name"],
                "uri":          doc["uri"],
                "upload_date":  doc["upload_date"],
                "dest_path":    str(dest_path),
                "status":       result["status"],
                "size_bytes":   result.get("size_bytes", 0),
                "message":      result.get("message", ""),
            })

            if result["status"] == "ok":
                kb = result.get("size_bytes", 0) / 1024
                print(f"            [OK] {kb:.1f} KB")
                stats["downloads_ok"] += 1
                stats["bytes_total"] += result.get("size_bytes", 0)
            elif result["status"] == "skipped":
                print(f"            [JA EXISTE]")
                stats["downloads_skipped"] += 1
            else:
                print(f"            [ERRO] {result.get('message', '')}")
                stats["downloads_erro"] += 1

        stats["projetos_processados"] += 1

        # Salvar log parcial a cada 10 projetos
        if (idx + 1) % 10 == 0:
            pd.DataFrame(log_records).to_csv(LOG_FILE, index=False, encoding="utf-8-sig")
            print(f"\n  [LOG] Salvo em {LOG_FILE}")

    # Salvar log final
    log_df = pd.DataFrame(log_records)
    log_df.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")

    # Relatório final
    print("\n" + "=" * 65)
    print("  RESUMO FINAL")
    print("=" * 65)
    print(f"  Projetos processados:   {stats['projetos_processados']}")
    print(f"  Documentos encontrados: {stats['documentos_encontrados']}")
    print(f"  Downloads concluidos:   {stats['downloads_ok']}")
    print(f"  Ja existiam (skip):     {stats['downloads_skipped']}")
    print(f"  Erros:                  {stats['downloads_erro']}")
    mb = stats["bytes_total"] / (1024 * 1024)
    print(f"  Total baixado:          {mb:.1f} MB")
    print(f"\n  Arquivos em:  {DOWNLOAD_DIR.resolve()}")
    print(f"  Log salvo em: {LOG_FILE}")
    print(f"\n  Concluido em: {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()
