"""
Verra Registry Scraper - Projetos do Brasil
==========================================
Faz scraping de todos os projetos VCS do Brasil via a API interna do Verra Registry.

Método confirmado:
  - Endpoint: POST https://registry.verra.org/uiapi/resource/resource/search
  - Filtro por país: query param $filter=country eq 'Brazil'
  - Retorna ~337 projetos (testado em 2026-07-08)

Campos disponíveis por projeto (da API):
  program, resourceIdentifier, resourceName, proponent, operator, designee,
  protocolCategories, protocolSubCategories, protocols, resourceStatus, country,
  estAnnualEmissionReductions, region, projectRegistrationDate, version,
  compatibleProgramScenarioTypeName, inputTypes, programObjectives,
  creditingPeriodStartDate, creditingPeriodEndDate, createDate

Output:
  - verra_projetos_brasil.csv
  - verra_projetos_brasil.xlsx
"""

import requests
import pandas as pd
import json
import time
from datetime import datetime

# ─── Configuração ─────────────────────────────────────────────────────────────
BASE_URL  = "https://registry.verra.org/uiapi/resource/resource/search"
PAGE_SIZE = 50
COUNTRY   = "Brazil"
DELAY_S   = 1.0  # segundos entre páginas

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://registry.verra.org",
    "Referer": "https://registry.verra.org/app/search/VCS/All%20Projects",
}

# Payload base (programa VCS, sem outros filtros para pegar todos os status)
BASE_PAYLOAD = {"program": "VCS"}


def fetch_page(session: requests.Session, skip: int, top: int) -> dict:
    """Busca uma página de projetos do Brasil."""
    params = {
        "$count": "true",
        "$skip":  str(skip),
        "$top":   str(top),
        "$filter": f"country eq '{COUNTRY}'",
    }
    resp = session.post(
        BASE_URL,
        params=params,
        json=BASE_PAYLOAD,
        headers=HEADERS,
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def flatten_project(proj: dict) -> dict:
    """Converte um projeto em dicionário plano para o DataFrame."""
    return {
        "ID Verra":                       proj.get("resourceIdentifier", ""),
        "Nome do Projeto":                proj.get("resourceName", ""),
        "Proponente":                     proj.get("proponent", ""),
        "Operador":                       proj.get("operator", ""),
        "Designee":                       proj.get("designee", ""),
        "Status":                         proj.get("resourceStatus", ""),
        "País":                           proj.get("country", ""),
        "Região":                         proj.get("region", ""),
        "Categoria do Protocolo":         proj.get("protocolCategories", ""),
        "Sub-Categoria do Protocolo":     proj.get("protocolSubCategories", ""),
        "Metodologia(s)":                 proj.get("protocols", ""),
        "Redução Anual Estimada (tCO2e)": proj.get("estAnnualEmissionReductions", ""),
        "Versão VCS":                     proj.get("version", ""),
        "Início Credenciamento":          proj.get("creditingPeriodStartDate", ""),
        "Fim Credenciamento":             proj.get("creditingPeriodEndDate", ""),
        "Data Registro":                  proj.get("projectRegistrationDate", ""),
        "Data Criação (sistema)":         proj.get("createDate", ""),
        "Tipo Compatível":                proj.get("compatibleProgramScenarioTypeName", ""),
        "Objetivos do Programa":          proj.get("programObjectives", ""),
        "Link Verra":                     f"https://registry.verra.org/app/projectDetail/VCS/{proj.get('resourceIdentifier', '')}",
    }


def scrape_all_projects() -> pd.DataFrame:
    session = requests.Session()
    all_projects = []

    print(f"[{datetime.now():%H:%M:%S}] ========================================")
    print(f"[{datetime.now():%H:%M:%S}] Verra Registry Scraper — {COUNTRY}")
    print(f"[{datetime.now():%H:%M:%S}] ========================================")

    # Primeira página para descobrir o total
    print(f"[{datetime.now():%H:%M:%S}] Buscando primeira página...")
    first_page = fetch_page(session, skip=0, top=PAGE_SIZE)

    total = first_page.get("@count") or first_page.get("totalCount") or 0
    items = first_page.get("value", [])

    print(f"[{datetime.now():%H:%M:%S}] Total de projetos: {total}")
    print(f"[{datetime.now():%H:%M:%S}] Primeira página: {len(items)} projetos")

    for proj in items:
        all_projects.append(flatten_project(proj))

    # Paginar o restante
    skip = len(items)
    page_num = 2
    while skip < total:
        time.sleep(DELAY_S)
        end = min(skip + PAGE_SIZE, total)
        print(f"[{datetime.now():%H:%M:%S}] Página {page_num}: projetos {skip+1}–{end} de {total}...")
        try:
            page_data = fetch_page(session, skip=skip, top=PAGE_SIZE)
            page_items = page_data.get("value", [])
            if not page_items:
                print(f"[{datetime.now():%H:%M:%S}] Nenhum item retornado. Encerrando paginação.")
                break
            for proj in page_items:
                all_projects.append(flatten_project(proj))
            skip += len(page_items)
            page_num += 1
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now():%H:%M:%S}] Erro na página {page_num}: {e}")
            print(f"[{datetime.now():%H:%M:%S}] Aguardando 10s e tentando novamente...")
            time.sleep(10)

    df = pd.DataFrame(all_projects)
    print(f"[{datetime.now():%H:%M:%S}] ========================================")
    print(f"[{datetime.now():%H:%M:%S}] Total coletado: {len(df)} projetos")
    return df


def main():
    df = scrape_all_projects()

    if df.empty:
        print("Nenhum projeto encontrado.")
        return

    # ── Salvar outputs ─────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path   = f"verra_projetos_brasil.csv"
    excel_path = f"verra_projetos_brasil.xlsx"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV salvo:   {csv_path}")

    try:
        df.to_excel(excel_path, index=False, engine="openpyxl")
        print(f"[OK] Excel salvo: {excel_path}")
    except Exception as e:
        print(f"[AVISO] Erro ao salvar Excel: {e}")

    # ── Resumo estatístico ─────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  RESUMO — PROJETOS DO BRASIL NO VERRA REGISTRY")
    print("=" * 55)
    print(f"  Total de projetos: {len(df)}")

    if "Status" in df.columns:
        print("\n  Por Status:")
        for status, count in df["Status"].value_counts().items():
            print(f"    {count:>4}  {status}")

    if "Categoria do Protocolo" in df.columns:
        print("\n  Por Categoria de Protocolo:")
        for cat, count in df["Categoria do Protocolo"].value_counts().items():
            if cat:
                print(f"    {count:>4}  {cat}")

    if "Metodologia(s)" in df.columns and df["Metodologia(s)"].notna().any():
        all_meths = df["Metodologia(s)"].dropna().str.split(", ").explode()
        print("\n  Metodologias mais comuns (top 10):")
        for meth, count in all_meths.value_counts().head(10).items():
            if meth:
                print(f"    {count:>4}  {meth}")

    total_red = df["Redução Anual Estimada (tCO2e)"].replace("", None).dropna()
    if not total_red.empty:
        total_red = pd.to_numeric(total_red, errors="coerce").dropna()
        print(f"\n  Redução anual total estimada: {total_red.sum():,.0f} tCO2e")
        print(f"  Redução anual média:          {total_red.mean():,.0f} tCO2e")

    print("\n[OK] Scraping concluido com sucesso!")


if __name__ == "__main__":
    main()
