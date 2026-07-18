# Instructions - install and run the skills

Operational guide for running these skills on your own data. For the "what and why," see [README.md](README.md).

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ with `pandas`, `matplotlib`, `seaborn`, `statsmodels`
  (only needed to execute the analysis scripts; Claude writes them either way)

## Install a skill

```bash
git clone https://github.com/phoebefu6/phoebe-data-skills.git
ln -s "$PWD/phoebe-data-skills/skills/how-to-eda" ~/.claude/skills/
```

Each folder under `skills/` is a standalone Claude skill. Symlink the ones you want; Claude Code picks them up automatically.

## Run it on your own data

In Claude Code, give Claude your schema and business context:

```
Run EDA on this schema. Business context: <your industry, business model,
what the team cares about this quarter>.

<paste your table + column list>
```

Claude picks up the `how-to-eda` skill and walks the 6 steps. When you already have real data, step 2 (sample-data generation) is skipped - the quirks are already in your tables.

## Reproduce the showcase run

To regenerate everything on the Everrest walkthrough exactly:

```bash
cd phoebe-data-skills/materials/how-to-eda
python generate_everrest.py    # 8 tables, 233,835 rows, seed 42
python eda_everrest_v2.py      # 12 charts + findings.md, ranked by $ impact
```

Fixed seed means byte-identical output every run. `eda_everrest_v1.py` is the pre-review version kept for the before/after comparison.

## Repo layout

```
skills/          installable Claude skills (one folder per skill)
docs/            the showcase site (homepage + one page per skill)
materials/       Everrest case canon + generator + v1/v2 analysis scripts
```

Generated data (`materials/*/data/`) and v1 output are gitignored - regenerate them from the seeded scripts above.
