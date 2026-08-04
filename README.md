# OptimusDB

**OptimusDB** is an AI-powered SQL query optimization engine that analyzes PostgreSQL execution plans and automatically detects performance bottlenecks - sequential scans, missing indexes, row estimation errors, and cartesian products. It generates composite index recommendations and structural query rewrites, benchmarks them against the original, and shows before/after latency deltas. Indexes are applied temporarily and dropped after every run; your schema is never permanently modified.

Achieves up to **47.4× query speedup** on TPC-H SF=1 benchmarks via automated composite index recommendation and correlated subquery elimination.

## Highlights

- **Deterministic analysis first.** A rule-based detector flags sequential scans, missing indexes, bad row estimates, and problematic nested loops without touching an LLM.
- **LLM rewrites on demand.** The optimizer only calls an LLM when the user explicitly clicks Optimize. No debounce spend, no surprise token bills.
- **Three provider backends.** Swap between Groq (Llama 3.3 70B), Mistral (Codestral), or Cerebras via one environment variable. All use OpenAI-compatible endpoints.
- **Honest benchmarks.** Every proposed rewrite is validated (`EXPLAIN` without `ANALYZE`) and then benchmarked side-by-side against the original with cold and warm p50/p95 timings.
- **Workload discovery.** Pulls the top-N slowest queries from `pg_stat_statements` and fans them through the analyzer automatically.
- **Full desktop-style UI.** Five-view app (Editor, Workload, History, Settings, Reference) with a syntax-highlighted SQL editor, 800 ms debounced analysis, a split diff pane for rewrites, and log-scale latency dot charts. Keyboard-first: `Cmd+Enter` analyze, `Cmd+Shift+O` optimize, `Cmd+1..5` switch view.
- **Safe schema mutation.** Recommended indexes are applied under `optimusdb_tmp_<uuid>` names, benchmarked, then dropped in a `try/finally`. Every optimize call ends with a leak-verify query that logs `LEAK DETECTED` if anything survives.
- **Cross-join guard.** Queries with comma-separated FROMs and insufficient join predicates are rejected before `EXPLAIN` runs, so a cartesian product can never hang the backend or reach the LLM.

## Architecture

```
Frontend (Vite + React 19)         Backend (FastAPI + psycopg2)   PostgreSQL 16
        localhost:5173      /api/*        localhost:8000                 :5432
              |                              |
              |  POST /analyze  ---------->  |  cross-join guard + plan + detector
              |  POST /optimize ---------->  |  analyze + LLM rewrite + apply/bench/drop
              |  POST /benchmark --------->  |  run query N times, p50/p95
              |  POST /workload  --------->  |  pg_stat_statements + batch analysis
              |  GET  /health   ---------->  |  SELECT 1
                                             |
                                             +-> LLM provider (Groq / Mistral / Cerebras)
```

### Data flow: analyze + rewrite loop

```
SQL text
   |
   v
detect_cross_join_risk           (pre-flight, short-circuits on cartesian)
   |
   v
run_explain  ->  Postgres (EXPLAIN ANALYZE, FORMAT JSON, 8s timeout)
   |
   v
parse_plan   ->  list[PlanNode]
   |
   +-> detect_problems  ->  list[Problem]                      (deterministic)
   |
   v
optimize_query (on user click)
   |
   v
LLM (Groq / Mistral / Cerebras)  ->  rewritten SQL + CREATE INDEX suggestions
   |
   v
_validate_sql (EXPLAIN, no ANALYZE)  ->  valid?
   |
   v
run_benchmark (original, no indexes)                          (baseline)
   |
   v
apply_indexes  ->  CREATE INDEX optimusdb_tmp_<uuid> ...       (60s timeout)
   |
   v
run_explain (rewrite)  ->  plan_changes diff                   (before/after)
   |
   v
run_benchmark (rewrite, with indexes)
   |
   v
drop_indexes  ->  DROP INDEX IF EXISTS optimusdb_tmp_<uuid>    (try/finally)
   |
   v
leak-verify  ->  COUNT(*) WHERE indexname LIKE 'optimusdb_tmp_%'
   |
   v
speedup ratio + verdict
```

## Tech stack

| Layer         | Technology                                                       |
|---------------|------------------------------------------------------------------|
| Database      | PostgreSQL 16 with `pg_stat_statements`                          |
| Benchmark set | TPC-H at scale factor 1 (roughly 1 GB, 6 M row `lineitem`)       |
| Backend       | Python 3.11+, FastAPI, psycopg2, Pydantic v2                     |
| LLM SDK       | `openai` (works with Groq, Mistral, Cerebras compatible APIs)    |
| Frontend      | Vite, React 19, TypeScript, Tailwind CSS v4                      |
| Container     | Docker Compose for Postgres                                      |

