"""Optional AI analysis through OpenRouter (https://openrouter.ai), an OpenAI-compatible chat API.

Configuration (environment / .env only; never sent to the browser, logged or stored):
  OPENROUTER_API_KEY            required to enable AI features
  OPENROUTER_MODEL              required; a model ID from https://openrouter.ai/models
  PLACCRIC_AI_DAILY_LIMIT       requests per UTC day across the workspace (default 25)
  PLACCRIC_AI_MAX_OUTPUT_TOKENS maximum answer length per request (default 1500)
  OPENROUTER_BASE_URL           advanced: API base URL (default https://openrouter.ai/api/v1)

Requests happen only when a user clicks an AI button. Identical requests (same model, kind,
evidence and question) are answered from the ai_requests cache without a new call. Every call
is logged with its token usage. Answers are labelled as AI-generated in the UI.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
TIMEOUT_SECONDS = 90

SYSTEM_PROMPT = """You are PlacCric's cricket analyst for a club captain in Malaysian amateur T20/T25 cricket.
Rules:
- Use ONLY the JSON evidence provided. Every number you mention must appear in, or be directly computed from, it.
- Never invent players, scores, conditions, pitch reports, ball-by-ball facts, line/length, pace/spin or phase data.
- State sample sizes. When evidence is thin (few matches or innings), say so plainly and keep advice tentative.
- Respect the listed data_limits. If a question cannot be answered from the evidence, say what data would be needed.
- Be practical and specific: name players, give concrete plans a club captain can use.
- Write concise Markdown with '## ' headings and '- ' bullet points. No tables. Under 450 words."""

TASKS = {
    'matchup': ('Prepare a match plan for the captain of "{team}" against "{opponent}". Sections: '
                '## Summary, ## Their threats, ## Our strengths, ## Batting plan, ## Bowling plan, '
                '## Key match-ups, ## Uncertainty and data gaps.'),
    'player': ('Write a scouting report on {subject}. Sections: ## Summary, ## Batting, ## Bowling, '
               '## How to bowl to / bat against this player (only what the evidence supports), ## Data gaps.'),
    'compare': ('Compare {subject} for selection purposes. Sections: ## Summary, ## Batting, ## Bowling, '
                '## Which situations suit each, ## Data gaps. Do not declare one player better overall '
                'when samples are small.'),
}


class AiNotConfigured(RuntimeError):
    pass


class AiError(RuntimeError):
    pass


def settings():
    def number(name, default, low, high):
        try:
            return max(low, min(high, int(os.environ.get(name, '') or default)))
        except ValueError:
            return default
    return {'api_key': os.environ.get('OPENROUTER_API_KEY', '').strip(),
            'model': os.environ.get('OPENROUTER_MODEL', '').strip(),
            'daily_limit': number('PLACCRIC_AI_DAILY_LIMIT', 25, 0, 1000),
            'max_tokens': number('PLACCRIC_AI_MAX_OUTPUT_TOKENS', 1500, 200, 8000),
            'base_url': (os.environ.get('OPENROUTER_BASE_URL', '').strip() or DEFAULT_BASE_URL).rstrip('/')}


def _today_start():
    n = datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def status(db):
    s = settings()
    used = db.execute(text('SELECT count(*) FROM ai_requests WHERE created_at >= :d'), {'d': _today_start()}).scalar_one()
    return {'configured': bool(s['api_key'] and s['model']), 'provider': 'OpenRouter', 'model': s['model'] or None,
            'daily_limit': s['daily_limit'], 'used_today': used, 'max_output_tokens': s['max_tokens'],
            'missing': [k for k, v in (('OPENROUTER_API_KEY', s['api_key']), ('OPENROUTER_MODEL', s['model'])) if not v]}


def cache_key(model, kind, evidence, question):
    blob = json.dumps({'model': model, 'kind': kind, 'evidence': evidence, 'question': question, 'prompt': SYSTEM_PROMPT},
                      sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def messages(kind, evidence, question, **names):
    task = TASKS[kind].format(**names)
    if question:
        task += f'\nThe captain also asks: "{question}". Answer it within the relevant section.'
    return [{'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': task + '\n\nEvidence (JSON):\n' + json.dumps(evidence, default=str, ensure_ascii=False)}]


def _call(s, msgs, transport=None):
    headers = {'Authorization': f'Bearer {s["api_key"]}', 'X-Title': 'PlacCric', 'Content-Type': 'application/json'}
    body = {'model': s['model'], 'messages': msgs, 'max_tokens': s['max_tokens'], 'temperature': 0.3}
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            r = client.post(s['base_url'] + '/chat/completions', headers=headers, json=body)
    except httpx.HTTPError as e:
        raise AiError(f'Could not reach OpenRouter ({type(e).__name__}).')
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or 'error' in data:
        message = str((data.get('error') or {}).get('message') or r.reason_phrase or 'unknown error')[:200]
        raise AiError(f'OpenRouter returned {r.status_code}: {message}')
    try:
        answer = data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        raise AiError('OpenRouter returned an unexpected response.')
    if not answer.strip():
        raise AiError('The model returned an empty answer.')
    usage = data.get('usage') or {}
    return answer.strip(), usage.get('prompt_tokens'), usage.get('completion_tokens')


def analyze(engine, kind, subject, evidence, question='', created_by='workspace PIN user', refresh=False,
            transport=None, **names):
    """Return {'answer', 'model', 'cached', 'created_at', 'prompt_tokens', 'completion_tokens'}."""
    s = settings()
    if not (s['api_key'] and s['model']):
        raise AiNotConfigured('AI is not configured. Add OPENROUTER_API_KEY and OPENROUTER_MODEL to .env and restart.')
    key = cache_key(s['model'], kind, evidence, question)
    with engine.connect() as db:
        if not refresh:
            hit = db.execute(text("SELECT answer, model, created_at, prompt_tokens, completion_tokens FROM ai_requests "
                                  "WHERE cache_key=:k AND status='ok' ORDER BY id DESC LIMIT 1"), {'k': key}).mappings().first()
            if hit:
                return {**dict(hit), 'cached': True}
        used = db.execute(text('SELECT count(*) FROM ai_requests WHERE created_at >= :d'), {'d': _today_start()}).scalar_one()
    if used >= s['daily_limit']:
        raise AiError(f'The daily AI limit ({s["daily_limit"]} requests) has been reached. It resets at 00:00 UTC; '
                      'change PLACCRIC_AI_DAILY_LIMIT to adjust it.')
    row = {'at': datetime.now(timezone.utc), 'by': created_by, 'kind': kind, 'subject': subject[:300], 'model': s['model'],
           'key': key, 'pt': None, 'ct': None, 'answer': '', 'error': ''}
    try:
        row['answer'], row['pt'], row['ct'] = _call(s, messages(kind, evidence, question, subject=subject, **names), transport)
        row['status'] = 'ok'
    except AiError as e:
        row.update(status='error', error=str(e))
    with engine.begin() as db:
        db.execute(text('INSERT INTO ai_requests(created_at, created_by, kind, subject, model, cache_key, status, '
                        'prompt_tokens, completion_tokens, answer, error) VALUES (:at, :by, :kind, :subject, :model, :key, '
                        ':status, :pt, :ct, :answer, :error)'), row)
    if row['status'] != 'ok':
        raise AiError(row['error'])
    return {'answer': row['answer'], 'model': row['model'], 'cached': False, 'created_at': row['at'],
            'prompt_tokens': row['pt'], 'completion_tokens': row['ct']}
