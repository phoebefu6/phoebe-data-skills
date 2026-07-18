# Instructions - install and run the skills

Operational guide for running these skills on your own data. For the "what and why," see [README.md](README.md).

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ with `pandas`, `matplotlib`, `seaborn`, `statsmodels`, `duckdb`,
  `pandera` (only needed to run the baseline scripts; Claude writes/tunes them either way)

## Install (recommended) - one skill at a time

Each skill is its own plugin, so analysts install only what they need. Add the
marketplace once, then install per skill in Claude Code:

```
/plugin marketplace add phoebefu6/phoebe-data-skills
/plugin install how-to-eda@phoebe-data-skills
```

Swap `how-to-eda` for any skill: `how-to-eda-codex`, `how-to-rfm`,
`how-to-schema-and-warehouse`, `how-to-schema-consolidation`. Each ships **with its
baseline python bundled**. When the repo updates, analysts get the new version with
`/plugin marketplace update phoebe-data-skills`.

## Install (single skill, no marketplace) - clone + symlink

```bash
git clone https://github.com/phoebefu6/phoebe-data-skills.git
ln -s "$PWD/phoebe-data-skills/plugins/how-to-eda/skills/how-to-eda" ~/.claude/skills/how-to-eda
```

## The baseline script (start here, then tune)

Every skill ships a runnable baseline in `plugins/<skill>/skills/<skill>/baseline/` -
the real code behind the Everrest showcase. Ask Claude:

```
Use how-to-eda. Start from the baseline script and tune it for my data.
Business context: <your industry / question>.
<paste your table + column list>
```

Claude reads the bundled baseline, then adapts it to your schema and question -
you get a working script fast instead of a blank page.

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
.claude-plugin/  marketplace.json (the skill catalog)
plugins/         one installable plugin per skill (SKILL.md + baseline/ inside)
docs/            the showcase site (homepage + one page per skill)
materials/       Everrest case canon + generator + v1/v2 analysis scripts
```

Generated data (`materials/*/data/`) and v1 output are gitignored - regenerate them from the seeded scripts above.
