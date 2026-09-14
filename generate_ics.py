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
    """Pulisce il titolo mantenendo solo il nome del corso."""
    if not title_raw:
        return ""
    title = re.sub(r'^\d+_[A-Z0-9\-_]+\s*-\s*', '', title_raw)
    title = re.sub(r'\s*\(\d+\s*CFU\)', '', title)
    return title.strip()

def format_aula_name(aula_raw):
    """Assicura che l'aula sia prefissata da 'Aula' se c'è solo il numero/codice."""
    if not aula_raw:
        return ""
    aula_str = str(aula_raw).strip()
    if not re.search(r'aula', aula_str, re.IGNORECASE):
        if re.match(r'^[A-Z0-9\.]+$', aula_str, re.IGNORECASE):
            return f"Aula {aula_str}"
    return aula_str

def extract_full_location(item):
    """Formatta la posizione esattamente come 'Aula XX, Indirizzo'."""
    aula = ""
    indirizzo = ""

    # 1. Estrazione dall'array 'aule'
    aule_list = item.get('aule')
    if isinstance(aule_list, list) and len(aule_list) > 0:
        first = aule_list[0]
        if isinstance(first, dict):
            aula = first.get('des_aula') or first.get('nome') or first.get('aula') or first.get('title') or ""
            indirizzo = first.get('des_indirizzo') or first.get('indirizzo') or first.get('des_edificio') or first.get('edificio') or ""
        elif isinstance(first, str):
            aula = first

    # 2. Estrazione dal campo 'aula'
    if not aula:
        raw_aula = item.get('aula')
        if isinstance(raw_aula, dict):
            aula = raw_aula.get('des_aula') or raw_aula.get('nome') or ""
            if not indirizzo:
                indirizzo = raw_aula.get('des_indirizzo') or raw_aula.get('indirizzo') or ""
        elif isinstance(raw_aula, str):
            aula = raw_aula

    # 3. Estrazione indirizzo da campi singoli
    if not indirizzo:
        for k in ['des_indirizzo', 'indirizzo', 'des_edificio', 'edificio', 'via']:
            val = item.get(k)
            if isinstance(val, str) and val.strip():
                indirizzo = val.strip()
                break

    # 4. Parsing dal campo 'luogo' come paracadute
    luogo_str = item.get('luogo')
    if isinstance(luogo_str, str) and luogo_str.strip():
        if not aula:
            m = re.search(r'\b(aula\s+[a-z0-9]+)\b', luogo_str, re.IGNORECASE)
            if m:
                aula = m.group(1)
            else:
                parts = [p.strip() for p in luogo_str.split('-') if p.strip()]
                if parts:
                    aula = parts[0]
        if not indirizzo:
            m_ind = re.search(r'\b((?:via|viale|piazza|corso|p\.zza|v\.le)\s+[^,\-\n]+(?:\s*,\s*\d+)?(?:\s*-\s*Forlì)?)', luogo_str, re.IGNORECASE)
            if m_ind:
                indirizzo = m_ind.group(1)
            else:
                parts = [p.strip() for p in luogo_str.split('-') if p.strip()]
                if len(parts) > 1:
                    indirizzo = parts[-1]

    aula_formatted = format_aula_name(aula)
    ind_clean = str(indirizzo).strip()

    if aula_formatted and ind_clean:
        if aula_formatted.lower() in ind_clean.lower():
            return ind_clean
        return f"{aula_formatted}, {ind_clean}"

    return aula_formatted or ind_clean or (str(luogo_str).strip() if luogo_str else "")

def generate_stable_uid(item, location_str):
    """Versione v11 dell'UID per forzare la riscrittura completa della cache Apple."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{location_str}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v11"

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

        # Posizione: "Aula XX, Via..."
        if location_str:
            event.add('location', location_str)

        event.add('uid', generate_stable_uid(item, location_str))

        # Docente
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Notifica 30 min prima
        alarm = Alarm()
        alarm.add('action', 'DISPLAY')
        alarm.add('description', f"Promemoria lezione: {base_title}")
        alarm.add('trigger', timedelta(minutes=-30))
        event.add_component(alarm)

        # Descrizione / Note
        desc_lines = []
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
