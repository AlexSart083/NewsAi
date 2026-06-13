"""
NewsAI - Configuratore e Generatore di Report Notizie
======================================================
Politica ZERO-PERSISTENCE: nessun DB, nessun log lato server.
API Key solo in st.session_state (memoria volatile).

Flusso:
  1. L'utente inserisce le API Key (NewsAPI + provider LLM) nella sidebar
  2. Clicca "🔍 Cerca Notizie" → l'app interroga NewsAPI per 6 categorie tematiche
  3. Clicca "🚀 Genera Report" → le notizie raccolte vengono inviate all'LLM scelto
  4. Il report strutturato in Markdown viene mostrato e scaricabile

Esegui con: streamlit run app.py
"""

import json
import time
import streamlit as st
import requests
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Dipendenze opzionali (fallback HTTP diretto se non installate)
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
    "gemini-2.5-flash":      "Gemini 2.5 Flash (Stable Workhorse with Thinking)",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite (High Throughput, Free Tier)",
    "gemini-2.5-pro":        "Gemini 2.5 Pro (Complex Reasoning, Rate-Limited Free)",
    "gemini-3.5-flash":      "Gemini 3.5 Flash (Latest Fast, Near-Pro Intelligence)",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite (Highest Efficiency, Low Latency)",
    "gemma-4-12b-unified":   "Gemma 4 12B (Local Multimodal, 16GB VRAM)",
    "gemma-4-26b-moe":       "Gemma 4 26B MoE (High-Performance Open-Weights)",
    "gemma-4-e4b-edge":      "Gemma 4 E4B (Edge Optimized, Ultra-Lightweight 4.5B)",
}

OPENROUTER_MODELS = {
    "openrouter/free":             "OpenRouter Free (Auto-Routing - Free Tier)",
    "deepseek/deepseek-v4-flash":  "DeepSeek V4 Flash (Ultra-Fast)",
    "deepseek/deepseek-v4-pro":    "DeepSeek V4 Pro (Deep Reasoning & Coding)",
    "meta-llama/llama-4-maverick": "Llama 4 Maverick (Next-Gen Intelligence)",
    "xiaomi/mimo-v2.5":            "Xiaomi Mimo v2.5 (On-Device & Efficient)",
}

OPENAI_MODELS = {
    "gpt-4o":        "GPT-4o (Flagship Multimodal)",
    "gpt-4o-mini":   "GPT-4o Mini (Fast & Cost-Effective)",
    "gpt-4-turbo":   "GPT-4 Turbo (High Context)",
    "gpt-3.5-turbo": "GPT-3.5 Turbo (Legacy Budget)",
    "o1-preview":    "o1 Preview (Advanced Reasoning)",
    "o1-mini":       "o1 Mini (Compact Reasoning)",
}

PROVIDERS = ["Google (Gemini)", "OpenRouter", "OpenAI"]

# ---------------------------------------------------------------------------
# Definizione delle 6 categorie di ricerca su NewsAPI
# Ogni categoria ha: nome visualizzato, endpoint, e parametri di query
# ---------------------------------------------------------------------------
NEWS_CATEGORIES = [
    {
        "id":       "europe",
        "label":    "🇪🇺 Notizie Europee",
        "endpoint": "everything",
        "params": {
            "q":        "Europe OR European Union OR EU OR Eurozone OR Brussels",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 15,
        },
    },
    {
        "id":       "germany",
        "label":    "🏭 Economia Tedesca",
        "endpoint": "everything",
        "params": {
            "q":        "Germany economy OR Germany Wirtschaft OR Bundesbank OR DAX OR German industry OR Scholz OR Merz",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 12,
        },
    },
    {
        "id":       "usa",
        "label":    "🇺🇸 USA",
        "endpoint": "top-headlines",
        "params": {
            "country":  "us",
            "category": "general",
            "pageSize": 12,
        },
    },
    {
        "id":       "asia",
        "label":    "🌏 Asia",
        "endpoint": "everything",
        "params": {
            "q":        "China OR Japan OR India OR South Korea OR Taiwan OR ASEAN OR Xi Jinping OR Modi",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 12,
        },
    },
    {
        "id":       "mideast",
        "label":    "🕌 Medio Oriente",
        "endpoint": "everything",
        "params": {
            "q":        "Middle East OR Israel OR Iran OR Gaza OR Palestine OR Lebanon OR Saudi Arabia OR Syria OR Yemen",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 12,
        },
    },
    {
        "id":       "markets",
        "label":    "📊 Mercati Finanziari",
        "endpoint": "everything",
        "params": {
            "q":        "DAX stock market OR EUR/USD OR Federal Reserve OR ECB OR interest rates OR inflation OR oil price Brent",
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 12,
        },
    },
]


