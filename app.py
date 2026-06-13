"""
NewsAI - Configuratore e Generatore di Report Notizie
======================================================
Applicazione Streamlit con politica ZERO-PERSISTENCE:
- Nessun database o log lato server
- API Key solo in memoria volatile (st.session_state)
- Configurazione esportabile/importabile via file JSON locale

Esegui con: streamlit run app.py
"""

import json
import streamlit as st
import requests

# ---------------------------------------------------------------------------
# Dipendenze opzionali (installate solo se necessario)
# ---------------------------------------------------------------------------
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import google.generativeai as genai
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


# ===========================================================================
# COSTANTI: Cataloghi dei modelli
# ===========================================================================

GEMINI_MODELS = {
    "gemini-3.5-flash":      "Gemini 3.5 Flash (Latest Fast, Near-Pro Intelligence)",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite (Highest Efficiency, Low Latency)",
    "gemini-2.5-flash":      "Gemini 2.5 Flash (Stable Workhorse with Thinking)",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite (High Throughput, Free Tier)",
    "gemini-2.5-pro":        "Gemini 2.5 Pro (Complex Reasoning, Highly Rate-Limited Free)",
    "gemma-4-12b-unified":   "Gemma 4 12B (Local Multimodal, Encoder-Free, 16GB VRAM)",
    "gemma-4-26b-moe":       "Gemma 4 26B MoE (High-Performance Open-Weights, 3.8B Active)",
    "gemma-4-e4b-edge":      "Gemma 4 E4B (Edge Optimized, Ultra-Lightweight 4.5B)",
}

OPENROUTER_MODELS = {
    "openrouter/free":               "OpenRouter Free (Auto-Routing - Free Tier)",
    "deepseek/deepseek-v4-flash":    "DeepSeek V4 Flash (Ultra-Fast)",
    "deepseek/deepseek-v4-pro":      "DeepSeek V4 Pro (Deep Reasoning & Coding)",
    "meta-llama/llama-4-maverick":   "Llama 4 Maverick (Next-Gen Intelligence)",
    "xiaomi/mimo-v2.5":              "Xiaomi Mimo v2.5 (On-Device & Efficient)",
}

OPENAI_MODELS = {
    "gpt-4o":            "GPT-4o (Flagship Multimodal)",
    "gpt-4o-mini":       "GPT-4o Mini (Fast & Cost-Effective)",
    "gpt-4-turbo":       "GPT-4 Turbo (High Context)",
    "gpt-3.5-turbo":     "GPT-3.5 Turbo (Legacy Budget)",
    "o1-preview":        "o1 Preview (Advanced Reasoning)",
    "o1-mini":           "o1 Mini (Compact Reasoning)",
}

PROVIDERS = ["Google (Gemini)", "OpenRouter", "OpenAI"]

# ===========================================================================
# SYSTEM PROMPT per la generazione del report geopolitico/economico
# ===========================================================================

SYSTEM_PROMPT = """Sei un analista geopolitico ed economico senior con specializzazione in Europa e mercati finanziari.
Il tuo compito è elaborare le notizie grezze fornite dall'utente e produrre un **Report Notizie Strutturato** professionale.

## Struttura obbligatoria del report

### 🇪🇺 Notizie Europee
Riassumi le principali notizie riguardanti l'Unione Europea, le istituzioni comunitarie, i singoli paesi membri e le dinamiche intra-europee.
Organizza per paese o per tema. Utilizza elenchi puntati chiari.

### 🌍 Notizie Mondiali
Riassumi i principali eventi geopolitici globali: conflitti, diplomazia, elezioni, accordi internazionali.
Includi Asia, Americhe, Africa e Medio Oriente se presenti nei dati.

### 🏛️ Politica
Analizza gli sviluppi politici chiave: governi, partiti, legislature, riforme normative.
Distingui tra politica europea, nazionale e internazionale.

### 🏭 Economia Tedesca
Sezione dedicata all'economia della Germania. Includi:
- Dati macro (PIL, inflazione, disoccupazione se menzionati)
- Settore industriale e automotive
- Politiche fiscali e commerciali del governo tedesco
- Impatto delle dinamiche UE sull'economia tedesca

### 📊 Mercati Finanziari
Inserisci una tabella Markdown con i dati di mercato se presenti nelle notizie.

| Asset / Indice | Valore | Variazione % | Nota |
|---|---|---|---|
| DAX 40 | ... | ... | ... |
| Euro Stoxx 50 | ... | ... | ... |
| EUR/USD | ... | ... | ... |
| Bund 10Y | ... | ... | ... |
| Petrolio Brent | ... | ... | ... |

Se i dati di mercato non sono presenti nell'input, ometti la tabella e inserisci una nota: *Nessun dato di mercato disponibile nell'input fornito.*

---

## Norme redazionali
- Usa un tono neutro, professionale e analitico
- Evidenzia in **grassetto** i soggetti chiave (paesi, istituzioni, leader)
- Usa i corsivi per citazioni dirette o termini tecnici
- Chiudi il report con un breve paragrafo **📌 Sintesi e Outlook** che evidenzi le tendenze principali della giornata
- Formatta sempre in Markdown standard
"""


