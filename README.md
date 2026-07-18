# Phoebe's Data Skills

Data skills you can **install, not just read**.

Each skill in this repo teaches Claude to run one data workflow end to end (EDA first, more coming), and ships with a full visual walkthrough of the workflow on one complex industry case - real code, real executed charts, real review. Built by [Phoebe Fu](https://github.com/phoebefu6).

**Start here:** open `docs/how-to-eda-using-claude-python/` (or the GitHub Pages site once enabled) for the complete walkthrough.

## Why this is different

Most EDA tutorials show you `df.describe()` on the Titanic dataset. These skills work differently:

1. **Installable, not just readable.** Every skill is a Claude skill folder you clone and symlink. Hand Claude your schema and business context; the same 6 steps run on your data.
2. **Real executed outputs only.** Every chart on every page came from an actual run with a fixed seed (42). No mockups, no "illustrative" screenshots. Re-run the scripts and you get pixel-identical results.
3. **A built-in answer key.** The sample-data generator plants problems on purpose - missing-not-at-random values, an outlier merchant, duplicate rows, seasonality, a suspicious segment - and documents them in its docstring. The analysis is then graded against that ground truth: did EDA catch everything we hid? (Spoiler: all 5, plus one bonus finding that wasn't planted.)
4. **Decision-first, not technique-first.** The objective is a question an executive would pay to answer, every chart is titled with its finding, and results are ranked by dollar impact - not by p-value.
5. **Review that changes the code.** Version 1 of the analysis is kept in the repo with its real flaws. Four reviewer lenses (code level, methodology, decision framing, practicality) produced concrete fixes; version 2 applies them. The before/after is on the page - review that changes nothing is theater.

## The 6-step pipeline

Every skill runs the same spine:

```
1. Input        schema + business context
2. Sample data  seeded generator with planted quirks (skipped when real data exists)
3. Objective    one decision question + 3-5 sub-questions
4. Find-skills  assemble the toolbox before writing code
5. Code+charts  data-quality gate first, then business questions, 10+ chart types
6. Mentor-verify apply the fixes, re-run, keep the before/after
```

## Install

Requires [Claude Code](https://claude.com/claude-code) and Python 3.10+ with pandas, matplotlib, seaborn, statsmodels.

```bash
git clone https://github.com/phoebefu6/phoebe-data-skills.git
ln -s "$PWD/phoebe-data-skills/skills/how-to-eda" ~/.claude/skills/
```

Then in Claude Code, paste your schema and say something like:

```
Run EDA on this schema. Business context: <your industry, business model,
what the team cares about this quarter>.
```

Claude picks up the `how-to-eda` skill and walks the 6 steps on your data.

### Reproduce the showcase run

```bash
cd phoebe-data-skills/materials/how-to-eda
python generate_everrest.py    # 8 tables, 233,835 rows, seed 42
python eda_everrest_v2.py      # 12 charts + findings.md, ranked by $ impact
```

## Repo layout

```
skills/          installable Claude skills (one folder per skill)
docs/            the walkthrough site (homepage + one page per skill)
materials/       Everrest case canon + generator + v1/v2 analysis scripts
```

## The case: Everrest

Everrest is a fictional B2B2C retail platform in Southeast Asia - 400 merchants, 20,000 customers, 8 tables. Complex enough for pareto curves, cohort grids, seasonal decomposition, and one bulk wholesaler (M0007 "Summit Wholesale Co") that distorts every KPI it touches. Full canon in `materials/everrest-case.md`. No real company data anywhere in this repo.

## Roadmap

- `how-to-eda-using-claude-python` - live
- `how-to-feature-engineering` - planned
- `how-to-data-quality` - planned
- `how-to-forecasting` - planned

## License

MIT
