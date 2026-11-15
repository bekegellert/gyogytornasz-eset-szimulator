import os
import json
import streamlit as st
from google import genai
from google.genai import types

# Oldal beállításai
st.set_page_config(page_title="Gyógytornász Klinikai Eset-Szimulátor", page_icon="🩺", layout="wide")

st.title("🩺 Gyógytornász Klinikai Eset-Szimulátor")
st.markdown("Válassz egy esetet a helyi adatbázisból, válaszolj lépésről lépésre (akár diktálással), majd kapj átfogó értékelést!")

# Konstansok
DB_FOLDER = "teszt_adatbazis"
QUESTIONS = [
    "1. Mit kérdeznél a betegtől az anamnézis felvétel során?",
    "2. Mit vizsgálnál az inspekció során?",
    "3. Mit vizsgálnál a palpáció során?",
    "4. Milyen funkcionális méréseket végeznél?",
    "5. Milyen speciális teszteket végeznél el a betegen?",
    "6. Milyen rövidtávú kezelési célt és tervet állítanál fel?",
    "7. Milyen hosszútávú kezelési célt és tervet állítanál fel?"
]

# Segédfüggvény a Gemini API híváshoz
def generate_with_fallback(client, contents):
    models_to_try = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
    last_exception = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents
            )
            return response.text
        except Exception as e:
            last_exception = e
            continue
    raise last_exception

# --- ADATBÁZIS KEZELŐ FÜGGVÉNYEK ---
def get_saved_cases():
    if not os.path.exists(DB_FOLDER):
        return []
    files = sorted([f for f in os.listdir(DB_FOLDER) if f.endswith(".json")])
    cases = []
    for f in files:
        filepath = os.path.join(DB_FOLDER, f)
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                data = json.load(file)
                data["filename"] = f
                cases.append(data)
        except Exception:
            pass
    return cases

def generate_single_case(client, category, difficulty, custom_topic=""):
    topic_instruction = f"Konkrét téma/kórkép: {custom_topic}" if custom_topic.strip() else "Válassz egy tipikus, élethű kórképet a szakterületen belül."
    prompt = f"""
    Klinikai gyógytornász szakoktató vagy. Generálj egy élethű, részletes, szakmailag pontos ORVOSI KARTONT egy fiktív beteghez.
    Kizárólag az általános klinikai orvosi és gyógytornászati tudásodra támaszkodj!
    
    Szakterület: {category}
    {topic_instruction}
    Nehézségi szint: {difficulty}
    
    FONTOS SZABÁLYOK:
    - Csak az orvosi karton adatait írd le!
    - NE áruld el előre a teljes fizikális vizsgálati eredményeket (inspekció, palpáció, tesztek), és NE írj kezelési tervet!
    
    A karton kötelező felépítése (pontosan ezekkel a címsorokkal):
    ### 1. Személyes adatok
    (Név, életkor, nem, foglalkozás)
    
    ### 2. Családi anamnézis
    (Családban előforduló releváns betegségek)
    
    ### 3. Szociális anamnézis
    (Lakókörülmények, lépcsőzés, családi támogatás, munkahelyi/sport terhelés, káros szenvedélyek)
    
    ### 4. Kórelőzmény (Anamnesis morbi)
    (Korábbi betegségek, műtétek, sérülések, rendszeresen szedett gyógyszerek, esetleges friss képalkotó/orvosi diagnózis)
    
    ### 5. Jelen panasz
    (Mivel érkezett most a beteg, mióta tart, milyen jellegű a panasz/fájdalom, mi váltja ki vagy enyhíti)
    """
    return generate_with_fallback(client, prompt)

