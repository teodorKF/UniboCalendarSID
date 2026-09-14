import re
import hashlib
import requests
from datetime import datetime
from icalendar import Calendar, Event

# Parametri di configurazione
UNIBO_JSON_URL = "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni/@@orario_recap_data?anno=1&curricula=B10-000"
OUTPUT_ICS_FILE = "orario_sid_anno1_AL.ics"

def is_target_channel(text):
    """Verifica che l'evento appartenga alle classi A-L ed escluda espressamente M-Z."""
    if not text:
        return True  # Se non specificato, si include
    
    text_upper = text.upper()
    # Escludi chiaramente i canali M-Z
    if re.search(r'\bM-Z\b', text_upper) or re.search(r'CANALE\s+[M-Z]', text_upper):
        return False
    
    # Includi se contiene A-L o lettere comprese tra A e L
    if re.search(r'\bA-L\b', text_upper) or re.search(r'CANALE\s+[A-L]', text_upper):
        return True
        
    return True

def generate_stable_uid(item):
    """Genera un UID SHA-256 univoco e stabile per evitare duplicati su Apple Calendar."""
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
        
        # Filtro stringente sezioni M-Z
        if not is_target_channel(f"{title} {note}"):
            continue

        event = Event()
        
        # Titolo formattato: "Materia – Prof. Rossi"
        docente = item.get('docente', '').strip()
        clean_title = title.strip()
        if docente:
            event.add('summary', f"{clean_title} – {docente}")
        else:
            event.add('summary', clean_title)

        # Date e Orari (ISO8601)
        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)

        # UID Stabile per aggiornamenti/cancellazioni impreviste
        event.add('uid', generate_stable_uid(item))

        # Luogo e Aula
        aula = item.get('aula', '')
        edificio = item.get('edificio', '')
        location = f"Aula {aula}, {edificio}".strip(", ") if aula else edificio
        if location:
            event.add('location', location)

        # Descrizione dettagliata
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
