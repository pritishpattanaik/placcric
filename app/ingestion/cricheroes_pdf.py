"""Reader for the scorecard PDF that CricHeroes offers as "Download Scorecard".

The PDF is generated from the scorecard page and has a real text layer, so it is read
deterministically with pypdf's layout extraction (no OCR, nothing inferred). The PDF contains
names but no CricHeroes player or match IDs: the match ID comes from the upload (the download is
named Scorecard_<matchid>.pdf) and players are identified in the review step.

Anything that cannot be read exactly is reported as an error rather than skipped.
"""
import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PAGES = 12

HEADER = re.compile(r'^\s*(?P<team>\S.*?) (?P<runs>\d+)/(?P<wk>\d+) \((?P<ov>\d+(?:\.\d)?) Ov\) '
                    r'\(\d+(?:st|nd|rd|th) Innings\)')
BAT_ROW = re.compile(r'^\s*(?P<no>\d+)\s+(?P<name>\S.*?)\s{2,}(?P<status>\S.*?)\s{2,}(?P<r>\d+)\s+(?P<b>\d+)\s+'
                     r'(?P<m>\d+|-)\s+(?P<f>\d+)\s+(?P<s>\d+)\s+(?P<sr>[\d.]+|-)\s*$')
BOWL_ROW = re.compile(r'^\s*(?P<no>\d+)\s+(?P<name>\S.*?)\s{2,}(?P<o>\d+(?:\.\d)?)\s+(?P<m>\d+)\s+(?P<r>\d+)\s+'
                      r'(?P<w>\d+)\s+(?P<dots>\d+)\s+(?P<f>\d+)\s+(?P<s>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s+'
                      r'(?P<eco>[\d.]+|-)\s*$')
# Fall of wickets entry, e.g. '39-2 (SHARIF HASAN (Rabbi), 5.4 ov)'; entries may wrap across lines.
FOW = re.compile(r'(\d+)-(\d+)\s*\((.+?),\s*(\d+(?:\.\d)?)\s+ov\)')
NUMBERED = re.compile(r'^\s*\d+\s+\S')
EXTRAS = re.compile(r'^\s*Extras:\s*(?:\((?P<detail>[^)]*)\))?.*?(?P<n>\d+)\s*$')
TOTAL = re.compile(r'^\s*Total:\s*Overs\s+(?P<ov>\d+(?:\.\d)?),\s*Wickets\s+(?P<wk>\d+)\s+(?P<runs>\d+)')
FOOTER = re.compile(r'^\s*(?P<printed>\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2}\s*[AP]M)\s+cricheroes\.com\s+\d+ of \d+\s*$')
ROLE = re.compile(r'\(\s*(?:c|wk|c\s*&\s*wk|wk\s*&\s*c|lhb|rhb)\s*\)', re.I)
DETAILS_LABELS = {'Match', 'Ground', 'Date', 'Toss', 'Total', 'Result'}


class ScorecardPdfError(ValueError):
    pass


def clean_name(raw):
    """Display name without role or batting-hand markers: 'AU Mahi (wk) (RHB)' -> 'AU Mahi'."""
    return re.sub(r'\s+', ' ', ROLE.sub('', raw.replace('†', ''))).strip()


def alias_key(raw):
    """Case- and spacing-insensitive key for a scorecard name. Punctuation is kept on purpose:
    'Md. Anowar Zahid' and 'Md Anowar Zahid' are different keys until an admin links them."""
    return clean_name(raw).casefold()


def loose_key(raw):
    """Letters and digits only. Used for review hints and suggestions, never to merge players."""
    return re.sub(r'[^0-9a-z]', '', clean_name(raw).casefold())


def balls_from_overs(value, where):
    whole, _, part = value.partition('.')
    if part and int(part) > 5:
        raise ScorecardPdfError(f'{where}: "{value}" is not valid cricket overs notation')
    return int(whole) * 6 + int(part or 0)