## Prerequisites

Install once on your machine:

- **Docker Desktop** (Windows / macOS) or Docker Engine (Linux)
- **Python 3.11 or newer**
- **Node.js 20 or newer** (Vite requires it)
- **Git Bash** on Windows if you plan to run the TPC-H loader script (uses bash and `sed`). PowerShell works for everything else.

You also need an API key for at least one LLM provider. Sign up here:

| Provider | Signup URL              | Env variable        | Notes                                |
|----------|-------------------------|---------------------|--------------------------------------|
| Groq     | https://console.groq.com | `GROQ_API_KEY`      | Fastest inference, most generous free tier |
| Mistral  | https://console.mistral.ai | `MISTRAL_API_KEY` | Codestral is SQL-specialized         |
| Cerebras | https://cloud.cerebras.ai | `CEREBRAS_API_KEY` | Best for batch workloads             |

## Quick start

### 1. Clone and configure

```bash
git clone <repo-url> OptimusDB
cd OptimusDB
```

Create `project/.env` (this file is gitignored):

```env
# Required (at least one)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# Optional
MISTRAL_API_KEY=...
MISTRAL_MODEL=codestral-latest
CEREBRAS_API_KEY=csk-...
CEREBRAS_MODEL=llama-3.3-70b

# Which provider /optimize uses (default: groq)
LLM_PROVIDER=groq
```

### 2. Install dependencies

```bash
# Backend
python -m pip install -r project/backend/requirements.txt

# Frontend
cd project/frontend
npm install
cd ../..
```

### 3. Start Postgres and load TPC-H data

Postgres runs in Docker; TPC-H data is generated by a script the first time only.

```bash
docker compose -f project/docker-compose.yml up -d
bash project/backend/scripts/load_tpch.sh
```

The loader script builds `tpch-dbgen` inside a throwaway container, generates all 8 TPC-H tables at scale factor 1, and loads them into Postgres with primary and foreign keys. Expect roughly 3 to 5 minutes on first run; subsequent runs are near-instant because the artifacts are cached in `project/backend/scripts/tpch-build/`.

### 4. Run the stack

Three terminals from `D:\OptimusDB\project` (PowerShell shown; adapt for your shell):

**Terminal 1**: Postgres (idempotent, safe to skip if already up)
```powershell
docker compose up -d
```

