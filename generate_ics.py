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
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def extract_full_location(item):
    """Estrae con certezza l'aula controllando anche 'des_risorsa' e il campo 'luogo'."""
    aula = ""
    indirizzo = ""

    # 1. Controllo dell'array 'aule' (inclusa la chiave 'des_risorsa')
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

    # 2. Controllo chiavi singole se manca l'aula
    if not aula:
        raw_aula = item.get('aula') or item.get('des_aula') or item.get('des_risorsa')
        if isinstance(raw_aula, dict):
            aula = raw_aula.get('des_aula') or raw_aula.get('des_risorsa') or raw_aula.get('nome') or ""
            if not indirizzo:
                indirizzo = raw_aula.get('des_indirizzo') or raw_aula.get('indirizzo') or ""
        elif isinstance(raw_aula, str) and raw_aula.strip():
            aula = raw_aula.strip()

    # 3. Controllo indirizzo se manca
    if not indirizzo:
        for k in ['des_indirizzo', 'indirizzo', 'des_edificio', 'edificio', 'via']:
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                indirizzo = v.strip()
                break

    aula = aula.strip()
    indirizzo = indirizzo.strip()

    # Se l'aula è stata estratta con successo dai dati strutturati
    if aula:
        if not re.search(r'aula|lab|sala', aula, re.IGNORECASE):
            if re.match(r'^[A-Z0-9\.\s]+$', aula, re.IGNORECASE):
                aula = f"Aula {aula}"
        if indirizzo:
            if aula.lower() in indirizzo.lower():
                return indirizzo
            return f"{aula}, {indirizzo}"
        return aula

    # PARACADUTE: Se l'aula non è stata trovata nei dati strutturati, usiamo 'luogo'
    luogo = item.get('luogo')
    if isinstance(luogo, str) and luogo.strip():
        return luogo.strip()

    return indirizzo or ""

def generate_stable_uid(item, loc):
    """Versione v13 per sostituire la scheda in cache."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{loc}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v13"

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

        base_title = clean_title(raw_title)
        location_str = extract_full_location(item)

        event = Event()
        event.add('summary', base_title)

        start_dt = datetime.fromisoformat(item['start'])
        end_dt = datetime.fromisoformat(item['end'])
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', now_utc)
        event.add('sequence', current_timestamp)

        if location_str:
            event.add('location', location_str)

        event.add('uid', generate_stable_uid(item, location_str))

        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        alarm = Alarm()
        alarm.add('action', 'DISPLAY')
        alarm.add('description', f"Promemoria lezione: {base_title}")
        alarm.add('trigger', timedelta(minutes=-30))
        event.add_component(alarm)

        desc_lines = []
        if location_str:
            desc_lines.append(f"📍 Posizione: {location_str}")
        if note:
            desc_lines.append(f"Note: {note}")
            
        source_url = "https://corsi.unibo.it/laurea/ScienzeInternazionaliDiplomatiche/orario-lezioni"
        if source_url not in note:
            desc_lines.append(f"Fonte: {source_url}")
            
        event.add('description', "\n\n".join(desc_lines))

        cal.add_component(event)

    with open(OUTPUT_ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())

if __name__ == "__main__":
    build_calendar()
