"""
Verra Registry Carbon & MapBiomas Intelligence Platform
======================================================
Interface web premium baseada em Streamlit com:
  1. 🗺️ Mapa Interativo com limites vetoriais dos projetos Verra e alertas MapBiomas
  2. 🤖 RAG com Gemini Flash (injeção direta de PDDs e relatórios)
  3. 📊 Análise Espacial e Ranking de Risco de Desmatamento
  4. ⚙️ Painel de Controle do Pipeline de Dados
"""

import os
import json
import subprocess
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from datetime import datetime

from verra_rag import VerraRAG

# ─── Configurações da Página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Super Carbon Engine | Verra & MapBiomas",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Estilo Visual Premium (Custom CSS) ──────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@500;700;800;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    h1, h2, h3, h4, .title-grad {
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        letter-spacing: -0.02em;
    }

    .title-grad {
        background: linear-gradient(135deg, #10B981 0%, #06B6D4 50%, #3B82F6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.6rem;
        margin-bottom: 0.2rem;
    }
    
    .subtitle {
        color: #94A3B8;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }

    /* Glass Cards */
    .glass-card {
        background: rgba(30, 41, 59, 0.5);
        border-radius: 14px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(10px);
    }

    .metric-card {
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
    }
    .metric-val {
        font-family: 'Outfit', sans-serif;
        font-size: 1.8rem;
        font-weight: 800;
        color: #F8FAFC;
    }
    .metric-lbl {
        font-size: 0.8rem;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 0.2rem;
    }

    /* Tags */
    .status-tag {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 6px;
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        margin-right: 0.4rem;
    }
    .status-registered { background: rgba(34, 197, 94, 0.15); color: #4ADE80; border: 1px solid rgba(34, 197, 94, 0.3); }
    .status-validation { background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.3); }
    .status-alert { background: rgba(249, 115, 22, 0.15); color: #FB923C; border: 1px solid rgba(249, 115, 22, 0.3); }

    /* Chat bubbles */
    .chat-bubble-user {
        background-color: rgba(51, 65, 85, 0.5);
        border-radius: 12px 12px 0px 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    .chat-bubble-agent {
        background-color: rgba(6, 182, 212, 0.05);
        border-radius: 12px 12px 12px 0px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(6, 182, 212, 0.2);
    }
    
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        border-radius: 8px;
        padding: 0 20px;
        background: rgba(30, 41, 59, 0.3);
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .stTabs [aria-selected="true"] {
        background: rgba(16, 185, 129, 0.15) !important;
        border: 1px solid #10B981 !important;
        color: #10B981 !important;
    }
</style>
""", unsafe_allow_html=True)

# ─── Estado da Sessão ────────────────────────────────────────────────────────
if "api_key" not in st.session_state:
    st.session_state["api_key"] = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "agente_atual" not in st.session_state:
    st.session_state["agente_atual"] = None
if "docs_carregados" not in st.session_state:
    st.session_state["docs_carregados"] = []
if "selected_proj_id" not in st.session_state:
    st.session_state["selected_proj_id"] = None

# Inicializar o RAG Manager
rag = VerraRAG(api_key=st.session_state["api_key"] if st.session_state["api_key"] else None)

# Carregar dataset enriquecido
@st.cache_data
def carregar_dados():
    csv_geo = Path("verra_intersect_mapbiomas.csv")
    csv_padrao = Path("verra_projetos_brasil.csv")
    
    if csv_geo.exists():
        df = pd.read_csv(csv_geo, encoding="utf-8-sig")
    elif csv_padrao.exists():
        df = pd.read_csv(csv_padrao, encoding="utf-8-sig")
    else:
        df = pd.DataFrame()
    return df

df_projetos = carregar_dados()

# ─── SIDEBAR: Controles e Filtros Globais ─────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌿 Carbon Mapper")
    st.caption("Super Carbon Engine · Brasil")
    st.markdown("---")
    
    # Configuração de API Key
    with st.expander("🔑 Configuração API Gemini", expanded=not bool(st.session_state["api_key"])):
        api_key_input = st.text_input(
            "Google API Key",
            value=st.session_state["api_key"],
            type="password",
            help="Insira a GOOGLE_API_KEY do Google AI Studio para ativar o RAG Gemini."
        )
        if api_key_input != st.session_state["api_key"]:
            st.session_state["api_key"] = api_key_input
            os.environ["GOOGLE_API_KEY"] = api_key_input
            st.rerun()

    st.markdown("### 🔍 Filtros de Projetos")

    if not df_projetos.empty:
        # Filtro de Status
        status_opts = ["Todos"] + sorted([str(s) for s in df_projetos["Status"].dropna().unique()])
        status_sel = st.selectbox("Status Verra", status_opts)

        # Filtro de Alertas MapBiomas
        filtro_alerta = st.radio(
            "Filtro de Alertas MapBiomas",
            ["Todos", "Apenas COM alertas ⚠️", "Apenas SEM alertas ✅"],
            index=0
        )

        # Filtro por Categoria
        if "Categoria do Protocolo" in df_projetos.columns:
            cats = ["Todas"] + sorted([str(c) for c in df_projetos["Categoria do Protocolo"].dropna().unique()])
            cat_sel = st.selectbox("Categoria", cats)
        else:
            cat_sel = "Todas"

        # Busca textual
        busca = st.text_input("Buscar por Nome, ID ou Proponente", placeholder="Ex: Manoa, 1571, ARR...")

        # Aplicação dos filtros
        df_filtrado = df_projetos.copy()
        if status_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["Status"] == status_sel]
        if cat_sel != "Todas":
            df_filtrado = df_filtrado[df_filtrado["Categoria do Protocolo"] == cat_sel]
        if filtro_alerta == "Apenas COM alertas ⚠️" and "tem_alerta" in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado["tem_alerta"] == True]
        elif filtro_alerta == "Apenas SEM alertas ✅" and "tem_alerta" in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado["tem_alerta"] == False]
        if busca:
            df_filtrado = df_filtrado[
                df_filtrado["ID Verra"].astype(str).str.contains(busca, case=False, na=False) |
                df_filtrado["Nome do Projeto"].astype(str).str.contains(busca, case=False, na=False) |
                df_filtrado["Proponente"].astype(str).str.contains(busca, case=False, na=False)
            ]

        st.caption(f"**{len(df_filtrado)}** projetos correspondentes")

        # Seleção de projeto ativo
        st.markdown("#### Selecionar Projeto")
        projetos_dict = {}
        for _, r in df_filtrado.iterrows():
            alerta_ico = "⚠️ " if r.get("tem_alerta") == True else ""
            label = f"{alerta_ico}[{r['ID Verra']}] {str(r['Nome do Projeto'])[:40]}"
            projetos_dict[label] = str(r["ID Verra"])

        if projetos_dict:
            proj_labels = list(projetos_dict.keys())
            # Tentar manter o selecionado anteriormente
            default_ix = 0
            if st.session_state["selected_proj_id"]:
                for ix, lab in enumerate(proj_labels):
                    if projetos_dict[lab] == st.session_state["selected_proj_id"]:
                        default_ix = ix
                        break

            proj_selecionado_label = st.selectbox(
                "Projeto Ativo para Análise",
                proj_labels,
                index=default_ix
            )
            st.session_state["selected_proj_id"] = projetos_dict[proj_selecionado_label]
        else:
            st.info("Nenhum projeto encontrado com os filtros.")
            st.session_state["selected_proj_id"] = None
    else:
        st.warning("Nenhum dado encontrado.")

# ─── HEADER PRINCIPAL ────────────────────────────────────────────────────────
st.markdown("<div class='title-grad'>Super Carbon Engine 🌿</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Inteligência Geoespacial, Cruzamento de Alertas MapBiomas e RAG com Gemini Flash</div>", unsafe_allow_html=True)

# ─── KPIS GLOBAIS ────────────────────────────────────────────────────────────
if not df_projetos.empty:
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    
    total_proj = len(df_projetos)
    com_geom = df_projetos["area_km2"].notna().sum() if "area_km2" in df_projetos.columns else 172
    com_alerta = df_projetos["tem_alerta"].sum() if "tem_alerta" in df_projetos.columns else 58
    total_alertas = int(df_projetos["alertas_num"].sum()) if "alertas_num" in df_projetos.columns else 40862
    area_alertada = float(df_projetos["alertas_area_ha"].sum()) if "alertas_area_ha" in df_projetos.columns else 1529349.0

    with kpi1:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{total_proj}</div><div class='metric-lbl'>Projetos Verra Brasil</div></div>", unsafe_allow_html=True)
    with kpi2:
        st.markdown(f"<div class='metric-card'><div class='metric-val' style='color:#38BDF8;'>{com_geom}</div><div class='metric-lbl'>Com Polígono Real (51%)</div></div>", unsafe_allow_html=True)
    with kpi3:
        st.markdown(f"<div class='metric-card'><div class='metric-val' style='color:#FB923C;'>{com_alerta}</div><div class='metric-lbl'>Com Alertas MapBiomas</div></div>", unsafe_allow_html=True)
    with kpi4:
        st.markdown(f"<div class='metric-card'><div class='metric-val' style='color:#F87171;'>{total_alertas:,}</div><div class='metric-lbl'>Alertas Detectados</div></div>", unsafe_allow_html=True)
    with kpi5:
        st.markdown(f"<div class='metric-card'><div class='metric-val' style='color:#A78BFA;'>{area_alertada:,.0f} ha</div><div class='metric-lbl'>Área Alertada Total</div></div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─── NAVEGAÇÃO POR ABAS ──────────────────────────────────────────────────────
tab_mapa, tab_rag, tab_analise, tab_pipeline = st.tabs([
    "🗺️ Mapa Interativo & Alertas",
    "🤖 RAG & Chat Gemini Flash",
    "📊 Análise de Risco & Tabela",
    "⚙️ Pipeline & Downloads"
])

# ══════════════════════════════════════════════════════════════════════════════
# ABA 1: MAPA INTERATIVO & MAPBIOMAS
# ══════════════════════════════════════════════════════════════════════════════
with tab_mapa:
    st.markdown("### 🗺️ Visualizador Geoespacial dos Projetos e Desmatamento")
    st.caption("Polígonos vetoriais reais extraídos dos anexos KML/KMZ oficiais e sobreposição com a malha de alertas do MapBiomas.")

    map_path = Path("mapa_verra_brasil.html")
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as fh:
            map_html = fh.read()
        components.html(map_html, height=650, scrolling=False)
        st.caption("💡 **Dica**: Use o controle de camadas no canto superior direito para alternar entre satélite, mapa claro, mapa escuro e camada de calor (Heatmap).")
    else:
        st.warning("Arquivo `mapa_verra_brasil.html` não encontrado. Execute o script `verra_mapa.py` na aba Pipeline.")

    # Detalhes do Projeto Ativo no Mapa
    if st.session_state["selected_proj_id"] and not df_projetos.empty:
        proj_row = df_projetos[df_projetos["ID Verra"].astype(str) == st.session_state["selected_proj_id"]]
        if not proj_row.empty:
            p = proj_row.iloc[0]
            st.markdown("---")
            st.markdown(f"#### 🔍 Detalhes Rápidos: [{p['ID Verra']}] {p['Nome do Projeto']}")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(f"**Proponente:** {p.get('Proponente', '—')}")
                st.markdown(f"**Status:** {p.get('Status', '—')}")
            with c2:
                st.markdown(f"**Metodologia:** {p.get('Metodologia(s)', '—')}")
                st.markdown(f"**Categoria:** {p.get('Categoria do Protocolo', '—')}")
            with c3:
                area_km = p.get('area_km2')
                st.markdown(f"**Área do Projeto:** {f'{area_km:,.1f} km²' if pd.notna(area_km) else 'Sem polígono'}")
                st.markdown(f"**Redução Anual:** {p.get('Redução Anual Estimada (tCO2e)', '—')} tCO2e")
            with c4:
                tem_alt = p.get('tem_alerta', False)
                if tem_alt:
                    st.error(f"⚠️ **{int(p.get('alertas_num',0))} alertas** ({p.get('alertas_area_ha',0):,.1f} ha)")
                else:
                    st.success("✅ **Nenhum alerta detectado**")
                
                link = p.get('Link Verra', '#')
                st.markdown(f"[🔗 Abrir no Verra Registry]({link})")

# ══════════════════════════════════════════════════════════════════════════════
# ABA 2: RAG & CHAT GEMINI FLASH
# ══════════════════════════════════════════════════════════════════════════════
with tab_rag:
    st.markdown("### 🤖 Consulta Inteligente com Gemini Flash aos PDDs e Relatórios")
    
    if not st.session_state["selected_proj_id"]:
        st.info("👈 Selecione um projeto na barra lateral para carregar seus documentos e iniciar a conversa.")
    else:
        proj_id = st.session_state["selected_proj_id"]
        dados_proj = df_projetos[df_projetos["ID Verra"].astype(str) == proj_id].iloc[0]

        st.markdown(f"#### 📄 Projeto: **[{dados_proj['ID Verra']}] {dados_proj['Nome do Projeto']}**")
        
        # Buscar documentos físicos na pasta de downloads
        documentos = rag.get_project_docs(proj_id)

        if not documentos:
            st.warning(f"Nenhum documento físico encontrado para o projeto VCS {proj_id} na pasta `downloads/`.")
            st.info("Execute `verra_download_docs.py` para baixar os relatórios e PDDs deste projeto.")
        else:
            # Agrupar por categoria
            docs_por_grupo = {}
            for doc in documentos:
                g = doc["grupo"]
                if g not in docs_por_grupo:
                    docs_por_grupo[g] = []
                docs_por_grupo[g].append(doc)

            with st.form("form_carregar_docs"):
                st.markdown(f"**Arquivos Disponíveis ({len(documentos)})** — Selecione os documentos que o Gemini Flash deve ler:")
                
                selecionados = []
                col_g1, col_g2 = st.columns(2)
                
                grupos_list = list(docs_por_grupo.items())
                half = (len(grupos_list) + 1) // 2
                
                for idx, (grupo, arqs) in enumerate(grupos_list):
                    col_target = col_g1 if idx < half else col_g2
                    with col_target:
                        with st.expander(f"📁 {grupo} ({len(arqs)} docs)", expanded=True):
                            for f_idx, arq in enumerate(arqs):
                                pode_ler = arq["extensao"] in {".pdf", ".docx", ".doc", ".txt", ".kml", ".geojson", ".json"}
                                nome_low = arq["nome"].lower()
                                
                                # Default inteligente: PDDs, Resumos e KMLs
                                default_check = pode_ler and any(kw in nome_low for kw in ["pdd", "desc", "summary", "resumo", "valid", "kml"])
                                
                                cb = st.checkbox(
                                    f"{arq['nome']} ({arq['tamanho_mb']:.1f} MB)",
                                    value=default_check,
                                    disabled=not pode_ler,
                                    key=f"rag_cb_{proj_id}_{grupo}_{f_idx}_{arq['nome']}"
                                )
                                if cb and pode_ler:
                                    selecionados.append(arq["caminho"])

                submit_btn = st.form_submit_button("⚡ Carregar Documentos na Janela de Contexto")

                if submit_btn:
                    if not selecionados:
                        st.warning("Selecione pelo menos um documento de texto ou PDF.")
                    else:
                        with st.spinner(f"Injetando {len(selecionados)} arquivos no Gemini Flash..."):
                            try:
                                agente = rag.criar_agente_contexto_direto(selecionados)
                                st.session_state["agente_atual"] = agente
                                st.session_state["docs_carregados"] = [Path(p).name for p in selecionados]
                                st.session_state["chat_history"] = []
                                st.success(f"✅ {len(selecionados)} documentos carregados com sucesso! Faça sua pergunta abaixo.")
                            except Exception as e:
                                st.error(f"Erro ao inicializar agente: {e}")

        # Interface de Chat
        if st.session_state["agente_atual"]:
            st.markdown("---")
            st.markdown("### 💬 Chat com os Documentos do Projeto")
            st.caption(f"Documentos ativos no contexto: {', '.join(st.session_state['docs_carregados'])}")

            # Sugestões rápidas
            sug_col1, sug_col2, sug_col3 = st.columns(3)
            with sug_col1:
                if st.button("📌 Resuma os objetivos e metodologia"):
                    st.session_state["prompt_input"] = "Faça um resumo completo dos objetivos do projeto, a metodologia VCS utilizada e as atividades previstas."
            with sug_col2:
                if st.button("🗺️ Quais os limites e áreas descritos?"):
                    st.session_state["prompt_input"] = "Descreva a área do projeto, localização, municípios abrangidos e as coordenadas ou polígonos informados."
            with sug_col3:
                if st.button("⚠️ Quais os riscos de não-permanência?"):
                    st.session_state["prompt_input"] = "Quais são os principais riscos de não-permanência, vazamento (leakage) ou desmatamento identificados no PDD?"

            # Exibir histórico de chat
            for msg in st.session_state["chat_history"]:
                if msg["role"] == "user":
                    st.markdown(f"<div class='chat-bubble-user'><b>Você:</b><br>{msg['content']}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='chat-bubble-agent'><b>Gemini Flash:</b><br>{msg['content']}</div>", unsafe_allow_html=True)

            # Input do chat
            prompt_default = st.session_state.get("prompt_input", "")
            user_input = st.chat_input("Pergunte qualquer coisa sobre o projeto ou seus relatórios...", key="chat_user_input")
            
            pergunta = user_input or (prompt_default if prompt_default else None)

            if pergunta:
                st.session_state["prompt_input"] = ""
                st.session_state["chat_history"].append({"role": "user", "content": pergunta})
                
                with st.spinner("Analisando documentos..."):
                    try:
                        agente = st.session_state["agente_atual"]
                        resp = agente.run(pergunta)
                        resp_text = resp.content if hasattr(resp, "content") else str(resp)
                        st.session_state["chat_history"].append({"role": "agent", "content": resp_text})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao gerar resposta: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ABA 3: ANÁLISE DE RISCO & TABELA
# ══════════════════════════════════════════════════════════════════════════════
with tab_analise:
    st.markdown("### 📊 Análise Espacial & Ranking de Risco de Desmatamento")
    st.caption("Cruzamento analítico entre projetos Verra e alertas do MapBiomas.")

    if not df_projetos.empty:
        col_r1, col_r2 = st.columns(2)

        with col_r1:
            st.markdown("#### 🚨 Top 10 Projetos com Maior Área Alertada")
            if "tem_alerta" in df_projetos.columns and df_projetos["tem_alerta"].any():
                top10 = df_projetos[df_projetos["tem_alerta"]].nlargest(10, "alertas_area_ha")
                
                df_top_display = top10[[
                    "ID Verra", "Nome do Projeto", "Status", "alertas_num", "alertas_area_ha"
                ]].rename(columns={
                    "Nome do Projeto": "Projeto",
                    "alertas_num": "Qtd Alertas",
                    "alertas_area_ha": "Área Alertada (ha)"
                })
                st.dataframe(df_top_display, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum projeto com alertas.")

        with col_r2:
            st.markdown("#### 📌 Distribuição de Alertas por Status")
            if "tem_alerta" in df_projetos.columns:
                status_alerta = df_projetos.groupby("Status").agg(
                    total_projetos=("ID Verra", "count"),
                    projetos_com_alerta=("tem_alerta", "sum"),
                    area_alertada_ha=("alertas_area_ha", "sum")
                ).reset_index()
                st.dataframe(status_alerta, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 📋 Tabela Completa de Projetos & Métricas Geoespaciais")

        # Configurar colunas de exibição
        cols_show = [
            "ID Verra", "Nome do Projeto", "Status", "Proponente",
            "Categoria do Protocolo", "Metodologia(s)", "Redução Anual Estimada (tCO2e)",
            "area_km2", "alertas_num", "alertas_area_ha", "tem_alerta"
        ]
        cols_existentes = [c for c in cols_show if c in df_filtrado.columns]
        
        st.dataframe(
            df_filtrado[cols_existentes],
            use_container_width=True,
            hide_index=True
        )

        # Botão para download do CSV
        csv_data = df_filtrado[cols_existentes].to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "📥 Baixar Tabela Filtrada (CSV)",
            data=csv_data,
            file_name=f"verra_mapbiomas_filtrado_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# ══════════════════════════════════════════════════════════════════════════════
# ABA 4: PIPELINE & EXECUTOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_pipeline:
    st.markdown("### ⚙️ Painel de Execução do Pipeline Geoespacial")
    st.caption("Execute ou atualize as etapas do pipeline diretamente da interface.")

    pcol1, pcol2 = st.columns(2)

    with pcol1:
        st.markdown("#### 1. Ingestão e Classificação")
        
        if st.button("🚀 Executar Classificador RAG (Etapa 0)"):
            with st.spinner("Classificando arquivos geo com Gemini..."):
                res = subprocess.run(["python", "verra_geo_classifier.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)

        if st.button("📐 Executar Parser de Polígonos (Etapa 1)"):
            with st.spinner("Parseando e dissolvendo KMLs/KMZs..."):
                res = subprocess.run(["python", "verra_geo_parser.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)

        if st.button("🔗 Executar Enriquecimento de Metadados (Etapa 2)"):
            with st.spinner("Unindo metadados e geometrias..."):
                res = subprocess.run(["python", "verra_geo_enrich.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)

    with pcol2:
        st.markdown("#### 2. MapBiomas & Intersecção")

        if st.button("🛰️ Baixar/Atualizar Alertas MapBiomas (Etapa 3)"):
            with st.spinner("Obtendo dados do MapBiomas..."):
                res = subprocess.run(["python", "mapbiomas_alertas.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)

        if st.button("⚔️ Executar Intersecção Espacial (Etapa 4)"):
            with st.spinner("Intersectando projetos com alertas..."):
                res = subprocess.run(["python", "verra_mapbiomas_intersect.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)

        if st.button("🗺️ Regenerar Mapa HTML (Etapa 5)"):
            with st.spinner("Gerando novo mapa Folium..."):
                res = subprocess.run(["python", "verra_mapa.py"], capture_output=True, text=True)
                st.code(res.stdout or res.stderr)
                st.success("Mapa regenerado com sucesso!")
