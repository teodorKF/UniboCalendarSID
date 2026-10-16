import re
import time
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event, Alarm

ROME_TZ = ZoneInfo("Europe/Rome")
now_rome = datetime.now(ROME_TZ)

BASE_JSON_URL = "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni/@@orario_reale_json"
OUTPUT_ICS_FILE = "orario_sid_anno1_AL.ics"


def fetch_unibo_events():
    """Scarica gli eventi a blocchi di 45 giorni per evitare il blocco/timeout HTTP 503 di UNIBO."""
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive"
    }

    # Finestra totale: da -15 giorni fa a +180 giorni (6 mesi coprono tutto il semestre/anno)
    start_window = now_rome - timedelta(days=15)
    end_window = now_rome + timedelta(days=180)
    chunk_days = 45

    all_events = []
    seen_keys = set()
    current_start = start_window
    successful_chunks = 0

    while current_start < end_window:
        current_end = min(current_start + timedelta(days=chunk_days), end_window)
        s_str = current_start.strftime("%Y-%m-%d")
        e_str = current_end.strftime("%Y-%m-%d")

        params = {
            "anno": "1",
            "curricula": "B10-000",
            "start": s_str,
            "end": e_str
        }

        try:
            resp = session.get(BASE_JSON_URL, params=params, headers=headers, timeout=25)
            resp.raise_for_status()
            chunk_data = resp.json()
            if isinstance(chunk_data, list):
                successful_chunks += 1
                for ev in chunk_data:
                    # Evita duplicati ai confini dei blocchi di date
                    ev_key = f"{ev.get('cod_modulo')}_{ev.get('start')}_{ev.get('end')}_{ev.get('title')}"
                    if ev_key not in seen_keys:
                        seen_keys.add(ev_key)
                        all_events.append(ev)
            print(f"✅ Blocco {s_str} -> {e_str}: {len(chunk_data)} eventi ricevuti.")
        except Exception as e:
            print(f"⚠️ Errore sul blocco {s_str} -> {e_str}: {e}")

        current_start = current_end
        time.sleep(0.5)  # Piccola pausa gentile per non far scattare il rate-limit UNIBO

    if successful_chunks == 0:
        raise RuntimeError("Nessun blocco scaricato con successo da UNIBO.")

    return all_events


def is_target_event(item):
    """Filtra Canale M-Z, tutoriali, OFA, lezioni annullate ed esclude i lab di inglese tranne il Lab 7."""
    raw_title = item.get('title', '') or ''
    note = item.get('note', '') or ''
    text_upper = f"{raw_title} {note}".upper()

    # 1. Esclusione Canale M-Z
    if re.search(r'\bM-Z\b', text_upper) or re.search(r'CANALE\s+[M-Z]', text_upper):
        return False

    # 2. Esclusione Corsi Tutoriali
    if re.search(r'TUTOR', text_upper):
        return False

    # 3. Esclusione OFA (Obblighi Formativi Aggiuntivi)
    if re.search(r'\bOFA\b', text_upper):
        return False

    # 4. Esclusione Lezioni Annullate / Sospese
    if re.search(r'ANNULLA|SOSPEN|CANCELL|NON\s+LAVORO|NO\s+LEZIONE', text_upper):
        return False

    # 5. Laboratori di Lingua Inglese: mantieni SOLO il Lab 7 / Gruppo 7
    is_english_lab = bool(
        re.search(r'\bLAB(?:ORATORIO)?\b.*INGLESE', text_upper) or
        re.search(r'\bLAB\..*INGLESE', text_upper) or
        re.search(r'LINGUA INGLESE.*LAB', text_upper)
    )
    if is_english_lab:
        is_lab_7 = bool(
            re.search(r'(?:LAB(?:\.|ORATORIO)?|GRUPPO|GR\.?|N\.?|CANALE|SEZ\.?)\s*7\b', text_upper) or
            re.search(r'INGLESE\s*[-–]?\s*7\b', text_upper)
        )
        if not is_lab_7:
            return False

    return True


def clean_title(title_raw):
    """Pulisce il titolo mantenendo solo il nome del corso."""
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()


