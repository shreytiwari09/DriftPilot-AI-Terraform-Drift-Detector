<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" alt="DriftPilot" width="360">
  </picture>
</p>

<p align="center">
  <b>One product, two solutions: it catches Terraform drift and database drift, judges how much each change matters, and proposes fixes that are proven correct before a human sees them.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.2.0-1f6feb" alt="version 2.2.0">
  <img src="https://img.shields.io/badge/GitHub%20Action-composite-2088FF?logo=githubactions&logoColor=white" alt="GitHub Action">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/terraform-%E2%89%A5%201.5-7B42BC?logo=terraform&logoColor=white" alt="Terraform 1.5+">
  <img src="https://img.shields.io/badge/postgres-16-4169E1?logo=postgresql&logoColor=white" alt="Postgres">
  <img src="https://img.shields.io/badge/tests-818%20passing%20(%2B26%20need%20Postgres)-2ea44f" alt="818 tests passing, 26 more need a live Postgres">
  <img src="https://img.shields.io/badge/AI-Gemini%20Flash--Lite-8E75B2" alt="Gemini Flash-Lite">
</p>

<p align="center">
  <a href="#the-problem">The problem</a> ·
  <a href="#see-it-in-action">See it in action</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#guardrails-the-ai-cannot-be-talked-into-it">Guardrails</a> ·
  <a href="#the-dashboard">Dashboard</a> ·
  <a href="#solution-1-infrastructure-drift-terraform-github-docker-aws">Infrastructure</a> ·
  <a href="#solution-2-database-schema-drift-postgres">Database</a> ·
  <a href="#results">Results</a> ·
  <a href="#use-it">Use it</a> ·
  <a href="#limitations-honest-version">Limitations</a>
</p>

---

> **Status:** this is the version 2 work on the branch `v2`. It is not released yet. The live dashboard links below still show
> the version 1 page.

## The problem

Teams describe their infrastructure (servers, databases, firewalls, repository settings, permissions) as **code**, the
blueprint: Terraform for infrastructure, migration files for databases. People still change the real thing by hand: an
urgent fix during an outage, a shortcut, a mistake. Reality then **drifts** away from the code.

<p align="center"><img src="assets/diagrams/problem.png" alt="Terraform code says approvals = 2; someone changes it to 0 by hand; the real infrastructure now differs: drift" width="720"></p>

Plain tools have four blind spots:

- **They only notice when someone runs them** (`terraform plan`, a migration tool).
- **They can't see things created outside the code.**
- **They print a raw diff with no judgment** about what's dangerous and what's noise.
- **The next `apply` or migration can silently undo an emergency fix.**

## What DriftPilot does

| | Step | How |
| --- | --- | --- |
| 🔎 | **Detect** | Runs on a schedule, on demand, or seconds after a change. **Infrastructure:** asks Terraform what changed and scans GitHub, Docker and AWS for resources it doesn't manage. **Databases:** builds the schema your migration files describe and compares it with the live Postgres database. |
| ⚖️ | **Judge** | Rules filter noise and catch critical cases instantly. An LLM judges the rest: real or not, how severe, hotfix or mistake, keep or undo, and why. Guardrails make sure text written by strangers cannot talk it into playing a danger down. |
| 🛠️ | **Fix** | Dangerous change: an **issue** with the exact commands (Terraform, or SQL for a database). Good change: a **pull request** whose change is **proven** (a zero-change `terraform plan`, or a scratch database that matches the live one). |
| 📈 | **Learn** | Keeps history by team, repo and type, spots spikes and settings that keep drifting, tracks whether people accept its suggestions, and publishes a filterable dashboard. |

DriftPilot **never changes infrastructure or a database itself**. It proposes, and people decide.

```
                          DriftPilot
          ┌──────────────────┴──────────────────┐
  Infrastructure drift                     Database schema drift
  (Terraform: GitHub, Docker, AWS)         (Postgres: migration files vs live database)
          └──────────────────┬──────────────────┘
  One shared brain: rules · LLM triage · guardrails · policy · verification ·
                    issues and PRs · history · analytics · dashboard
```

## See it in action

**1. A scan.** Rules decide the obvious cases; the AI judges the rest and explains why. Noise is hidden.

<img src="assets/screenshots/cli-scan.svg" alt="driftpilot scan output: severity, change, action and reason for each drifted setting">

<sub>Replay of a live run on the demo org: approvals lowered → critical (rule); team raised to admin → high (rule);
the other changes judged by Gemini. Reasons shortened for the image.</sub>

**2. A verified fix.** The AI writes the code change, and Terraform proves it in a throwaway copy before anyone sees
a pull request.

<img src="assets/screenshots/cli-fix.svg" alt="driftpilot fix output: a two-line diff and the Terraform proof 'No changes'" width="760">