def extract_text(data):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ScorecardPdfError('The PDF is encrypted; download the scorecard again without a password.')
        if len(reader.pages) > MAX_PAGES:
            raise ScorecardPdfError(f'The PDF has {len(reader.pages)} pages; a scorecard has at most {MAX_PAGES}.')
        return '\n'.join(page.extract_text(extraction_mode='layout') for page in reader.pages)
    except ScorecardPdfError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        raise ScorecardPdfError(f'The file could not be read as a PDF ({type(e).__name__}).')


def _details(lines):
    """Two-column 'Match Details | Match Result' block -> {label: value}."""
    start = next((i for i, l in enumerate(lines) if 'Match Details' in l and 'Match Result' in l), None)
    if start is None:
        raise ScorecardPdfError('This does not look like a CricHeroes scorecard PDF (no "Match Details" section).')
    mid = lines[start].index('Match Result')
    fields, current = {}, {'left': None, 'right': None}
    for line in lines[start + 1:]:
        if 'Best Performances' in line or HEADER.match(line):
            break
        for side, part in (('left', line[:mid]), ('right', line[mid:])):
            part = part.strip()
            if not part:
                continue
            label, _, value = part.partition(' ')
            if label in DETAILS_LABELS:
                current[side] = label
                fields.setdefault(label, []).append(value.strip())
            elif current[side]:
                fields[current[side]].append(part)
    return {k: ' '.join(v).strip() for k, v in fields.items()}


def _squads(lines):
    """Playing squads by team name, from the two-column 'Playing Squad' table."""
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == 'Playing Squad')
    except StopIteration:
        return {}
    squads, header = {}, None
    for line in lines[start + 1:]:
        if HEADER.match(line) or FOOTER.match(line):
            break
        if header is None and line.strip():
            names = re.split(r'\s{2,}', line.strip())
            if len(names) == 2:
                # A lone name is assigned to the column whose heading it is closer to.
                split = (line.index(names[0]) + line.index(names[1])) // 2
                header = (names, split)
                squads = {names[0]: [], names[1]: []}
            continue
        m = re.match(r'^\s*\d+\s+', line)
        if header and m:
            (left_team, right_team), split = header
            parts = re.split(r'\s{2,}', line[m.end():].strip())
            if len(parts) == 2:
                squads[left_team].append(clean_name(parts[0]))
                squads[right_team].append(clean_name(parts[1]))
            elif len(parts) == 1 and parts[0]:
                side = left_team if line.index(parts[0], m.end()) < split else right_team
                squads[side].append(clean_name(parts[0]))
    return squads


