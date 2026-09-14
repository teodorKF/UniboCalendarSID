import re
import hashlib
import requests
from datetime import datetime, timedelta
from icalendar import Calendar, Event

# Calcola automaticamente un intervallo ampio (da oggi a circa 10 mesi avanti)
start_date = datetime.now().strftime("%Y-%m-%d")
end_date = (datetime.now() + timedelta(days=300)).strftime("%Y-%m-%d")

UNIBO_JSON_URL = f"https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni/@@orario_reale_json?anno=1&curricula=B10-000&start={start_date}&end={end_date}"
OUTPUT_ICS_FILE = "orario_sid_anno1_AL.ics"

def is_target_channel(text):
    """Filtra per includere solo le classi A-L ed escludere M-Z."""
    if not text:
        return True
    text_upper = text.upper()
    if re.search(r'\bM-Z\b', text_upper) or re.search(r'CANALE\s+[M-Z]', text_upper):
        return False
    return True

def generate_stable_uid(item):
    """Crea un identificatore univoco e stabile per evitare duplicati su Apple Calendar."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-al"

def build_calendar():
    response = requests.get(UNIBO_JSON_URL, headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    events_data = response.json()

    cal = Calendar()
    cal.add('prodid', '-//UNIBO SID 1 Anno A-L Sync//NONSGML v1.0//IT')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', 'Lezioni SID 1° Anno (A-L)')
    cal.add('x-published-ttl', 'PT15M')
    cal.add('refresh-interval;value=duration', 'PT15M')

    for item in events_data:
        title = item.get('title', '')
        note = item.get('note', '')
        
        if not is_target_channel(f"{title} {note}"):
            continue

        event = Event()
        
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        clean_title = title.strip()
        
        if docente:
            event.add('summary', f"{clean_title} – {docente}")
        else:
            event.add('summary', clean_title)

        # Conversione date ISO
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)

        event.add('uid', generate_stable_uid(item))

        aula = item.get('aula', '')
        edificio = item.get('edificio', '')
        location = f"Aula {aula}, {edificio}".strip(", ") if aula else edificio
        if location:
            event.add('location', location)

        description_lines = [
            f"Materia: {clean_title}",
            f"Docente: {docente if docente else 'N/D'}",
            f"Aula: {aula if aula else 'N/D'}",
            f"Sede: {edificio if edificio else 'N/D'}",
            f"Note: {note if note else 'Nessuna'}",
            f"Fonte: https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni?anno=1&curricula=B10-000"
        ]
        event.add('description', "\n".join(description_lines))

        cal.add_component(event)

    with open(OUTPUT_ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())

if __name__ == "__main__":
    build_calendar()
