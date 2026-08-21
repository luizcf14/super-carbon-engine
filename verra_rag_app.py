"""
Verra Registry RAG Web Application
==================================
Uma interface web premium baseada em Streamlit para explorar e fazer consultas RAG
sobre todos os projetos de carbono da Verra no Brasil.
Suporta injeção de documentos direta na janela de contexto de 1M/2M de tokens do Gemini Flash.
"""

import streamlit as st
import os
import pandas as pd
from pathlib import Path
from verra_rag import VerraRAG

# Configurações de página Streamlit
st.set_page_config(
    page_title="Verra Carbon RAG - Brasil",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Estilo Visual Premium (Custom CSS) ──────────────────────────────────────
st.markdown("""
<style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=Outfit:wght@400;600;800&display=swap');
    
    /* Configurações básicas */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    h1, h2, h3, .title-grad {
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
    }

    /* Título com gradiente elegante */
    .title-grad {
        background: linear-gradient(135deg, #00FF87 0%, #60EFFF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.8rem;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        color: #A0AEC0;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }

    /* Efeito de Card Glassmorphism */
    .glass-card {
        background: rgba(26, 32, 44, 0.45);
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
    }
    
    /* Tags de Status do Verra */
    .status-tag {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        margin-right: 0.5rem;
    }
    .status-registered { background-color: rgba(72, 187, 120, 0.2); color: #48BB78; border: 1px solid #48BB78; }
    .status-validation { background-color: rgba(236, 201, 75, 0.2); color: #ECC94B; border: 1px solid #ECC94B; }
    .status-development { background-color: rgba(66, 153, 225, 0.2); color: #4299E1; border: 1px solid #4299E1; }
    .status-other { background-color: rgba(160, 174, 192, 0.2); color: #A0AEC0; border: 1px solid #A0AEC0; }

    /* Customizações de chat */
    .chat-bubble-user {
        background-color: #2D3748;
        padding: 1rem;
        border-radius: 12px 12px 0px 12px;
        margin-bottom: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .chat-bubble-agent {
        background-color: rgba(0, 255, 135, 0.03);
        padding: 1rem;
        border-radius: 12px 12px 12px 0px;
        margin-bottom: 1rem;
        border: 1px solid rgba(0, 255, 135, 0.15);
    }
</style>
""", unsafe_allow_html=True)

# ─── Estado da Sessão Streamlit ──────────────────────────────────────────────
if "api_key" not in st.session_state:
    st.session_state["api_key"] = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "agente_atual" not in st.session_state:
    st.session_state["agente_atual"] = None
if "docs_carregados" not in st.session_state:
    st.session_state["docs_carregados"] = []

# Inicializar o RAG Manager
rag = VerraRAG(api_key=st.session_state["api_key"] if st.session_state["api_key"] else None)
df_projetos = rag.get_projects()

# ─── SIDEBAR: Configuração & Busca de Projetos ───────────────────────────────
with st.sidebar:
    st.image("https://verra.org/wp-content/uploads/2021/04/Verra-Logo-TaglineHorizontal-Color-sm.png", width=200)
    st.markdown("### Configurações de API")
    
    # Input da chave API
    api_key_input = st.text_input(
        "Chave de API do Gemini",
        value=st.session_state["api_key"],
        type="password",
        help="Insira sua GOOGLE_API_KEY gerada no Google AI Studio. Se estiver rodando em ambiente GCP autenticado, pode deixar em branco para usar Vertex AI default."
    )
    if api_key_input != st.session_state["api_key"]:
        st.session_state["api_key"] = api_key_input
        st.rerun()

    st.markdown("---")
    st.markdown("### Filtros de Busca")

    if not df_projetos.empty:
        # Filtro de Status
        status_options = ["Todos"] + sorted(df_projetos["Status"].dropna().unique().tolist())
        status_selecionado = st.selectbox("Status do Projeto", status_options)

        # Filtro por Categoria de Protocolo
        categorias = ["Todas"] + sorted(df_projetos["Categoria do Protocolo"].dropna().unique().tolist())
        categoria_selecionada = st.selectbox("Categoria", categorias[:10] + ["Outros..."] if len(categorias) > 10 else categorias)

        # Busca livre por texto
        busca_texto = st.text_input("Busca livre (Nome, ID, Proponente)")

        # Aplicar filtros
        df_filtrado = df_projetos.copy()
        if status_selecionado != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Status"] == status_selecionado]
        if categoria_selecionada != "Todas" and categoria_selecionada != "Outros...":
            df_filtrado = df_filtrado[df_filtrado["Categoria do Protocolo"] == categoria_selecionada]
        if busca_texto:
            df_filtrado = df_filtrado[
                df_filtrado["ID Verra"].astype(str).str.contains(busca_texto, case=False, na=False) |
                df_filtrado["Nome do Projeto"].str.contains(busca_texto, case=False, na=False) |
                df_filtrado["Proponente"].str.contains(busca_texto, case=False, na=False)
            ]

        # Lista de projetos resultantes
        st.markdown(f"#### Projetos Encontrados ({len(df_filtrado)})")
        
        projetos_dict = {}
        for _, r in df_filtrado.iterrows():
            label = f"[{r['ID Verra']}] {r['Nome do Projeto'][:45]}..."
            projetos_dict[label] = str(r["ID Verra"])
            
        proj_label_selecionado = st.selectbox(
            "Selecione o Projeto para Análise", 
            options=list(projetos_dict.keys()) if projetos_dict else ["Nenhum encontrado"]
        )
        
        projeto_id_selecionado = projetos_dict.get(proj_label_selecionado) if proj_label_selecionado != "Nenhum encontrado" else None
    else:
        st.warning("Metadados não encontrados. Execute o scraper primeiro.")
        projeto_id_selecionado = None

# ─── TELA PRINCIPAL ──────────────────────────────────────────────────────────
st.markdown("<div class='title-grad'>Verra Registry RAG🌱</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Faça perguntas inteligentes baseadas em todos os relatórios, KMLs e PDDs oficiais dos projetos do Brasil</div>", unsafe_allow_html=True)

if not projeto_id_selecionado:
    st.info("👈 Use os filtros da barra lateral para localizar e selecionar um projeto de carbono do Brasil.")
else:
    # Obter detalhes do projeto selecionado
    dados_proj = df_projetos[df_projetos["ID Verra"].astype(str) == projeto_id_selecionado].iloc[0]
    
    # Header do projeto
    st.markdown(f"## [{dados_proj['ID Verra']}] {dados_proj['Nome do Projeto']}")
    
    # Criar colunas para metadados rápidos
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Redução Anual Estimada", f"{dados_proj.get('Redução Anual Estimada (tCO2e)', 'N/A')} tCO2e")
    with col2:
        st.metric("Status do Projeto", dados_proj.get("Status", "N/A"))
    with col3:
        st.metric("Proponente", str(dados_proj.get("Proponente", "N/A"))[:30] + "...")
    with col4:
        st.markdown(f"<br><a href='{dados_proj.get('Link Verra', '#')}' target='_blank'><button style='padding: 6px 12px; border-radius: 8px; background-color: #2D3748; color: white; border: 1px solid #4A5568; cursor: pointer;'>Ver no Verra Registry 🔗</button></a>", unsafe_allow_html=True)

    # Buscar documentos físicos disponíveis na pasta downloads
    documentos = rag.get_project_docs(projeto_id_selecionado)
    
    st.markdown("### 📂 Documentos Físicos Disponíveis")
    if not documentos:
        st.warning("Nenhum arquivo encontrado na pasta de downloads para este projeto. Certifique-se de executar o script `verra_download_docs.py`.")
    else:
        # Agrupar documentos por categoria
        documentos_por_grupo = {}
        for doc in documentos:
            grupo = doc["grupo"]
            if grupo not in documentos_por_grupo:
                documentos_por_grupo[grupo] = []
            documentos_por_grupo[grupo].append(doc)
            
        # Form para selecionar arquivos para o RAG
        with st.form("form_docs"):
            st.write("Selecione os relatórios e anexos que deseja que o Gemini Flash leia e analise:")
            
            selecionados = []
            
            # Criar abas ou colunas para grupos
            for grupo, arquivos in documentos_por_grupo.items():
                with st.expander(f"📁 {grupo} ({len(arquivos)} arquivos)", expanded=True):
                    for arq in arquivos:
                        # Habilitar checkbox apenas para tipos de texto que sabemos ler
                        pode_ler = arq["extensao"] in {".pdf", ".docx", ".doc", ".txt", ".kml", ".geojson", ".json"}
                        disabled = not pode_ler
                        
                        # Checkbox
                        cb_key = f"cb_{projeto_id_selecionado}_{grupo}_{arq['nome']}"
                        
                        # Pré-selecionar os mais importantes (Project Description / PDD / Resumos / KML)
                        default_val = False
                        nome_low = arq["nome"].lower()
                        if pode_ler and ("description" in nome_low or "pdd" in nome_low or "summary" in nome_low or "resumo" in nome_low or arq["extensao"] == ".kml"):
                            default_val = True
                            
                        escolhido = st.checkbox(
                            f"{arq['nome']} ({arq['tamanho_mb']:.2f} MB)", 
                            value=default_val, 
                            key=cb_key,
                            disabled=disabled,
                            help="Tipos não textuais/não suportados estão desabilitados."
                        )
                        if escolhido:
                            selecionados.append(arq["caminho"])
                            
            # Botão de submissão do form
            submit_carga = st.form_submit_button("🔥 Carregar Documentos Selecionados no Gemini Flash")
            
            if submit_carga:
                if not selecionados:
                    st.error("Por favor, selecione pelo menos um documento para carregar.")
                else:
                    with st.spinner("Carregando arquivos e extraindo texto para o contexto do Gemini..."):
                        try:
                            # Criar o agente com o contexto injetado
                            agente = rag.criar_agente_contexto_direto(selecionados)
                            st.session_state["agente_atual"] = agente
                            st.session_state["docs_carregados"] = [Path(p).name for p in selecionados]
                            st.session_state["chat_history"] = [] # Resetar chat
                            st.success(f"Sucesso! {len(selecionados)} documentos carregados na janela de contexto do Gemini Flash (RAG de alta fidelidade).")
                        except Exception as e:
                            st.error(f"Erro ao inicializar o assistente do Agno: {e}")

    # Painel do Chat
    if st.session_state["agente_atual"]:
        st.markdown("---")
        st.markdown("### 💬 Chat Inteligente com Gemini Flash")
        
        # Mostrar quais documentos o Gemini está lendo no momento
        st.caption(f"📚 **Documentos carregados na sessão atual:** {', '.join(st.session_state['docs_carregados'])}")
        
        # Mostrar histórico
        for chat in st.session_state["chat_history"]:
            if chat["role"] == "user":
                st.markdown(f"<div class='chat-bubble-user'><b>Você:</b><br>{chat['content']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='chat-bubble-agent'><b>Gemini Flash:</b><br>{chat['content']}</div>", unsafe_allow_html=True)
                
        # Input do chat
        user_query = st.chat_input("Pergunte algo sobre a área, metodologia, proponentes ou metas de redução de carbono do projeto...")
        
        if user_query:
            # Mostrar pergunta do usuário imediatamente
            st.markdown(f"<div class='chat-bubble-user'><b>Você:</b><br>{user_query}</div>", unsafe_allow_html=True)
            
            # Adicionar ao histórico do usuário
            st.session_state["chat_history"].append({"role": "user", "content": user_query})
            
            # Chamar o agente Agno
            with st.spinner("Processando resposta..."):
                try:
                    response_container = st.empty()
                    # Chamar o run() para obter a resposta do Agno
                    agente_instancia = st.session_state["agente_atual"]
                    
                    # Obter resposta completa do agente
                    resp_obj = agente_instancia.run(user_query)
                    # O conteúdo do texto pode ser extraído diretamente de resp_obj.content
                    resposta_texto = resp_obj.content if hasattr(resp_obj, "content") else str(resp_obj)
                    
                    # Exibir resposta formatada no container
                    response_container.markdown(f"<div class='chat-bubble-agent'><b>Gemini Flash:</b><br>{resposta_texto}</div>", unsafe_allow_html=True)
                    
                    # Adicionar resposta ao histórico
                    st.session_state["chat_history"].append({"role": "agent", "content": resposta_texto})
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao obter resposta do Gemini: {e}")
