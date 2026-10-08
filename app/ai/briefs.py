"""Structured AI briefs: the JSON shape each feature asks the model for, and strict validation.

Models are asked for one JSON object only. Some models (especially "thinking" models) still write
reasoning around it, so `extract` takes the last JSON object that matches the schema and ignores
everything else. `validate` enforces types, enum values, list sizes and string lengths, so the UI
always receives a compact, predictable brief — or an error, never raw model text.
"""
import json
import re

CONFIDENCE = ('low', 'medium', 'high')

# Field spec: ('str', max_len) | ('enum', values) | ('list', max_items, item_spec) | ('obj', {field: spec})
S = lambda n: ('str', n)  # noqa: E731
GAPS = ('list', 3, S(140))

SCHEMAS = {
    'matchup': {
        'headline': S(140), 'confidence': ('enum', CONFIDENCE),
        'pivot_points': ('list', 3, ('obj', {'title': S(60), 'insight': S(200), 'evidence': S(140)})),
        'threats': ('list', 4, ('obj', {'player': S(60), 'team': S(80), 'threat': S(160), 'evidence': S(120)})),
        'matchups': ('list', 4, ('obj', {'our_player': S(60), 'their_player': S(60), 'plan': S(160), 'evidence': S(120)})),
        'blueprint': ('obj', {'batting': ('list', 4, S(140)), 'bowling': ('list', 4, S(140)), 'field': ('list', 3, S(140))}),
        'data_gaps': GAPS,
    },
    'player': {
        'headline': S(140), 'confidence': ('enum', CONFIDENCE), 'role': S(40), 'answer': S(320),
        'patterns': ('list', 4, ('obj', {'label': S(40), 'value': S(30), 'insight': S(160)})),
        'diagnosis': ('list', 3, ('obj', {'area': ('enum', ('intent', 'technique', 'shot selection', 'bowling', 'other')),
                                          'finding': S(180), 'evidence': S(120)})),
        'drills': ('list', 3, ('obj', {'name': S(50), 'focus': S(80), 'detail': S(180)})),
        'strengths': ('list', 3, S(120)),
        'data_gaps': GAPS,
    },
    'compare': {
        'headline': S(140), 'confidence': ('enum', CONFIDENCE),
        'verdicts': ('list', 5, ('obj', {'situation': S(60), 'pick': ('enum', ('A', 'B', 'either', 'unclear')),
                                         'reason': S(160)})),
        'edges': ('list', 5, ('obj', {'metric': S(40), 'edge': ('enum', ('A', 'B', 'even')), 'note': S(120)})),
        'data_gaps': GAPS,
    },
    'debrief': {
        'headline': S(140), 'confidence': ('enum', CONFIDENCE),
        'turning_points': ('list', 3, ('obj', {'title': S(60), 'insight': S(200), 'evidence': S(140)})),
        'team_reviews': ('list', 2, ('obj', {'team': S(80), 'went_well': ('list', 3, S(140)), 'to_improve': ('list', 3, S(140))})),
        'standouts': ('list', 4, ('obj', {'player': S(60), 'team': S(80), 'contribution': S(140)})),
        'data_gaps': GAPS,
    },
}

EXAMPLES = {
    'matchup': {'headline': '…', 'confidence': 'low|medium|high',
                'pivot_points': [{'title': '…', 'insight': '…', 'evidence': 'number from evidence'}],
                'threats': [{'player': '…', 'team': '…', 'threat': '…', 'evidence': '…'}],
                'matchups': [{'our_player': '…', 'their_player': '…', 'plan': '…', 'evidence': '…'}],
                'blueprint': {'batting': ['…'], 'bowling': ['…'], 'field': ['…']}, 'data_gaps': ['…']},
    'player': {'headline': '…', 'confidence': 'low|medium|high', 'role': '…', 'answer': '… or empty',
               'patterns': [{'label': '…', 'value': '…', 'insight': '…'}],
               'diagnosis': [{'area': 'intent|technique|shot selection|bowling|other', 'finding': '…', 'evidence': '…'}],
               'drills': [{'name': '…', 'focus': '…', 'detail': '…'}], 'strengths': ['…'], 'data_gaps': ['…']},
    'compare': {'headline': '…', 'confidence': 'low|medium|high',
                'verdicts': [{'situation': '…', 'pick': 'A|B|either|unclear', 'reason': '…'}],
                'edges': [{'metric': '…', 'edge': 'A|B|even', 'note': '…'}], 'data_gaps': ['…']},
    'debrief': {'headline': '…', 'confidence': 'low|medium|high',
                'turning_points': [{'title': '…', 'insight': '…', 'evidence': '…'}],
                'team_reviews': [{'team': '…', 'went_well': ['…'], 'to_improve': ['…']}],
                'standouts': [{'player': '…', 'team': '…', 'contribution': '…'}], 'data_gaps': ['…']},
}


class BriefError(ValueError):
    pass


def _clip(text_, n):
    text_ = re.sub(r'\s+', ' ', str(text_)).strip()
    return text_ if len(text_) <= n else text_[:n - 1].rstrip() + '…'


def _coerce(spec, value, path):
    kind = spec[0]
    if kind == 'str':
        if value is None:
            return ''
        if not isinstance(value, (str, int, float)):
            raise BriefError(f'{path} should be text')
        return _clip(value, spec[1])
    if kind == 'enum':
        v = str(value or '').strip()
        match = next((e for e in spec[1] if e.lower() == v.lower()), None)
        if match is None:
            raise BriefError(f'{path} must be one of {", ".join(spec[1])}')
        return match
    if kind == 'list':
        if value is None:
            return []
        if not isinstance(value, list):
            raise BriefError(f'{path} should be a list')
        items = [_coerce(spec[2], v, f'{path}[{i}]') for i, v in enumerate(value[:spec[1]])]
        return [i for i in items if i not in ('', {}, [])]
    if kind == 'obj':
        if not isinstance(value, dict):
            raise BriefError(f'{path} should be an object')
        return {k: _coerce(s, value.get(k), f'{path}.{k}') for k, s in spec[1].items()}
    raise AssertionError(kind)


def validate(kind, data):
    if not isinstance(data, dict):
        raise BriefError('the answer is not a JSON object')
    brief = _coerce(('obj', SCHEMAS[kind]), data, kind)
    if not brief['headline']:
        raise BriefError('the answer has no headline')
    return brief


def extract(kind, content):
    """Return the validated brief from model output that may include reasoning or code fences."""
    content = (content or '')[:60000]
    decoder, last_error = json.JSONDecoder(), 'no JSON object found'
    candidates = []
    for m in re.finditer(r'\{', content):
        try:
            obj, _ = decoder.raw_decode(content, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and 'headline' in obj:
            candidates.append(obj)
    for obj in reversed(candidates):
        try:
            return validate(kind, obj)
        except BriefError as e:
            last_error = str(e)
    raise BriefError(last_error)