def parse(data):
    """Parse PDF bytes into {'record': …, 'source': …, 'warnings': […]}. Player rows have names, no IDs."""
    text_ = extract_text(data)
    lines = text_.splitlines()
    if 'cricheroes.com' not in text_:
        raise ScorecardPdfError('This does not look like a CricHeroes scorecard PDF (no cricheroes.com footer).')
    title = next((l.strip() for l in lines if l.strip()), '')
    tm = re.match(r'^(?P<name>.+?)\s*\((?P<stage>[^()]*)\)$', title)
    printed = next((m['printed'] for m in map(FOOTER.match, lines) if m), '')
    details = _details(lines)
    content = [l for l in lines if not FOOTER.match(l) and l.strip() != title]

    innings, cur, section = [], None, None
    for line in content:
        h = HEADER.match(line)
        if h:
            cur = {'team': h['team'].strip(), 'runs': int(h['runs']), 'wickets': int(h['wk']),
                   'balls': balls_from_overs(h['ov'], 'Innings header'), 'batting': [], 'bowling': []}
            innings.append(cur)
            section = 'batting'
            continue
        if cur is None:
            continue
        where = f'Innings {len(innings)} ({cur["team"]})'
        if 'Bowler' in line and 'Eco' in line:
            section = 'bowling'
            continue
        if re.match(r'^\s*Fall of Wickets', line, re.I):
            section = 'fow'
            cur['_fow'] = []
            continue
        if re.match(r'^\s*(To Bat|Did not bat|Yet to bat)', line, re.I):
            section = None
            continue
        if section == 'fow':
            cur['_fow'].append(line.strip())
            continue
        e = EXTRAS.match(line)
        if e and section == 'batting':
            cur['extras'] = int(e['n'])
            if e['detail'] is not None:
                cur['extras_detail'] = {k: int(v) for k, v in re.findall(r'\b(wd|nb|lb|b|p)\s+(\d+)', e['detail'])}
            continue
        t = TOTAL.match(line)
        if t and section == 'batting':
            if (int(t['runs']), int(t['wk']), balls_from_overs(t['ov'], where)) != (cur['runs'], cur['wickets'], cur['balls']):
                raise ScorecardPdfError(f'{where}: the "Total" line disagrees with the innings header')
            continue
        if section == 'batting':
            m = BAT_ROW.match(line)
            if m:
                status = m['status'].strip()
                cur['batting'].append({'name': clean_name(m['name']), 'source_name': m['name'].strip(),
                                       'runs': int(m['r']), 'balls': int(m['b']), 'fours': int(m['f']),
                                       'sixes': int(m['s']), 'dismissal': status,
                                       'not_out': status.lower() in ('not out', 'retired hurt', 'retired not out')})
            elif NUMBERED.match(line) and 'Batsman' not in line:
                raise ScorecardPdfError(f'{where}: could not read batting row "{line.strip()[:120]}"')
        elif section == 'bowling':
            m = BOWL_ROW.match(line)
            if m:
                cur['bowling'].append({'name': clean_name(m['name']), 'source_name': m['name'].strip(),
                                       'balls': balls_from_overs(m['o'], where), 'runs': int(m['r']),
                                       'wickets': int(m['w']), 'dots': int(m['dots']), 'wides': int(m['wd']),
                                       'no_balls': int(m['nb'])})
            elif NUMBERED.match(line):
                raise ScorecardPdfError(f'{where}: could not read bowling row "{line.strip()[:120]}"')

    if not innings:
        raise ScorecardPdfError('No innings were found in the PDF.')
    for no, inn in enumerate(innings, 1):
        if 'extras' not in inn:
            raise ScorecardPdfError(f'Innings {no} ({inn["team"]}): no "Extras" line was found')
        if not inn['batting'] or not inn['bowling']:
            raise ScorecardPdfError(f'Innings {no} ({inn["team"]}): batting or bowling table is missing')
        fow_text = ' '.join(inn.pop('_fow', []))
        if fow_text:
            inn['fall_of_wickets'] = [
                {'wicket': int(w), 'runs': int(r), 'balls': balls_from_overs(o, f'Innings {no} fall of wickets'),
                 'batter': clean_name(name)}
                for r, w, name, o in FOW.findall(fow_text)]

    team1 = innings[0]['team']
    team2 = innings[1]['team'] if len(innings) > 1 else ''
    result = details.get('Result', '')
    won = re.match(r'^(?P<team>.+?) won\b', result)
    winner = next((t for t in (team1, team2) if won and t.casefold() == won['team'].strip().casefold()), None)
    date = re.match(r'(\d{4}-\d{2}-\d{2})', details.get('Date', ''))
    dls = bool(re.search(r'\b(DLS|D/L|VJD)\b', result))
    warnings = []
    squads = _squads(lines)
    for no, inn in enumerate(innings, 1):
        squad = {loose_key(n) for n in squads.get(inn['team'], [])}
        if squad:
            for r in inn['batting']:
                if loose_key(r['name']) not in squad:
                    warnings.append(f'Innings {no}: batter "{r["name"]}" is not in the {inn["team"]} playing squad '
                                    'listed in the PDF')
    if dls:
        warnings.append('The result was decided by a rain rule (DLS/VJD); compare rates with care.')
    record = {'id': '', 'date': date[1] if date else '', 'venue': details.get('Ground', ''), 'team1': team1,
              'team2': team2, 'winner': winner, 'result': result, 'toss': details.get('Toss', ''), 'pom': '',
              'dls': dls, 'warning': 'Rain-affected result (per source).' if dls else '',
              'stage': tm['stage'].strip() if tm else '', 'source_url': '',
              'retrieved_at': f'PDF generated {printed}' if printed else '', 'innings': innings}
    return {'record': record,
            'source': {'title': title, 'tournament_title': tm['name'].strip() if tm else title,
                       'printed_at': printed, 'squads': squads},
            'warnings': warnings}
