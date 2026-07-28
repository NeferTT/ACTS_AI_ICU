# ICU Admission Tool
   A Python tool to support ICU admission decision-making using patient case data.
# ACTS-AI — Daily ICU Progress Note (MVP)

A Streamlit prototype that drafts a daily ICU progress note for mechanically
ventilated adult patients from structured case data, with a physician
review-and-sign-off workflow built in.

**This is a research/capstone prototype, not a validated clinical tool.**
It is tested only on synthetic cases, produces drafts that always require
physician review and sign-off, and is out of scope for any patient who is not
an adult receiving invasive mechanical ventilation (the app enforces this
scope gate and will refuse to draft a note otherwise).

## What it does

- Loads a structured synthetic ICU case (JSON) from `cases/`.
- Sends it to an LLM (via the OpenAI API) using a frozen, versioned prompt
  (`prompt.py`) that requires every clinical statement to be tagged with the
  exact source identifier it came from, forbids inventing data, and flags
  contradictions instead of silently resolving them.
- Displays the draft note next to its evidence tags, runs automated
  traceability and consistency checks, and only allows sign-off after the
  reviewing physician has seen and acknowledged any flags.
- Logs every generation/approval/rejection to `audit_log.csv` for later
  review.

## Project structure

## How to run it

There are two ways to use this app: run it yourself locally, or deploy it as a live website. GitHub itself does not run the app — GitHub only stores the code. Either option below reads directly from this repository, so there is nothing to "build" or upload separately.

### Option A — Run it on your own computer

1. **Clone the repo**
```bash
   git clone https://github.com/<your-username>/<repo-name>.git
   cd <repo-name>
```

2. **Create a virtual environment** (recommended, keeps dependencies isolated)
```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
   pip install -r requirements.txt
```

4. **Provide your OpenAI API key** — pick one:
   - Paste it into the sidebar text field when the app opens (kept in memory for that session only), or
   - Create a file at `.streamlit/secrets.toml` in the project folder:
```toml
     OPENAI_API_KEY = "sk-..."
```
   - Or set it as an environment variable: `export OPENAI_API_KEY=sk-...` (Windows: `set OPENAI_API_KEY=sk-...`)

5. **Run the app**
```bash
   streamlit run app.py
```
   This opens automatically in your browser, usually at `http://localhost:8501`.

### Option B — Deploy it for free as a live website (Streamlit Community Cloud)

This runs directly from this GitHub repo — no separate upload needed.

1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click **New app**.
3. Select this repository, branch `main`, and set the main file path to `app.py`.
4. Under **Advanced settings → Secrets**, add:
```toml
   OPENAI_API_KEY = "sk-..."
```
5. Click **Deploy**. After a minute or two, you'll get a public URL for the live app.
6. Any future `git push` to `main` automatically redeploys the app with your latest code.

## Continuous integration

`.github/workflows/ci.yml` runs automatically on every push or pull request to `main`. It installs the dependencies, checks all Python files for syntax errors, and validates that every file in `cases/` is well-formed JSON. This does **not** run or host the app — it only catches broken commits early. Check the **Actions** tab on GitHub after pushing to see the result.

## The synthetic test cases

Each file in `cases/` is fabricated data built to probe a specific behavior:

| File | Tests |
|---|---|
| `02_synthetic_case_01_deteriorating.json` | Trend detection, missing chest X-ray, undocumented code status |
| `07_synthetic_case_02_stable.json` | Proportionate tone, an allergy/medication safety flag |
| `08_synthetic_case_03_incomplete.json` | Behavior under large data gaps — must not invent values |
| `09_synthetic_case_04_contradictory.json` | Contradiction detection (extubation vs. charted vent settings; conflicting med status) |
| `10_synthetic_case_05_out_of_scope.json` | The scope gate — non-invasive ventilation must be refused, not drafted |

No real patient data is used or should ever be added to this folder.

## Safety design notes

- **Scope gate**: the prompt requires the model to refuse (`in_scope: false`)
  for anyone not an adult on invasive mechanical ventilation, rather than
  drafting a plausible-but-invalid note.
- **Source tagging**: every statement must cite a real `source_id` from the
  input case; invented identifiers or untagged claims are surfaced as flags
  in the UI, not silently accepted.
- **Human sign-off required**: there is no path in the app that files a note
  without an explicit physician approval action, and case-switching mid-review
  withholds the draft to prevent showing one patient's note next to another's data.

## License / disclaimer

Prototype for educational/capstone purposes. Not FDA-cleared, not validated
for clinical use, and not intended to make or influence real admission or
treatment decisions.