# ===========================================================================
# SYSTEM PROMPT per la generazione del report geopolitico/economico
# ===========================================================================

SYSTEM_PROMPT = """Sei un analista geopolitico ed economico senior specializzato in Europa e mercati finanziari globali.
Ricevi un insieme strutturato di notizie grezze recuperate automaticamente da NewsAPI, organizzate per categoria.
Il tuo compito è elaborarle e produrre un **Report Notizie Strutturato** professionale in italiano.

## Struttura obbligatoria del report

### 🇪🇺 Notizie Europee
Sintetizza i principali sviluppi riguardanti l'Unione Europea, le sue istituzioni, i paesi membri e le dinamiche intra-europee.
Organizza per paese o per tema. Usa elenchi puntati chiari con **soggetto** in grassetto.

### 🌍 Notizie Mondiali
Riassumi i principali eventi geopolitici globali per area:
- 🇺🇸 **USA**: politica interna, economia, diplomazia
- 🌏 **Asia**: Cina, Giappone, India, Corea del Sud, Taiwan, ASEAN
- 🕌 **Medio Oriente**: conflitti, diplomazia, energia

### 🏛️ Politica
Analizza i principali sviluppi politici trasversali: governi, riforme normative, elezioni imminenti, accordi internazionali.

### 🏭 Economia Tedesca
Sezione dedicata alla Germania. Includi:
- Dati macro se menzionati (PIL, inflazione, occupazione)
- Settore industriale, automotive, energia
- Politica fiscale e commerciale del governo Scholz/Merz
- Impatto delle dinamiche UE sull'export tedesco

### 📊 Mercati Finanziari
Inserisci una tabella Markdown con tutti i dati di mercato estratti dalle notizie.

| Asset / Indice | Ultimo Valore | Variazione % | Nota Contestuale |
|---|---|---|---|
| DAX 40 | — | — | |
| Euro Stoxx 50 | — | — | |
| EUR/USD | — | — | |
| Bund 10Y Yield | — | — | |
| Petrolio Brent | — | — | |
| Fed Funds Rate | — | — | |
| BCE Tasso Deposito | — | — | |

Compila solo le righe per cui hai dati effettivi dalle notizie. Lascia "—" dove non disponibile.
Aggiungi un breve commento sulle tendenze dei mercati basato sulle notizie ricevute.

---

### 📌 Sintesi e Outlook
Chiudi il report con 3-5 bullet point che evidenziano:
- Le tendenze geopolitiche dominanti della giornata
- I rischi principali per i mercati europei nel breve periodo
- Un evento da monitorare nelle prossime 24-48 ore

---

## Norme redazionali
- Scrivi **sempre in italiano**, anche se le notizie di input sono in inglese
- Tono neutro, professionale, analitico — mai sensazionalistico
- **Grassetto** per soggetti chiave (paesi, istituzioni, leader politici)
- *Corsivo* per termini tecnici o citazioni dirette tradotte
- Formatta sempre in Markdown standard, pronto per il rendering
- Se una categoria non ha notizie rilevanti, indicalo brevemente e prosegui
"""


# ===========================================================================
# INIZIALIZZAZIONE SESSION STATE (Zero-Persistence: solo RAM)
# ===========================================================================

