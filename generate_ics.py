import re
import hashlib
import requests
from datetime import datetime, timedelta
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

    for item in events_data:
        title = item.get('title', '').strip()
        note = item.get('note', '').strip() if item.get('note') else ''
        
        if not is_target_channel(f"{title} {note}"):
            continue

        event = Event()
        
        # Titolo pulito come nell'immagine di riferimento
        event.add('summary', title)

        # Date e Orari
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)

        # UID Stabile
        event.add('uid', generate_stable_uid(item))

        # Luogo/Aula sotto il titolo
        aula = item.get('aula', '').strip() if item.get('aula') else ''
        edificio = item.get('edificio', '').strip() if item.get('edificio') else ''
        location_parts = [p for p in [aula, edificio] if p]
        if location_parts:
            event.add('location', ", ".join(location_parts))

        # Docente impostato come Organizzatore (Crea il badge "Invitation from Docente")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Note pulite: inserisce solo informazioni reali, evita le scritte N/D
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
