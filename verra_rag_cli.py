"""
Verra RAG CLI - Interface de Linha de Comando
=============================================
Interface interativa em terminal para interagir com o Verra RAG.
Permite buscar projetos, selecionar documentos e fazer perguntas ao Gemini Flash.
"""

import os
import sys
from pathlib import Path
import pandas as pd
from verra_rag import VerraRAG

def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    limpar_tela()
    print("=" * 65)
    print("        VERRA REGISTRY RAG AGENT (BRASIL) — CLI")
    print("=" * 65)

    # 1. Configurar chave API
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\nChave de API do Gemini/Google não encontrada no ambiente.")
        api_key = input("Cole sua GOOGLE_API_KEY do Google AI Studio (ou pressione Enter se usar GCP ADC): ").strip()
        if not api_key:
            api_key = None

    rag = VerraRAG(api_key=api_key)
    df = rag.get_projects()

    if df.empty:
        print("\n[ERRO] Metadados 'verra_projetos_brasil.csv' não encontrados.")
        print("Execute primeiro o verra_scraper.py para coletar os projetos.")
        return

    print(f"\nProjetos carregados com sucesso: {len(df)}")

    # 2. Escolher modo do RAG
    print("\nEscolha a modalidade de RAG:")
    print("  [1] RAG por Contexto Direto (Recomendado - Instantâneo, sem custo de indexação)")
    print("  [2] RAG Semântico por Banco Vetorial (LanceDB - requer gerar embeddings)")
    opcao_modo = input("\nOpção (padrão 1): ").strip() or "1"

    if opcao_modo == "1":
        modo_direto = True
        print("\n-> Modo selecionado: Contexto Direto (Gemini Flash 1M/2M Window)")
    else:
        modo_direto = False
        print("\n-> Modo selecionado: Banco Vetorial (LanceDB)")

    # 3. Escolher projeto
    while True:
        print("\n" + "-" * 60)
        busca = input("Busque um projeto por Nome, ID ou Proponente (ou 'sair'): ").strip()
        if busca.lower() in {"sair", "exit", "q"}:
            break

        if not busca:
            continue

        # Filtrar projetos
        df_filtrado = df[
            df["ID Verra"].astype(str).str.contains(busca, case=False, na=False) |
            df["Nome do Projeto"].str.contains(busca, case=False, na=False) |
            df["Proponente"].str.contains(busca, case=False, na=False)
        ]

        if df_filtrado.empty:
            print("Nenhum projeto encontrado para esta busca.")
            continue

        print(f"\nResultados encontrados ({len(df_filtrado)}):")
        projetos_lista = df_filtrado.head(10).to_dict("records")
        for i, proj in enumerate(projetos_lista):
            print(f"  [{i+1}] ID={proj['ID Verra']} | {proj['Nome do Projeto'][:55]} | {proj['Status']}")

        if len(df_filtrado) > 10:
            print("  ...e outros (mostrando apenas os top 10)")

        opcao_proj = input("\nSelecione o número do projeto (ou Enter para buscar novamente): ").strip()
        if not opcao_proj or not opcao_proj.isdigit():
            continue

        idx = int(opcao_proj) - 1
        if idx < 0 or idx >= len(projetos_lista):
            print("Opção inválida.")
            continue

        projeto_selecionado = projetos_lista[idx]
        project_id = str(projeto_selecionado["ID Verra"])
        project_name = projeto_selecionado["Nome do Projeto"]

        print(f"\n=> Projeto selecionado: [{project_id}] {project_name}")

        # 4. Listar documentos do projeto
        docs = rag.get_project_docs(project_id)
        if not docs:
            print("Nenhum documento físico encontrado para este projeto na pasta downloads.")
            print("Verifique se o verra_download_docs.py baixou os anexos deste projeto.")
            continue

        print(f"\nDocumentos disponíveis ({len(docs)}):")
        # Filtrar apenas tipos de texto relevantes para ler
        docs_relevantes = [d for d in docs if d["extensao"] in {".pdf", ".docx", ".doc", ".txt", ".kml"}]
        for i, d in enumerate(docs_relevantes):
            print(f"  [{i+1}] {d['grupo']} / {d['nome']} ({d['tamanho_mb']:.2f} MB)")

        if not docs_relevantes:
            print("Nenhum documento de texto ou PDF disponível para leitura.")
            continue

        opcao_docs = input("\nSelecione o(s) documento(s) para incluir no RAG (ex: '1, 3', 'todos', padrão 'todos'): ").strip()
        caminhos_selecionados = []

        if not opcao_docs or opcao_docs.lower() == "todos":
            caminhos_selecionados = [d["caminho"] for d in docs_relevantes]
        else:
            try:
                indices = [int(x.strip()) - 1 for x in opcao_docs.split(",")]
                caminhos_selecionados = [docs_relevantes[i]["caminho"] for i in indices if 0 <= i < len(docs_relevantes)]
            except Exception:
                print("Entrada inválida. Usando todos os documentos.")
                caminhos_selecionados = [d["caminho"] for d in docs_relevantes]

        if not caminhos_selecionados:
            print("Nenhum documento selecionado.")
            continue

        print(f"\nCarregando {len(caminhos_selecionados)} documento(s)...")

        # 5. Criar o Agente
        try:
            if modo_direto:
                agent = rag.criar_agente_contexto_direto(caminhos_selecionados)
            else:
                agent = rag.criar_agente_vetorial(caminhos_selecionados, collection_name=f"verra_proj_{project_id}")
        except Exception as e:
            print(f"\n[ERRO] Falha ao inicializar o Agente Agno/Gemini: {e}")
            continue

        print("\n=== Agente Pronto para Perguntas! (digite 'voltar' para escolher outro projeto) ===")
        while True:
            pergunta = input("\nPergunta: ").strip()
            if pergunta.lower() in {"voltar", "back", "q"}:
                break
            if not pergunta:
                continue

            print("\nResposta Gemini Flash:")
            try:
                agent.print_response(pergunta, stream=True)
                print()
            except Exception as e:
                print(f"\nErro ao processar resposta: {e}")

if __name__ == "__main__":
    main()
