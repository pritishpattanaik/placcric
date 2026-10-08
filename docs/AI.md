# AI analysis (optional, OpenRouter)

PlacCric works fully without AI. When you add an OpenRouter key, captains get AI-written analysis on top of the statistics PlacCric already computes. Every number given to the model comes from your imported, approved scorecards.

## Where it appears

| Page | Feature | What the model receives |
| --- | --- | --- |
| Captain's room | **AI tactical brief** for your team against an opposition, with an optional question ("We bat first, who opens the bowling?") | The team-against-team report shown on the page: records, run rates, economy, head to head, top batters/bowlers, how wickets fall, who dismissed whom, pivot points (wickets by over phase, collapses, partnerships) and data limits. Your saved match plan notes only if you tick "Include my saved match plan notes". |
| Player profile | **AI performance diagnosis** | That player's recorded innings and spells, batting role/positions, how they were dismissed, dot-ball %. |
| Compare players | **AI selection verdict** | Both players' records (same fields as above). |
| Match scorecard | **AI match debrief** | That match's scorecard, fall of wickets, collapses and partnerships. |
| PlacCric coach | **Answer with AI** checkbox | The selected player's record plus your question. Without the checkbox the coach stays rules-based. |

The page shows the deterministic statistics and charts first (comparison butterfly chart, wicket timelines, pivot cards); the AI panel is below them, labelled with the model name, and every answer says it is AI-generated and should be checked against the figures.

## Structured briefs (short answers, no "thinking" text)

The model is asked for **one JSON object** in a fixed shape (`app/ai/briefs.py`), never free prose:

- **Tactical brief** — headline, confidence, then three tiers: *Pivot points* (up to 3), *Matchup matrix* (threats and our-player-vs-their-player plans), *Blueprint* (batting, bowling, field).
- **Performance diagnosis** — headline, role, short answer to the question, patterns (label/value/insight), diagnosis (intent / technique / shot selection / bowling), up to 3 drills, strengths.
- **Selection verdict** — who to pick per situation (A / B / either / unclear) and per-metric edges.
- **Match debrief** — turning points, what went well / to improve per team, standout players.

Every brief carries a confidence level and data gaps. PlacCric validates the answer (types, allowed values, list sizes, length limits) and shows only the validated fields, so reasoning text that "thinking" models write before the answer is discarded. If no valid object is found you get a clear error instead of raw model text; try again or pick a model whose OpenRouter page lists *structured outputs* / *response format* support. Free "lightning"/reasoning models work but are less reliable at following the shape.

**Not implemented, deliberately:** a "what-if" simulator, line/length or pace/spin analysis, phase strike rates per batter, synthetic ball-by-ball data and weather/pitch tags. Scorecard PDFs do not contain that information, and generating it would be fabricated statistics. Pivot points use the fall-of-wickets list printed on the scorecard instead.

## Setup

1. Create an account and key at https://openrouter.ai/keys. **Set a credit/spending limit on the key in OpenRouter** — that is your hard cost cap.
2. Choose a model at https://openrouter.ai/models and copy its ID.
3. Add to `.env` (stage: your MacBook project folder; never commit it):
   ```
   OPENROUTER_API_KEY=sk-or-...
   OPENROUTER_MODEL=<model id from openrouter.ai/models>
   PLACCRIC_AI_DAILY_LIMIT=25
   PLACCRIC_AI_MAX_OUTPUT_TOKENS=2000
   ```
4. Restart: `docker compose up -d app` (or `scripts/deploy.sh main`). The AI panels then show the model name; without a key they say "AI · OFF" and explain what is missing.

`OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`) exists for testing and proxies; leave it unset.

## Cost controls

- Requests happen **only when someone clicks** Generate / Ask again / sends a coach question with AI ticked. Viewing pages never calls the AI, and there is no background job.
- **Daily cap**: `PLACCRIC_AI_DAILY_LIMIT` requests per UTC day for the whole workspace (default 25; failed calls count).
- **Answer length cap**: `PLACCRIC_AI_MAX_OUTPUT_TOKENS` (default 2000).
- **Cache**: an identical request (same model, evidence and question) returns the saved answer for free. "Ask again" forces a new request.
- **Log**: every request is stored in the `ai_requests` table with time, model, subject, token counts and status. Rough cost per request = tokens × your model's price on openrouter.ai.
- The OpenRouter key's own credit limit is the ultimate safeguard.

## Privacy: what leaves your server

Sent to OpenRouter (and on to the model provider it routes to): team names, player names, the statistics listed above, the tournament name, your optional question, and your match plan notes only when you tick the box.

Never sent: CricHeroes player or match IDs, your PIN or sessions, uploaded PDF files, other teams' notes, database passwords, or the API key (it is used only in the request header).

Player names are personal data of third parties (opponents included). Use AI features only if you are comfortable sending them to OpenRouter under its privacy policy and the chosen model provider's terms. OpenRouter lets you restrict which providers may receive your data in your account settings.

## Accuracy rules given to the model

The system prompt (`app/ai/openrouter.py`) instructs the model to use only the provided JSON evidence, never invent statistics, conditions or ball-by-ball facts, state sample sizes, respect the data limits and say what data would be needed when it cannot answer. Models can still make mistakes; the statistics on the page are the source of truth.

## Where the code is

- `app/matchup.py` — team-against-team report, pivot points (phases, collapses, partnerships), player cards and dismissal parsing (deterministic, tested).
- `app/ai/evidence.py` — builds the evidence packs on the server (the browser cannot supply numbers).
- `app/ai/briefs.py` — brief shapes, extraction from model output and validation.
- `app/ai/openrouter.py` — settings, caching, daily cap, logging, the HTTP call.
- `tests/test_ai.py` — uses a mocked OpenRouter; tests never contact the real service.
