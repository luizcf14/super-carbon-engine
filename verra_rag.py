"""
Verra RAG Manager
=================
Módulo central para gerenciar a busca, carregamento e indexação de documentos do Verra.
Suporta duas modalidades de RAG usando Agno e Gemini Flash:
  1. RAG por Contexto Direto (Instantâneo): Carrega os PDFs selecionados e insere seu
     conteúdo direto na janela de contexto de 1M/2M do Gemini Flash. Ideal para analisar
     projetos específicos com precisão total, zero custo de embedding e sem delay de indexação.
  2. RAG por Vector DB (LanceDB + GeminiEmbedder): Cria uma base vetorial local para buscas
     semânticas cruzadas (ex: pesquisar termos específicos em todos os projetos).
"""

import os
import re
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
import pypdf
from docx2txt import process as docx_to_text

# Importações do Agno
from agno.agent import Agent
from agno.models.google import Gemini
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb, SearchType

# ─── Configurações globais ───────────────────────────────────────────────────
CSV_METADADOS = Path("verra_projetos_brasil.csv")
PASTA_DOWNLOADS = Path("downloads")
LANCE_DB_DIR = Path("lancedb_data")

class VerraRAG:
    def __init__(self, api_key: Optional[str] = None):
        """Inicializa o RAG Manager. Configura a API Key do Gemini."""
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if self.api_key:
            # Garantir que ambas as variáveis de ambiente fiquem setadas
            os.environ["GOOGLE_API_KEY"] = self.api_key
            os.environ["GEMINI_API_KEY"] = self.api_key

        self.df_metadados = self._carregar_metadados()

    def _carregar_metadados(self) -> pd.DataFrame:
        """Carrega os metadados dos projetos."""
        if CSV_METADADOS.exists():
            try:
                return pd.read_csv(CSV_METADADOS, encoding="utf-8-sig")
            except Exception as e:
                print(f"Erro ao carregar metadados: {e}")
        return pd.DataFrame()

    def get_projects(self) -> pd.DataFrame:
        """Retorna o DataFrame de metadados dos projetos."""
        return self.df_metadados

    def get_project_folder(self, project_id: str) -> Optional[Path]:
        """Localiza a pasta física de um projeto com base no ID."""
        if not PASTA_DOWNLOADS.exists():
            return None
        # Procurar por pastas que começam com VCS_{project_id}_
        prefix = f"VCS_{project_id}_"
        for p in PASTA_DOWNLOADS.iterdir():
            if p.is_dir() and p.name.startswith(prefix):
                return p
        return None

    def get_project_docs(self, project_id: str) -> List[Dict[str, Any]]:
        """Retorna a lista de documentos baixados para um projeto específico."""
        folder = self.get_project_folder(project_id)
        if not folder:
            return []

        docs = []
        # Percorrer recursivamente as subpastas (grupos de documentos do Verra)
        for file_path in folder.glob("**/*"):
            if file_path.is_file():
                # Obter o grupo (nome do diretório pai direto dentro da pasta do projeto)
                try:
                    relative = file_path.relative_to(folder)
                    grupo = relative.parts[0] if len(relative.parts) > 1 else "Geral"
                except Exception:
                    grupo = "Geral"

                docs.append({
                    "nome": file_path.name,
                    "caminho": str(file_path.resolve()),
                    "tamanho_mb": file_path.stat().st_size / (1024 * 1024),
                    "extensao": file_path.suffix.lower(),
                    "grupo": grupo
                })
        return docs

    def win_path(self, path_str: str) -> str:
        """Retorna o path com prefixo \\?\\ para suportar caminhos longos no Windows."""
        p = Path(path_str).resolve()
        resolved = str(p)
        if os.name == 'nt' and not resolved.startswith("\\\\?\\"):
            return "\\\\?\\" + resolved
        return resolved

    def extrair_texto(self, caminho_arquivo: str) -> str:
        """Extrai o texto do arquivo (PDF, DOCX ou TXT)."""
        caminho_seguro = self.win_path(caminho_arquivo)
        p = Path(caminho_seguro)
        ext = p.suffix.lower()

        if not p.exists():
            return f"[Erro: Arquivo não encontrado: {caminho_arquivo}]"

        try:
            if ext == ".pdf":
                texto = []
                with open(p, "rb") as f:
                    reader = pypdf.PdfReader(f)
                    for i, page in enumerate(reader.pages):
                        texto_pag = page.extract_text()
                        if texto_pag:
                            texto.append(texto_pag)
                return "\n".join(texto)
            elif ext in {".docx", ".doc"}:
                return docx_to_text(str(p))
            elif ext in {".txt", ".kml", ".geojson", ".json"}:
                return p.read_text(encoding="utf-8", errors="ignore")
            else:
                return f"[Tipo de arquivo {ext} não suportado para leitura direta de texto]"
        except Exception as e:
            return f"[Erro ao extrair texto de {p.name}: {e}]"

    def criar_agente_contexto_direto(self, caminhos_arquivos: List[str], instrucoes: Optional[List[str]] = None) -> Agent:
        """
        Cria um Agente Agno com os documentos injetados diretamente na janela de contexto.
        Esta abordagem é instantânea e de altíssima precisão.
        """
        # Limitar número de arquivos para não estourar limite razoável (ex: 20 arquivos grandes)
        conteudo_docs = []
        total_chars = 0

        for caminho in caminhos_arquivos:
            p = Path(caminho)
            print(f"Lendo {p.name}...")
            texto = self.extrair_texto(caminho)
            total_chars += len(texto)
            conteudo_docs.append(
                f"<documento nome='{p.name}' caminho='{caminho}'>\n"
                f"{texto}\n"
                f"</documento>"
            )

        contexto_completo = (
            "Você tem acesso aos seguintes documentos do Verra Registry:\n\n" +
            "\n\n".join(conteudo_docs)
        )

        base_instrucoes = [
            "Você é um assistente de inteligência de carbono especializado em projetos do Verra Registry no Brasil.",
            "Use as informações contidas nos documentos fornecidos dentro das tags <documento> para responder às perguntas.",
            "Sempre cite o nome do documento fonte de onde você extraiu a informação.",
            "Se a resposta não estiver nos documentos, informe claramente, mas você pode usar seu conhecimento geral do Verra para complementar.",
            "Escreva sempre em formato markdown de leitura agradável (use listas, tabelas e negritos se útil)."
        ]
        if instrucoes:
            base_instrucoes.extend(instrucoes)

        # Configurar modelo Gemini
        model_args = {
            "id": "gemini-2.0-flash",
        }
        if self.api_key:
            model_args["api_key"] = self.api_key
        else:
            # Caso não tenha API key explícita, tenta usar autenticação default do GCP se configurado
            # (Agno lida com isso se passarmos vertexai=True)
            if not os.getenv("GOOGLE_API_KEY"):
                model_args["vertexai"] = True

        agent = Agent(
            model=Gemini(**model_args),
            instructions=base_instrucoes,
            system_prompt=f"INFORMAÇÕES DE SUPORTE (CONTEXTO DOS PROJETOS):\n{contexto_completo}",
            markdown=True
        )

        return agent

    def criar_agente_vetorial(self, caminhos_arquivos: List[str], collection_name: str = "verra_projetos", force_rebuild: bool = False) -> Agent:
        """
        Cria um Agente Agno com base de conhecimento baseada em banco vetorial (LanceDB).
        Adequado para pesquisas semânticas em grandes volumes de documentos.
        """
        LANCE_DB_DIR.mkdir(exist_ok=True)

        embedder_args = {"id": "gemini-embedding-exp-03-07"}
        if self.api_key:
            embedder_args["api_key"] = self.api_key
        elif not os.getenv("GOOGLE_API_KEY"):
            embedder_args["vertexai"] = True

        embedder = GeminiEmbedder(**embedder_args)

        # Configurar banco de vetores LanceDB
        vector_db = LanceDb(
            table_name=collection_name,
            uri=str(LANCE_DB_DIR.resolve()),
            search_type=SearchType.hybrid,
            embedder=embedder,
        )

        knowledge = Knowledge(vector_db=vector_db)

        # Indexar arquivos
        print(f"Indexando {len(caminhos_arquivos)} arquivos no banco vetorial LanceDB...")
        for caminho in caminhos_arquivos:
            p = Path(self.win_path(caminho))
            if p.exists():
                print(f"  -> Adicionando {p.name}...")
                try:
                    knowledge.insert(path=str(p), skip_if_exists=not force_rebuild)
                except Exception as e:
                    print(f"  [Erro] Falha ao indexar {p.name}: {e}")

        # Configurar agente
        model_args = {"id": "gemini-2.0-flash"}
        if self.api_key:
            model_args["api_key"] = self.api_key
        elif not os.getenv("GOOGLE_API_KEY"):
            model_args["vertexai"] = True

        agent = Agent(
            model=Gemini(**model_args),
            knowledge=knowledge,
            search_knowledge=True,
            instructions=[
                "Você é um especialista em projetos de carbono da Verra no Brasil.",
                "Pesquise na base de conhecimento fornecida para responder às perguntas do usuário.",
                "Seja preciso e cite os nomes dos documentos fontes sempre que possível.",
                "Escreva de forma clara em markdown estruturado."
            ],
            markdown=True
        )

        return agent