def build_initial_database(client):
    os.makedirs(DB_FOLDER, exist_ok=True)
    preset_configs = [
        ("Ortopédia & Traumatológia", "Könnyű (Klasszikus eset)", "LCA (elülső keresztszalag) rekonstrukció utáni állapot"),
        ("Reumatológia", "Közepes (Kísérőbetegségekkel)", "Lumboischialgia / porckorongsérv konzervatív kezelése"),
        ("Neurológia", "Közepes (Kísérőbetegségekkel)", "Ischaemiás stroke utáni hemiparesis"),
        ("Ortopédia & Traumatológia", "Könnyű (Klasszikus eset)", "Csípőprotézis (TPA) beültetés utáni rehabilitáció"),
        ("Kardiorespiratorikus rehabilitáció", "Nehéz (Komplex / Differenciáldiagnosztika)", "COPD akut exacerbáció utáni légzésrehabilitáció")
    ]
    for idx, (cat, diff, topic) in enumerate(preset_configs, start=1):
        record_text = generate_single_case(client, cat, diff, topic)
        case_data = {
            "id": idx,
            "title": f"{idx}. eset – {cat} ({topic})",
            "category": cat,
            "difficulty": diff,
            "record": record_text
        }
        filepath = os.path.join(DB_FOLDER, f"eset_{idx}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(case_data, f, ensure_ascii=False, indent=2)

# --- MUNKAMENET ÁLLAPOTOK (Session State) ---
if "medical_record" not in st.session_state:
    st.session_state.medical_record = None
if "current_case_title" not in st.session_state:
    st.session_state.current_case_title = ""
if "current_step" not in st.session_state:
    st.session_state.current_step = 0
if "answers" not in st.session_state:
    st.session_state.answers = []
if "evaluation" not in st.session_state:
    st.session_state.evaluation = None
if "dictation_active" not in st.session_state:
    st.session_state.dictation_active = {}

# --- OLDALSÁV (Beállítások & Adatbázis) ---
st.sidebar.header("⚙️ API Beállítás")
api_key = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.sidebar.success("✅ Beépített API kulcs aktív")
except Exception:
    pass

if not api_key:
    api_key = st.sidebar.text_input(
        "Google Gemini API Key", 
        type="password", 
        help="Add meg a Google AI Studio-ból kimásolt API kulcsodat"
    )

st.sidebar.markdown("---")
st.sidebar.header("📂 Teszt Adatbázis (Helyi mappa)")

saved_cases = get_saved_cases()

# Ha még nincs legenerálva az 5 eset
if len(saved_cases) == 0:
    st.sidebar.warning("Még nincs létrehozva az 5 elemű teszt adatbázis!")
    if st.sidebar.button("🏭 5 teszteset legenerálása és mentése", type="primary"):
        if not api_key:
            st.sidebar.error("Add meg az API kulcsot a generáláshoz!")
        else:
            try:
                client = genai.Client(api_key=api_key)
                with st.spinner("5 különböző klinikai eset legenerálása és mentése a 'teszt_adatbazis' mappába..."):
                    build_initial_database(client)
                st.sidebar.success("5 eset sikeresen elmentve!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Hiba történt: {e}")
else:
    st.sidebar.success(f"Elérhető mentett esetek száma: {len(saved_cases)} db")
    case_options = {c["title"]: c for c in saved_cases}
    selected_title = st.sidebar.selectbox(
        "Válaszd ki, hanyas esetet töltöd be:",
        options=list(case_options.keys())
    )
    
    if st.sidebar.button("📥 Kiválasztott eset betöltése", type="primary"):
        chosen = case_options[selected_title]
        st.session_state.medical_record = chosen["record"]
        st.session_state.current_case_title = chosen["title"]
        st.session_state.current_step = 0
        st.session_state.answers = []
        st.session_state.evaluation = None
        st.session_state.dictation_active = {}
        st.rerun()

# --- ÚJ TESZT GENERÁLÁSA (OPCIONÁLIS) ---
st.sidebar.markdown("---")
with st.sidebar.expander("➕ Új teszt(ek) generáltatása"):
    new_cat = st.selectbox(
        "Szakterület:",
        [
            "Ortopédia & Traumatológia",
            "Reumatológia",
            "Neurológia",
            "Kardiorespiratorikus rehabilitáció",
            "Sportfizioterápia",
            "Gyermekgyógyászat"
        ]
    )
    new_topic = st.text_input("Opcionális kórkép:", placeholder="Pl.: Rotátorköpeny szakadás")
    new_diff = st.select_slider(
        "Nehézség:",
        options=["Könnyű (Klasszikus eset)", "Közepes (Kísérőbetegségekkel)", "Nehéz (Komplex / Differenciáldiagnosztika)"]
    )
    
    if st.button("🎲 1 új eset generálása és mentése"):
        if not api_key:
            st.error("Add meg az API kulcsot!")
        else:
            try:
                client = genai.Client(api_key=api_key)
                os.makedirs(DB_FOLDER, exist_ok=True)
                next_id = len(saved_cases) + 1
                with st.spinner("Új eset generálása és mentése..."):
                    rec = generate_single_case(client, new_cat, new_diff, new_topic)
                    topic_label = new_topic.strip() if new_topic.strip() else "Általános"
                    case_data = {
                        "id": next_id,
                        "title": f"{next_id}. eset – {new_cat} ({topic_label})",
                        "category": new_cat,
                        "difficulty": new_diff,
                        "record": rec
                    }
                    filepath = os.path.join(DB_FOLDER, f"eset_{next_id}.json")
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(case_data, f, ensure_ascii=False, indent=2)
                    
                    st.session_state.medical_record = rec
                    st.session_state.current_case_title = case_data["title"]
                    st.session_state.current_step = 0
                    st.session_state.answers = []
                    st.session_state.evaluation = None
                    st.session_state.dictation_active = {}
                st.rerun()
            except Exception as e:
                st.error(f"Hiba: {e}")

    if len(saved_cases) > 0:
        if st.button("🔄 Teljes 5-ös adatbázis újragenerálása"):
            if not api_key:
                st.error("Add meg az API kulcsot!")
            else:
                try:
                    client = genai.Client(api_key=api_key)
                    with st.spinner("Mind az 5 eset újragenerálása..."):
                        build_initial_database(client)
                    st.success("Új 5-ös adatbázis kész!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hiba: {e}")

# --- FŐKÉPERNYŐ: HA NINCS BETÖLTÖTT ESET ---
if not st.session_state.medical_record:
    if len(saved_cases) == 0:
        st.info("👈 Kezdéshez add meg a **Google Gemini API kulcsot** a bal oldalsávban, majd kattints az **'5 teszteset legenerálása és mentése'** gombra! Ezután az esetek elmentődnek a gépedre, és bármikor betölthetők lesznek.")
    else:
        st.info("👈 Válaszd ki a bal oldalsávban, **hanyas esetet** szeretnéd betölteni a mentett adatbázisból, majd kattints a **'Kiválasztott eset betöltése'** gombra!")

# --- FŐKÉPERNYŐ: BETÖLTÖTT ORVOSI KARTON ÉS KÉRDÉSEK ---
else:
    st.markdown("---")
    st.subheader(f"📁 Orvosi Karton ({st.session_state.current_case_title})")
    with st.container(border=True):
        st.markdown(st.session_state.medical_record)
    
    st.markdown("---")
    
    # Korábbi válaszok megjelenítése
    if st.session_state.answers:
        with st.expander(f"📝 Eddigi válaszaid megtekintése ({len(st.session_state.answers)} / {len(QUESTIONS)})", expanded=False):
            for idx, ans in enumerate(st.session_state.answers):
                st.markdown(f"**{QUESTIONS[idx]}**")
                st.write(ans)
                st.markdown("---")

    # --- LÉPÉSRŐL LÉPÉSRE KÉRDÉSEK ---
    if st.session_state.current_step < len(QUESTIONS):
        step = st.session_state.current_step
        
        st.progress(step / len(QUESTIONS), text=f"Haladás: {step + 1}. / {len(QUESTIONS)} kérdés")
        st.subheader(f"❓ {QUESTIONS[step]}")
        
        # Diktálás gomb kezelése
        is_dictating = st.session_state.dictation_active.get(step, False)
        
        if not is_dictating:
            if st.button("🎙️ Diktálás indítása", key=f"start_dict_{step}"):
                st.session_state.dictation_active[step] = True
                st.rerun()
        else:
            col_mic, col_close = st.columns([4, 1])
            with col_mic:
                audio_value = st.audio_input("Kattints a mikrofonra, mondd el a választ, majd állítsd le:", key=f"audio_{step}")
            with col_close:
                st.write("")
                st.write("")
                if st.button("❌ Diktálás bezárása", key=f"stop_dict_{step}"):
                    st.session_state.dictation_active[step] = False
                    st.rerun()
            
            # Hang átírása szöveggé
            if audio_value is not None:
                audio_bytes = audio_value.getvalue()
                if st.session_state.get(f"last_audio_len_{step}") != len(audio_bytes):
                    if not api_key:
                        st.error("A diktálás szöveggé alakításához add meg az API kulcsot az oldalsávban!")
                    else:
                        try:
                            client = genai.Client(api_key=api_key)
                            transcribe_prompt = (
                                "Hallgasd meg ezt a magyar nyelvű hangfelvételt, amely egy gyógytornász hallgató válasza egy klinikai vizsgakérdésre. "
                                "Írd le pontosan, szó szerint magyarul a hallott szöveget, az orvosi és fizioterápiás szakkifejezéseket helyesen írva. "
                                "Csak a leírt szöveget add vissza, semmi más kommentárt ne fűzz hozzá!"
                            )
                            contents = [
                                transcribe_prompt,
                                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
                            ]
                            with st.spinner("Diktált szöveg feldolgozása..."):
                                transcribed_text = generate_with_fallback(client, contents)
                                existing_text = st.session_state.get(f"answer_input_{step}", "")
                                combined = f"{existing_text} {transcribed_text.strip()}".strip()
                                st.session_state[f"answer_input_{step}"] = combined
                                st.session_state[f"last_audio_len_{step}"] = len(audio_bytes)
                                st.rerun()
                        except Exception as e:
                            st.error(f"Hiba a hang feldolgozásakor: {e}")

        # Válasz szövegdoboz
        current_answer = st.text_area(
            "Válaszod (gépelhetsz, vagy a fenti 'Diktálás indítása' gombbal szóban is megadhatod):",
            height=180,
            key=f"answer_input_{step}",
            placeholder="Írd ide a válaszodat, vagy kattints a Diktálás indítása gombra..."
        )
        
        btn_label = "➡️ Válasz rögzítése és következő kérdés" if step < len(QUESTIONS) - 1 else "✅ Utolsó válasz rögzítése és Kiértékelés indítása"
        
        if st.button(btn_label, type="primary"):
            if not current_answer.strip():
                st.warning("Kérlek, írj be vagy diktálj be egy választ, mielőtt továbblépsz!")
            else:
                st.session_state.answers.append(current_answer.strip())
                st.session_state.current_step += 1
                st.rerun()

    # --- ÖSSZES KÉRDÉS MEGVÁLASZOLVA -> KIÉRTÉKELÉS ---
    else:
        st.progress(1.0, text="Minden kérdés megválaszolva! (7 / 7)")
        st.success("🎉 Minden kérdésre válaszoltál!")
        
        if st.session_state.evaluation is None:
            if not api_key:
                st.error("Hiányzik az API kulcs az értékeléshez! Add meg az oldalsávban.")
            else:
                try:
                    client = genai.Client(api_key=api_key)
                    
                    qa_summary = ""
                    for i in range(len(QUESTIONS)):
                        qa_summary += f"\nKÉRDÉS {QUESTIONS[i]}\nHALLGATÓ VÁLASZA:\n{st.session_state.answers[i]}\n"
                    
                    eval_prompt = f"""
                    Szigorú, de segítőkész klinikai gyógytornász vizsgáztató vagy.
                    Értékeld a hallgató teljes vizsgálati és kezelési gondolkodásmenetét a megadott orvosi karton alapján!
                    
                    ORVOSI KARTON:
                    {st.session_state.medical_record}
                    
                    A HALLGATÓ VÁLASZAI A 7 LÉPÉSRE:
                    {qa_summary}
                    
                    FELADATOD:
                    1. Adj egy átfogó értékelést és pontszámot (pl. 100-ból vagy 10-ből).
                    2. Haladj végig MIND A 7 KÉRDÉSEN külön-külön pontokba szedve:
                       - Mi volt jó a hallgató válaszában?
                       - Mi maradt ki, vagy mi volt szakmailag pontatlan/kontraindikált?
                       - Mi lett volna az optimális, szakmailag teljes válasz az adott pontra?
                    3. A hangnem legyen támogató, szakmai és konstruktív.
                    """
                    
                    with st.spinner("Az AI vizsgáztató elemzi mind a 7 válaszodat..."):
                        st.session_state.evaluation = generate_with_fallback(client, eval_prompt)
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"Hiba történt az értékelés során: {e}")
        
        if st.session_state.evaluation:
            st.subheader("📊 Részletes Vizsgáztatói Kiértékelés")
            st.markdown(st.session_state.evaluation)
            
            full_report = f"ORVOSI KARTON ({st.session_state.current_case_title})\n{st.session_state.medical_record}\n\n" + "="*40 + "\nHALLGATÓ VÁLASZAI\n" + "="*40 + "\n"
            for i in range(len(QUESTIONS)):
                full_report += f"\n{QUESTIONS[i]}\n{st.session_state.answers[i]}\n"
            full_report += "\n" + "="*40 + "\nVIZSGÁZTATÓI ÉRTÉKELÉS\n" + "="*40 + f"\n\n{st.session_state.evaluation}"
            
            st.download_button(
                label="📥 Teljes eset és kiértékelés letöltése (.txt)",
                data=full_report,
                file_name="gyogytornasz_esettanulmany.txt",
                mime="text/plain"
            )