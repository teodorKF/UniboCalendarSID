import re
import hashlib
import requests
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event, Alarm, vCalAddress, vText

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
    """Pulisce il titolo rimuovendo codici numerici iniziali e CFU."""
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def extract_location(item):
    """Estrae con garanzia sia l'aula che l'indirizzo senza perdere pezzi."""
    aula = ""
    indirizzo = ""

    # 1. Cerca nell'array 'aule' (oggetti o stringhe)
    aule_list = item.get('aule')
    if isinstance(aule_list, list) and len(aule_list) > 0:
        for a in aule_list:
            if isinstance(a, dict):
                if not aula:
                    aula = a.get('des_aula') or a.get('nome') or a.get('aula') or a.get('title') or ""
                if not indirizzo:
                    indirizzo = a.get('des_indirizzo') or a.get('indirizzo') or a.get('des_edificio') or a.get('edificio') or ""
            elif isinstance(a, str) and a.strip():
                if not aula:
                    aula = a.strip()

    # 2. Cerca nel campo 'aula' singolare se ancora manca
    if not aula:
        raw_aula = item.get('aula')
        if isinstance(raw_aula, dict):
            aula = raw_aula.get('des_aula') or raw_aula.get('nome') or ""
            if not indirizzo:
                indirizzo = raw_aula.get('des_indirizzo') or raw_aula.get('indirizzo') or ""
        elif isinstance(raw_aula, str) and raw_aula.strip():
            aula = raw_aula.strip()

    # 3. Cerca indirizzo/edificio tra i campi di primo livello
    if not indirizzo:
        for k in ['des_indirizzo', 'indirizzo', 'des_edificio', 'edificio', 'via']:
            val = item.get(k)
            if isinstance(val, str) and val.strip():
                indirizzo = val.strip()
                break

    aula_clean = str(aula).strip()
    ind_clean = str(indirizzo).strip()

    # Unione finale
    if aula_clean and ind_clean:
        if aula_clean.lower() in ind_clean.lower():
            return ind_clean
        return f"{aula_clean}, {ind_clean}"
    
    if aula_clean:
        return aula_clean
        
    if ind_clean:
        return ind_clean

    # 4. Paracadute finale su 'luogo'
    luogo_val = item.get('luogo')
    if isinstance(luogo_val, str) and luogo_val.strip():
        return luogo_val.strip()

    return ""

def generate_stable_uid(item, location_str):
    """Versione v9 per forzare il refresh immediato in iOS/macOS."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{location_str}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v9"

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
        event.add('summary', clean_title(raw_title))

        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', now_utc)
        event.add('sequence', current_timestamp)

        # Posizione garantita (Aula + Indirizzo)
        location_str = extract_location(item)
        if location_str:
            event.add('location', location_str)

        event.add('uid', generate_stable_uid(item, location_str))

        # Organizzatore ("Invitation from Docente")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Alert 30 minuti prima
        alarm = Alarm()
        alarm.add('action', 'DISPLAY')
        alarm.add('description', f"Promemoria lezione: {clean_title(raw_title)}")
        alarm.add('trigger', timedelta(minutes=-30))
        event.add_component(alarm)

        # Note / Fonte
        desc_lines = []
        source_url = "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni"
        if note:
            desc_lines.append(f"Note: {note}")
        if source_url not in note:
            desc_lines.append(f"Fonte: {source_url}")
            
        event.add('description', "\n\n".join(desc_lines))

        cal.add_component(event)

    with open(OUTPUT_ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())

if __name__ == "__main__":
    build_calendar()