def extract_full_location(item):
    """Estrae l'aula e l'indirizzo dal JSON UNIBO."""
    aula = ""
    indirizzo = ""

    aule = item.get('aule', [])
    if isinstance(aule, list):
        for a in aule:
            if isinstance(a, dict):
                des = a.get('des_aula') or a.get('des_risorsa') or a.get('nome') or a.get('title') or a.get('aula')
                ind = a.get('des_indirizzo') or a.get('indirizzo') or a.get('des_edificio')
                if des and not aula:
                    aula = str(des).strip()
                if ind and not indirizzo:
                    indirizzo = str(ind).strip()
            elif isinstance(a, str) and a.strip() and not aula:
                aula = a.strip()

    if not aula:
        raw_aula = item.get('aula') or item.get('des_aula') or item.get('des_risorsa')
        if isinstance(raw_aula, dict):
            aula = raw_aula.get('des_aula') or raw_aula.get('des_risorsa') or raw_aula.get('nome') or ""
            if not indirizzo:
                indirizzo = raw_aula.get('des_indirizzo') or raw_aula.get('indirizzo') or ""
        elif isinstance(raw_aula, str) and raw_aula.strip():
            aula = raw_aula.strip()

    if not indirizzo:
        for k in ['des_indirizzo', 'indirizzo', 'des_edificio', 'edificio', 'via']:
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                indirizzo = v.strip()
                break

    aula = aula.strip()
    indirizzo = indirizzo.strip()

    if aula:
        if not re.search(r'aula|lab|sala', aula, re.IGNORECASE):
            if re.match(r'^[A-Z0-9\.\s]+$', aula, re.IGNORECASE):
                aula = f"Aula {aula}"
        if indirizzo:
            if aula.lower() in indirizzo.lower():
                return indirizzo
            return f"{aula}, {indirizzo}"
        return aula

    luogo = item.get('luogo')
    if isinstance(luogo, str) and luogo.strip():
        return luogo.strip()

    return indirizzo or ""


def parse_iso_datetime(dt_str):
    """Converte la stringa ISO in datetime con fuso orario Europe/Rome."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ROME_TZ)
        return dt
    except Exception:
        return None


def generate_stable_uid(item, loc, note):
    """Versione v17: aggiorna l'evento se cambiano orario, aula o note."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{loc}_{note}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v17"


def build_calendar():
    try:
        events_data = fetch_unibo_events()
        print(f"📦 Totale eventi unici scaricati: {len(events_data)}")
    except Exception as e:
        print(f"⚠️ Server UNIBO temporaneamente offline ({e}). Mantenuto il file .ics esistente.")
        return

    cal = Calendar()
    cal.add('prodid', '-//UNIBO SID 1 Anno A-L Sync//NONSGML v1.17//IT')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', 'Orario università')
    cal.add('x-wr-timezone', 'Europe/Rome')
    cal.add('x-published-ttl', 'PT15M')
    cal.add('refresh-interval;value=duration', 'PT15M')

    events_data.sort(key=lambda x: (x.get('start', ''), x.get('title', '')))
    added_count = 0

    for item in events_data:
        try:
            if not is_target_event(item):
                continue

            raw_title = item.get('title', '')
            note = item.get('note', '').strip() if item.get('note') else ''
            docente = item.get('docente', '').strip() if item.get('docente') else ''

            base_title = clean_title(raw_title)
            location_str = extract_full_location(item)

            start_dt = parse_iso_datetime(item.get('start'))
            end_dt = parse_iso_datetime(item.get('end'))
            if not start_dt or not end_dt:
                continue

            event = Event()
            event.add('summary', base_title)
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            event.add('dtstamp', start_dt.astimezone(timezone.utc))
            event.add('sequence', 0)

            if location_str:
                event.add('location', location_str)

            event.add('uid', generate_stable_uid(item, location_str, note))

            alarm = Alarm()
            alarm.add('action', 'DISPLAY')
            alarm.add('description', f"Promemoria lezione: {base_title}")
            alarm.add('trigger', timedelta(minutes=-30))
            event.add_component(alarm)

            desc_lines = []
            if docente:
                desc_lines.append(f"👨‍🏫 Docente: {docente}")
            if location_str:
                desc_lines.append(f"📍 Posizione: {location_str}")
            if note:
                desc_lines.append(f"📝 Note: {note}")

            source_url = "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni"
            if source_url not in note:
                desc_lines.append(f"🔗 Fonte: {source_url}")

            event.add('description', "\n\n".join(desc_lines))
            cal.add_component(event)
            added_count += 1

        except Exception as e:
            print(f"Errore salto evento singolo: {e}")
            continue

    with open(OUTPUT_ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())

    print(f"✅ File {OUTPUT_ICS_FILE} aggiornato con successo! ({added_count} lezioni valide inserite).")


if __name__ == "__main__":
    build_calendar()
