# FIFA 2026 Polymarket Arb Agent

Daily cron agent that:

1. loads upcoming FIFA 2026 fixtures,
2. estimates each side's regulation win probability with a World Cup-specific calibration layer,
3. enriches the model with API-Football team profile, squad, standings, and tournament-stat context,
4. discovers related Polymarket markets,
5. compares model probability against market-implied probability,
6. sends Telegram only when a probability edge is above threshold.

This is read-only market monitoring. It does not place orders.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

For a Telegram group chat, add the bot to the group, send a message in the group, then call:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

Use the returned group `chat.id`.

## Run

```bash
fifa-arb-agent --dry-run
fifa-arb-agent
```

`--dry-run` prints the report and does not send Telegram.

Normal Telegram delivery sends upcoming match predictions for observation on every
scan, including any matched prediction-market deviations without applying
`EDGE_THRESHOLD`. The threshold is still used to label arbitrage alerts and to filter
stage-market alerts. Each persisted scan report includes upcoming match predictions,
Polymarket comparisons, tournament advancement probabilities, and a rolling backtest
summary.

## Data Inputs

### API-Football Fixtures

The repo includes an API-Football adapter:

```bash
python scripts/update_fixtures.py --dry-run
python scripts/update_fixtures.py
```

Configure it in `.env`:

```env
API_FOOTBALL_KEY=...
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_LEAGUE_ID=1
API_FOOTBALL_SEASON=2026
FIXTURES_PATH=data/fixtures.json
FIXTURES_URL=
```

API-Football league `1` is the men's World Cup. The updater writes normalized fixtures to `data/fixtures.json`, which the agent reads by default.

If API-Football returns a plan/season-access error for `2026`, the key is valid but the current plan does not expose the 2026 season yet. Upgrade API-Football access or run the agent from a manually maintained normalized fixture file until that season is enabled.

`FIXTURES_PATH` expects normalized fixtures:

```json
[
  {
    "match_id": "group-a-001",
    "kickoff_utc": "2026-06-16T19:00:00Z",
    "team_a": "Argentina",
    "team_b": "France",
    "stage": "group",
    "venue": "MetLife Stadium",
    "rest_days_a": 5,
    "rest_days_b": 4
  }
]
```

`FIXTURES_URL` can replace the local file. It should return the same JSON shape.

`TEAM_RATINGS_PATH` holds pre-match team priors. Generate the current complete file from World Football Elo data:

```bash
python scripts/update_ratings.py
```

The default file is `data/team_ratings.json`. It covers every team currently present in `data/fixtures.json`.

```json
{
  "teams": {
    "Argentina": {
      "elo": 2145,
      "fifa_rank": 1,
      "wc_points_last_3": 18,
      "confederation": "CONMEBOL",
      "host": false,
      "form_delta": 0.12,
      "injury_penalty": 0.02
    }
  }
}
```

Update ratings daily from your preferred source, or run `scripts/update_ratings.py` before the agent. `injury_penalty` defaults to `0.0` and should be manually adjusted when team news matters.

### API-Football Team Context

The model also reads `TEAM_CONTEXT_PATH`, generated from API-Football:

```bash
python scripts/update_team_context.py
```

This creates `data/team_context.json` with:

- team ids, codes, logos, founded year, and venue metadata from `/teams`,
- squad size, average age, and position balance from `/players/squads`,
- live World Cup form and goals from `/teams/statistics`,
- group rank, points, and qualification description from `/standings`,
- injury count from `/injuries` when available.

These fields are applied as capped calibration adjustments. Elo remains the main prior; API-Football context moves the forecast only modestly so early-tournament noise does not dominate.

## Tournament Simulation

Each run also simulates the tournament path using `TOURNAMENT_SIMULATIONS`
Monte Carlo runs. The current simulator:

- locks completed group-stage scores from API-Football,
- simulates remaining group matches with the match model,
- advances group top two plus the eight best third-place teams,
- estimates top-8, semi-final, final, and champion probabilities,
- uses a seeded knockout bracket approximation until the official Round-of-32 slot mapping is added.

Configure:

```env
TOURNAMENT_SIMULATIONS=20000
TOURNAMENT_SEED=2026
```

## Calibration Method

The model produces a 3-way regulation-time forecast: `team_a_win`, `draw`, `team_b_win`.
Daily scan reports also show no-draw fair probabilities for each upcoming match, which
are useful when comparing against two-outcome winner/advance markets.
The first score-distribution layer calibrates a Poisson-style grid to the same 1X2
forecast and prices common prediction-market props:

- team handicap `+1.5`, `+2.5`, `-1.5`, `-2.5`,
- win-by-margin phrasing such as `win by 2 or more`,
- total goals over/under `2.5`.

These handicap and total-goals markets are shown as observation deviations in daily
reports. They only become arbitrage alerts when the model edge reaches
`EDGE_THRESHOLD`.

Daily reports also include a balanced combo suggestion for each upcoming match. The
combo mixes:

- a higher-probability handicap safety leg,
- a 1X2 directional leg,
- a smaller upside handicap leg.

The combo prints model probability, fair Polymarket price, decimal fair odds, and any
matched market edge. It is a research sizing template, not an instruction to trade.

The side-strength logit combines:

- global rating delta: Elo-like rating difference,
- FIFA rank prior: small stabilizer when Elo is stale,
- World Cup pedigree: log-scaled points from the last three World Cups,
- confederation tournament adjustment,
- host / near-host advantage,
- rest-day difference,
- short-term form delta,
- injury/suspension penalty.

The draw logit is World Cup-aware:

- higher base draw rate in group matches,
- closeness boost when teams are evenly rated,
- lower draw mass in knockout markets if you decide to model advancement instead of regulation time.

Arbitrage/opportunity flag:

```text
edge = model_probability - polymarket_implied_probability
```

The default threshold is `EDGE_THRESHOLD=0.15` (at least 15 percentage points). Treat this as a research alert, not a trade instruction. Before trading, account for spread, liquidity, slippage, fees, market resolution wording, and legal restrictions.

Stage-market alerts currently compare:

- reach quarterfinals against simulated `top_8`,
- reach semifinals against simulated `semi_final`,
- reach final against simulated `final`,
- win World Cup against simulated `champion`.

## Rolling Backtest

Every daily scan scores completed fixtures against the current model inputs and appends
a compact validation block to the persisted report. The block includes:

- 1X2 top-pick accuracy,
- non-draw side accuracy,
- draw top-pick hits,
- Brier score,
- log loss.

This is a current-snapshot diagnostic, not a clean historical pre-match backtest. A
fully clean backtest would require saving ratings and team context snapshots before
each kickoff.

## Cron

Cloud cron is configured with GitHub Actions in `.github/workflows/daily-report.yml`.
It runs at 08:00 and 14:00 Hong Kong time:

```yaml
schedule:
  - cron: "0 0 * * *"
  - cron: "0 6 * * *"
```

Configure these GitHub repository secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `API_FOOTBALL_KEY`

Local cron is not required. For ad hoc local runs:

```cron
cd "/Users/bluoaa/Documents/FIFA 2026" && . .venv/bin/activate && python scripts/update_fixtures.py && python scripts/update_ratings.py && python scripts/update_team_context.py && fifa-arb-agent
```

GitHub Actions cron is included in `.github/workflows/daily-report.yml`.
