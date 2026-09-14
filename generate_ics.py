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
    """Rimuove codici numerici e CFU per lasciare solo il nome del corso."""
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def extract_location(item):
    """Estrae ed elenca in modo esaustivo aula, piano e indirizzo da qualsiasi struttura JSON."""
    parts = []

    def collect(val):
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif isinstance(val, dict):
            for k in ['des_aula', 'nome', 'title', 'aula', 'luogo', 'edificio', 'indirizzo', 'via', 'piano', 'sede']:
                if k in val and val[k]:
                    collect(val[k])
        elif isinstance(val, list):
            for elem in val:
                collect(elem)

    # Scansione campi principali
    for field in ['aula', 'luogo', 'edificio', 'indirizzo', 'sede', 'via']:
        if field in item and item[field]:
            collect(item[field])

    # Scansione fallback di sicurezza per parole chiave
    if not parts:
        for k, v in item.items():
            if isinstance(v, str) and any(w in v.upper() for w in ['AULA', 'VIALE', 'VIA ', 'PIANO', 'FORLÌ', 'CAMPUS', 'TEACHING']):
                parts.append(v.strip())

    if not parts:
        return ""

    # Rimozione duplicati
    unique_parts = []
    for p in parts:
        if p not in unique_parts:
            unique_parts.append(p)

    full_loc = ", ".join(unique_parts)
    return re.sub(r'\s+', ' ', full_loc)

def generate_stable_uid(item, location_str):
    """Rigenera gli ID con versione v3 per forzare l'aggiornamento immediato su iOS."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{location_str}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v3"

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
        
        # Titolo pulito
        event.add('summary', clean_title(raw_title))

        # Orari e Timestamp
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', now_utc)
        event.add('sequence', current_timestamp)

        # Posizione (Aula + Indirizzo sotto al titolo)
        location_str = extract_location(item)
        if location_str:
            event.add('location', location_str)

        # UID Stabile
        event.add('uid', generate_stable_uid(item, location_str))

        # Organizzatore ("Invitation from Docente")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Descrizione
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
