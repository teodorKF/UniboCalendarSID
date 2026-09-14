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

def extract_full_location(item):
    """Estrae aula e indirizzo cercando in tutte le chiavi del JSON UNIBO (compresa des_indirizzo)."""
    aula = ""
    indirizzo = ""

    # 1. Scansione di tutti i possibili oggetti aula nel JSON UNIBO
    all_dicts = []
    if isinstance(item.get('aule'), list):
        all_dicts.extend([x for x in item['aule'] if isinstance(x, dict)])
    if isinstance(item.get('teoria_aule'), list):
        all_dicts.extend([x for x in item['teoria_aule'] if isinstance(x, dict)])
    if isinstance(item.get('aula'), dict):
        all_dicts.append(item['aula'])
    if isinstance(item.get('luogo'), dict):
        all_dicts.append(item['luogo'])

    for d in all_dicts:
        if not aula:
            aula = d.get('des_aula') or d.get('aula') or d.get('nome') or d.get('title') or ""
        if not indirizzo:
            indirizzo = d.get('des_indirizzo') or d.get('indirizzo') or d.get('via') or d.get('des_edificio') or d.get('edificio') or ""

    # 2. Fallback su chiavi stringa di primo livello
    if not aula:
        raw_aula = item.get('aula')
        if isinstance(raw_aula, str) and raw_aula.strip():
            aula = raw_aula.strip()

    if not indirizzo:
        for k in ['des_indirizzo', 'indirizzo', 'via', 'des_edificio', 'edificio']:
            val = item.get(k)
            if isinstance(val, str) and val.strip():
                indirizzo = val.strip()
                break

    # 3. Parsing della stringa 'luogo' completa se ancora incompleta
    luogo_str = item.get('luogo')
    if isinstance(luogo_str, str) and luogo_str.strip():
        luogo_clean = luogo_str.strip()
        
        if not aula:
            m_aula = re.search(r'\b(AULA\s+[A-Z0-9]+)\b', luogo_clean, re.IGNORECASE)
            if m_aula:
                aula = m_aula.group(1).upper()
        
        if not indirizzo:
            m_ind = re.search(r'\b((?:via|viale|piazza|corso|p\.zza|v\.le)\s+[^,\-\n]+(?:\s*,\s*\d+)?(?:\s*-\s*Forlì)?)', luogo_clean, re.IGNORECASE)
            if m_ind:
                indirizzo = m_ind.group(1).strip()
            else:
                parts = [p.strip() for p in luogo_clean.split('-') if p.strip()]
                if len(parts) > 1:
                    indirizzo = parts[-1]

    aula_clean = str(aula).strip()
    ind_clean = str(indirizzo).strip()

    # Formattazione finale: "AULA 12, Viale Filippo Corridoni, 20 - Forlì"
    if aula_clean and ind_clean:
        if ind_clean.lower().startswith(aula_clean.lower()):
            return ind_clean
        return f"{aula_clean}, {ind_clean}"

    return aula_clean or ind_clean or (luogo_str.strip() if isinstance(luogo_str, str) else "")

def generate_stable_uid(item, location_str):
    """Versione v7 dell'UID per forzare l'aggiornamento grafico immediato."""
    raw_id = f"{item.get('cod_modulo', '')}_{item.get('start', '')}_{item.get('end', '')}_{item.get('title', '')}_{location_str}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest() + "@unibo-sid-v7"

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

        # Posizione (Aula + Indirizzo)
        location_str = extract_full_location(item)
        if location_str:
            event.add('location', location_str)

        event.add('uid', generate_stable_uid(item, location_str))

        # Organizzatore ("Invitation from Docente")
        docente = item.get('docente', '').strip() if item.get('docente') else ''
        if docente:
            organizer = vCalAddress('mailto:docente@unibo.it')
            organizer.params['cn'] = vText(docente)
            event['organizer'] = organizer

        # Alert 30 min prima della lezione
        alarm = Alarm()
        alarm.add('action', 'DISPLAY')
        alarm.add('description', f"Promemoria lezione: {clean_title(raw_title)}")
        alarm.add('trigger', timedelta(minutes=-30))
        event.add_component(alarm)

        # Note / Fonte
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