**Terminal 2**: FastAPI backend
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```

**Terminal 3**: Vite frontend
```powershell
cd frontend
npm run dev
```

Open http://localhost:5173.

## Usage

### Web UI

The app has 5 views, switchable from the left nav rail or via `Cmd+1..5`:

1. **Editor.** Type or paste SQL in the left pane. After 800 ms of no typing (or `Cmd+Enter`) the right pane shows detected problems and the parsed plan. Click **Optimize** (or `Cmd+Shift+O`) to launch the LLM rewrite overlay: pipeline steps, verdict, applied indexes, before/after plan node types, and a split diff. **Accept** pastes the rewrite back into the editor.
2. **Workload.** Pulls the top-N slowest queries from `pg_stat_statements` and lets you analyze or paste each into the editor.
3. **History.** Every analyze/optimize run is stored in `localStorage` (up to 50). Verdict chip, speedup, and click-to-restore.
4. **Settings.** Provider cards (Groq / Mistral / Cerebras), model info, connection details.
5. **Reference.** Design tokens, type scale, keyboard shortcuts, motion notes.

### API

The backend serves OpenAPI docs at http://localhost:8000/docs. Every endpoint has a "Try it out" button.

| Method | Path         | Purpose                                          | Latency          |
|--------|--------------|--------------------------------------------------|------------------|
| GET    | `/health`    | Liveness probe (Postgres round-trip)             | < 5 ms           |
| POST   | `/analyze`   | Parse plan, run detector, no LLM                 | 20 to 200 ms     |
| POST   | `/optimize`  | Analyze, LLM rewrite, benchmark both             | 2 to 5 s         |
| POST   | `/benchmark` | Run one query N times, return p50/p95            | depends on query |
| POST   | `/workload`  | Top-N slow queries from `pg_stat_statements`     | 100 ms to 2 s    |

Example request:

```bash
curl -X POST http://localhost:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT count(*) FROM lineitem WHERE l_shipdate > DATE '\''1995-06-01'\''"}'
```

### CLI demos

Each pipeline phase has a standalone smoke test:

```bash
python project/backend/scripts/test_pipeline.py    # Phase 1: analyzer + benchmark
python project/backend/scripts/test_workload.py    # Phase 2: workload discovery
python project/backend/scripts/test_optimize.py    # Phase 3: LLM rewrite loop
python project/backend/llm/client.py               # Ping every configured provider
```

## Configuration

All configuration lives in `project/.env`. The file is gitignored.

| Variable          | Default                    | Purpose                                    |
|-------------------|----------------------------|--------------------------------------------|
| `GROQ_API_KEY`    | (required for Groq)        | API key for console.groq.com               |
| `GROQ_MODEL`      | `llama-3.3-70b-versatile`  | Groq model id                              |
| `MISTRAL_API_KEY` | (optional)                 | API key for console.mistral.ai             |
| `MISTRAL_MODEL`   | `codestral-latest`         | Mistral model id                           |
| `CEREBRAS_API_KEY`| (optional)                 | API key for cloud.cerebras.ai              |
| `CEREBRAS_MODEL`  | `llama-3.3-70b`            | Cerebras model id                          |
| `LLM_PROVIDER`    | `groq`                     | Which provider `/optimize` uses            |
| `PG_HOST`         | `localhost`                | Postgres host                              |
| `PG_PORT`         | `5432`                     | Postgres port                              |
| `PG_USER`         | `optimus`                  | Postgres user                              |
| `PG_PASSWORD`     | `optimus`                  | Postgres password                          |
| `PG_DB`           | `tpch`                     | Postgres database                          |

### Pointing at your own database

The analyzer is not TPC-H specific. Change the `PG_*` variables in `.env` to point at any Postgres 12+ database with `pg_stat_statements` enabled. Use a read-only user (the analyzer runs `EXPLAIN ANALYZE`, which executes the query). Restart the backend to pick up the new configuration.

## Project structure

```
OptimusDB/
├── PLANNING.md              Architecture decisions (outside git repo)
├── TASKS.md                 Phase checklist (outside git repo)
└── project/                 ← git repo root
    ├── .env                 Local secrets (gitignored)
    ├── .gitignore
    ├── docker-compose.yml   Postgres 16 with pg_stat_statements preloaded
    ├── README.md
    ├── postgres/
    │   └── postgresql.conf  Custom Postgres config
    ├── backend/
    │   ├── main.py                    FastAPI app entry point
    │   ├── requirements.txt
    │   ├── api/
    │   │   ├── db.py                  psycopg2 connection pool + DI
    │   │   ├── schemas.py             Pydantic request/response models
    │   │   └── routes.py              /analyze /optimize /benchmark /workload /health
    │   ├── analyzer/
    │   │   ├── plan_parser.py         EXPLAIN ANALYZE parser + cross-join guard
    │   │   ├── detector.py            Deterministic problem detector (5 rules)
    │   │   ├── indexes.py             CREATE INDEX allowlist parser + apply/drop
    │   │   ├── workload.py            pg_stat_statements reader
    │   │   └── batch.py               Fans slow queries through the analyzer
    │   ├── benchmarks/
    │   │   └── harness.py             N-run cold/warm p50/p95 timing
    │   ├── llm/
    │   │   ├── client.py              Unified Groq/Mistral/Cerebras client
    │   │   └── optimizer.py           System prompt, rewrite, validate, index parse
    │   └── scripts/
    │       ├── load_tpch.sh           TPC-H SF=1 loader
    │       ├── test_pipeline.py       Phase 1 end-to-end demo
    │       ├── test_workload.py       Phase 2 demo
    │       ├── test_optimize.py       Phase 3 demo
    │       └── sql/                   TPC-H schema and keys SQL
    └── frontend/
        ├── package.json
        ├── vite.config.ts             Vite + Tailwind + /api proxy
        ├── index.html
        └── src/
            ├── main.tsx
            ├── App.tsx                View router, debounce, /optimize orchestration
            ├── index.css              Tailwind v4 base + keyframes
            ├── api/
            │   ├── client.ts          Fetch wrappers (analyze/optimize/workload/health)
            │   └── types.ts           TypeScript mirrors of Pydantic schemas
            ├── lib/
            │   ├── tokens.ts          Design tokens (color, type, spacing)
            │   ├── format.ts          fmtN, fmtMs, fmtDur helpers
            │   ├── sql.tsx            SqlText + syntax-highlighting tokenizer
            │   ├── history.ts         localStorage-backed history (max 50)
            │   └── diff.ts            LCS line diff for the split diff pane
            ├── hooks/
            │   ├── useDebounce.ts
            │   └── useShortcuts.ts    Cmd+Enter / Cmd+Shift+O / Cmd+1..5 / Esc
            ├── views/
            │   ├── EditorView.tsx     SQL editor + analysis pane
            │   ├── WorkloadView.tsx   Top-N slow queries from pg_stat_statements
            │   ├── HistoryView.tsx    Per-run history from localStorage
            │   ├── SettingsView.tsx   Provider cards, connection info
            │   └── ReferenceView.tsx  Design system reference (tokens, shortcuts)
            └── components/
                ├── NavRail.tsx        Left 52px nav rail + pg health dot
                ├── Toast.tsx          Bottom-center mono toast
                ├── SqlEditor.tsx      Textarea over syntax-highlighted <pre>
                ├── ProblemsList.tsx   Severity-chipped problem cards
                ├── PlanTree.tsx       Depth-indented plan with cost bars
                ├── ScanLoader.tsx     Scan-line loader (deterministic ops)
                ├── PipelineSteps.tsx  Optimize pipeline stage indicator
                ├── BenchmarkStrip.tsx Log-scale latency dot distribution
                ├── DiffPane.tsx       Split diff (LCS) for rewrites
                └── OptimizePanel.tsx  Overlay: pipeline → verdict → indexes+plan+bench
