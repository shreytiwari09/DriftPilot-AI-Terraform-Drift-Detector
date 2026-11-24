## Database schema drift evaluation

30 cases, 35 labelled findings (Postgres, `eval/cases/database.yaml`): the schema the migrations build against a live schema that someone changed by hand. No Terraform and no live database is needed: the cases are catalogs plus hand changes. The main tables above do not include them.

| Setup | Noise filtered | Real drift found | Severity right | Critical caught | Action right | False alarms | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw schema diff | 0% | 100% | 0% | 0% | 0% | 100% | 0 |
| rules only | 83% | 100% | 72% | 100% | 72% | 17% | 0 |
| rules + cloud LLM | 83% | 100% | 97% | 100% | 100% | 17% | 8 |

Where `rules + cloud LLM` is not right (1 of 29 real findings):

- `db-index-added-for-speed` `index:CREATE INDEX ON public.orders USING btree (status)`: expected low / codify|investigate, got medium / codify (llm)

Noise reported as drift:

- `db-injection-next-to-an-rls-switch` `comment`: reported as medium / investigate (policy)

- *rules only* leaves findings no rule decides as "needs triage": they count as real (a person sees them) but with no severity or action, so severity and action accuracy show what the AI has to add.
- Weakenings of row-level security, policies and grants to PUBLIC are decided by rules and are on the never-soften list, so the AI cannot play them down.
