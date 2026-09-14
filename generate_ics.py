import re
import hashlib
import requests
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event, vCalAddress, vText

start_date = datetime.now().strftime("%Y-%m-%d")
end_date = (datetime.now() + timedelta(days=300)).strftime("%Y-%m-%d")

UNIBO_JSON_URL = f"https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni/@@orario_reale_json?anno=1&curricula=B10-000&start={start_date}&end={end_date}"
OUTPUT_ICS_FILE = "orario_sid_anno1_AL.ics"

def is_target_channel(text):
    if not text:
        return True
    text_upper = text.upper()
    if re.search(r'\bM-Z\b', text_upper) or re.search(r'CANALE\s+[M-Z]', text_upper):
        return False
    return True

def clean_title(title_raw):
    if not title_raw:
        return ""
    # Rimuove codici numerici (es. '96813_A-L - ')
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    # Rimuove la dicitura dei CFU (es. '(10 CFU)')
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def format_clean_location(item):
    """Formatta la posizione esattamente come: AULA 12, Viale Filippo Corridoni, 20 - Forlì"""
    aula = ""
    indirizzo = ""

    raw_aula = item.get('aula')
    if isinstance(raw_aula, dict):
        aula = raw_aula.get('des_aula', '').strip()
    elif isinstance(raw_aula, str):
        aula = raw_aula.strip()

    raw_ind = item.get('indirizzo') or item.get('edificio')
    if isinstance(raw_ind, str) and raw_ind.strip():
        indirizzo = raw_ind.strip()

    if aula and indirizzo:
        return f"{aula}, {indirizzo}"
    elif aula:
        return aula
    elif indirizzo:
        return indirizzo

    # Gestione stringa unica 'luogo'
    luogo_raw = item.get('luogo', '')
    if isinstance(luogo_raw, str) and luogo_raw.strip():
        # Semplifica rimuovendo indicazioni intermedie del piano se già presenti aula e via
        return luogo_raw.replace(" Piano Secondo - Campus di Forlì - Teaching Hub - ", ", ").strip()

    return ""

def generate_stable_uid(item):
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-al"

def build_calendar():
    response = requests.get(UNIBO_JSON_URL, headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    events_data = response.json()

    cal = Calendar()
    cal.add('prodid', '-//UNIBO SID 1 Anno A-L Sync//NONSGML v1.0//IT')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', 'Orario università')
    cal.add('x-published-ttl', 'PT15M')
    cal.add('refresh-interval;value=duration', 'PT15M')

    now_utc = datetime.now(timezone.utc)
    current_timestamp = int(now_utc.timestamp())

    for item in events_data:
        raw_title = item.get('title', '')
        note = item.get('note', '').strip() if item.get('note') else ''
        
        if not is_target_channel(f"{raw_title} {note}"):
            continue

        event = Event()
        
        # Titolo (STORIA INTERNAZIONALE DELL'ETA' CONTEMPORANEA / (A-L))
        event.add('summary', clean_title(raw_title))

        # Orari e Timestamp di aggiornamento
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', now_utc)
        event.add('sequence', current_timestamp)

        # UID Stabile
        event.add('uid', generate_stable_uid(item))

        # Luogo posizionato sotto il titolo
        location_str = format_clean_location(item)
        if location_str:
            event.add('location', location_str)

        # Badge Organizzatore ("Invitation from Giuliana Laschi")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Note
        desc_lines = []
        if note:
            desc_lines.append(f"Note: {note}")
        desc_lines.append("Fonte: https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni")
        event.add('description', "\n\n".join(desc_lines))

        cal.add_component(event)

    with open(OUTPUT_ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())

if __name__ == "__main__":
    build_calendar()