# ===========================================================================
# INIZIALIZZAZIONE SESSION STATE (Zero-Persistence: solo RAM)
# ===========================================================================

def init_session_state():
    """Inizializza le variabili di sessione se non già presenti."""
    defaults = {
        "openrouter_key": "",
        "openai_key":     "",
        "google_key":     "",
        "provider":       PROVIDERS[0],           # Google di default
        "model_id":       "gemini-2.5-flash",
        "raw_news":       "",
        "report_output":  "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()


# ===========================================================================
# UTILITÀ: Import / Export configurazione JSON
# ===========================================================================

def export_config() -> str:
    """Serializza la configurazione corrente in una stringa JSON."""
    config = {
        "provider":       st.session_state.provider,
        "model_id":       st.session_state.model_id,
        "openrouter_key": st.session_state.openrouter_key,
        "openai_key":     st.session_state.openai_key,
        "google_key":     st.session_state.google_key,
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def import_config(uploaded_file) -> bool:
    """
    Legge il file JSON caricato e ripopola st.session_state.
    Restituisce True se l'importazione è andata a buon fine.
    """
    try:
        raw = uploaded_file.read()
        config = json.loads(raw)

        # Mappa i campi del JSON allo session_state (con fallback ai valori correnti)
        st.session_state.provider       = config.get("provider",       st.session_state.provider)
        st.session_state.model_id       = config.get("model_id",       st.session_state.model_id)
        st.session_state.openrouter_key = config.get("openrouter_key", "")
        st.session_state.openai_key     = config.get("openai_key",     "")
        st.session_state.google_key     = config.get("google_key",     "")
        return True

    except (json.JSONDecodeError, KeyError, Exception) as e:
        st.sidebar.error(f"❌ Errore nel file JSON: {e}")
        return False


# ===========================================================================
# LOGICA DI CHIAMATA API (tre provider)
# ===========================================================================

def call_openrouter(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    """
    Chiama l'API OpenRouter tramite richieste HTTP dirette.
    Endpoint compatibile con OpenAI Chat Completions.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://newsai.local",   # Richiesto da OpenRouter
        "X-Title":       "NewsAI Report Generator",
    }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=90)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def call_openai(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    """
    Chiama l'API OpenAI usando la libreria ufficiale `openai`.
    Se la libreria non è installata, fallback a richieste HTTP dirette.
    """
    if OPENAI_AVAILABLE:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    else:
        # Fallback HTTP diretto
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def call_google(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    """
    Chiama l'API Google AI Studio (Gemini) usando la libreria `google-generativeai`
    oppure tramite richiesta HTTP REST diretta come fallback.
    """
    if GOOGLE_AVAILABLE:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_id,
            system_instruction=system_prompt,
        )
        response = model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.3),
        )
        return response.text
    else:
        # Fallback: API REST diretta di Google AI Studio
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:generateContent?key={api_key}"
        )
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"parts": [{"text": user_prompt}]}
            ],
            "generationConfig": {"temperature": 0.3},
        }
        response = requests.post(url, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


def generate_report(provider: str, model_id: str, raw_news: str) -> str:
    """
    Dispatcher centrale: sceglie il provider corretto e avvia la chiamata API.
    Restituisce il testo del report o solleva un'eccezione con messaggio leggibile.
    """
    if not raw_news.strip():
        raise ValueError("Il campo notizie grezze è vuoto. Incolla almeno alcune notizie prima di generare il report.")

    if provider == "OpenRouter":
        key = st.session_state.openrouter_key
        if not key:
            raise ValueError("OpenRouter API Key mancante. Inseriscila nella barra laterale.")
        return call_openrouter(key, model_id, SYSTEM_PROMPT, raw_news)

    elif provider == "OpenAI":
        key = st.session_state.openai_key
        if not key:
            raise ValueError("OpenAI API Key mancante. Inseriscila nella barra laterale.")
        return call_openai(key, model_id, SYSTEM_PROMPT, raw_news)

    elif provider == "Google (Gemini)":
        key = st.session_state.google_key
        if not key:
            raise ValueError("Google API Key mancante. Inseriscila nella barra laterale.")
        return call_google(key, model_id, SYSTEM_PROMPT, raw_news)

    else:
        raise ValueError(f"Provider sconosciuto: {provider}")


# ===========================================================================
# LAYOUT STREAMLIT
# ===========================================================================

# --- Configurazione pagina ---
st.set_page_config(
    page_title="NewsAI · Report Generator",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- CSS personalizzato ---
st.markdown("""
<style>
/* Palette: sfondo scuro inchiostro, accento ambra giornalistica */
:root {
    --ink:    #0f1117;
    --slate:  #1e2230;
    --amber:  #e8a838;
    --paper:  #f5f0e8;
    --muted:  #8b9ab0;
}

/* Header brand */
.brand-header {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    margin-bottom: 0.2rem;
}
.brand-title {
    font-family: 'Georgia', serif;
    font-size: 2rem;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.5px;
}
.brand-dot {
    color: #e8a838;
    font-size: 2rem;
}
.brand-sub {
    font-size: 0.78rem;
    color: #8b9ab0;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 1.2rem;
}

/* Etichette sidebar */
.sidebar-section-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #8b9ab0;
    margin: 1rem 0 0.3rem 0;
}

/* Badge provider attivo */
.provider-badge {
    display: inline-block;
    background: #e8a838;
    color: #0f1117;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
}

/* Area report output */
.report-container {
    border-left: 3px solid #e8a838;
    padding-left: 1.2rem;
    margin-top: 0.5rem;
}

/* Bottone genera prominente */
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #e8a838 0%, #c98a1a 100%);
    color: #0f1117;
    font-weight: 700;
    border: none;
    padding: 0.6rem 2rem;
    font-size: 1rem;
}
div.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #f0b94a 0%, #d99b2b 100%);
    box-shadow: 0 0 12px rgba(232, 168, 56, 0.4);
}
</style>
""", unsafe_allow_html=True)


# ===========================================================================
# SIDEBAR
# ===========================================================================

with st.sidebar:
    # Brand mini-header
    st.markdown("""
    <div class="brand-header">
        <span class="brand-title">News</span>
        <span class="brand-dot">AI</span>
    </div>
    <div class="brand-sub">Report Generator · Zero Persistence</div>
    """, unsafe_allow_html=True)

    st.divider()

    # -----------------------------------------------------------------------
    # IMPORTAZIONE configurazione JSON
    # -----------------------------------------------------------------------
    st.markdown('<div class="sidebar-section-label">📂 Importa Configurazione</div>', unsafe_allow_html=True)
    uploaded_config = st.file_uploader(
        label="Carica config.json",
        type=["json"],
        help="Carica un file config.json esportato in precedenza per ripristinare le impostazioni.",
        label_visibility="collapsed",
    )
    if uploaded_config is not None:
        if import_config(uploaded_config):
            st.success("✅ Configurazione importata correttamente.")

    st.divider()

    # -----------------------------------------------------------------------
    # API KEY (mascherato con type="password")
    # -----------------------------------------------------------------------
    st.markdown('<div class="sidebar-section-label">🔑 API Keys</div>', unsafe_allow_html=True)

    st.session_state.google_key = st.text_input(
        "Google API Key",
        value=st.session_state.google_key,
        type="password",
        placeholder="AIza...",
        help="Ottieni la chiave su https://aistudio.google.com/apikey",
    )
    st.session_state.openrouter_key = st.text_input(
        "OpenRouter API Key",
        value=st.session_state.openrouter_key,
        type="password",
        placeholder="sk-or-...",
        help="Ottieni la chiave su https://openrouter.ai/keys",
    )
    st.session_state.openai_key = st.text_input(
        "OpenAI API Key",
        value=st.session_state.openai_key,
        type="password",
        placeholder="sk-...",
        help="Ottieni la chiave su https://platform.openai.com/api-keys",
    )

    st.divider()

    # -----------------------------------------------------------------------
    # SELEZIONE PROVIDER e MODELLO
    # -----------------------------------------------------------------------
    st.markdown('<div class="sidebar-section-label">⚙️ Provider & Modello</div>', unsafe_allow_html=True)

    provider_index = PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0
    st.session_state.provider = st.selectbox(
        "Provider attivo",
        options=PROVIDERS,
        index=provider_index,
        help="Scegli quale provider LLM utilizzare per la generazione del report.",
    )

    # Suggerisci il catalogo modelli in base al provider selezionato
    provider = st.session_state.provider
    if provider == "Google (Gemini)":
        model_options = list(GEMINI_MODELS.keys())
        model_labels  = list(GEMINI_MODELS.values())
    elif provider == "OpenRouter":
        model_options = list(OPENROUTER_MODELS.keys())
        model_labels  = list(OPENROUTER_MODELS.values())
    else:  # OpenAI
        model_options = list(OPENAI_MODELS.keys())
        model_labels  = list(OPENAI_MODELS.values())

    # Seleziona l'indice del modello attuale nel catalogo corrente (o 0 come fallback)
    current_model = st.session_state.model_id
    if current_model in model_options:
        model_index = model_options.index(current_model)
    else:
        model_index = 0
        st.session_state.model_id = model_options[0]

    selected_label = st.selectbox(
        "Modello",
        options=model_labels,
        index=model_index,
        help="Seleziona il modello dal catalogo del provider scelto.",
    )
    # Risali all'ID dal label selezionato
    st.session_state.model_id = model_options[model_labels.index(selected_label)]

    # Override manuale dell'ID modello
    with st.expander("✏️ Sovrascrivi ID modello manualmente"):
        custom_model = st.text_input(
            "ID modello personalizzato",
            value=st.session_state.model_id,
            help="Inserisci l'esatto ID del modello se non è nel catalogo (es. meta-llama/llama-3.1-70b-instruct).",
        )
        if custom_model:
            st.session_state.model_id = custom_model

    # Riepilogo visivo della configurazione attiva
    st.markdown(f"""
    **Configurazione attiva:**
    - Provider: <span class="provider-badge">{st.session_state.provider}</span>
    - Modello: `{st.session_state.model_id}`
    """, unsafe_allow_html=True)

    st.divider()

    # -----------------------------------------------------------------------
    # ESPORTAZIONE configurazione JSON
    # -----------------------------------------------------------------------
    st.markdown('<div class="sidebar-section-label">💾 Esporta Configurazione</div>', unsafe_allow_html=True)
    st.caption("Scarica le impostazioni correnti (incluse le API Key) come file JSON da conservare localmente.")

    config_json_str = export_config()
    st.download_button(
        label="⬇️ Scarica config.json",
        data=config_json_str,
        file_name="config.json",
        mime="application/json",
        use_container_width=True,
        help="Il file conterrà le API Key in chiaro: conservalo in modo sicuro.",
    )

    st.divider()
    st.caption("⚠️ **Zero Persistence**: nessun dato è memorizzato sul server. Ricaricare la pagina cancella tutto.")


# ===========================================================================
# CORPO PRINCIPALE
# ===========================================================================

# Brand header principale
st.markdown("""
<div style="display:flex; align-items:baseline; gap:0.5rem; margin-bottom:0.1rem;">
    <span style="font-family:'Georgia',serif; font-size:2.4rem; font-weight:700; color:#fff;">News</span>
    <span style="font-family:'Georgia',serif; font-size:2.4rem; color:#e8a838;">AI</span>
