# Universal Research Intelligence Assistant (URIA)

A modular, researcher-led Streamlit workbench for journal discovery, literature scanning, open-dataset discovery, climate and agriculture data workflows, research-project planning and conversational AI research assistance.

**Current implementation: Phases 1.1, 2, 2.2, 2.3, 3.1 and 3.2.**

## Implemented capabilities

### Phase 1.1 — Journal discovery and publication-readiness screening
- Discover journal records through OpenAlex Sources and check metadata through Crossref.
- Record human-verified evidence for publication fees, Scopus and Web of Science status, scope, peer review, author guidelines and ethics.
- Rank and export transparent journal shortlists. Scores are screening aids, not acceptance probabilities or journal-quality certifications.

### Phase 2 — Research topic, literature and dataset intelligence
- Search scholarly records through OpenAlex and screen using a transparent keyword-overlap heuristic.
- Explore recurring terms and candidate research questions.
- Discover dataset leads through Zenodo, Harvard Dataverse and World Bank indicators.
- Export literature scan results to CSV. Results are leads, not proof of a research gap.

### Phase 2.2 — Agriculture and climate data explorer
- Retrieve monthly point climate data from NASA POWER.
- Link to official FAOSTAT and CHIRPS portals and workflows.

### Phase 2.3 — Kenya agriculture and rainfall integration
- Download normalized FAOSTAT bulk records and filter Kenya maize production, area harvested and yield for 2000–2025.
- Retrieve CHIRPS v2 monthly GeoTIFFs and calculate an unweighted Kenya-wide mean using a Kenya ADM0 boundary.
- Preview an exploratory annual merge. Check units, flags, versions, coverage and suitability before inference. Bulk and raster downloads can be very large; start with one year.

### Phase 3.1 — Universal research workspace
- Structure ordinary-language ideas into candidate titles, draft objectives and keywords.
- Save projects, update workflow status and export the local SQLite project register.
- The brief generator is rule-based; drafts require researcher review.

### Phase 3.2 — Conversational AI research assistant
- Chat through the OpenAI Responses API with its web-search tool.
- Supply research-discipline, geography and study-period context.
- Explore topics, literature, datasets, methods, R code, manuscripts and journal selection.
- Review and explicitly approve a response before saving it to the project library.

Phase 3.2 requires an OpenAI API key. API usage is billed separately from a ChatGPT subscription. The app reads `OPENAI_API_KEY` from the environment, Streamlit secrets or a session-only password field. Requests use `store=False`; submitted conversation content is sent to the OpenAI API. Do not submit confidential participant data or identifiable health information.

## Planned capabilities
- Systematic evidence-grounded research-gap validation.
- Dataset suitability scoring and complete human-approval workflow.
- Controlled R/Python execution and reproducible environments.
- Automated manuscript and LaTeX workflows with journal-specific formatting.
- Multi-user authentication and centrally hosted database synchronisation.

## Installation

Python 3.11 is recommended. See [requirements.txt](requirements.txt). Rasterio supports CHIRPS raster extraction; OpenAI and python-dotenv support Phase 3.2.

### Windows
```bat
py -3.11 -m venv .venv
.venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Linux or macOS
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## OpenAI API configuration

Create a private `.env` file in the project root:
```text
OPENAI_API_KEY=your_api_key_here
URIA_MODEL=gpt-5.5
```

Use a model enabled for your API project and restart Streamlit after changes. Alternatively, set `OPENAI_API_KEY` in Streamlit deployment secrets. Never commit `.env` or API keys. API billing is separate from ChatGPT subscriptions.

## Local storage and backups

Journal verification and research projects are stored in `data/research_journals.db`. FAOSTAT and CHIRPS downloads are cached under `data/phase2_3/`. These data are excluded from Git; back up `data/` separately. Hosted platforms may have ephemeral local storage; use managed database and object storage for durable multi-device deployments.

## Data sources

OpenAlex, Crossref, Zenodo, Harvard Dataverse, World Bank Indicators, NASA POWER, FAOSTAT, CHIRPS and geoBoundaries. Phase 3.2 also uses the OpenAI API and web-search tool. Retain source URLs, retrieval dates, versions and documentation in research records.

## Security and research ethics

- Never commit `data/`, downloaded datasets, unpublished manuscripts, participant data, `.env`, credentials or `.streamlit/secrets.toml`.
- Review dataset licences, privacy restrictions and research ethics before using or redistributing data.
- Do not enter confidential participant information or identifiable health data into the conversational assistant.
- URIA is a research-support prototype, not an autonomous researcher. Verify sources and claims; never fabricate citations or results. Human approval remains essential for topics, datasets, analysis, interpretation and manuscripts.


### Phase 4 — Academic Opportunities & Application Intelligence
- Analyse official conference, grant, fellowship, scholarship and research-visit opportunity pages from a pasted URL; paste call text when a portal blocks automated access.
- Extract eligibility, deadlines, funding, submission instructions, document requirements, word limits and selection criteria; unknown information is explicitly flagged for verification.
- Generate opportunity-tailored academic CVs, abstracts, proposals, motivation and cover letters, research statements, budgets and compliance reports.
- Apply ATS-friendly CV structure and run basic readability checks. The researcher must review final formatting in the actual portal and confirm every claim.
- Maintain a master academic profile, accept an uploaded master CV/publication record, and archive generated DOCX documents and opportunity analyses in a local SQLite register.
- Optionally email generated documents to the applicant using separately configured Gmail SMTP credentials.
- The system does not autonomously sign declarations, pay fees or submit applications. Final review and submission remain under the applicant's control.

Phase 4 requires `beautifulsoup4`, `python-docx` and `pypdf`. Configure `OPENAI_API_KEY` and optionally `URIA_MODEL` in the private `.env` file. For optional Gmail SMTP filing, configure `URIA_EMAIL_SENDER`, `URIA_EMAIL_APP_PASSWORD` and optionally `URIA_EMAIL_RECIPIENT`. Never commit credentials. The SMTP option uses a Gmail App Password, not your normal account password.

**Local archive:** opportunity records, profile text and generated DOCX files are stored under `data/academic_applications/`. Back up this folder; it is excluded from Git.