```

## Development

### Detector rules

The deterministic detector lives in `project/backend/analyzer/detector.py`. Current rules:

| Rule                        | Triggers when                                              |
|-----------------------------|------------------------------------------------------------|
| `SEQ_SCAN_LARGE`            | Sequential scan produces more than 1,000 rows total        |
| `ROW_ESTIMATE_ERROR`        | `actual_rows / plan_rows` ratio exceeds 10x or is under 0.1x |
| `NESTED_LOOP_HIGH_ROWS`     | Nested Loop join produces more than 500 rows               |
| `MISSING_INDEX_CANDIDATE`   | Sequential scan carries a filter predicate                 |
| `STALE_STATISTICS`          | `actual_rows / plan_rows` exceeds 100x; message includes a runnable `ANALYZE <table>;` |

Plus a pre-flight guard that fires before any `EXPLAIN` runs:

| Guard                       | Triggers when                                              |
|-----------------------------|------------------------------------------------------------|
| `CROSS_JOIN_RISK`           | FROM clause has comma-separated tables with fewer join predicates than needed (would produce a cartesian product) |

Add a new plan-node rule by writing a `_check_*(node) -> list[Problem]` function and appending it to `detect_problems`. The cross-join guard lives in `analyzer/plan_parser.py`.

### Adding a fourth LLM provider

Every provider uses the same OpenAI-compatible protocol. In `project/backend/llm/client.py`, add an entry to the `PROVIDERS` dict:

```python
PROVIDERS["your_provider"] = {
    "base_url": "https://api.example.com/v1",
    "default_model": "some-model",
    "api_key_env": "YOUR_API_KEY",
    "model_env": "YOUR_MODEL",
}
```

Then optionally add a subclass mirror (`YourClient(LLMClient)`) for convenience. The optimizer picks it up automatically via `get_client()` and `LLM_PROVIDER=your_provider`.

### Frontend

```bash
cd project/frontend
npm run dev        # Vite dev server with HMR
npm run build      # Type-check and bundle for production
npm run preview    # Preview the production bundle
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so the frontend never needs to know the backend port and CORS stays a non-issue in development.

## Benchmarks

All benchmarks run against TPC-H Scale Factor 1 (1GB dataset) on PostgreSQL 16. Latency figures are p50 warm across 10 runs + 1 cold run. Indexes are applied temporarily, benchmarked, then dropped - database is restored to baseline after every optimize call.

| Query | Type | Original p50 | Optimized p50 | Speedup |
|-------|------|-------------|---------------|---------|
| Selective filter - orders (status + price range) | Composite index | 61.6ms | 1.3ms | **47.4×** |
| Correlated subquery → LEFT JOIN rewrite | Rewrite + index | 1,700ms | 993ms | **1.67×** |
| TPC-H Q3 - 3-table join (customer/orders/lineitem) | Index only | 335ms | 310ms | 1.08× |
| Leading wildcard LIKE (%BRASS) - part table | Index only | 28.5ms | 12.6ms | **2.27×** |
| Implicit cross join (orders × customer × lineitem) | Blocked | - | - | guard ✓ |

### Notes

- **47.4× (T1)** - composite index `(o_orderstatus, o_totalprice)` eliminated a 346k-row Seq Scan; high selectivity (1,746 rows returned) is why the speedup is dramatic. Equality predicate first, range last.

