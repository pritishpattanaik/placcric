"""Synthetic scorecard PDFs in the CricHeroes "Download Scorecard" layout, for tests.

All teams and players are invented. A tiny PDF writer places each text line with a monospaced
font, so pypdf's layout extraction reproduces the column spacing of the real downloads.
"""
import copy

TITLE = 'TEST LEAGUE T20 SEASON 1 (Final)'
FOOTER = ' 1/2/26, 9:00 AM                           cricheroes.com                            {page} of {pages}'

MATCH = {
    'teams': ('Alpha Strikers XI', 'Beta Royals CC'),
    'toss': 'Beta Royals CC opt to field',
    'result': 'Alpha Strikers XI won by 20 runs',
    'ground': ('Test Oval,', 'Testville'),
    'date': '2026-01-02, 10:00 AM UTC',
    'squads': (['Ann One', 'Ben Two', 'Cal Three', 'Dev Four', 'Eli Five', 'Fay Six', 'Gus Seven', 'Md Hal Eight'],
               ['Ian Nine', 'Jo Ten', 'Kit Eleven', 'Lee Twelve', 'Max Thirteen', 'Ned Fourteen', 'Oli Fifteen',
                'Pat Sixteen', 'Quin Seventeen', 'Ray Eighteen']),
    'innings': [
        {'runs': 120, 'wickets': 5, 'overs': '20.0', 'extras': 12, 'extras_text': 'wd 5, nb 1, b 4, lb 2',
         'batting': [('Ann One (RHB)', 'c Ian Nine b Jo Ten', 40, 30, 4, 1), ('Ben Two (wk) (LHB)', 'b Jo Ten', 30, 25, 2, 1),
                     ('Cal Three (c) (RHB)', 'lbw b Kit Eleven', 20, 20, 1, 0),
                     ('Dev Four (RHB)', 'c Lee Twelve b Max Thirteen', 10, 15, 0, 0),
                     ('Eli Five (RHB)', 'run out Ned Fourteen', 5, 10, 0, 0), ('Fay Six (RHB)', 'not out', 3, 5, 0, 0)],
         'fow': [(55, 1, 'Ann One', '6.2'), (60, 2, 'Ben Two', '7.4'), (64, 3, 'Cal Three', '8.5'),
                 (95, 4, 'Dev Four', '14.1'), (112, 5, 'Eli Five', '18.3')],
         'bowling': [('Jo Ten', '4', 25, 2, 10, 2, 0), ('Kit Eleven', '4', 30, 1, 8, 1, 1),
                     ('Max Thirteen', '4', 20, 1, 12, 2, 0), ('Ned Fourteen', '4', 22, 0, 9, 0, 0),
                     ('Oli Fifteen (c)', '4', 17, 0, 11, 0, 0)]},
        {'runs': 100, 'wickets': 9, 'overs': '20.0', 'extras': 5, 'extras_text': 'wd 3, lb 2',
         'batting': [('Ian Nine (RHB)', 'c Ann One b Ben Two', 25, 20, 3, 0), ('Jo Ten (RHB)', 'b Cal Three', 20, 18, 2, 0),
                     ('Kit Eleven (RHB)', 'b Cal Three', 15, 14, 1, 0), ('Lee Twelve (wk) (RHB)', 'b Dev Four', 10, 12, 0, 0),
                     ('Max Thirteen (RHB)', 'b Dev Four', 8, 9, 0, 0), ('Ned Fourteen (RHB)', 'b Eli Five', 6, 8, 0, 0),
                     ('Oli Fifteen (c) (RHB)', 'b Eli Five', 5, 6, 0, 0), ('Pat Sixteen (RHB)', 'b Md. Hal Eight', 4, 5, 0, 0),
                     ('Quin Seventeen (RHB)', 'c Ann One b Ben Two', 2, 3, 0, 0), ('Ray Eighteen (LHB)', 'not out', 0, 1, 0, 0)],
         'fow': [(30, 1, 'Ian Nine', '4.1'), (52, 2, 'Jo Ten', '8.0'), (70, 3, 'Kit Eleven', '11.2'),
                 (80, 4, 'Lee Twelve', '13.4'), (84, 5, 'Max Thirteen', '14.5'), (88, 6, 'Ned Fourteen', '15.3'),
                 (92, 7, 'Oli Fifteen', '16.4'), (96, 8, 'Pat Sixteen', '18.1'), (99, 9, 'Quin Seventeen', '19.2')],
         'bowling': [('Ben Two', '4', 20, 2, 10, 1, 0), ('Cal Three (c)', '4', 18, 2, 11, 0, 0),
                     ('Dev Four', '4', 22, 2, 9, 1, 0), ('Eli Five', '4', 17, 2, 12, 1, 0),
                     ('Md. Hal Eight', '4', 21, 1, 8, 0, 0)]},
    ],
}


