# Super Carbon Engine (Carbon Mapper)

Motor de coleta, processamento, indexação vetorial e análise inteligente (RAG com Gemini 2.5 / Agno) de projetos de crédito de carbono (Verra VCS / Brasil).

---

## 🚀 Funcionalidades

1. **Scraper Verra VCS (`verra_scraper.py`)**:
   - Extrai metadados de projetos de carbono registrados no Brasil diretamente da API pública da Verra.
   - Gera relatórios estruturados em `.csv` e `.xlsx`.

2. **Downloader de Documentos (`verra_download_docs.py`)**:
   - Baixa automaticamente Project Descriptions (PD), Relatórios de Monitoramento (MR), Relatórios de Validação/Verificação (VVR) e outros documentos de projetos.
   - Gera log de download estruturado (`download_log.csv`).

3. **Mecanismo RAG e Análise de Projetos (`verra_rag.py` / `verra_rag_cli.py`)**:
   - Indexação de PDFs e documentos Word de projetos.
   - Suporte a vector store (LanceDB) e injeção de contexto longo no Google Gemini.
   - Interface CLI para consultas rápidas e geração de relatórios de risco, metodologias e cálculo de créditos.

4. **Interface Web Interativa (`verra_rag_app.py`)**:
   - Dashboard em Streamlit para explorar projetos, selecionar documentos e interagir com o agente especialista via chat.

---

## 🛠️ Instalação e Configuração

### 1. Clonar o repositório
```bash
git clone https://github.com/luizcf14/super-carbon-engine.git
cd super-carbon-engine
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

### 3. Configurar Chave de API
Defina a variável de ambiente com sua chave do Google AI Studio:
```bash
# Windows (PowerShell)
$env:GOOGLE_API_KEY="sua_chave_gemini_aqui"

# Linux / Mac
export GOOGLE_API_KEY="sua_chave_gemini_aqui"
```

---

## 💻 Como Usar

### Executar a aplicação Streamlit
```bash
streamlit run verra_rag_app.py
```

### Executar consultas via CLI
```bash
python verra_rag_cli.py
```

### Coletar dados da Verra
```bash
python verra_scraper.py
python verra_download_docs.py
```
