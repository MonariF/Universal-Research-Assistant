# Universal Research Intelligence Assistant

A modular, researcher-led Streamlit workbench for journal discovery, literature scanning, open-dataset discovery, climate and agriculture data workflows, and research-project planning.

**Published baseline: Phase 3.1.1 — Research Brief Quality Fix.**

## Current capabilities

### Phase 1.1 — Journal discovery and publication-readiness screening
- Discover journal records through the OpenAlex Sources API.
- Check journal metadata through Crossref.
- Record evidence for publication fees, Scopus and Web of Science status, scope, peer review, author guidelines and ethics.
- Rank a journal shortlist using transparent discovery and human-verification scores.
- Export journal shortlists to CSV.

The scores are screening aids, not journal-quality certifications or probabilities of acceptance. Unverified fee and indexing claims must be checked against official sources.

### Phase 2 — Research topic, literature and dataset intelligence
- Search scholarly records through OpenAlex.
- Screen records using a transparent keyword-overlap relevance heuristic.
- Explore recurring terms in the retrieved literature sample.
- Produce candidate research questions for researcher review.
- Discover dataset leads through Zenodo, Harvard Dataverse and World Bank indicators.
- Export literature scan results to CSV.

The app treats these results as leads; it does not claim that a candidate topic is a proven research gap.

### Phase 2.2 — Agriculture and climate data explorer
- Retrieve monthly point climate data from NASA POWER.
- Link to official FAOSTAT and CHIRPS portals and workflows.

### Phase 2.3 — Kenya agriculture and rainfall integration
- Download public normalized FAOSTAT bulk records and filter Kenya maize production, area harvested and yield records for 2000–2025.
- Retrieve CHIRPS v2 monthly GeoTIFF files and calculate a Kenya-wide mean from valid grid cells using a Kenya ADM0 boundary.
- Preview an exploratory annual merge of maize yield and rainfall, with CSV export.

**Resource warning:** FAOSTAT's normalized archive can be large. CHIRPS monthly GeoTIFFs are global grids; a multi-year download may require several gigabytes. Begin with one year. The current CHIRPS national mean is an unweighted mean of valid grid cells, not an area-weighted national estimate. Check units, flags, coverage, versions and suitability before statistical inference.

### Phase 3.1.1 — Universal research workspace
- Accept a research instruction in ordinary language.
- Structure an idea into candidate working titles, draft objectives and suggested keywords.
- Clean common conversational lead-ins and reduce duplicated geography in title suggestions.
- Save projects and update workflow status in a local SQLite research-project table.
- Export the research-project register to CSV.

The brief generator is **rule-based**, not a hosted generative-AI model. Draft titles, objectives and keywords require researcher review and validation against literature, available data and appropriate methods.

## Planned capabilities — not yet implemented
- Hosted conversational AI and research-tool orchestration.
- Evidence-grounded research-gap validation with source citations.
- Dataset suitability scoring and a complete human-approval workflow.
- R/Python code generation and controlled code execution.
- Automated manuscript drafting, LaTeX generation and journal-specific formatting.
- Multi-user authentication and centrally hosted database synchronisation.

Human review remains essential for topic selection, data selection, analysis, interpretation and manuscript approval.

## Installation

Python 3.11 is recommended.

Dependencies are listed in [requirements.txt](requirements.txt). Rasterio is used for CHIRPS raster extraction.

### Windows
```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
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

Open the local URL shown by Streamlit, usually `http://localhost:8501`.

## Local storage and backups

Journal verification records and research projects are stored in `data/research_journals.db`. Phase 2.3 caches downloaded FAOSTAT and CHIRPS files under `data/phase2_3/`. These files are excluded from Git. Back up the local `data/` directory separately before upgrading or moving the application.

Cloud deployments may have ephemeral local storage. Use a managed database and durable object storage before relying on hosted persistence across restarts or devices.

## Data sources

The application calls public services and data sources including OpenAlex, Crossref, Zenodo, Harvard Dataverse, World Bank Indicators, NASA POWER, FAOSTAT, CHIRPS and geoBoundaries. Internet access is needed for retrieval. API availability, rate limits, dataset definitions and source versions can change. Retain source URLs, retrieval dates, versions and data documentation in formal research records.

## Security and research ethics

- Do not commit `data/`, downloaded datasets, unpublished manuscripts, participant data or confidential records.
- Do not commit API keys, passwords, access tokens or `.streamlit/secrets.toml`.
- The current source uses public API endpoints and contains no private provider key.
- Review dataset licences, privacy restrictions and research ethics before using or redistributing downloaded data.

## Project status

This is a research-support prototype and workflow workbench, not an autonomous researcher. It must not invent citations, fabricate data or submit manuscripts without explicit human verification and approval.