**3. A database change.** Someone turns off row-level security on `orders` straight on the live database. This is real output
from the local Docker demo (see [Solution 2](#solution-2-database-schema-drift-postgres)):

```
$ driftpilot db scan --dir demo/postgres --fail-on-drift        # exit code 2
 critical  postgres.public.orders  row_level_security  true -> false  revert
           Row-level security is off ... (rule pg-rls-disabled)
$ driftpilot db fix --dir demo/postgres
 Issue: postgres.public.orders (revert)   Severity: critical   Compliance tags: least-privilege
 ### Suggested SQL (review before running)
   ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
```

**4. Learning over time.** 90 days of simulated history with planted patterns. All of them are found: the spike
(red dot and change-point), the setting that keeps drifting, and people overruling DriftPilot more often.

<a href="https://driftpilot-demo.github.io/drift-dashboard/simulated/"><img src="assets/screenshots/dashboard.png" alt="DriftPilot dashboard (version 1 look): daily drift with anomalies, severity mix, human overrule rate" width="820"></a>

<sub>This screenshot and the live link show the version 1 dashboard. The version 2 dashboard (filters, KPI tiles) is described
[below](#the-dashboard).</sub>

In GitHub, the same results appear as a **job summary** on each run, plus **issues** and **pull requests** in the
repository.

## How it works

```mermaid
flowchart TB
  T["⏰ Triggers<br/>schedule · button · events<br/>cloud runner (container)"]
  T --> A["Infrastructure drift<br/>terraform plan -refresh-only<br/>+ scanners: GitHub · Docker · AWS"]
  T --> B["Database drift (Postgres)<br/>migrations in a scratch database<br/>vs the live database (read-only)"]
  EV["☁️ Cloud event<br/>who changed it"] -.-> A
  A --> C["Collector<br/>one finding per changed setting"]
  B --> C
  C --> RD["🔒 Redaction + 🧼 sanitising<br/>untrusted text cleaned"]
  RD --> RU["📏 Rules<br/>noise · critical · compliance tags"]
  RU --> L["🤖 LLM triage<br/>text is data, never instructions"]
  L --> PO["🛡️ Policy + guardrails<br/>never-soften list · suspicious input<br/>call and PR limits · audit log"]
  RU --> PO
  PO -->|"risky / critical"| I["🎫 Issue<br/>Terraform commands or SQL to undo"]
  PO -->|"keep the change"| V["Patch, then proof<br/>terraform plan: No changes<br/>or scratch DB: 0 differences"]
  V --> PR["🔀 Pull request with proof"]
  PO --> H["📈 History with team · repo · type<br/>filterable dashboard"]
```

**Four layers of judgment**

| Layer | Role | Why |
| --- | --- | --- |
| **Rules** (`driftpilot/triage/rules/default.yaml`) | Filter known noise (provider defaults, API etags, runtime IPs, reordered lists, reformatted JSON, AWS tag copies). Always flag critical changes (protection weakened, admin ports open to the internet, public storage, wildcard IAM, encryption off, row-level security off ...). Each rule can carry a **compliance tag** (`public-storage`, `least-privilege`, ...) | Instant, free, guaranteed |
| **LLM** (Gemini, prompt `triage-v4`) | Judges what rules don't decide: severity, intent, action, confidence, reason. One call per resource, secrets redacted, answer forced into a JSON schema, everything it reads treated as data | Context and explanations |
| **Guardrails** | Sanitise untrusted text, flag injection attempts, a never-soften list the AI cannot override, hard limits, an audit log | Safety against hostile text |
| **Policy** | Low confidence → a human investigates; critical → never an automatic PR; team settings always win | Safety |

### Story 1: someone weakens security

```mermaid
sequenceDiagram
  actor P as Person
  participant GH as GitHub repo settings
  participant A as DriftPilot (GitHub Actions)
  participant T as Terraform
  P->>GH: sets required approvals 2 → 0
  GH->>A: starts a run (event, ~15 s)
  A->>T: plan -refresh-only
  T-->>A: approvals: 2 → 0
  Note over A: rule: approvals lowered → critical, revert
  A->>GH: 🎫 issue with "terraform plan" + "terraform apply" commands
  P->>T: runs the commands from the issue
  A->>GH: next run: ✅ No drift detected
```

### Story 2: someone makes a good change

```mermaid
sequenceDiagram
  actor P as Engineer
  participant GH as GitHub
  participant A as DriftPilot
  participant AI as Gemini
  participant T as Terraform (throwaway copy)
  P->>GH: adds a required status check during an incident
  GH->>A: starts a run
  A->>AI: what changed + the resource's code
  AI-->>A: medium · likely hotfix · keep it (codify) · 90%
  A->>AI: update the code to match
  AI-->>A: new resource block
  A->>T: fmt → validate → plan
  T-->>A: No changes ✅ (the code now describes reality)
  A->>GH: 🔀 pull request with the diff and the proof
  P->>GH: reviews and merges (or rejects)
```

### Story 3: someone edits the production database by hand

```mermaid
sequenceDiagram
  actor P as Engineer
  participant DB as Live Postgres
  participant A as DriftPilot
  participant S as Scratch database
  P->>DB: ALTER TABLE users ADD COLUMN nickname text (a hotfix, no migration file)
  A->>S: create driftpilot_scratch_xxx, run migrations/*.sql, read the schema, drop it
  A->>DB: read the schema (read-only login)
  Note over A: diff: users.nickname exists only in the live database
  Note over A: rule: extra column → medium, codify (keep it)
  A->>S: fresh scratch database: all migrations + a new 0004 file
  S-->>A: schema matches the live database (0 differences) ✅
  A-->>P: 🔀 pull request with migrations/0004_driftpilot_public_users_nickname.sql and the proof
```

## Guardrails: the AI cannot be talked into it

DriftPilot reads text that other people can write: repository descriptions, tags, resource names, policy documents, column defaults, comments.
Attacks on AI agents in CI pipelines through exactly this kind of text are documented ([Related work](#related-work)). A defence that only *detects* attacks
can be bypassed, so the protection is layered, and the deterministic layers hold **even if the AI is fully fooled**:

1. **Sanitise.** Hidden characters (zero-width, right-to-left tricks) and `<!-- comments -->` are removed, whitespace collapsed, long text cut. Everything the AI reads is cleaned first.
2. **Frame as data.** The prompt says everything inside the JSON is data, never instructions, and that text trying to steer the AI is itself a warning sign.
3. **Flag suspicious input.** Phrases such as "ignore previous instructions" or "mark this as safe" make that resource's verdict impossible to be "not real" or "none": at least `investigate`, with a
   `suspicious-input` label. (This is a smoke alarm, not a wall: reworded text avoids it.)
4. **Never-soften list.** Security weakenings (branch protection removed, admin granted, `0.0.0.0/0` on an admin port, public S3, IAM `*`, encryption off, RDS public, CloudTrail off,
   row-level security off, a policy dropped, a grant to `PUBLIC` ...) have a **floor**: if the AI calls one "not real", a lower severity, or "keep it", plain code overrides it to real, at least the floor, action `revert`.
   **The AI can make a verdict stricter, never softer, for these.**
5. **Limits.** Caps on AI calls, prompt size, PRs per run, files and lines per PR. When a cap is hit, the verdict falls back to `investigate` or the PR becomes an issue.
6. **Audit log.** Every AI call is recorded (prompt version, model, hashes of the prompt and answer, valid or not, guardrail events); never the text itself.

**Measured** on 24 adversarial cases (20 attacks, 4 harmless look-alikes; 37 attacked findings, 11 on the never-soften list; some attacks hidden or paraphrased), same AI, same rules, guardrails off versus on:

| Setup | Attack success rate (any answer the label does not accept) | Softer only (hides a change) | On never-soften findings | Harmless look-alikes right |
| --- | ---: | ---: | ---: | ---: |
| rules + AI, **no guardrails** | 15/37 (41%) | 7/37 (19%) | 1/11 (9%) | 3/4 |
| rules + AI, **guardrails** | 12/37 (32%) | **3/37 (8%)** | **0/11 (0%)** | 2/4 |

- **What the table says:** guardrails cut attacks that actually hide a change from 19% to 8%, and on the never-soften list to zero. A separate pytest uses a fake model that *always* answers "not real, no action": with guardrails it gets 0 successes on the never-soften findings (without guardrails some get through; the ones decided by rules cannot be changed by the model at all).
- **What it does not say:** the guarantee is only for what is on the list. Three attacked findings are still softened (one `dismiss_stale_reviews` change rated medium when the label says critical, twice; one EC2 public IP rated high where the label says critical, which is a rule choice rather than an AI failure).
- **The costs, honestly:** the harmless look-alikes get escalated to `investigate` more often (3/4 → 2/4), and the stricter-than-label share is large (9 of the 12 "successes" with guardrails are answers *stricter* than the label, such as `revert` on hostile-looking text). An earlier run of this table (before the AWS rules and the final prompt) gave 24% and 3%: the numbers move with the rules and the prompt, which is why they are re-run at every release.

## The dashboard

A React app (no server: it is static files on GitHub Pages) that a team can filter and use to act. `driftpilot report --html DIR` writes
the app, `data.json` (the data), `metrics.prom` (for Prometheus or Grafana) and an `index.html` with a copy of the data embedded, so
double-clicking the file works. The page re-reads `data.json` every 5 minutes. It is **near real time, not streaming**: the data changes
only when a scan runs and republishes.

- **Pages:** Overview (with a "Needs attention" list of open drift and its deadline), Findings, Teams, Infrastructure vs database, Scans
  (is DriftPilot itself running on time), Guardrails (with the measured test results) and About (endpoints and setup snippets).
- **Filters:** date range, team, repo, environment, drift type (infrastructure or database), severity, status (open or resolved),
  decided by (rule, LLM or policy), what the human did with it (accepted or overruled), plus text search.
- **KPI tiles that follow the filters.** Two come from the **AWS Well-Architected guidance** and are labelled as such:
  - **IaC coverage** = managed resources ÷ (managed + unmanaged)
  - **Drift rate** = distinct drifted resources ÷ managed resources

  The rest are **DriftPilot metrics** (our own definitions, labelled as such on the page): open drift and the age of the oldest one, mean time to
  resolve, overrule rate (how often people reject DriftPilot's advice), alert precision (accepted ÷ decided) and recurring offenders
  (the same setting drifting again and again).
- **Charts:** new drift per day by severity, by team, infrastructure vs database split, weekly overrule rate.
- **A sortable table** of every drift episode, and a CSV export (`driftpilot report --csv FILE`).
- **Who owns it** is decided in this order: a resource tag (`team`, `owner`), a pattern in `.driftpilot.yml`, the CODEOWNERS file, a default
  team, else `unowned`. Account numbers and ARNs are masked, and `dashboard.publish_addresses: false` replaces resource addresses with
  hashes before anything is published.
- Everything is bundled (charts and fonts included); the page makes no external requests, only the read of `data.json`.

Preview it from simulated data (90 days, seed 7, teams and both drift types):

```bash
python scripts/simulate_history.py --out /tmp/history
driftpilot report --history /tmp/history --html /tmp/site && open /tmp/site/index.html
```

## Observability

The dashboard is **near real time, not streaming**. Its data changes only when a scan runs, so there are a few waits in a row:

| Step | Delay |
| --- | --- |
| A cloud change event reaches the workflow (event-triggered run) | about 15 seconds, then 1 to 2 minutes for the scan |
| Scheduled run | every `dashboard.scan_every_hours` (default 6); a change waits up to that long |
| GitHub Pages deploys the new `data.json` | about 1 minute |
| The page re-reads `data.json` | every 5 minutes (the refresh button does it now) |

What the page and the files add on top of the drift list:

- **Needs attention** (top of Overview): open drift, most serious and oldest first, flagged when it is past its deadline (`dashboard.sla_hours`, default critical 24 h, high 72 h, medium 168 h, low none).
- **Scans page**: is DriftPilot itself running on time? Per repo, environment and type: last scan, runs in 24 h and 7 d, errors, longest gap, and a status (on time up to 1.5x the expected interval, late up to 3x, stale beyond). The header lamp uses the same thresholds. By default the page cannot pause or resume scans; it links to the workflow page on GitHub, where Disable workflow / Enable workflow / Run workflow do it. The optional control below can do the same from the page.
- **Pause, resume and scan now from the page (optional, off until you connect a token).** In the Schedule card on the Scans page, a closed section "Control from this page" lets the owner paste a GitHub token and then pause scans (disable the workflow), resume them (enable it) or start a run (`workflow_dispatch` on the configured branch). The page is static and has no login, so it calls GitHub's REST API (`api.github.com`) straight from the browser. Pause and resume ask for confirmation first. The token is kept in the tab's memory only: never in storage, a cookie or the address, it is forgotten on reload, on leaving the Scans page and on Disconnect, and a Content Security Policy (`connect-src 'self' https://api.github.com`) stops the page from sending it anywhere else. Use a fine-grained token for this one repository with only the **Actions: read and write** permission and a 7-day expiry (the About page has the click-by-click steps; organisations may need an owner to approve it), and never reuse a broad admin token. The trade-off: anyone who gets that token, for example from a browser extension or a script injected into the page, can pause or start your scans until it expires, so the page is as safe as the token is narrow. **By default the page is read-only**: it holds no token and changes nothing, and the control stays hidden if the repo, workflow or branch in `dashboard.links` look wrong. The older single-file dashboard page has no such control. Not yet tried against the real GitHub API: only a mocked `fetch` was used in tests.
- **Change against the previous period** on Open drift, Drift rate and Mean time to resolve, when a 7, 30 or 90 day range is chosen.
- **Guardrails page**: "Measured effectiveness" from the saved evaluation (24 adversarial cases, one model, labels written by the same author as the rules: a measurement, not a security proof).
- **Notifications** (new, optional): a message for new drift (only findings not in the stream's previous run, at `min_severity` or above), for a verdict-monitor alert when it first appears, and for a failed scan. Set `webhook-url` in the Action (a secret) and, if wanted, a `notifications:` block (see Settings). `slack` sends `{"text": ...}` (also works for Mattermost; for Discord append `/slack` to the webhook URL), `teams` sends `{"text": ...}` for a Teams Workflows "when a webhook request is received" flow, `generic` sends `{"event", "severity", "summary", "url", "time"}`. The URL is never printed, only `https` is accepted, a failed send becomes a note in the run and never fails the scan. Needs the history branch (without it DriftPilot cannot tell what is new); a failed scan is announced either way.
- **`metrics.prom`** is published next to `data.json` in the Prometheus text format (open and total episodes by severity, team, type and repo; IaC coverage; drift rate; mean time to resolve; overrule ratio; last scan time; scan errors; monitor alerts). Point Prometheus or Grafana Alloy at it; scraping faster than your scan interval adds nothing.
- **SARIF**: `driftpilot scan --sarif drift.sarif` (also `driftpilot db scan`) writes SARIF 2.1.0, one result per real finding, for GitHub code scanning (`github/codeql-action/upload-sarif`). The Terraform address is a logical location and the scanned folder is the file location; I have not checked how GitHub's code-scanning tab displays results without a real source line.

## Solution 1: infrastructure drift (Terraform: GitHub, Docker, AWS, Azure)

Everything from version 1 still works (see [Use it](#use-it)). Version 2 adds AWS, Azure and "who changed it":

- **AWS rules** in the same rule pack. Critical: S3 public access block turned off, a bucket policy open to `*`, IAM `Action`/`Resource` `*`,
  a publicly accessible database, storage or EBS encryption off, CloudTrail logging off. High: backup retention lowered, deletion protection off,
  EC2 public IP on. Noise: `tags_all` mirroring `tags`, a database's moving restore time. Rules were checked against the provider's own
  documentation; attributes that could also be a real change were deliberately **not** made noise rules.
- **Azure rules.** Critical: blob anonymous access turned on, public network access turned on, HTTPS-only turned off, and a network security group rule that allows SSH or RDP from anywhere. High: the minimum TLS version lowered to 1.0 or 1.1. Low: tag edits. The four critical rules are on the never-soften list. Attribute names were taken from the provider's own schema, and 10 labelled cases are in `eval/cases/azure.yaml`. With rules only they give severity right 78% (7 of 9 real findings), critical caught 100% (5 of 5) and no false alarms; they are not part of the main tables below, which were generated before these cases existed. The live Azure run is described under [Results](#what-was-measured-live).
- **Compliance tags.** Rules and issues carry descriptive tags (`public-storage`, `network-exposure`, `least-privilege`, `encryption-at-rest`,
  `audit-logging`, `code-review`, `backup`, `data-integrity`, `pii`). They are **not** CIS or SOC 2 control numbers: those have to be checked
  against the official texts before anyone names them.
- **AWS scanner** (read-only boto3): S3 buckets, security groups and IAM users that exist in the account but not in Terraform's state, with
  an import suggestion. Settings: `scanners.aws: {region, include_names, ignore_names, resource_types}`. Tested with **moto**, an offline fake of AWS.
- **Who changed it.** Give DriftPilot a CloudTrail event (`driftpilot scan --event FILE`, `driftpilot action --event-path FILE`) and the finding on
  that resource gets the actor and the call. The AI sees it as a *hint* (a named operator making a stricter change suggests a hotfix; an unknown
  identity suggests a mistake), never as proof, and the issue says "Changed by ... via ...". Event text is untrusted too: it is cleaned, secret-looking
  keys are redacted and account numbers are masked.
- **Cloud runner.** A `Dockerfile` (Python 3.12, a pinned and checksum-verified Terraform, non-root user) and `deploy/` with four templates: EventBridge
  Scheduler → ECS Fargate, an EventBridge rule on CloudTrail events → the same task, Google Cloud Run + Cloud Scheduler, and plain cron.
  `driftpilot action` also works outside GitHub: it prints the summary and writes `driftpilot-outputs.json`.
  **The image was built and run locally. The deploy templates are untested: nothing was ever deployed to a cloud account, and the AWS
  scanner and rules have only been tested against mocks, recorded events and recorded plans, never a live AWS account.**

## Solution 2: database schema drift (Postgres)

**Why:** hotfixes made directly on a production database are the cause database vendors cite most. Live-vs-migration drift detection exists in
paid tiers of Atlas, Flyway and Liquibase, and the documentation reviewed does not describe intent triage or fix PRs that are proven before they open.
(See [related work](#related-work); this is a finding from limited reading, not a proven gap.)

**How it works** (the code is in `driftpilot/database/`):

1. **Expected:** create a scratch database `driftpilot_scratch_<random>`, run `migrations/*.sql` in order, read its schema, and always drop it.
2. **Live:** read the real database with a read-only login (system-catalog queries; the session itself cannot write). Types and defaults are normalised
   (`int4` = `integer`, casts removed, `serial` vs identity) and constraints/indexes are matched by definition, not by auto-generated name, so harmless
   spelling differences are not "drift".
3. **Diff:** every difference becomes the same finding object the Terraform side uses (types `pg_table`, `pg_column`, `pg_constraint`, `pg_index`,
   `pg_policy`, `pg_grant`, `pg_table_rls`).
4. **Judge:** 17 database rules plus the same AI, guardrails and policy. Critical (and on the never-soften list): row-level security off, a policy
   dropped or loosened, a grant to `PUBLIC`. High: NOT NULL or a key/check/unique constraint dropped, a new column that looks like personal data
   (`email`, `ssn`, `phone`, `dob`, `aadhaar` ...). Medium: an extra table or column, a dropped index, a type change. Noise: owner-only and comment-only changes.
5. **Fix:** a revert becomes an issue with **"Suggested SQL (review before running)"**. A change worth keeping becomes a pull request with a new migration
   file, and the proof is: *a fresh scratch database built from all migrations plus the new file matches the live database (0 differences)*. It is the
   database version of Terraform's "No changes".

**Safety:** the database URLs come only from environment variables or secrets and are never printed (passwords are stripped from error text); the live
connection is read-only; DriftPilot only ever creates and drops databases it owns (names that start with `driftpilot_scratch_`); secret-looking text in a default
value or comment is replaced by `<redacted>` and never copied into a migration.

**Try it** (needs Docker; everything is local, port 5433):

```bash
cd demo/postgres && docker compose up -d && cd ../..           # wait until "healthy"
export DRIFTPILOT_DB_URL=postgresql://driftpilot_ro:driftpilot_ro@localhost:5433/appdb
export DRIFTPILOT_SCRATCH_DB_URL=postgresql://driftpilot_scratch:driftpilot_scratch@localhost:5433/postgres
uv pip install --python .venv/bin/python -e ".[dev,demo,db,aws]"
driftpilot db scan --dir demo/postgres --no-llm                # No drift detected
python scripts/inject_drift.py inject 15                       # RLS off on orders (16 NOT NULL, 17 ssn column, 18 PUBLIC grant, 19 harmless column)
driftpilot db scan --dir demo/postgres --no-llm                # critical / revert
driftpilot db fix  --dir demo/postgres --no-llm                # the SQL, or the verified migration for 19
python scripts/inject_drift.py revert 15
cd demo/postgres && docker compose down -v
```

**Proof it works:** on the local demo each scenario gave the expected result (15 critical/revert, 16 high/revert, 17 high/investigate, 18 critical/revert,
19 medium/codify with a verified migration), the undo SQL made the next scan clean, and no scratch database was left behind. 26 live tests run against that container
(`DRIFTPILOT_TEST_DB_URL=... pytest -m postgres`), and 30 labelled database cases are in the evaluation ([Results](#results)).

**Not covered yet:** views, functions, triggers, enums, extensions, sequences, partitions and MySQL. Only Postgres.

## Results

Everything below was **re-run once on the final version 2 code and prompt** (`triage-v4`, Gemini `gemini-3.1-flash-lite`, answers cached in `eval/cache/`), so the tables agree with each other.
Full tables: [`eval/results/summary.md`](eval/results/summary.md). The labels were written before scoring, by the author of the tool.

### Infrastructure drift

A fixed, labelled test set: **79 inputs, 142 findings** (77 real drift, 23 of them critical, plus 65 noise). It covers all 14 GitHub/Docker demo scenarios, recordings from live runs, variants, and
31 AWS-style cases (version 1 had 73 inputs and 135 findings; the six extra AWS cases are new).

| Setup | Noise filtered | Severity right | Critical caught | Action right | False alarms | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw Terraform | 0% | 0% | 0% | 0% | 100% | 0 |
| Rules only | 98% | 31% | 74% | 32% | 2% | 0 |
| **Rules + Gemini Flash-Lite** | **98%** | **88%** | **87%** | **82%** | **2%** | **46** |
| Gemini without rules | 89% | 90% | 91% | 82% | 11% | 82 |
| Rules + local LLM (Ollama) | not run on the 8 GB test machine | | | | | |

**Compared with version 1 (the old table: 89% severity, 90% critical, 92% action; without rules 98% noise filtered).** Honest reading:

- **Rules only got much better** (severity 19% → 31%, critical caught 45% → 74%, action 19% → 32%) because of the new AWS rules. On the AWS cases alone: severity 16% → 47%, critical caught 36% → 86%, action right 16% → 50% (rules only, no AI).
- **Rules + AI got slightly worse, and action accuracy clearly worse: 92% → 82%.** Severity 89% → 88% and critical caught 90% → 87%. On the original 73 inputs only: severity 87.5%, critical 85%, action 80.6%.
  - **Action:** the model now answers `investigate` (9 findings) or `revert` (5) where the labels expect `codify` (sometimes also accepting `revert`), for example a raised memory limit, a changed restart policy, a wiki turned on. The labels allow the human-friendly "keep it" for deliberate hotfixes; the newer prompt makes the model more cautious.
  - **Critical caught:** three critical findings are missed now: the EC2 public IP (the new rule rates it **high**, as planned, while the label says **critical**; the AI alone used to say critical), attaching `AdministratorAccess` to a user (no rule; the AI said high, it said critical before) and `dismiss_stale_reviews` turned off (rated medium, also missed in version 1).
  - **Cause, unmeasured:** between the version 1 run and this one the prompt changed twice (untrusted-data framing in Phase 5, a `change_event` sentence in Phase 9). I could not separate the two without more AI calls, so I cannot say which one makes the model more cautious. The non-AI numbers did not move.
- **Gemini without rules** now lets 11% of the noise through (7 findings, such as a container's runtime network values that the rules always hide), against 2% in version 1. With the rules in front the false alarm rate stays at 2%. That is the reason for the rules.
- **The rules still cut AI calls** (46 vs 82, about 44% fewer) and guarantee the critical catches when the AI is unavailable.
- **Not re-measured:** prompt stability (the version 1 result, 100% identical on 12 findings, was for an older prompt; it was left out to save quota). Live results from version 1 (event-driven detection in 10–18 s, verified fix PRs on the first attempt, every planted pattern found in the simulated history) are unchanged and were not repeated.
- **Caveat:** labels and prompt were written by the same author.

### Prompt injection (adversarial)

See [Guardrails](#guardrails-the-ai-cannot-be-talked-into-it) for the table: the share of attacks that hide a change fell from 19% to 8% and, on the never-soften list, from 1 of 11 to 0 of 11, with an honest cost on harmless look-alikes.

### Database drift (30 cases, 35 labelled findings)

Catalog replays: the schema the migrations build against a live schema that someone changed by hand (29 real findings, 7 critical; 6 noise). No live database needed.

| Setup | Noise filtered | Real found | Severity right | Critical caught | Action right | False alarms | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw schema diff (every difference "real") | 0% | 100% | 0% | 0% | 0% | 100% | 0 |
| rules only | 83% | 100% | 72% | 100% | 72% | 17% | 0 |
| **rules + Gemini Flash-Lite** | 83% | 100% | **97%** | **100%** | **100%** | 17% | 8 |

The one miss: an index added "for speed" (label low, the AI said medium). The one "false alarm" is an injection case on purpose: a table comment carrying "ignore previous instructions" is a noise change, but the suspicious-input guardrail makes it `investigate`. These cases were written by the author and
calibrated against the rules of the same author, so treat the high numbers as a check that the pipeline works, not as an independent benchmark.

### What was measured live (not in the tables)

- **Postgres demo (Docker):** the five scenarios gave the expected severity and action; the undo SQL made the next scan clean; a verified migration was produced for the harmless-column case; no scratch database was left behind; 26 live tests pass against the container.
- **Runner image:** built and run locally (Terraform 1.9.8 inside, non-root user); it ran a recorded scan and a database scan.
- **Azure (live, Terraform):** on an Azure for Students subscription in Korea Central, Terraform created a resource group, a storage account and a network security group. The baseline scan found no drift. After three portal changes and a tag edit, DriftPilot reported four real findings, all decided by rules with no AI call: three critical (SSH open to any source, blob public access on, HTTPS-only off, each `revert`) and one low (tag edit, `codify`). It then wrote one issue per resource with the undo commands. Everything was destroyed afterwards and a clean check passed. The run needed an MFA sign-in for writes and one of the five allowed regions.
- **Postgres on Neon (live, cloud):** the demo tables and a read-only login were created on a free Neon project (Postgres 18.7). A clean scan found nothing; after row-level security was switched off, a grant to everyone was added and an `ssn` column was added by hand, DriftPilot reported two critical findings (`revert`) and one high (`investigate`), all by rule, and printed the undo SQL. After undoing the changes the scan was clean and no scratch database was left.
- **AWS (live):** not run. The account used was on the AWS Free plan, whose service control policy refused creating S3 buckets and denied EC2 and RDS in every region tried. Nothing was created. AWS support is tested only with mocks, recorded events and recorded plans.
- **Not run anywhere:** the deploy templates and the GitHub Action on version 2.

### Proven on two repositories (version 1)

| Repository | Terraform style | Live result |
| --- | --- | --- |
| `driftpilot-demo/infra` | Written for the demo (repos, branch protection, teams) | Hand change → run started by itself → critical issue → fixed → "No drift detected" |
| `driftpilot-demo/platform` | **Someone else's code**: the community module [`cloudposse/repository/github`](https://registry.terraform.io/modules/cloudposse/repository/github), using rulesets | Weakened ruleset → critical issue; description change → verified PR that edits the **module call** |

Running on someone else's code exposed six real problems, all fixed in v1:
- the scanner needed scoping when an org has several Terraform setups
- rulesets were unknown to the rules
- code inside a module couldn't be fixed directly
- a revert command broke when pasted into a shell
- module warnings cluttered the proof
- `-target` also touched dependencies, so issues now say to preview first

Version 2 has **not** been run on those live repositories yet (the branch is local); its checks are the tests, the recorded evaluations and the local Docker demos described above.

## Use it

### In a company: about 15 minutes, once

1. **Pick the repo that holds your Terraform code** (and, for the database check, your migration files). Application repos don't need anything.
2. **Make sure the GitHub runner can read your Terraform state** (e.g. an S3 or Terraform Cloud backend) and has
   read-only credentials for your provider (e.g. an AWS role via OIDC).
3. **Optional:** add a Gemini API key as the secret `LLM_API_KEY`. Without it, rules and reports still work.
4. **For pull requests:** enable **Settings → Actions → General → "Allow GitHub Actions to create and approve pull
   requests"**.
5. **Add this workflow:**

```yaml
name: DriftPilot
on:
  schedule:
    - cron: "17 */6 * * *"       # every 6 hours
  workflow_dispatch:              # "Run workflow" button
permissions:
  contents: write
  pull-requests: write
  issues: write
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_wrapper: false
      - uses: shreytiwari09/DriftPilot-AI-Terraform-Drift-Detector@v1   # use @v2 once version 2 is released
        with:
          working-directory: infra/
          provider-token: ${{ secrets.INFRA_GITHUB_TOKEN }}   # credentials your Terraform provider needs
          llm-api-key: ${{ secrets.LLM_API_KEY }}
          mode: advise                                         # issues only; use open-prs for fix PRs
          # checks: infrastructure,database                    # version 2: add the Postgres check
          # database-url: ${{ secrets.DRIFTPILOT_DB_URL }}     #   read-only login (a secret, never printed)
          # scratch-database-url: ${{ secrets.DRIFTPILOT_SCRATCH_DB_URL }}
```

DriftPilot covers everything that repository's Terraform manages. With several Terraform repos, add it to each one
and use `include_names` so they don't report each other's resources.

| Input | Default | Purpose |
| --- | --- | --- |
| `working-directory` | `.` | Terraform folder |
| `provider-token` | | Credentials for the provider and scanners (passed as `GITHUB_TOKEN`) |
| `llm-api-key` | | Gemini key; without it, undecided findings stay "needs triage" |
| `llm-provider` / `llm-model` | `gemini` / pinned | `ollama` for a local model |
| `mode` | `advise` | `advise` (issues only) or `open-prs` |
| `config-path` | `.driftpilot.yml` | Repo settings |
| `history-branch` | `driftpilot-data` | Where history is stored |
| `dashboard-repo` / `dashboard-token` | | Public repo with GitHub Pages for the dashboard |
| `checks` *(new)* | `infrastructure` | Comma list: `infrastructure`, `database`, or both |
| `event-path` *(new)* | | A CloudTrail event file: adds "who changed it" to the findings on that resource |
| `database-url` *(new)* | | Live Postgres URL for a **read-only** login. A secret, masked in logs |
| `scratch-database-url` *(new)* | | A Postgres server where DriftPilot may create and drop its own `driftpilot_scratch_*` databases (login with CREATEDB). A secret |
| `migrations-dir` *(new)* | `migrations` | Folder with the migration `.sql` files, relative to `working-directory` |

### Settings (`.driftpilot.yml`)

```yaml
mode: advise
confidence_threshold: 0.7
ignore: ["docker_container.*.restart"]
severity_overrides:
  - match: { type: "github_repository", attribute: "description" }
    severity: low
scanners:
  github:
    owner: my-org
    include_names: ["billing-*"]     # only the repos this Terraform owns
  aws:                               # new: needs `pip install 'driftpilot[aws]'` and read-only AWS credentials
    region: eu-west-1
    ignore_names: ["tmp-*"]
guardrails:
  enabled: true                      # new: sanitising, untrusted-data prompt, never-soften, suspicious-input
limits:                              # new: hard caps, whatever the AI says
  max_llm_calls: 60
  max_prompt_chars: 300000
  max_prs: 5                         # more become issues
  max_files_per_pr: 3
  max_patch_lines: 300               # bigger patches become unverified issues
ownership:                           # new: who owns what (dashboard filters)
  teams:
    - { match: "github_repository.pay-*", team: payments }
  default_team: platform
  environment: prod
  account: "123456789012"            # stored masked
dashboard:
  publish_addresses: true            # false: resource addresses become hashes in data.json
  scan_every_hours: 6                # expected scan interval: on time <= 1.5x, late <= 3x, stale beyond
  sla_hours: { critical: 24, high: 72, medium: 168, low: null }   # "overdue" deadlines (null = none)
notifications:                       # new: needs the `webhook-url` input (a secret) or $DRIFTPILOT_WEBHOOK_URL
  format: slack                      # slack | teams | generic
  min_severity: high                 # new drift below this is not sent
  on: [new_drift, monitor_alert, scan_failed]
database:                            # new: Postgres schema drift
  migrations: migrations
  schemas: [public]
  ignore: ["tmp_*"]
```

### On a laptop (CLI)

The same engine, for trying it out and debugging. It needs Terraform installed and your provider's credentials in
the shell (the database commands need Docker only for the demo).

```bash
pip install "git+https://github.com/shreytiwari09/DriftPilot-AI-Terraform-Drift-Detector@v1"   # version 2: install from the v2 branch or tag once published
driftpilot scan --dir infra/          # drift table, noise hidden (--event FILE adds "who changed it")
driftpilot fix  --dir infra/          # the issues/PRs it would open, with verified patches
driftpilot db scan --dir demo/postgres   # database drift (needs DRIFTPILOT_DB_URL / DRIFTPILOT_SCRATCH_DB_URL)
driftpilot db fix  --dir demo/postgres   # the SQL or migration it would propose
driftpilot report --history history/ --html site/ --csv episodes.csv   # dashboard + CSV
```

Run it as a container instead of in GitHub Actions: `docker build -t driftpilot:dev . && docker run --rm driftpilot:dev version`.
The cloud-runner templates are in [`deploy/`](deploy/README.md) and are **untested**.

## Safety model

- 🚫 **Never applies, never writes to your database.** For Terraform it runs only `init`, `plan`, `show`, `validate` and `fmt`. For Postgres it reads with a
  read-only session and only creates and drops its own scratch databases. People merge PRs or run the commands from an issue.
- 🔒 **Secrets stay out of prompts.** Sensitive values and anything that looks like a token or key are redacted before display or any LLM call.
  Database URLs are never printed.
- 🧼 **Text written by others is data, never instructions.** Everything the AI reads is sanitised and framed as data, and a never-soften list the AI cannot override
  holds even if the AI is fully fooled.
- 🧾 **LLM output is never trusted raw.** It must match a strict schema; otherwise the verdict is `investigate`.
- ✅ **Every PR is proven.** `fmt`, `validate` and a `plan` showing no changes (or, for a database, a scratch database that matches live). Otherwise it becomes an issue labelled `unverified`.
- 🧑‍⚖️ **Critical drift goes to people.** Critical findings never get an automatic PR.
- 📏 **Hard limits and an audit log.** Caps on AI calls, prompt size, PRs and patch size; a log of what was asked (hashes, never the text).

## Demo and evaluation

| What | Command |
| --- | --- |
| Inject or undo any of the 19 drift scenarios (1-14 GitHub/Docker, 15-19 Postgres) | `python scripts/inject_drift.py list \| inject N \| revert N` |
| Clickable demo console (local; has a "5 · Database" tab) | `pip install -e ".[demo]" && streamlit run demo/console/app.py` |
| Postgres demo, click by click | [`demo/postgres/README.md`](demo/postgres/README.md) |
| Regenerate the results (cached LLM answers, no key needed) | `python eval/run_eval.py` |
| Only the prompt-injection evaluation / only the database one | `python eval/run_eval.py --adversarial-only` / `--database-only` |
| Dashboard from simulated history | `python scripts/simulate_history.py --out /tmp/h && driftpilot report --history /tmp/h --html /tmp/site` |

Live dashboards (still the version 1 page): [real history](https://driftpilot-demo.github.io/drift-dashboard/) ·
[simulated 90 days](https://driftpilot-demo.github.io/drift-dashboard/simulated/)

## Repository layout

```
action.yml               GitHub Action (composite)
Dockerfile               the cloud-runner image
driftpilot/
  collector.py           terraform plan -refresh-only → findings
  redact.py              strip secrets before display / LLM
  guardrails.py          sanitise untrusted text, injection signals
  ownership.py           team / environment / account for each finding
  cloud_events.py        CloudTrail events → "who changed it"
  scanners/              GitHub, Docker and AWS resources outside Terraform
  database/              Postgres: catalog, expected schema, diff, SQL, proof
  triage/                rules (YAML, never-soften list), LLM triage + prompts, policy
  remediate/             codify / ignore_changes / import, verify, issues and PRs
  history/               history store, audit log, outcomes, analytics, verdict monitor
  report/                terminal, job summary, dashboard (index.html + data.json)
  evaluation/            labelled-case scorer
demo/                    Docker, GitHub and Postgres demos, demo console
deploy/                  cloud-runner templates (untested)
scripts/                 drift injector (19 scenarios), history simulator
eval/                    cases (main, adversarial, database), results, cached LLM answers
tests/                   612 tests (586 run anywhere; 26 need a live Postgres; no network, no cloud) + recorded fixtures
```

## Related work

DriftPilot builds on these findings and methods. The newer rows (guardrails, cloud, database) come from a short research report
written for version 2; several of the underlying figures are **vendor reports** or blog posts and are marked as such.

### The problem

| Work | Finding | How it shapes DriftPilot |
| --- | --- | --- |
| Rahman, Mahdavi-Hezaveh & Williams, [*A systematic mapping study of infrastructure as code research*](https://arxiv.org/abs/1807.04872), Information and Software Technology 108 (2019) | Defects and security flaws in IaC are under-studied | A tool aimed at that gap |
| Rahman, Parnin & Williams, [*The Seven Sins: Security Smells in Infrastructure as Code Scripts*](https://2019.icse-conferences.org/event/icse-2019-technical-papers-the-seven-sins-security-smells-in-infrastructure-as-code-scripts), ICSE 2019 | 21,201 security smells in 15,232 IaC scripts, including hard-coded passwords | Secrets are redacted; weakened security controls are critical |
| HashiCorp, [HCP Terraform drift detection](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/health) | Drift detection is an established, paid platform feature | DriftPilot adds judgment, verified fixes and learning on top of detection |
| SC Media, [report on the $80M Capital One fine](https://www.scworld.com/news/security-news/regulators-levy-80-million-fine-hammer-capital-one-for-massive-breach) | The Capital One breach combined an over-permissioned IAM role with a misconfiguration; the US bank regulator (OCC) fined the bank $80M | Cloud misconfiguration is a real breach cause: AWS rules for public storage, wildcard IAM, encryption |
| AWS Well-Architected DevOps guidance, [metrics for everything as code](https://docs.aws.amazon.com/wellarchitected/latest/devops-guidance/metrics-for-everything-as-code.html) | Defines "IaC coverage" and "configuration drift rate" | The two dashboard KPIs that are labelled as AWS-defined |
| [CVE-2025-48757](https://nvd.nist.gov/vuln/detail/CVE-2025-48757) (NVD) | A vulnerability caused by a row-level-security misconfiguration (a bad-configuration case) | Row-level security off is critical and on the never-soften list |

### Using an LLM safely

| Work | Finding | How it shapes DriftPilot |
| --- | --- | --- |
| Kon et al., [*IaC-Eval: A Code Generation Benchmark for Cloud Infrastructure-as-Code Programs*](https://proceedings.neurips.cc/paper_files/paper/2024/hash/f26b29298ae8acd94bd7e839688e329b-Abstract.html), NeurIPS 2024 | GPT-4 wrote correct Terraform only about 19% of the time | Every generated fix must pass `terraform plan` before a PR exists |
| Chen, Lin, Schärli & Zhou, [*Teaching Large Language Models to Self-Debug*](https://arxiv.org/abs/2304.05128), ICLR 2024 | Feeding execution feedback back to the model improves code by up to 12% | Terraform's errors go back to the model, for up to 3 attempts |
| Zheng et al., [*Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract.html), NeurIPS 2023 | LLM judges agree with humans over 80% of the time, but have biases | Structured output, a confidence threshold and human approval |
| Aikido, [*PromptPwnd*](https://aikido.dev/blog/promptpwnd-github-actions-ai-agents) (Dec 2025) | Issue titles, PR descriptions and commit messages placed into the prompts of AI agents in GitHub Actions could make them leak tokens (a vendor's security research) | DriftPilot also reads text strangers can write (names, tags, descriptions): it sanitises it and treats it as data |
| SecurityWeek, [report on prompt injection via comments against Claude Code, Gemini CLI and GitHub Copilot agents](https://www.securityweek.com/claude-code-gemini-cli-github-copilot-agents-vulnerable-to-prompt-injection-via-comments/) (Apr 2026) | The same pattern against three coding agents; the fixes were mostly prompt changes | Prompt wording alone is not a defence, so the deterministic never-soften layer is what holds |
| Simon Willison, [*the lethal trifecta*](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) | Danger arises when an agent combines private data, untrusted text and a way to send data out; the reliable fix removes one leg | The AI only classifies and explains; deterministic code acts; output is plain text under a strict schema |
| [Design-patterns paper on securing LLM agents against prompt injection](https://arxiv.org/html/2506.08837v3) (arXiv 2506.08837) | Patterns such as "action selector" confine what an injected model can do | The verdict is a constrained choice; the policy layer decides what happens |
| [Study of adaptive attacks on published prompt-injection defences](https://arxiv.org/abs/2510.09023) (arXiv 2510.09023) | Adaptive attackers beat 12 published defences at over 90% success | Why the numbers in [Results](#results) are reported as measured on a fixed set, not as security proof |

### Learning from history

| Work | Method | Used for |
| --- | --- | --- |
| Killick, Fearnhead & Eckley, [*Optimal detection of changepoints with a linear computational cost*](https://arxiv.org/abs/1101.1438), JASA 2012 | PELT change-point detection | The day the drift level changed |
| Liu, Ting & Zhou, *Isolation Forest*, IEEE ICDM 2008 | Unsupervised anomaly detection | Unusual runs |
| Gama et al., [*A Survey on Concept Drift Adaptation*](https://doi.org/10.1145/2523813), ACM Computing Surveys 2014 | Concept drift: a model's judgment degrading as the world changes | The verdict monitor watches DriftPilot's own judgment |
| Google, [SRE Workbook, alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) | Precision and recall as the language for alert quality | "Alert precision" and "overrule rate" on the dashboard (our adaptation; no published benchmark gives "good" values) |
| Roadie, [documentation on ownership](https://roadie.io/docs/details/ownership) | Ownership from an explicit tag, then CODEOWNERS, then a default | The order DriftPilot uses to decide a team |

### Similar tools

| Tool | Overlap | What DriftPilot adds |
| --- | --- | --- |
| [driftctl](https://github.com/snyk/driftctl) | Drift and unmanaged-resource detection | Severity and intent triage, verified fixes, history |
| [Atlantis](https://www.runatlantis.io/) | Terraform changes reviewed through pull requests | PRs generated from drift and proven before they open |
| [Atlas drift detection](https://atlasgo.io/versioned/drift-detection), Flyway, Liquibase, Bytebase | Compare a live database with its migrations (the stronger versions are paid editions) | Intent triage, a verified migration PR, learning from human decisions, and one brain shared with infrastructure drift (the documentation reviewed does not describe these; a finding from limited reading) |
| [Argo CD diffing](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/) and Flux | Already detect, and can revert, Kubernetes drift | Kubernetes is future work for this reason: the gap is smaller and normalising the noise is a large job |

## Limitations (honest version)

- **Not reinforcement learning, and it does not learn automatically.** It records whether people accept or overrule its advice and measures
  its own judgment over time, but nothing retrains the AI or the rules from that feedback yet.
- **Evidence for the extra drift types is mostly vendor-sourced.** For database and Kubernetes drift the research found tool documentation and vendor writing,
  with no hard statistic and no named public post-mortem. Statistics such as "80% of organisations experience drift" could not be traced to a primary source and are not used.
- **Small, same-author evaluation.** The labelled sets (135 infrastructure findings, 37 attack findings, 35 database findings) were written by the author of the tool and the
  prompts, before scoring; there are no independent labels. One model (Gemini Flash-Lite) and one cached run each; several results are a single run.
- **The guardrails are not a security proof.** Only the never-soften list is a guarantee, and only for security weakenings that are on it. Paraphrased or obfuscated text can
  avoid the injection signals, and the signals also make some harmless look-alikes get escalated to "investigate". Published research shows adaptive attackers beat many defences.
- **Unmeasured:** the local-LLM (Ollama) setup was not run; prompt stability was not re-measured for the current prompt; the effect of "who changed it" on AI verdicts was not
  evaluated (no case carries an event); live AWS behaviour and the cloud deploy templates were never exercised. The database check ran against a free hosted Postgres (Neon) and the Terraform checks against one small Azure subscription, both as small demos.
- **AWS:** rules, scanner and event handling are tested only against mocks (moto), recorded plans and documented event formats; a live run was blocked by the Free plan's service control policy. Two AWS rule gaps are known (attaching
  `AdministratorAccess` to a user has no rule; whether a public IP on an EC2 instance is "high" or "critical" is undecided).
- **Database:** Postgres only; views, functions, triggers, enums, extensions and sequences are not compared; a migration that adds a role-dependent grant needs those roles on the scratch server.
- **Modules:** resources inside modules are fixed by editing the module call; `ignore_changes` can't be set from a call.
- **Imports:** some resources can't be imported without being recreated (e.g. a Docker container's `env`). Verification rejects these, and they become issues.
- **State:** the demo commits Terraform state to git. Real use needs a remote backend with locking.
- **Instant runs:** the demo uses a small relay workflow. In production that would be an org webhook or GitHub App, or CloudTrail with EventBridge on AWS (template provided, untested).
- **Dashboard:** the public dashboard is public, so publish only aggregate data (account numbers and ARNs are masked, addresses can be hashed).
- **Kubernetes drift and data-file drift are future work** (see the roadmap), not features.

## Roadmap

- **Next:** update the demo workflows to version 2, publish the new dashboard, and try the AWS runner and a live AWS check in an account that is not on the Free plan.
- **More drift types:**
  - data-file drift (a baseline profile in Git, a population-stability score with a minimum-sample gate, an "accept new baseline" PR); the research notes found no source linking Terraform drift to data drift, so it would be framed as a triage aid
  - Kubernetes drift (weakest case: Argo CD and Flux already cover it)
  - more database objects (views, functions, triggers, enums) and MySQL
  - Azure and Google Cloud scanners for resources created outside Terraform (the Azure drift checks above use Terraform's plan, so they need no scanner)
- **Smarter judgment:**
  - a classifier trained on accept/overrule decisions
  - noise rules suggested from repeated dismissals
  - independent evaluation labels and more than one model
  - a rule for attaching `AdministratorAccess`, and a decision on EC2 public IP severity
- **Easier for teams:**
  - a GitHub App (one-click, org-wide)
  - Marketplace and PyPI releases
  - Slack approvals
  - an "Apply Guardian" that warns when a PR would undo a hotfix

## Development

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"      # add ,demo,aws,db for the console, AWS scanner and Postgres support
pytest                          # unit tests, no network (live Postgres tests are skipped unless DRIFTPILOT_TEST_DB_URL is set)
ruff check . && ruff format .
```