def spec(**changes):
    s = copy.deepcopy(MATCH)
    s.update(changes)
    return s


def _innings_lines(team, inn):
    head = f'{team} {inn["runs"]}/{inn["wickets"]} ({inn["overs"]} Ov) (1st Innings)'
    lines = [head, f'  {"No":<7}{"Batsman":<42}{"Status":<40}{"R":>4}{"B":>6}{"M":>6}{"4s":>6}{"6s":>6}{"SR":>9}']
    for no, (name, status, r, b, f, s) in enumerate(inn['batting'], 1):
        sr = f'{r * 100 / b:.2f}' if b else '0.00'
        lines.append(f'  {no:<7}{name:<42}{status:<40}{r:>4}{b:>6}{b + 3:>6}{f:>6}{s:>6}{sr:>9}')
    lines.append(f'  {"Extras: (" + inn["extras_text"] + ")":<101}{inn["extras"]:>6}')
    lines.append(f'  {"Total: Overs " + inn["overs"] + ", Wickets " + str(inn["wickets"]):<101}{inn["runs"]:>6}')
    lines.append('')
    lines.append(f'  {"No":<8}{"Bowler":<40}{"O":>5}{"M":>5}{"R":>6}{"W":>6}{"0s":>6}{"4s":>6}{"6s":>6}{"WD":>6}{"NB":>6}{"Eco":>8}')
    for no, (name, o, r, w, dots, wd, nb) in enumerate(inn['bowling'], 1):
        balls = int(o.split('.')[0]) * 6 + int((o.split('.') + ['0'])[1])
        lines.append(f'  {no:<8}{name:<40}{o:>5}{0:>5}{r:>6}{w:>6}{dots:>6}{1:>6}{0:>6}{wd:>6}{nb:>6}{r * 6 / balls:>8.2f}')
    lines += ['', 'Fall of Wickets']
    entries = [f'{r}-{w} ({name}, {ov} ov)' for r, w, name, ov in inn.get('fow', [])]
    # Wrap like the real PDF: entries continue on the next line, sometimes mid-entry.
    text = ', '.join(entries)
    lines += [text[i:i + 110] for i in range(0, len(text), 110)] or ['']
    return lines


def lines_for(s):
    t1, t2 = s['teams']
    details = [
        f'{"":<30}{TITLE if "title" not in s else s["title"]}',
        f'{"Match Details":<62}Match Result',
        f'  {"Match":<12}{t1 + " vs":<48}{"Toss":<8}{s["toss"]}',
        f'  {"":<12}{t2:<48}{"Total":<8}{t1} {s["innings"][0]["runs"]}/{s["innings"][0]["wickets"]} ({s["innings"][0]["overs"]} Ov)',
        f'  {"Ground":<12}{s["ground"][0]}',
        f'  {"":<12}{s["ground"][1]:<48}{"Result":<8}{s["result"]}',
        f'  {"Date":<12}{s["date"]}',
        '',
        f'{"Best Performances - Batsmen":<62}Best Performances - Bowlers',
    ]
    squad = [f'{"":<30}{TITLE if "title" not in s else s["title"]}', 'Playing Squad', '',
             f'{"":<30}{t1:<46}{t2}']
    for i in range(max(len(s['squads'][0]), len(s['squads'][1]))):
        left = s['squads'][0][i] if i < len(s['squads'][0]) else ''
        right = s['squads'][1][i] if i < len(s['squads'][1]) else ''
        squad.append(f' {i + 1:<10}{left:<65}{right}')
    pages = [details, squad]
    for team, inn in zip(s['teams'], s['innings']):
        pages.append([f'{"":<30}{TITLE if "title" not in s else s["title"]}', ''] + _innings_lines(team, inn))
    for n, page in enumerate(pages, 1):
        page.append(FOOTER.format(page=n, pages=len(pages)))
    return pages


def _escape(line):
    return line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('latin-1')


def build_pdf(pages):
    """Minimal PDF: one Courier text object per page, one line per row."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', None, b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>']
    kids = []
    for lines in pages:
        stream = b'BT /F1 6 Tf 8 TL 15 820 Td ' + b' '.join(b'(' + _escape(l) + b') Tj T*' for l in lines) + b' ET'
        objects.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
        content_id = len(objects)
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> '
                       b'/Contents %d 0 R >>' % content_id)
        kids.append(len(objects))
    objects[1] = b'<< /Type /Pages /Kids [' + b' '.join(b'%d 0 R' % k for k in kids) + b'] /Count %d >>' % len(kids)
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + obj + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    out += b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


def scorecard_pdf(s=None):
    return build_pdf(lines_for(s or MATCH))