</div>
<p style="color:#8b9ab0; font-size:0.82rem; letter-spacing:0.1em; text-transform:uppercase; margin-top:0;">
    Configuratore & Generatore di Report Notizie · Geopolitica & Economia
</p>
""", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# TABS principali
# ---------------------------------------------------------------------------
tab_report, tab_system = st.tabs(["📰 Generazione Report", "⚙️ Istruzioni di Sistema"])


# ===========================================================================
# TAB 1: GENERAZIONE REPORT
# ===========================================================================
with tab_report:

    col_input, col_output = st.columns([1, 1], gap="large")

    # -------------------------------------------------------------------------
    # Colonna sinistra: input notizie grezze
    # -------------------------------------------------------------------------
    with col_input:
        st.subheader("📋 Notizie Grezze")
        st.caption("Incolla qui i testi, gli appunti o i titoli delle notizie raccolti dal web.")

        st.session_state.raw_news = st.text_area(
            label="Notizie grezze",
            value=st.session_state.raw_news,
            height=420,
            placeholder=(
                "Incolla qui le notizie del giorno...\n\n"
                "Esempi:\n"
                "- Titoli di giornale copiati\n"
                "- Riassunti da feed RSS\n"
                "- Note personali su eventi\n"
                "- Dati di mercato dal web\n"
                "- Qualsiasi testo grezzo"
            ),
            label_visibility="collapsed",
        )

        char_count = len(st.session_state.raw_news)
        word_count = len(st.session_state.raw_news.split()) if st.session_state.raw_news.strip() else 0
        st.caption(f"📝 {char_count:,} caratteri · {word_count:,} parole")

        # Pulsante GENERA prominente
        st.markdown("####")
        generate_clicked = st.button(
            "🚀 Genera Report",
            type="primary",
            use_container_width=True,
            help=f"Invia le notizie a {st.session_state.provider} · {st.session_state.model_id}",
        )

        if generate_clicked:
            with st.spinner(f"⏳ Elaborazione con **{st.session_state.provider}** · `{st.session_state.model_id}`…"):
                try:
                    result = generate_report(
                        provider=st.session_state.provider,
                        model_id=st.session_state.model_id,
                        raw_news=st.session_state.raw_news,
                    )
                    st.session_state.report_output = result
                    st.success("✅ Report generato con successo!")

                except ValueError as ve:
                    # Errori di validazione (chiave mancante, input vuoto ecc.)
                    st.error(f"⚠️ {ve}")

                except requests.exceptions.Timeout:
                    st.error("⏱️ Timeout: il provider ha impiegato troppo tempo a rispondere. Riprova.")

                except requests.exceptions.HTTPError as he:
                    status = he.response.status_code if he.response is not None else "?"
                    if status == 401:
                        st.error("🔐 Errore 401 – API Key non valida o scaduta. Controlla la chiave nella sidebar.")
                    elif status == 429:
                        st.error("🚦 Errore 429 – Rate limit superato. Attendi qualche minuto e riprova.")
                    elif status == 402:
                        st.error("💳 Errore 402 – Crediti insufficienti sul tuo account provider.")
                    else:
                        st.error(f"❌ Errore HTTP {status}: {he}")

                except Exception as e:
                    st.error(f"❌ Errore imprevisto: {e}")

    # -------------------------------------------------------------------------
    # Colonna destra: output report
    # -------------------------------------------------------------------------
    with col_output:
        st.subheader("📊 Report Generato")

        if st.session_state.report_output:
            # Pulsante copia/download del report
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    label="⬇️ Scarica .md",
                    data=st.session_state.report_output,
                    file_name="report_notizie.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with col_dl2:
                if st.button("🗑️ Cancella report", use_container_width=True):
                    st.session_state.report_output = ""
                    st.rerun()

            st.divider()
            # Render Markdown del report
            st.markdown(
                f'<div class="report-container">{st.session_state.report_output}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Il report apparirà qui dopo aver cliccato **🚀 Genera Report**.\n\n"
                "Assicurati di aver inserito:\n"
                "1. L'API Key del provider selezionato nella sidebar\n"
                "2. Almeno alcune notizie nel campo a sinistra",
                icon="💡",
            )


# ===========================================================================
# TAB 2: ISTRUZIONI DI SISTEMA
# ===========================================================================
with tab_system:
    st.subheader("⚙️ System Prompt Interno")
    st.caption(
        "Questo è il prompt di sistema che viene inviato all'IA ad ogni richiesta. "
        "Definisce la struttura e il tono del report generato. **Non è modificabile dall'interfaccia** "
        "(per modificarlo è necessario editare il file `app.py`)."
    )

    st.divider()

    # Visualizzazione in blocco di codice leggibile
    with st.expander("📜 Visualizza System Prompt completo", expanded=True):
        st.markdown(SYSTEM_PROMPT)

    st.divider()

    # Metadati sulla struttura del report
    st.subheader("📐 Struttura del Report Attesa")
    cols = st.columns(3)
    sections = [
        ("🇪🇺", "Notizie Europee", "UE, istituzioni, paesi membri, dinamiche intra-europee"),
        ("🌍", "Notizie Mondiali", "Geopolitica globale: Asia, Americhe, Africa, Medio Oriente"),
        ("🏛️", "Politica", "Governi, partiti, riforme normative, elezioni"),
        ("🏭", "Economia Tedesca", "PIL, inflazione, industria, automotive, politica fiscale"),
        ("📊", "Mercati Finanziari", "Tabella con DAX, Euro Stoxx, EUR/USD, Bund, Petrolio"),
        ("📌", "Sintesi & Outlook", "Paragrafo finale con tendenze chiave della giornata"),
    ]
    for i, (icon, title, desc) in enumerate(sections):
        with cols[i % 3]:
            st.markdown(f"**{icon} {title}**")
            st.caption(desc)
            st.markdown("")

    st.divider()
    st.subheader("📦 Dipendenze Python Consigliate")
    st.code(
        "# requirements.txt\n"
        "streamlit>=1.35.0\n"
        "requests>=2.31.0\n"
        "openai>=1.30.0            # Per provider OpenAI\n"
        "google-generativeai>=0.7  # Per provider Google Gemini\n",
        language="text",
    )
    st.caption(
        "Le librerie `openai` e `google-generativeai` sono opzionali: "
        "se non installate, l'app usa automaticamente richieste HTTP dirette come fallback."
    )
