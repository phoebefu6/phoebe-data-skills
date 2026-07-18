# Phoebe's Data Skills

**Data skills you can install, not just read.**

I'm [Phoebe Fu](https://github.com/phoebefu6). I build data and applied-AI skills that turn Claude into a working analyst - and I show the whole thing, end to end, on one complex industry case. Real code, real executed charts, real review. No toy datasets, no mockups.

### 🔗 See it in action

**[Open the showcase site →](https://phoebefu6.github.io/phoebe-data-skills/)** *(live once Pages is on)*

Watch `how-to-EDA` run a full exploratory analysis on Everrest, a fictional B2B2C retail platform - 233,835 rows, 12 chart types, six findings ranked by dollar impact. Every chart on the page came from a real run you can reproduce.

## Why these are different

Most data tutorials show you `df.describe()` on the Titanic dataset. These skills work differently:

🧩 **Installable, not just readable.** Each skill is a Claude skill you install once. Hand Claude your own schema and business context; it runs the same steps on your data.

📊 **Real executed outputs only.** Every chart came from an actual run with a fixed seed. No mockups, no "illustrative" screenshots - re-run it and get identical results.

🎯 **A built-in answer key.** The sample data has problems planted on purpose - missing values, an outlier merchant, duplicate rows, hidden seasonality, a suspicious segment. Then the analysis is graded: did it catch everything we hid? (It caught all five, plus one bonus nobody planted.)

💰 **Decision-first, not technique-first.** The question is one an executive would pay to answer. Every chart is titled with its finding. Results are ranked by dollars, not p-values.

🔁 **Review that changes the code.** Version 1 of each analysis is kept with its real flaws. Four reviewer lenses tear it apart; version 2 applies the fixes. The before-and-after is right there on the page.

## The idea behind every skill

Each skill walks the same six steps - so once you've seen one, you can read them all:

**Input** → **Sample data** → **Objective** → **Find-skills** → **Code + charts** → **Mentor-verify**

Schema in, a decision question, the toolbox Claude assembles, the real analysis, and a review loop that actually rewrites the code.

## What's inside

| Skill | What it does | Status |
|-------|-------------|--------|
| **how-to-EDA** | Full exploratory data analysis, decision-first | ✅ Live |
| how-to-feature-engineering | Raw tables → model-ready features | 🔜 Planned |
| how-to-data-quality | Schema → automated quality gates | 🔜 Planned |
| how-to-forecasting | Demand forecast with seasonality + honesty | 🔜 Planned |

## Want to run these yourself?

Installation and usage steps are in **[INSTRUCTION.md](INSTRUCTION.md)**. Short version: clone, symlink the skill into Claude Code, hand it your schema.

## Follow along

I ship these in public. Star the repo to catch new skills, and find me on [GitHub](https://github.com/phoebefu6).

---

*The Everrest case is entirely fictional - no real company data appears anywhere in this repo. MIT licensed.*