def init_session_state():
    """Inizializza le variabili di sessione se non già presenti."""
    defaults = {
        # --- API Keys ---
        "newsapi_key":      "",
        "openrouter_key":   "",
        "openai_key":       "",
        "google_key":       "",
        # --- Configurazione LLM ---
        "provider":         PROVIDERS[0],
        "model_id":         "gemini-2.5-flash",
        # --- Dati operativi ---
        "fetched_news":     {},      # dict: category_id -> list of article dicts
        "fetch_timestamp":  None,    # datetime dell'ultimo fetch
        "raw_news_text":    "",      # testo aggregato pronto per l'LLM
        "report_output":    "",      # testo del report generato
        "fetch_errors":     [],      # lista di errori durante il fetch
        # --- Opzioni ricerca ---
        "news_days_back":   1,       # quanti giorni indietro cercare
        "selected_cats":    [c["id"] for c in NEWS_CATEGORIES],  # categorie attive
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
        "newsapi_key":    st.session_state.newsapi_key,
        "openrouter_key": st.session_state.openrouter_key,
        "openai_key":     st.session_state.openai_key,
        "google_key":     st.session_state.google_key,
        "news_days_back": st.session_state.news_days_back,
        "selected_cats":  st.session_state.selected_cats,
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def import_config(uploaded_file) -> bool:
    """Legge il file JSON e ripopola st.session_state."""
    try:
        config = json.loads(uploaded_file.read())
        st.session_state.provider       = config.get("provider",       st.session_state.provider)
        st.session_state.model_id       = config.get("model_id",       st.session_state.model_id)
        st.session_state.newsapi_key    = config.get("newsapi_key",    "")
        st.session_state.openrouter_key = config.get("openrouter_key", "")
        st.session_state.openai_key     = config.get("openai_key",     "")
        st.session_state.google_key     = config.get("google_key",     "")
        st.session_state.news_days_back = config.get("news_days_back", 1)
        st.session_state.selected_cats  = config.get("selected_cats",  [c["id"] for c in NEWS_CATEGORIES])
        return True
    except Exception as e:
        st.sidebar.error(f"❌ Errore nel file JSON: {e}")
        return False


# ===========================================================================
# NEWSAPI: Recupero autonomo delle notizie
# ===========================================================================

NEWSAPI_BASE = "https://newsapi.org/v2"

def fetch_category(api_key: str, category: dict, from_date: str) -> list[dict]:
    """
    Recupera gli articoli per una singola categoria da NewsAPI.
    Restituisce una lista di dict con i campi normalizzati.
    """
    endpoint = category["endpoint"]
    params   = dict(category["params"])  # copia per non modificare la costante
    params["apiKey"] = api_key

    # Aggiunge il filtro temporale solo per l'endpoint /everything
    if endpoint == "everything":
        params["from"] = from_date

    url = f"{NEWSAPI_BASE}/{endpoint}"
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "ok":
        raise ValueError(f"NewsAPI error: {data.get('message', 'unknown error')}")

    articles = []
    for art in data.get("articles", []):
        # Filtra articoli senza titolo o con titolo "[Removed]"
        title = (art.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue
        articles.append({
            "title":       title,
            "source":      art.get("source", {}).get("name", "Unknown"),
            "description": (art.get("description") or "").strip(),
            "url":         art.get("url", ""),
            "publishedAt": art.get("publishedAt", ""),
        })
    return articles


def fetch_all_news(api_key: str, selected_cat_ids: list, days_back: int) -> tuple[dict, list]:
    """
    Interroga NewsAPI per tutte le categorie selezionate.
    Ritorna (fetched_news_dict, errors_list).
    """
    from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    results   = {}
    errors    = []

    active_cats = [c for c in NEWS_CATEGORIES if c["id"] in selected_cat_ids]

    for cat in active_cats:
        try:
            articles = fetch_category(api_key, cat, from_date)
            results[cat["id"]] = articles
            # Piccola pausa per non saturare il rate limit del piano free (100 req/giorno)
            time.sleep(0.3)
        except requests.exceptions.HTTPError as he:
            status = he.response.status_code if he.response is not None else "?"
            if status == 401:
                errors.append(f"{cat['label']}: NewsAPI Key non valida (401)")
            elif status == 429:
                errors.append(f"{cat['label']}: Rate limit raggiunto (429)")
            else:
                errors.append(f"{cat['label']}: Errore HTTP {status}")
        except Exception as e:
            errors.append(f"{cat['label']}: {str(e)}")

    return results, errors


def format_news_for_llm(fetched_news: dict) -> str:
    """
    Formatta il dizionario di notizie in un testo strutturato
    pronto da inviare all'LLM come User Prompt.
    """
    lines = [
        f"# Notizie Raccolte Automaticamente — {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC",
        "",
    ]
    cat_map = {c["id"]: c["label"] for c in NEWS_CATEGORIES}

    for cat_id, articles in fetched_news.items():
        label = cat_map.get(cat_id, cat_id)
        lines.append(f"## {label}")
        if not articles:
            lines.append("*Nessun articolo disponibile per questa categoria.*")
        else:
            for i, art in enumerate(articles, 1):
                lines.append(f"{i}. **{art['title']}** [{art['source']}]")
                if art["description"]:
                    lines.append(f"   {art['description']}")
                if art["publishedAt"]:
                    lines.append(f"   _(pubblicato: {art['publishedAt'][:10]})_")
        lines.append("")

    return "\n".join(lines)


# ===========================================================================
# LOGICA DI CHIAMATA LLM (tre provider)
# ===========================================================================

def call_openrouter(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://newsai.local",
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
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_openai(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    if OPENAI_AVAILABLE:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def call_google(api_key: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    if GOOGLE_AVAILABLE:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_id,
            system_instruction=system_prompt,
        )
        resp = model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.3),
        )
        return resp.text
    else:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:generateContent?key={api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents":           [{"parts": [{"text": user_prompt}]}],
            "generationConfig":   {"temperature": 0.3},
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def generate_report(provider: str, model_id: str, raw_news_text: str) -> str:
    """Dispatcher: sceglie il provider e avvia la chiamata LLM."""
    if not raw_news_text.strip():
        raise ValueError("Nessuna notizia disponibile. Esegui prima la ricerca con il pulsante 🔍 Cerca Notizie.")

    if provider == "OpenRouter":
        key = st.session_state.openrouter_key
        if not key:
            raise ValueError("OpenRouter API Key mancante. Inseriscila nella barra laterale.")
        return call_openrouter(key, model_id, SYSTEM_PROMPT, raw_news_text)

    elif provider == "OpenAI":
        key = st.session_state.openai_key
        if not key:
            raise ValueError("OpenAI API Key mancante. Inseriscila nella barra laterale.")
        return call_openai(key, model_id, SYSTEM_PROMPT, raw_news_text)

    elif provider == "Google (Gemini)":
        key = st.session_state.google_key
        if not key:
            raise ValueError("Google API Key mancante. Inseriscila nella barra laterale.")
        return call_google(key, model_id, SYSTEM_PROMPT, raw_news_text)

    else:
        raise ValueError(f"Provider sconosciuto: {provider}")


# ===========================================================================
# LAYOUT STREAMLIT
# ===========================================================================

st.set_page_config(
    page_title="NewsAI · Report Generator",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.brand-header { display:flex; align-items:baseline; gap:0.4rem; margin-bottom:0.1rem; }
.brand-title  { font-family:'Georgia',serif; font-size:2rem; font-weight:700; color:#fff; letter-spacing:-0.5px; }
.brand-dot    { color:#e8a838; font-size:2rem; }
.brand-sub    { font-size:0.75rem; color:#8b9ab0; letter-spacing:0.12em; text-transform:uppercase; margin-bottom:1rem; }
.sidebar-label{ font-size:0.67rem; font-weight:600; letter-spacing:0.1em; text-transform:uppercase; color:#8b9ab0; margin:1rem 0 0.3rem 0; }
.provider-badge{ display:inline-block; background:#e8a838; color:#0f1117; border-radius:4px; padding:2px 8px; font-size:0.7rem; font-weight:700; }
.report-container{ border-left:3px solid #e8a838; padding-left:1.2rem; margin-top:0.5rem; }
.news-card{ background:#1e2230; border-radius:8px; padding:0.7rem 1rem; margin-bottom:0.5rem; border-left:3px solid #e8a838; }
.news-card-title{ font-weight:600; font-size:0.9rem; color:#ffffff; line-height:1.3; }
.news-card-meta { font-size:0.72rem; color:#8b9ab0; margin-top:0.2rem; }
.news-card-desc { font-size:0.8rem; color:#c5cdd8; margin-top:0.3rem; line-height:1.4; }
.stats-row{ display:flex; gap:1.5rem; margin:0.5rem 0 1rem 0; }
.stat-box{ background:#1e2230; border-radius:8px; padding:0.6rem 1.2rem; text-align:center; min-width:90px; }
.stat-num{ font-size:1.5rem; font-weight:700; color:#e8a838; font-family:'Georgia',serif; }
.stat-lbl{ font-size:0.67rem; color:#8b9ab0; text-transform:uppercase; letter-spacing:0.08em; }
div.stButton > button[kind="primary"]{
    background:linear-gradient(135deg,#e8a838 0%,#c98a1a 100%);
    color:#0f1117; font-weight:700; border:none; font-size:1rem;
}
div.stButton > button[kind="primary"]:hover{
    background:linear-gradient(135deg,#f0b94a 0%,#d99b2b 100%);
    box-shadow:0 0 12px rgba(232,168,56,0.4);
}
</style>
""", unsafe_allow_html=True)


# ===========================================================================
# SIDEBAR
# ===========================================================================

with st.sidebar:
    st.markdown("""
    <div class="brand-header">
        <span class="brand-title">News</span><span class="brand-dot">AI</span>
    </div>
    <div class="brand-sub">Autonomous Report Generator · Zero Persistence</div>
    """, unsafe_allow_html=True)

    st.divider()

    # --- Import config ---
    st.markdown('<div class="sidebar-label">📂 Importa Configurazione</div>', unsafe_allow_html=True)
    uploaded_config = st.file_uploader(
        "Carica config.json", type=["json"], label_visibility="collapsed",
        help="Ripristina le impostazioni da un file config.json precedentemente esportato.",
    )
    if uploaded_config is not None:
        if import_config(uploaded_config):
            st.success("✅ Configurazione importata.")

    st.divider()

    # --- API Keys ---
    st.markdown('<div class="sidebar-label">🔑 API Keys</div>', unsafe_allow_html=True)

    st.session_state.newsapi_key = st.text_input(
        "NewsAPI Key 📰",
        value=st.session_state.newsapi_key,
        type="password",
        placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        help="Chiave gratuita su https://newsapi.org — 100 richieste/giorno sul piano free.",
    )
    st.session_state.google_key = st.text_input(
        "Google (Gemini) API Key",
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

    # --- Provider & Modello ---
    st.markdown('<div class="sidebar-label">⚙️ Provider LLM & Modello</div>', unsafe_allow_html=True)

    provider_idx = PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0
    st.session_state.provider = st.selectbox("Provider", options=PROVIDERS, index=provider_idx)

    provider = st.session_state.provider
    if provider == "Google (Gemini)":
        model_options = list(GEMINI_MODELS.keys())
        model_labels  = list(GEMINI_MODELS.values())
    elif provider == "OpenRouter":
        model_options = list(OPENROUTER_MODELS.keys())
        model_labels  = list(OPENROUTER_MODELS.values())
    else:
        model_options = list(OPENAI_MODELS.keys())
        model_labels  = list(OPENAI_MODELS.values())

    cur = st.session_state.model_id
    midx = model_options.index(cur) if cur in model_options else 0
    sel_label = st.selectbox("Modello", options=model_labels, index=midx)
    st.session_state.model_id = model_options[model_labels.index(sel_label)]

    with st.expander("✏️ ID modello personalizzato"):
        custom = st.text_input("Sovrascrivi model ID", value=st.session_state.model_id)
        if custom:
            st.session_state.model_id = custom

    st.divider()

    # --- Opzioni Ricerca Notizie ---
    st.markdown('<div class="sidebar-label">🔍 Opzioni Ricerca Notizie</div>', unsafe_allow_html=True)

    st.session_state.news_days_back = st.slider(
        "Notizie degli ultimi N giorni",
        min_value=1, max_value=7,
        value=st.session_state.news_days_back,
        help="NewsAPI piano free supporta fino a 30 giorni, ma più giorni = più articoli = più token LLM.",
    )

    cat_labels = {c["id"]: c["label"] for c in NEWS_CATEGORIES}
    st.caption("Categorie da includere:")
    selected_cats = []
    for cat in NEWS_CATEGORIES:
        checked = cat["id"] in st.session_state.selected_cats
        if st.checkbox(cat["label"], value=checked, key=f"cat_{cat['id']}"):
            selected_cats.append(cat["id"])
    st.session_state.selected_cats = selected_cats

    st.divider()

    # --- Export config ---
    st.markdown('<div class="sidebar-label">💾 Esporta Configurazione</div>', unsafe_allow_html=True)
    st.caption("Salva tutte le impostazioni e le API Key in locale.")
    st.download_button(
        label="⬇️ Scarica config.json",
        data=export_config(),
        file_name="config.json",
        mime="application/json",
        use_container_width=True,
    )

    st.divider()
    st.caption("⚠️ **Zero Persistence**: ricaricare la pagina cancella tutte le chiavi.")


# ===========================================================================
# CORPO PRINCIPALE
# ===========================================================================

st.markdown("""
<div style="display:flex; align-items:baseline; gap:0.5rem; margin-bottom:0.1rem;">
    <span style="font-family:'Georgia',serif; font-size:2.6rem; font-weight:700; color:#fff;">News</span>
    <span style="font-family:'Georgia',serif; font-size:2.6rem; color:#e8a838;">AI</span>
</div>
<p style="color:#8b9ab0; font-size:0.8rem; letter-spacing:0.1em; text-transform:uppercase; margin-top:0;">
    Generatore Autonomo di Report Geopolitici & Economici
</p>
""", unsafe_allow_html=True)

st.divider()

tab_main, tab_preview, tab_system = st.tabs([
    "🚀 Cerca & Genera Report",
    "📋 Anteprima Notizie Raccolte",
    "⚙️ Istruzioni di Sistema",
])


# ===========================================================================
# TAB 1: CERCA & GENERA REPORT
# ===========================================================================

with tab_main:

    # -------------------------------------------------------------------------
    # Riga status e pulsanti azione
    # -------------------------------------------------------------------------
    col_fetch, col_gen, col_status = st.columns([1, 1, 2])

    with col_fetch:
        fetch_clicked = st.button(
            "🔍 Cerca Notizie",
            use_container_width=True,
            type="secondary",
            disabled=not st.session_state.newsapi_key,
            help="Interroga NewsAPI per tutte le categorie selezionate.",
        )
        if not st.session_state.newsapi_key:
            st.caption("⚠️ Inserisci la NewsAPI Key nella sidebar.")

    with col_gen:
        gen_clicked = st.button(
            "🚀 Genera Report",
            use_container_width=True,
            type="primary",
            disabled=not st.session_state.raw_news_text,
            help="Invia le notizie raccolte all'LLM per generare il report.",
        )
        if not st.session_state.raw_news_text:
            st.caption("⚠️ Prima esegui la ricerca notizie.")

    with col_status:
        if st.session_state.fetch_timestamp:
            ts = st.session_state.fetch_timestamp.strftime("%d/%m/%Y %H:%M")
            total = sum(len(v) for v in st.session_state.fetched_news.values())
            cats_done = len(st.session_state.fetched_news)
            st.markdown(f"""
            <div class="stats-row">
                <div class="stat-box"><div class="stat-num">{total}</div><div class="stat-lbl">Articoli</div></div>
                <div class="stat-box"><div class="stat-num">{cats_done}</div><div class="stat-lbl">Categorie</div></div>
                <div class="stat-box"><div class="stat-num" style="font-size:1rem;padding-top:0.3rem">{ts}</div><div class="stat-lbl">Ultimo fetch</div></div>
            </div>
            """, unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # AZIONE: Fetch notizie
    # -------------------------------------------------------------------------
    if fetch_clicked:
        if not st.session_state.newsapi_key:
            st.error("❌ NewsAPI Key mancante. Inseriscila nella barra laterale.")
        elif not st.session_state.selected_cats:
            st.error("❌ Seleziona almeno una categoria di notizie nella sidebar.")
        else:
            active_labels = [c["label"] for c in NEWS_CATEGORIES if c["id"] in st.session_state.selected_cats]
            progress_bar = st.progress(0, text="Inizializzazione ricerca...")
            n = len(active_labels)

            fetched, errors = {}, []
            from_date = (datetime.utcnow() - timedelta(days=st.session_state.news_days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

            active_cats = [c for c in NEWS_CATEGORIES if c["id"] in st.session_state.selected_cats]
            for i, cat in enumerate(active_cats):
                progress_bar.progress(
                    int((i / n) * 100),
                    text=f"Recupero {cat['label']} ({i+1}/{n})…"
                )
                try:
                    articles = fetch_category(st.session_state.newsapi_key, cat, from_date)
                    fetched[cat["id"]] = articles
                    time.sleep(0.3)
                except requests.exceptions.HTTPError as he:
                    status = he.response.status_code if he.response is not None else "?"
                    if status == 401:
                        errors.append(f"{cat['label']}: NewsAPI Key non valida (401)")
                        break  # chiave invalida: inutile continuare
                    elif status == 429:
                        errors.append(f"{cat['label']}: Rate limit raggiunto (429) — attendi qualche minuto")
                    else:
                        errors.append(f"{cat['label']}: Errore HTTP {status}")
                except Exception as e:
                    errors.append(f"{cat['label']}: {str(e)}")

            progress_bar.progress(100, text="Completato!")
            time.sleep(0.5)
            progress_bar.empty()

            st.session_state.fetched_news    = fetched
            st.session_state.fetch_errors    = errors
            st.session_state.fetch_timestamp = datetime.utcnow()
            st.session_state.raw_news_text   = format_news_for_llm(fetched) if fetched else ""

            total_art = sum(len(v) for v in fetched.values())
            if fetched:
                st.success(f"✅ Recuperati **{total_art} articoli** in **{len(fetched)} categorie**.")
            if errors:
                for err in errors:
                    st.warning(f"⚠️ {err}")
            st.rerun()

    # -------------------------------------------------------------------------
    # AZIONE: Genera report LLM
    # -------------------------------------------------------------------------
    if gen_clicked:
        with st.spinner(f"⏳ Elaborazione con **{st.session_state.provider}** · `{st.session_state.model_id}`…"):
            try:
                result = generate_report(
                    provider=st.session_state.provider,
                    model_id=st.session_state.model_id,
                    raw_news_text=st.session_state.raw_news_text,
                )
                st.session_state.report_output = result
                st.success("✅ Report generato con successo!")
            except ValueError as ve:
                st.error(f"⚠️ {ve}")
            except requests.exceptions.Timeout:
                st.error("⏱️ Timeout: il provider LLM non ha risposto in tempo. Riprova.")
            except requests.exceptions.HTTPError as he:
                s = he.response.status_code if he.response is not None else "?"
                msgs = {
                    401: "🔐 API Key LLM non valida o scaduta (401). Controlla nella sidebar.",
                    429: "🚦 Rate limit LLM superato (429). Attendi qualche minuto.",
                    402: "💳 Crediti insufficienti sul provider LLM (402).",
                }
                st.error(msgs.get(s, f"❌ Errore HTTP {s}: {he}"))
            except Exception as e:
                st.error(f"❌ Errore imprevisto: {e}")

    st.divider()

    # -------------------------------------------------------------------------
    # REPORT OUTPUT
    # -------------------------------------------------------------------------
    if st.session_state.report_output:
        col_dl1, col_dl2, col_dl3 = st.columns([1, 1, 4])
        with col_dl1:
            st.download_button(
                "⬇️ Scarica .md",
                data=st.session_state.report_output,
                file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl2:
            if st.button("🗑️ Cancella", use_container_width=True):
                st.session_state.report_output = ""
                st.rerun()

        st.markdown(
            f'<div class="report-container">{st.session_state.report_output}</div>',
            unsafe_allow_html=True,
        )
    else:
        # Stato iniziale / guida
        st.markdown("""
        ### Come usare NewsAI

        **Passo 1** — Inserisci nella sidebar:
        - La tua **NewsAPI Key** (gratuita su [newsapi.org](https://newsapi.org))
        - La **API Key** del provider LLM che vuoi usare (Google, OpenRouter o OpenAI)

        **Passo 2** — Configura la ricerca:
        - Scegli quanti giorni di notizie recuperare (default: ultime 24h)
        - Seleziona le categorie geografiche che ti interessano

        **Passo 3** — Clicca **🔍 Cerca Notizie**
        L'app interroga autonomamente NewsAPI per ogni categoria selezionata.

        **Passo 4** — Clicca **🚀 Genera Report**
        Le notizie vengono inviate all'LLM scelto, che produce un report strutturato in italiano con sezioni per Europa, USA, Asia, Medio Oriente, economia tedesca e mercati finanziari.
        """)


# ===========================================================================
# TAB 2: ANTEPRIMA NOTIZIE RACCOLTE
# ===========================================================================

with tab_preview:
    st.subheader("📋 Anteprima Notizie Raccolte")

    if not st.session_state.fetched_news:
        st.info("Nessuna notizia disponibile. Esegui prima **🔍 Cerca Notizie** dal tab principale.", icon="ℹ️")
    else:
        ts = st.session_state.fetch_timestamp.strftime("%d/%m/%Y alle %H:%M UTC")
        st.caption(f"Ultimo aggiornamento: {ts}")

        cat_map = {c["id"]: c["label"] for c in NEWS_CATEGORIES}

        for cat_id, articles in st.session_state.fetched_news.items():
            label = cat_map.get(cat_id, cat_id)
            with st.expander(f"{label} — {len(articles)} articoli", expanded=False):
                if not articles:
                    st.caption("Nessun articolo recuperato.")
                else:
                    for art in articles:
                        pub = art["publishedAt"][:10] if art["publishedAt"] else ""
                        st.markdown(f"""
                        <div class="news-card">
                            <div class="news-card-title">{art['title']}</div>
                            <div class="news-card-meta">{art['source']} · {pub}</div>
                            {"<div class='news-card-desc'>" + art['description'] + "</div>" if art['description'] else ""}
                        </div>
                        """, unsafe_allow_html=True)

        st.divider()
        st.subheader("📄 Testo Grezzo inviato all'LLM")
        with st.expander("Visualizza testo completo", expanded=False):
            st.text(st.session_state.raw_news_text)
        st.caption(f"Dimensione: {len(st.session_state.raw_news_text):,} caratteri")


# ===========================================================================
# TAB 3: ISTRUZIONI DI SISTEMA
# ===========================================================================

with tab_system:
    st.subheader("⚙️ System Prompt Interno")
    st.caption(
        "Questo prompt viene inviato all'LLM come istruzione di sistema ad ogni generazione. "
        "Per modificarlo, edita la costante `SYSTEM_PROMPT` nel file `app.py`."
    )
    st.divider()

    with st.expander("📜 Visualizza System Prompt completo", expanded=True):
        st.markdown(SYSTEM_PROMPT)

    st.divider()
    st.subheader("🔍 Query NewsAPI per Categoria")

    for cat in NEWS_CATEGORIES:
        with st.expander(f"{cat['label']}", expanded=False):
            st.markdown(f"**Endpoint:** `/v2/{cat['endpoint']}`")
            params_display = {k: v for k, v in cat["params"].items()}
            st.json(params_display)

    st.divider()
    st.subheader("📦 Dipendenze Python")
    st.code(
        "# requirements.txt\n"
        "streamlit>=1.35.0\n"
        "requests>=2.31.0\n"
        "openai>=1.30.0             # opzionale: provider OpenAI\n"
        "google-generativeai>=0.7   # opzionale: provider Google Gemini\n",
        language="text",
    )
    st.caption(
        "Le librerie `openai` e `google-generativeai` sono opzionali: "
        "l'app usa HTTP diretto come fallback se non installate."
    )
