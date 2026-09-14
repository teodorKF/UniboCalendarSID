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

def extract_location(item):
    """Estrae aula, edificio e indirizzo in qualsiasi formato inviato da UNIBO."""
    parts = []
    aula_raw = item.get('aula')
    
    # Se 'aula' è un oggetto/dizionario
    if isinstance(aula_raw, dict):
        des = aula_raw.get('des_aula') or aula_raw.get('nome') or aula_raw.get('title')
        ind = aula_raw.get('indirizzo') or aula_raw.get('via')
        if des: parts.append(str(des).strip())
        if ind: parts.append(str(ind).strip())
    elif isinstance(aula_raw, str) and aula_raw.strip():
        parts.append(aula_raw.strip())

    # Controlla campi secondari per edificio/indirizzo/luogo
    for key in ['edificio', 'indirizzo', 'luogo', 'sede']:
        val = item.get(key)
        if val and isinstance(val, str) and val.strip():
            val_clean = val.strip()
            if val_clean not in parts and val_clean not in ", ".join(parts):
                parts.append(val_clean)

    return ", ".join(parts) if parts else ""

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

    for item in events_data:
        title = item.get('title', '').strip()
        note = item.get('note', '').strip() if item.get('note') else ''
        
        if not is_target_channel(f"{title} {note}"):
            continue

        event = Event()
        
        # Titolo
        event.add('summary', title)

        # Date e timestamp di aggiornamento per iOS
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', now_utc)

        # UID Stabile per modifiche/cancellazioni dinamiche
        event.add('uid', generate_stable_uid(item))

        # Posizione (Aula + Indirizzo)
        location_str = extract_location(item)
        if location_str:
            event.add('location', location_str)

        # Docente come Organizzatore
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