- **1.67× (T2)** - correlated subquery executed once per outer row (228k × 2 lineitem scans); rewritten to a single LEFT JOIN + GROUP BY. Structural rewrite + index on `o_orderdate` combined for the improvement.

- **1.08× (T3)** - lineitem Seq Scan (6M rows) persisted after indexing because the query returns a large result fraction; Postgres planner correctly chose Seq Scan (PLANNER CHOICE). Index on `l_shipdate` applied but not used - this is correct behavior, not a bug.

- **2.27× (T5)** - leading wildcard `LIKE '%BRASS'` cannot use a B-tree index on the pattern itself; improvement came from index on `p_size` (BETWEEN 1 AND 5) eliminating 95%+ of rows before the LIKE filter ran.

- **Cross join guard (T6)** - query with 3 comma-separated tables and 0 join predicates was blocked at /analyze before EXPLAIN executed. Cartesian product of orders(727k) × customer(150k) × lineitem(6M) would have produced trillions of combinations. Backend stayed responsive. LLM was never called.

## Safety

- **Index isolation** - every recommended index is created with a UUID prefix (`optimusdb_tmp_<uuid>`) and dropped after benchmarking. Your schema is never permanently modified.
- **Allowlist parser** - only plain `CREATE INDEX` statements are executed. `DROP`, `ALTER`, `SELECT`, subqueries, and parenthesized expressions are rejected before reaching the database.
- **Cross join guard** - queries with comma-separated FROM clauses and insufficient join predicates are blocked before EXPLAIN runs. Prevents multi-trillion-row cartesian products from hanging the backend.
- **Statement timeout** - EXPLAIN ANALYZE is capped at 8 seconds. CREATE INDEX is capped at 60 seconds. Both reset in try/finally.
- **Rewrite validation** - LLM-generated SQL is parsed and validated before benchmarking. Unparseable rewrites are rejected; nothing is benchmarked or accepted.
- **Leak detection** - after every optimize call, a verify query checks for surviving `optimusdb_tmp_%` indexes and logs LEAK DETECTED if any remain.

## Testing

Beyond the standalone demo scripts, there is no formal test suite yet. To smoke-test the whole stack:

```bash
# Terminal 1
docker compose -f project/docker-compose.yml up -d

# Terminal 2
python project/backend/scripts/test_pipeline.py
python project/backend/scripts/test_workload.py
python project/backend/scripts/test_optimize.py
python project/backend/llm/client.py
```

Each script prints its own pass/fail summary.

## Roadmap

Delivered:

- Phase 1: Deterministic analyzer, benchmark harness, TPC-H loader
- Phase 2: Workload discovery through `pg_stat_statements`
- Phase 3: LLM rewrite loop with validation and side-by-side benchmark
- Phase 4: FastAPI HTTP surface with Pydantic schemas
- Phase 5: Vite + React 19 frontend with 5 views (Editor, Workload, History, Settings, Reference), split diff pane, log-scale latency dots, keyboard shortcuts
- Phase 6: Index apply/drop pipeline, `optimusdb_tmp_*` naming, allowlist parser for CREATE INDEX (composite + partial), try/finally cleanup, post-cleanup leak-verify
- Phase 7: Composite-index recommendations in the system prompt (equality first, range last)
- Phase 8: Cross-join pre-flight guard (blocks cartesian products before EXPLAIN)
- Phase 9: STALE_STATISTICS detector with a runnable `ANALYZE <table>;` command in the message, copyable from the UI

Open items:

- `POST /execute` for SELECT-only query execution (so the frontend can run the accepted rewrite)
- Provider picker in the UI header
- Shareable analysis links (history is per-browser via localStorage today)
- Semantic equivalence check (`SELECT * FROM (original) EXCEPT SELECT * FROM (rewrite)` returns zero rows)
- Automated test suite (pytest for backend, Vitest for frontend)
- API authentication and rate limiting

## Attribution

- TPC-H is a trademark of the Transaction Processing Performance Council. The data generator used here is the [electrum/tpch-dbgen](https://github.com/electrum/tpch-dbgen) mirror.

## Security notes for local development

The default configuration is intended for local development only:

- Postgres binds to `0.0.0.0:5432` with the credentials `optimus / optimus`. Bind to `127.0.0.1` and rotate credentials before exposing.
- The FastAPI backend has CORS wide open (`allow_origins=["*"]`). Restrict origins before deploying.
- There is no API authentication or rate limiting. Anyone who can reach the port can spend LLM tokens through `/optimize`.
- LLM API keys live in `project/.env`, which is gitignored. Never commit that file.
