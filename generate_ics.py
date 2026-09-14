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
    """Rimuove codici numerici e CFU per lasciare solo il nome pulito del corso."""
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def extract_location(item):
    """Estrae l'aula e l'indirizzo leggendo la lista 'aule' usata da UNIBO."""
    aula_name = ""
    address = ""

    # 1. Lettura dalla lista ufficiale UNIBO 'aule'
    aule_list = item.get('aule', [])
    if isinstance(aule_list, list) and len(aule_list) > 0:
        first_aula = aule_list[0]
        if isinstance(first_aula, dict):
            aula_name = first_aula.get('des_aula') or first_aula.get('nome') or ""
            address = first_aula.get('indirizzo') or first_aula.get('des_edificio') or ""
        elif isinstance(first_aula, str):
            aula_name = first_aula

    # 2. Fallback su campi singoli se 'aule' non fosse presente
    if not aula_name:
        raw_aula = item.get('aula')
        if isinstance(raw_aula, str):
            aula_name = raw_aula
        elif isinstance(raw_aula, dict):
            aula_name = raw_aula.get('des_aula', '')

    if not address:
        address = item.get('indirizzo') or item.get('edificio') or item.get('luogo') or ""
        if isinstance(address, dict):
            address = address.get('indirizzo', '')

    # Formattazione finale: "AULA 12, Viale Filippo Corridoni, 20 - Forlì"
    aula_clean = str(aula_name).strip()
    addr_clean = str(address).strip()

    if aula_clean and addr_clean and addr_clean not in aula_clean:
        return f"{aula_clean}, {addr_clean}"
    elif aula_clean:
        return aula_clean
    elif addr_clean:
        return addr_clean

    return ""

def generate_stable_uid(item, location_str):
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{location_str}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v4"

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

        # Estrazione Posizione (Aula + Indirizzo)
        location_str = extract_location(item)
        if location_str:
            event.add('location', location_str)

        # UID Stabile versione 4
        event.add('uid', generate_stable_uid(item, location_str))

        # Organizzatore ("Invitation from Docente")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Descrizione / Note
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
