import streamlit as st
import pandas as pd
import requests
import sqlite3
import json
import re
from datetime import date
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path

APP_TITLE = "Universal Research Intelligence Assistant"
DB_PATH = "data/research_journals.db"
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
OPENALEX = "https://api.openalex.org/sources"
CROSSREF = "https://api.crossref.org/journals"

AREAS = {
    "Statistics and Data Science": ["statistics", "data science", "biostatistics", "statistical methods"],
    "AI and Machine Learning": ["artificial intelligence", "machine learning", "computational intelligence"],
    "Climate Analytics": ["climate", "climate change", "climate science", "environmental science"],
    "Agroforestry and Food Security": ["agroforestry", "agriculture", "food security", "agronomy"],
    "Medical Biostatistics": ["medical statistics", "biostatistics", "public health", "epidemiology"],
    "Epidemiology and Demography": ["epidemiology", "demography", "population health", "population studies"],
}
FEE_OPTIONS = ["Not checked", "No mandatory fee confirmed", "Fee applies", "Waiver available", "Unclear"]
INDEX_OPTIONS = ["Not checked", "Verified active", "Verified discontinued", "Not indexed"]

st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS journals (
        openalex_id TEXT PRIMARY KEY, name TEXT, issn TEXT, publisher TEXT, homepage TEXT,
        is_oa INTEGER, is_doaj INTEGER, apc_usd REAL, works_count INTEGER, cited_by_count INTEGER,
        area TEXT, fit_score REAL, evidence_json TEXT, updated_at TEXT)""")
    conn.commit()
    return conn

def safe_int(v):
    try: return int(v or 0)
    except (TypeError, ValueError): return 0

def clean_issn(value):
    return re.sub(r"[^0-9Xx]", "", value or "").upper()

def openalex_search(term, mailto=""):
    params = {"search": term, "filter": "type:journal", "per-page": 50,
              "select": "id,display_name,issn,issn_l,host_organization_name,homepage_url,is_oa,is_in_doaj,apc_usd,works_count,cited_by_count,topics"}
    if mailto.strip(): params["mailto"] = mailto.strip()
    r = requests.get(OPENALEX, params=params, timeout=35,
                     headers={"User-Agent": "ResearchPublicationIntelligence/0.2"})
    r.raise_for_status()
    return r.json().get("results", [])

def score_journal(j, terms):
    name = (j.get("display_name") or "").lower()
    topic_text = " ".join(str(t.get("display_name", "")) for t in (j.get("topics") or [])).lower()
    text = f"{name} {topic_text}"
    hits = sum(1 for term in terms if term.lower() in text)
    scope = min(30, hits * 10)
    doaj = 15 if j.get("is_in_doaj") else 0
    oa = 5 if j.get("is_oa") else 0
    metadata = (5 if j.get("homepage_url") else 0) + (5 if j.get("issn") or j.get("issn_l") else 0) + (5 if j.get("host_organization_name") else 0)
    works, cites = safe_int(j.get("works_count")), safe_int(j.get("cited_by_count"))
    activity = (5 if works >= 100 else 2 if works > 0 else 0) + (5 if cites >= 1000 else 2 if cites > 0 else 0)
    return min(70, scope + doaj + oa + metadata + activity), {
        "topic_match_0_30": scope, "doaj_signal_0_15": doaj,
        "open_access_signal_0_5": oa, "metadata_0_15": metadata,
        "activity_0_10": activity
    }

def normalize(j, area, terms):
    score, details = score_journal(j, terms)
    issns = j.get("issn") or []
    if isinstance(issns, str): issns = [issns]
    return {
        "openalex_id": j.get("id", ""), "journal": j.get("display_name", "Unknown"),
        "ISSN": ", ".join(issns) or j.get("issn_l") or "",
        "publisher": j.get("host_organization_name") or "Not supplied",
        "homepage": j.get("homepage_url") or "", "OpenAlex OA": bool(j.get("is_oa")),
        "DOAJ listed": bool(j.get("is_in_doaj")),
        "APC (USD)": j.get("apc_usd") if j.get("apc_usd") is not None else "Not reported",
        "works": safe_int(j.get("works_count")), "citations": safe_int(j.get("cited_by_count")),
        "research_area": area, "discovery_score": score, "score_details": details
    }

def crossref_check(issn):
    clean = clean_issn(issn)
    if not clean: return None, "Enter a valid ISSN."
    try:
        r = requests.get(f"{CROSSREF}/{clean}", timeout=20,
                         headers={"User-Agent": "ResearchPublicationIntelligence/0.2"})
        if r.status_code == 200: return r.json().get("message", {}), "Crossref record found."
        return None, f"No Crossref journal record returned (HTTP {r.status_code})."
    except requests.RequestException as e:
        return None, f"Crossref request failed: {e}"

def default_evidence():
    return {"fee_status":"Not checked","fee_amount":"","fee_currency":"USD",
            "fee_url":"","scopus_status":"Not checked","scopus_url":"",
            "wos_status":"Not checked","wos_url":"","scope_reviewed":False,
            "peer_review_reviewed":False,"guidelines_reviewed":False,
            "ethics_reviewed":False,"notes":"","checked_at":""}

def get_evidence(raw):
    try:
        data = json.loads(raw or "{}")
        base = default_evidence()
        base.update(data if isinstance(data, dict) else {})
        return base
    except Exception: return default_evidence()

def save_rows(rows):
    conn = db()
    for r in rows:
        old = conn.execute("SELECT evidence_json FROM journals WHERE openalex_id=?", (r["openalex_id"],)).fetchone()
        evidence = get_evidence(old[0] if old else "")
        evidence.setdefault("discovery_score_details", r["score_details"])
        conn.execute("""INSERT OR REPLACE INTO journals
        (openalex_id,name,issn,publisher,homepage,is_oa,is_doaj,apc_usd,works_count,
         cited_by_count,area,fit_score,evidence_json,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (r["openalex_id"],r["journal"],r["ISSN"],r["publisher"],r["homepage"],
         int(r["OpenAlex OA"]),int(r["DOAJ listed"]),
         float(r["APC (USD)"]) if isinstance(r["APC (USD)"],(int,float)) else None,
         r["works"],r["citations"],r["research_area"],r["discovery_score"],
         json.dumps(evidence),now()))
    conn.commit(); conn.close()

def load_saved():
    conn = db()
    rows = conn.execute("SELECT * FROM journals").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM journals").description]
    conn.close()
    return [dict(zip(cols,row)) for row in rows]

def save_evidence(journal_id, evidence):
    evidence["checked_at"] = now()
    conn = db()
    conn.execute("UPDATE journals SET evidence_json=?, updated_at=? WHERE openalex_id=?",
                 (json.dumps(evidence), now(), journal_id))
    conn.commit(); conn.close()

def verification_score(ev):
    # Only verified evidence contributes. Unknown is not treated as positive.
    score = 0
    score += 10 if ev.get("fee_status") == "No mandatory fee confirmed" else 5 if ev.get("fee_status") == "Waiver available" else 0
    score += 10 if ev.get("scopus_status") == "Verified active" else 0
    score += 10 if ev.get("wos_status") == "Verified active" else 0
    score += 5 if ev.get("scope_reviewed") else 0
    score += 5 if ev.get("peer_review_reviewed") else 0
    score += 5 if ev.get("guidelines_reviewed") else 0
    score += 5 if ev.get("ethics_reviewed") else 0
    return score

def official_links(name, issn):
    q = quote(name)
    return {
        "Publisher author guidelines": f"https://www.google.com/search?q={q}+official+author+guidelines",
        "Publisher publication fees": f"https://www.google.com/search?q={q}+official+publication+fees+APC",
        "Scopus source verification": f"https://www.google.com/search?q={q}+ISSN+Scopus+Sources",
        "Web of Science verification": "https://mjl.clarivate.com/home",
        "DOAJ search": f"https://doaj.org/search/journals?ref=homepage&q={q}",
        "Crossref ISSN search": f"https://api.crossref.org/journals/{clean_issn(issn)}" if clean_issn(issn) else "https://search.crossref.org/"
    }

st.title("🧠 Universal Research Intelligence Assistant")
st.caption("Research intelligence · Journal discovery, evidence verification and shortlist ranking")
st.info("Scores are screening aids, not acceptance probabilities. The system never treats missing fee or indexing data as a positive result.")

with st.sidebar:
    st.header("Search settings")
    areas = st.multiselect("Research areas", list(AREAS), default=list(AREAS))
    max_per_area = st.slider("Maximum records per area", 10, 50, 30, 5)
    mailto = st.text_input("Email for polite API access (optional)")
    st.caption("OpenAlex and Crossref are used for discovery and metadata checks.")

discover, verify, rank, methods = st.tabs(["🔎 Discover journals","🧾 Verify a journal","🏆 Ranked shortlist","ℹ️ Scoring and safeguards"])

with discover:
    st.subheader("Journal discovery")
    if st.button("Search journal databases", type="primary", disabled=not areas):
        found, errors = {}, []
        bar = st.progress(0); status = st.empty()
        for i, area in enumerate(areas):
            status.write(f"Searching {area}…")
            for term in AREAS[area]:
                try:
                    for item in openalex_search(term, mailto):
                        row = normalize(item, area, AREAS[area])
                        key = row["openalex_id"]
                        if key and (key not in found or row["discovery_score"] > found[key]["discovery_score"]):
                            found[key] = row
                except requests.RequestException as e: errors.append(f"{area}/{term}: {e}")
            bar.progress((i+1)/len(areas))
        st.session_state["journal_results"] = sorted(found.values(),key=lambda x:x["discovery_score"],reverse=True)[:max_per_area*len(areas)]
        if errors: st.warning("Some searches failed: "+"; ".join(errors[:3]))
        status.success(f"Retrieved {len(st.session_state['journal_results'])} unique journal records.")
    results = st.session_state.get("journal_results",[])
    if results:
        df = pd.DataFrame(results)
        min_score = st.slider("Minimum discovery score",0,70,10,5)
        doaj_only = st.checkbox("Show only DOAJ-listed records")
        view = df[df.discovery_score >= min_score]
        if doaj_only: view = view[view["DOAJ listed"]]
        st.dataframe(view[["journal","research_area","publisher","ISSN","DOAJ listed","OpenAlex OA","APC (USD)","discovery_score","homepage"]],
                     use_container_width=True,hide_index=True,
                     column_config={"homepage":st.column_config.LinkColumn("Journal website"),
                                    "discovery_score":st.column_config.ProgressColumn("Discovery score",min_value=0,max_value=70)})
        st.download_button("Download discovery results CSV",view.to_csv(index=False),"journal_discovery.csv","text/csv")
        if st.button("Save discovered journals to register"):
            save_rows(results); st.success("Saved. Open the verification tab to record evidence.")
    else:
        st.caption("Run a search to populate candidate journals.")

with verify:
    st.subheader("Evidence-based journal verification")
    saved = load_saved()
    if not saved:
        st.warning("No saved journals yet. Search journals and select 'Save discovered journals to register'.")
    else:
        labels = {f'{r["name"]} | {r["issn"] or "ISSN unavailable"}':r for r in saved}
        label = st.selectbox("Select a saved journal",list(labels))
        j = labels[label]; ev = get_evidence(j["evidence_json"])
        st.write(f"**Publisher:** {j['publisher']}  ·  **ISSN:** {j['issn'] or 'Not recorded'}")
        if j["homepage"]: st.markdown(f"**Journal website:** [{j['homepage']}]({j['homepage']})")
        st.markdown("**Verification links**")
        links = official_links(j["name"],j["issn"])
        cols = st.columns(2)
        for idx,(title,url) in enumerate(links.items()):
            cols[idx%2].markdown(f"- [{title}]({url})")
        with st.expander("Crossref ISSN check",expanded=False):
            issn_input = st.text_input("ISSN",value=(j["issn"] or "").split(",")[0].strip(),key="issn_"+j["openalex_id"])
            if st.button("Check Crossref",key="crossref_"+j["openalex_id"]):
                meta,msg = crossref_check(issn_input)
                st.session_state["crossref_"+j["openalex_id"]] = (meta,msg)
            result = st.session_state.get("crossref_"+j["openalex_id"])
            if result:
                meta,msg=result; st.write(msg)
                if meta: st.json({k:meta.get(k) for k in ["ISSN","publisher","title","prefix","counts"] if k in meta})
        st.markdown("**Record what you have verified from the official source.**")
        with st.form("evidence_form_"+j["openalex_id"]):
            fee = st.selectbox("Publication fee status",FEE_OPTIONS,index=FEE_OPTIONS.index(ev["fee_status"]) if ev["fee_status"] in FEE_OPTIONS else 0)
            fee_amount = st.text_input("Fee amount (if applicable)",value=ev.get("fee_amount",""))
            fee_currency = st.selectbox("Fee currency",["USD","EUR","GBP","KES","Other"],index=["USD","EUR","GBP","KES","Other"].index(ev.get("fee_currency","USD")) if ev.get("fee_currency","USD") in ["USD","EUR","GBP","KES","Other"] else 0)
            fee_url = st.text_input("URL proving fee information",value=ev.get("fee_url",""))
            scopus = st.selectbox("Scopus status",INDEX_OPTIONS,index=INDEX_OPTIONS.index(ev["scopus_status"]) if ev["scopus_status"] in INDEX_OPTIONS else 0)
            scopus_url = st.text_input("Scopus evidence URL",value=ev.get("scopus_url",""))
            wos = st.selectbox("Web of Science status",INDEX_OPTIONS,index=INDEX_OPTIONS.index(ev["wos_status"]) if ev["wos_status"] in INDEX_OPTIONS else 0)
            wos_url = st.text_input("Web of Science evidence URL",value=ev.get("wos_url",""))
            scope_ok = st.checkbox("I reviewed aims and scope",value=ev.get("scope_reviewed",False))
            peer_ok = st.checkbox("I reviewed peer-review process and editorial board",value=ev.get("peer_review_reviewed",False))
            guide_ok = st.checkbox("I reviewed author guidelines and manuscript types",value=ev.get("guidelines_reviewed",False))
            ethics_ok = st.checkbox("I reviewed publication ethics and policies",value=ev.get("ethics_reviewed",False))
            notes = st.text_area("Notes / evidence summary",value=ev.get("notes",""))
            submitted = st.form_submit_button("Save verification record",type="primary")
            if submitted:
                updated = {"fee_status":fee,"fee_amount":fee_amount,"fee_currency":fee_currency,"fee_url":fee_url,
                           "scopus_status":scopus,"scopus_url":scopus_url,"wos_status":wos,"wos_url":wos_url,
                           "scope_reviewed":scope_ok,"peer_review_reviewed":peer_ok,"guidelines_reviewed":guide_ok,
                           "ethics_reviewed":ethics_ok,"notes":notes}
                save_evidence(j["openalex_id"],updated)
                st.success("Verification evidence saved.")

with rank:
    st.subheader("Ranked journal shortlist")
    saved = load_saved()
    if not saved:
        st.info("Save journal discoveries first.")
    else:
        rows=[]
        for j in saved:
            ev=get_evidence(j["evidence_json"])
            verified=verification_score(ev)
            discovery=float(j["fit_score"] or 0)
            # Ranking is explicitly a combined readiness/screening score, not probability.
            combined=round((discovery/70)*50 + (verified/50)*50,1)
            rows.append({"Journal":j["name"],"Research area":j["area"],"Publisher":j["publisher"],
                         "Discovery /70":round(discovery,1),"Verified evidence /50":verified,
                         "Screening score /100":combined,"Fee status":ev["fee_status"],
                         "Scopus":ev["scopus_status"],"Web of Science":ev["wos_status"],
                         "Website":j["homepage"],"ISSN":j["issn"],"Evidence checked":ev.get("checked_at","")})
        ranked=pd.DataFrame(rows).sort_values("Screening score /100",ascending=False)
        st.caption("The top 20 are candidates for human review. Unverified fields receive no positive points.")
        st.dataframe(ranked.head(20),use_container_width=True,hide_index=True,
                     column_config={"Website":st.column_config.LinkColumn("Website"),
                                    "Screening score /100":st.column_config.ProgressColumn("Screening score",min_value=0,max_value=100)})
        st.download_button("Export ranked shortlist CSV",ranked.head(20).to_csv(index=False),
                           "top_20_journal_shortlist.csv","text/csv")
        st.warning("A high screening score does not mean a high probability of acceptance. Confirm every indexing and fee claim using the official source before submission.")

with methods:
    st.subheader("Scoring model and verification safeguards")
    st.markdown("""
    **Discovery score (maximum 70):** topic match (30), DOAJ signal (15), OpenAlex open-access signal (5),
    metadata completeness (15), and publication activity (10). This score helps discover candidates.

    **Verified evidence score (maximum 50):** confirmed no-mandatory-fee status (10; waiver available earns 5),
    active Scopus status (10), active Web of Science status (10), and documented human review of scope,
    peer review, author guidelines and ethics (5 each).

    **Combined screening score:** 50% normalized discovery score + 50% verified evidence score.
    It is a transparent shortlist aid, not a calibrated acceptance probability.

    **Non-negotiable safeguards**
    - Missing APC information is not evidence that publication is free.
    - DOAJ or Crossref records do not prove Scopus or Web of Science indexing.
    - Scopus and Web of Science status must be checked against official title lists.
    - Save the source URL and date for each material verification.
    - Review journal scope against the actual manuscript, not just broad subject labels.
    - The researcher retains approval of journals, topics, datasets, analysis and manuscripts.
    """)
    st.markdown("**Primary resources:** [OpenAlex Sources API](https://api.openalex.org/sources), [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/), [DOAJ](https://doaj.org/), [Scopus Sources](https://www.scopus.com/sources), [Clarivate Master Journal List](https://mjl.clarivate.com/), [COPE](https://publicationethics.org/).")

st.divider()
st.caption("Universal Research Intelligence Assistant · Phases 1–3.2 · Local database: data/research_journals.db")


# ================= PHASE 2: RESEARCH TOPIC & DATASET INTELLIGENCE =================
OPENALEX_WORKS = "https://api.openalex.org/works"
ZENODO_API = "https://zenodo.org/api/records"
DATAVERSE_API = "https://dataverse.harvard.edu/api/search"
WB_API = "https://api.worldbank.org/v2"

def p2_abstract(inv):
    if not isinstance(inv, dict) or not inv:
        return ""
    words = [""] * (max((max(v) for v in inv.values() if v), default=-1) + 1)
    for word, positions in inv.items():
        for pos in positions:
            if 0 <= pos < len(words): words[pos] = word
    return " ".join(w for w in words if w)

def p2_literature(query, year_from, limit):
    # OpenAlex query is bounded by today's date; results are checked again locally.
    today = date.today().isoformat()
    params={"search":query,
            "filter":f"from_publication_date:{year_from}-01-01,to_publication_date:{today},type:article",
            "sort":"publication_date:desc","per-page":min(200, limit * 3),
            "select":"id,doi,title,publication_year,publication_date,cited_by_count,authorships,primary_location,open_access,abstract_inverted_index"}
    r=requests.get(OPENALEX_WORKS,params=params,timeout=40); r.raise_for_status()
    results=r.json().get("results",[])
    # Defensive post-filter: never display future-dated publications.
    return [w for w in results if (w.get("publication_date") or "") <= today][:limit]

def p2_relevance(query, work):
    stop={"and","or","the","of","in","for","to","a","an","on","with","from","by","at","is","are","using","among"}
    terms=[t for t in re.findall(r"[a-z0-9]+",query.lower()) if len(t)>2 and t not in stop]
    title=(work.get("title") or "").lower()
    abstract=p2_abstract(work.get("abstract_inverted_index")).lower()
    combined=f"{title} {abstract}"
    if not terms:
        return 0, "Weakly relevant"
    title_hits=sum(1 for t in terms if t in title)
    abstract_hits=sum(1 for t in terms if t in abstract)
    # Weighted transparent heuristic: title evidence matters more than abstract evidence.
    score=round(100*(0.65*title_hits+0.35*abstract_hits)/len(terms))
    label="Highly relevant" if score>=60 else "Related" if score>=30 else "Weakly relevant"
    return min(score,100), label

def p2_zenodo(query, limit=15):
    r=requests.get(ZENODO_API,params={"q":query,"size":limit,"sort":"mostrecent"},timeout=40)
    r.raise_for_status(); return r.json().get("hits",{}).get("hits",[])

def p2_dataverse(query, limit=15):
    r=requests.get(DATAVERSE_API,params={"q":query,"type":"dataset","per_page":limit},timeout=40)
    r.raise_for_status(); return r.json().get("data",{}).get("items",[])

def p2_worldbank(query, limit=25):
    r=requests.get(f"{WB_API}/indicator",params={"format":"json","per_page":200},timeout=40)
    r.raise_for_status(); data=r.json()
    items=data[1] if isinstance(data,list) and len(data)>1 and data[1] else []
    q=query.lower()
    return [x for x in items if q in (x.get("name","")+" "+(x.get("source") or {}).get("value","")).lower()][:limit]

def p2_authors(items):
    return ", ".join((x.get("author") or {}).get("display_name","") for x in (items or [])[:4])

def p2_make_topics(theme, geo):
    place=geo or "selected countries"
    return [
      (f"Spatiotemporal patterns and determinants of {theme.lower()} in {place}",
       "Trend analysis, panel regression and spatial modelling if geographic coverage supports it."),
      (f"Comparing statistical and machine-learning models for {theme.lower()}",
       "Benchmark interpretable regression and tree-based models with nested cross-validation."),
      (f"Inequality and subgroup differences in {theme.lower()} in {place}",
       "Multilevel regression or decomposition, depending on available subgroup variables."),
      (f"Forecasting {theme.lower()} under alternative scenarios",
       "Time-series or probabilistic forecasting with out-of-sample validation and uncertainty intervals."),
      (f"Reproducible secondary-data analysis of {theme.lower()}",
       "Transparent data provenance, missingness assessment, robustness checks and sensitivity analysis.")
    ]

st.divider()
st.header("🧠 Phase 2 · Research Topic & Open Dataset Intelligence")
st.caption("Recent literature → candidate questions → public dataset discovery → researcher approval")
st.info("This module proposes candidate directions, not proven research gaps. Dataset search results are leads that require your review.")

p2_area=st.selectbox("Research area",list(AREAS.keys()),key="p2_area")
p2_theme=st.text_input("Research theme or problem",placeholder="e.g. climate variability and maize yield",key="p2_theme")
p2_geo=st.text_input("Geographical focus (optional)",value="Kenya and East Africa",key="p2_geo")
p2_year=st.slider("Literature scan start year",2015,date.today().year,date.today().year-6,key="p2_year")
st.caption(f"Publication records are capped at {date.today().isoformat()}; future-dated records are excluded.")
p2_limit=st.select_slider("Literature records",options=[10,15,20,25,40],value=20,key="p2_limit")

if st.button("Run Phase 2 research scan",type="primary",disabled=not p2_theme.strip(),key="p2_run"):
    st.session_state["p2_scan"]={"area":p2_area,"theme":p2_theme.strip(),"geo":p2_geo.strip()}
    try:
        with st.spinner("Searching recent scholarly literature through OpenAlex…"):
            st.session_state["p2_works"]=p2_literature(p2_theme.strip(),p2_year,p2_limit)
            st.session_state["p2_lit_error"]=None
    except Exception as e:
        st.session_state["p2_works"]=[]; st.session_state["p2_lit_error"]=str(e)
    ds={}
    for name,fn in [("Zenodo",lambda:p2_zenodo(p2_theme.strip())),
                    ("Harvard Dataverse",lambda:p2_dataverse(p2_theme.strip())),
                    ("World Bank indicators",lambda:p2_worldbank(p2_theme.strip()))]:
        try: ds[name]=fn()
        except Exception as e: ds[name]={"error":str(e)}
    st.session_state["p2_datasets"]=ds
    st.session_state["p2_candidates"]=p2_make_topics(p2_theme.strip(),p2_geo.strip())

if "p2_scan" in st.session_state:
    scan=st.session_state["p2_scan"]; works=st.session_state.get("p2_works",[])
    st.subheader("A. Recent literature landscape")
    if st.session_state.get("p2_lit_error"): st.error(st.session_state["p2_lit_error"])
    st.metric("Literature records retrieved",len(works))
    if works:
        lit=[]
        for w in works:
            loc=w.get("primary_location") or {}; src=(loc.get("source") or {}).get("display_name","")
            oa=w.get("open_access") or {}
            rel_score, rel_label = p2_relevance(scan["theme"], w)
            lit.append({"Year":w.get("publication_year"),"Title":w.get("title",""),
              "Relevance score":rel_score,"Relevance":rel_label,
              "Authors":p2_authors(w.get("authorships")),"Journal/source":src,
              "Citations":w.get("cited_by_count",0),"Open access signal":oa.get("is_oa",False),
              "DOI":w.get("doi") or "","OpenAlex record":w.get("id","")})
        litdf=pd.DataFrame(lit).sort_values(["Relevance score","Year"],ascending=[False,False])
        relevance_filter=st.multiselect("Show relevance classes",["Highly relevant","Related","Weakly relevant"],
                                        default=["Highly relevant","Related"],key="p2_relevance_filter")
        litdf=litdf[litdf["Relevance"].isin(relevance_filter)]
        st.dataframe(litdf,use_container_width=True,hide_index=True,
          column_config={"DOI":st.column_config.LinkColumn("DOI"),
                         "OpenAlex record":st.column_config.LinkColumn("OpenAlex record")})
        st.download_button("Download literature scan CSV",litdf.to_csv(index=False),
                           "phase2_literature_scan.csv","text/csv")
        st.caption(f"Abstract metadata available for {sum(bool(w.get('abstract_inverted_index')) for w in works)} records.")
        st.caption("Relevance is a transparent keyword-overlap screening heuristic, not a semantic peer review. Manually inspect abstracts and full texts before concluding relevance or novelty.")
    else:
        st.warning("No literature records returned. Try a broader or simpler search phrase.")

    st.subheader("B. Literature themes for gap exploration")
    if works:
        from collections import Counter
        theme_terms=[t for t in re.findall(r"[a-zA-Z]{4,}",scan["theme"].lower())
                     if t not in {"with","from","that","this","using","among","into"}]
        title_hits=Counter()
        for w in works:
            text=(w.get("title") or "").lower()+" "+p2_abstract(w.get("abstract_inverted_index")).lower()
            for term in theme_terms:
                if term in text: title_hits[term]+=1
        if title_hits:
            theme_df=pd.DataFrame([{"Search concept":k,"Records containing concept":v}
                                   for k,v in title_hits.most_common()])
            st.dataframe(theme_df,use_container_width=True,hide_index=True)
        st.caption("These are frequency signals in the retrieved sample, not proof of an under-researched gap. Gap claims require a structured review of methods, populations, datasets and findings.")
    st.subheader("C. Candidate research questions")
    st.warning("These are editable starting points, not validated novelty claims. Confirm the gap through a structured literature review.")
    for i,(title,method) in enumerate(st.session_state.get("p2_candidates",[]),1):
        with st.expander(f"Candidate {i}: {title}",expanded=(i==1)):
            st.write("**Possible analytical approach:** "+method)
            st.checkbox("Retain this candidate",key=f"p2_keep_{i}")
    if st.button("Save approved topic candidates",key="p2_save"):
        approved=[]
        for i,(title,method) in enumerate(st.session_state.get("p2_candidates",[]),1):
            if st.session_state.get(f"p2_keep_{i}",False):
                approved.append({"title":title,"method":method,"area":scan["area"],"theme":scan["theme"],"geography":scan["geo"]})
        st.session_state["p2_approved"]=approved
        st.success(f"Saved {len(approved)} candidate topic(s) for further review.")

    st.subheader("D. Open dataset discovery")
    st.caption("Check each repository record's license, variables, years, geography, documentation, missingness and access conditions before choosing it.")
    for repo,items in st.session_state.get("p2_datasets",{}).items():
        with st.expander(f"{repo}",expanded=True):
            if isinstance(items,dict) and "error" in items:
                st.warning(items["error"]); continue
            if not items: st.info("No matching records returned."); continue
            if repo=="Zenodo":
                rows=[{"Title":x.get("metadata",{}).get("title",""),
                       "Date":x.get("metadata",{}).get("publication_date",""),
                       "DOI":x.get("metadata",{}).get("doi",""),
                       "Record":x.get("links",{}).get("html",""),
                       "Description":re.sub("<[^>]+>"," ",x.get("metadata",{}).get("description",""))[:400]} for x in items]
                ddf=pd.DataFrame(rows)
                st.dataframe(ddf,use_container_width=True,hide_index=True,
                             column_config={"Record":st.column_config.LinkColumn("Record")})
            elif repo=="Harvard Dataverse":
                ddf=pd.DataFrame([{"Title":x.get("name",""),"Dataset":x.get("url",""),
                                   "Description":(x.get("description") or "")[:400]} for x in items])
                st.dataframe(ddf,use_container_width=True,hide_index=True,
                             column_config={"Dataset":st.column_config.LinkColumn("Dataset")})
            else:
                ddf=pd.DataFrame([{"Indicator":x.get("name",""),"Code":x.get("id",""),
                                   "Source":(x.get("source") or {}).get("value",""),
                                   "Source note":x.get("sourceNote","")} for x in items])
                st.dataframe(ddf,use_container_width=True,hide_index=True)
    st.subheader("E. Researcher decision gate")
    st.write("Only after you approve a topic and inspect a dataset should we proceed to R analysis.")
    for x in st.session_state.get("p2_approved",[]): st.markdown(f"- **{x['title']}**")
    st.markdown("**API documentation:** [OpenAlex](https://docs.openalex.org/), [Zenodo](https://developers.zenodo.org/), [Dataverse](https://guides.dataverse.org/en/latest/api/search.html), [World Bank Indicators](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api).")
else:
    st.markdown("Enter a theme such as *climate variability and crop productivity*, *machine learning for disease-risk prediction*, or *health inequality and demographic change*, then run the scan.")


# ================= PHASE 2.2: AGRICULTURE & CLIMATE DATA SOURCES =================
st.divider()
st.header("🌦️ Phase 2.2 · Agriculture & Climate Data Explorer")
st.caption("Official data portals + NASA POWER point-data retrieval")
st.info("This module helps locate and retrieve climate and agriculture data. A successful download does not establish that the data are suitable for a particular research question; inspect metadata, spatial/temporal coverage, units and licensing.")

st.subheader("A. Official public data repositories")
source_cards = [
    ("FAOSTAT", "Agricultural production, harvested area, yields, food balances and food-security indicators.",
     "https://www.fao.org/faostat/en/#data", "https://www.fao.org/faostat/en/#data"),
    ("NASA POWER", "Meteorological and solar variables, including precipitation and temperature, with point and regional services.",
     "https://power.larc.nasa.gov/", "https://power.larc.nasa.gov/docs/services/api/"),
    ("CHIRPS", "High-resolution rainfall estimates suitable for rainfall variability and drought-related studies.",
     "https://www.chc.ucsb.edu/data/chirps", "https://www.chc.ucsb.edu/data/chirps")
]
for name, desc, url, docs in source_cards:
    with st.container(border=True):
        st.markdown(f"**{name}**")
        st.write(desc)
        st.markdown(f"[Open data portal]({url}) · [Documentation / access information]({docs})")

st.subheader("B. Retrieve NASA POWER monthly climate data")
st.write("Enter a study-location coordinate. You can use a representative station/grid point, but document why it represents your study area.")
with st.form("p22_nasa_form"):
    c1,c2,c3 = st.columns(3)
    lat = c1.number_input("Latitude", min_value=-90.0, max_value=90.0, value=0.10, step=0.01, format="%.4f")
    lon = c2.number_input("Longitude", min_value=-180.0, max_value=180.0, value=34.80, step=0.01, format="%.4f")
    start_year = c3.number_input("Start year", min_value=1981, max_value=date.today().year, value=max(1981,date.today().year-10), step=1)
    end_year = st.number_input("End year", min_value=1981, max_value=date.today().year, value=date.today().year-1, step=1)
    nasa_submit = st.form_submit_button("Retrieve NASA POWER monthly data", type="primary")
if nasa_submit:
    if start_year > end_year:
        st.error("Start year must not be later than end year.")
    else:
        params = {
            "parameters":"PRECTOTCORR,T2M,T2M_MAX,T2M_MIN",
            "community":"AG",
            "longitude":lon,
            "latitude":lat,
            "start":int(start_year),
            "end":int(end_year),
            "format":"JSON"
        }
        try:
            with st.spinner("Requesting NASA POWER data…"):
                response = requests.get("https://power.larc.nasa.gov/api/temporal/monthly/point",
                                        params=params, timeout=90,
                                        headers={"User-Agent":"ResearchPublicationIntelligence/0.3"})
                response.raise_for_status()
                payload=response.json()
            parameter_data=payload.get("properties",{}).get("parameter",{})
            if not parameter_data:
                st.warning("NASA POWER returned no parameter data. Check coordinates, years and API response.")
                st.json(payload)
            else:
                frame=pd.DataFrame(parameter_data)
                frame.index.name="Year-Month"
                frame=frame.reset_index()
                frame.insert(1,"Latitude",lat)
                frame.insert(2,"Longitude",lon)
                st.session_state["p22_nasa_df"]=frame
                st.session_state["p22_nasa_meta"]=payload.get("parameters",{})
                st.success(f"Retrieved {len(frame)} monthly records.")
        except Exception as exc:
            st.error(f"NASA POWER request failed: {exc}")
if "p22_nasa_df" in st.session_state:
    ndf=st.session_state["p22_nasa_df"]
    st.dataframe(ndf,use_container_width=True,hide_index=True)
    st.download_button("Download NASA POWER data (CSV)",ndf.to_csv(index=False),
                       "nasa_power_monthly_climate.csv","text/csv")
    st.caption("Variables: PRECTOTCORR (corrected precipitation), T2M (2-m air temperature), T2M_MAX and T2M_MIN. Check NASA POWER metadata for units, missing-value codes and product-specific limitations before analysis.")
    with st.expander("NASA POWER response metadata"):
        st.json(st.session_state.get("p22_nasa_meta",{}))

st.subheader("C. FAOSTAT and CHIRPS data preparation")
st.markdown("""
**FAOSTAT workflow**
1. Open the FAOSTAT data portal and select the relevant domain (for example, Crops and livestock products).
2. Filter the item to maize, the elements to production / area harvested / yield, and the geography and years required.
3. Download the official CSV or bulk file and retain its metadata and download date.
4. Check units, flags, country coverage and definition changes before merging with climate data.

**CHIRPS workflow**
1. Open the CHIRPS data portal and select the appropriate product (daily, pentad or monthly) and resolution.
2. Select the years and spatial extent for the study.
3. Download the GeoTIFF/netCDF data or use an established geospatial platform.
4. Record the product version, spatial resolution, coordinate reference system and temporal aggregation.
""")
st.warning("FAOSTAT and CHIRPS are linked as official source portals in this version; automated bulk downloads and raster extraction are not yet implemented. Do not treat the NASA point series as a substitute for spatially complete CHIRPS rainfall.")


# ================= PHASE 2.3: KENYA FAOSTAT + CHIRPS INTEGRATION =================
import io as _io
import zipfile as _zipfile
import gzip as _gzip
import tempfile as _tempfile
from pathlib import Path as _Path

st.divider()
st.header("🇰🇪 Phase 2.3 · Kenya Agriculture & Rainfall Data Integration")
st.caption("Study geography: Kenya · Study period: 2000–2025")
st.info("This module downloads public FAOSTAT maize-production records and CHIRPS monthly rainfall grids. The first CHIRPS workflow extracts a Kenya-wide mean using an official country boundary where available. Download sizes can be substantial; begin with a one-year test.")

# Persistent storage paths
P23_DATA = _Path("data") / "phase2_3"
P23_DATA.mkdir(parents=True, exist_ok=True)
FAO_BULK_URL = "https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
CHIRPS_BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs"

def p23_fetch_faostat(url=FAO_BULK_URL):
    local_zip = P23_DATA / "faostat_production_crops_livestock_normalized.zip"
    if not local_zip.exists() or local_zip.stat().st_size == 0:
        with requests.get(url, stream=True, timeout=(30, 300),
                          headers={"User-Agent":"ResearchPublicationIntelligence/0.3"}) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            bar = st.progress(0.0)
            downloaded = 0
            with open(local_zip, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk); downloaded += len(chunk)
                        if total: bar.progress(min(downloaded/total, 1.0))
            bar.empty()
    with _zipfile.ZipFile(local_zip) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv") and "normalized" in n.lower()]
        if not csv_names:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV file was found inside the FAOSTAT bulk archive.")
        # Prefer the actual main data table, not code-list CSVs.
        chosen = max(csv_names, key=lambda n: zf.getinfo(n).file_size)
        with zf.open(chosen) as stream:
            chunks=[]
            seen_areas=set(); seen_items=set(); seen_elements=set()
            for chunk in pd.read_csv(stream, encoding="latin1", low_memory=False, chunksize=250000):
                cols={re.sub(r"\s+"," ",c.lower().strip()):c for c in chunk.columns}
                required=["area","item","element","year","value"]
                if not all(k in cols for k in required):
                    raise ValueError("FAOSTAT columns differ from expected normalized format. Found: "+", ".join(chunk.columns[:30]))
                area_s=chunk[cols["area"]].astype(str).str.strip()
                item_s=chunk[cols["item"]].astype(str).str.strip()
                element_s=chunk[cols["element"]].astype(str).str.strip()
                year_s=pd.to_numeric(chunk[cols["year"]],errors="coerce")
                seen_areas.update(area_s.dropna().unique().tolist()[:500])
                # Collect matching item/element labels for transparent diagnosis.
                maize_mask=item_s.str.contains(r"\bmaize\b",case=False,na=False,regex=True)
                if maize_mask.any():
                    seen_items.update(item_s[maize_mask].dropna().unique().tolist())
                    seen_elements.update(element_s[maize_mask].dropna().unique().tolist())
                area_mask=area_s.str.casefold().isin(["kenya","kenya (the)"])
                element_norm=element_s.str.casefold().str.replace(r"[^a-z]+"," ",regex=True).str.strip()
                element_mask=element_norm.isin(["production","yield","area harvested"])
                keep=area_mask & maize_mask & year_s.between(2000,2025) & element_mask
                if keep.any():
                    chunks.append(chunk.loc[keep].copy())
            if not chunks:
                # Store labels from the actual downloaded file so user can report/inspect them.
                diag={
                    "CSV member":chosen,
                    "Area labels containing Kenya":[x for x in seen_areas if "kenya" in x.casefold()][:20],
                    "Maize item labels":sorted(seen_items)[:50],
                    "Elements for maize":sorted(seen_elements)[:50],
                    "Expected elements":["Production","Yield","Area harvested"],
                    "Year range":"2000–2025"
                }
                raise ValueError("No records matched the flexible Kenya + maize + element filter. FAOSTAT labels found: "+json.dumps(diag,ensure_ascii=False))
            result=pd.concat(chunks,ignore_index=True)
    out=P23_DATA/"faostat_kenya_maize_2000_2025.csv"
    result.to_csv(out,index=False)
    return result, str(out), chosen

def p23_kenya_geojson():
    # geoBoundaries open boundary metadata endpoint; retrieve the downloadable GeoJSON.
    meta_url="https://www.geoboundaries.org/api/current/gbOpen/KEN/ADM0/"
    r=requests.get(meta_url,timeout=40,headers={"User-Agent":"ResearchPublicationIntelligence/0.3"})
    r.raise_for_status()
    meta=r.json()
    gj_url=meta.get("gjDownloadURL")
    if not gj_url: raise ValueError("Kenya boundary metadata did not provide a GeoJSON download URL.")
    g=requests.get(gj_url,timeout=60); g.raise_for_status()
    geo=g.json()
    features=geo.get("features",[])
    if not features: raise ValueError("Kenya boundary GeoJSON contained no features.")
    return features[0]["geometry"], meta.get("boundaryID","geoBoundaries-KEN-ADM0")

def p23_chirps_month(year, month, geometry):
    import rasterio
    import numpy as np
    from rasterio.io import MemoryFile
    filename=f"chirps-v2.0.{year}.{month:02d}.tif.gz"
    url=f"{CHIRPS_BASE}/{filename}"
    local=P23_DATA/filename
    if not local.exists():
        with requests.get(url,stream=True,timeout=(30,180),
                          headers={"User-Agent":"ResearchPublicationIntelligence/0.3"}) as resp:
            resp.raise_for_status()
            with open(local,"wb") as f:
                for chunk in resp.iter_content(1024*1024):
                    if chunk: f.write(chunk)
    with _gzip.open(local,"rb") as gz:
        tif_bytes=gz.read()
    with MemoryFile(tif_bytes) as mem:
        with mem.open() as ds:
            from rasterio.mask import mask
            arr, transform=mask(ds,[geometry],crop=True,filled=False)
            values=arr[0].compressed()
            values=values[np.isfinite(values)]
            if ds.nodata is not None:
                values=values[values != ds.nodata]
            if len(values)==0: raise ValueError(f"No valid CHIRPS pixels for {year}-{month:02d}.")
            return float(np.mean(values)), int(len(values)), ds.crs.to_string() if ds.crs else "Unknown"

with st.expander("A. Download FAOSTAT Kenya maize production, area harvested and yield",expanded=True):
    st.write("Source: FAOSTAT Crops and livestock products (QCL) normalized bulk archive. The archive is global and can be large; the application filters Kenya, Maize, 2000–2025 after download.")
    st.markdown(f"[Official FAOSTAT portal](https://www.fao.org/faostat/en/#data/QCL) · [FAOSTAT API documentation](https://www.fao.org/faostat/en/docs/redoc-static.html)")
    st.caption("The public bulk archive is used here to avoid requiring you to enter FAOSTAT account credentials. Verify the archive's update date and data flags in your research record.")
    if st.button("Download and filter FAOSTAT Kenya maize data",type="primary",key="p23_fao"):
        try:
            with st.spinner("Downloading and filtering FAOSTAT bulk data. This may take several minutes…"):
                fao_df,fao_path,fao_member=p23_fetch_faostat()
            st.session_state["p23_fao_df"]=fao_df
            st.session_state["p23_fao_path"]=fao_path
            st.session_state["p23_fao_member"]=fao_member
            st.success(f"Retrieved {len(fao_df):,} Kenya maize records from {fao_member}.")
        except Exception as e:
            st.error(f"FAOSTAT download/filter failed: {e}")
    if "p23_fao_df" in st.session_state:
        fdf=st.session_state["p23_fao_df"]
        st.dataframe(fdf.head(100),use_container_width=True,hide_index=True)
        st.download_button("Download filtered FAOSTAT CSV",fdf.to_csv(index=False),
                           "faostat_kenya_maize_2000_2025.csv","text/csv")
        st.caption(f"Cached archive: {st.session_state.get('p23_fao_path','')}")

with st.expander("B. Download CHIRPS monthly rainfall and calculate Kenya-wide mean",expanded=True):
    st.write("CHIRPS v2 monthly GeoTIFF archive is used for the historical 2000–2025 period. CHIRPS v3 is now the operational product; v2 is retained here as a consistent historical workflow during the transition. Do not mix versions without documenting and testing the effect.")
    st.markdown("[CHIRPS data and version guidance](https://www.chc.ucsb.edu/data/chirps) · [CHIRPS data archive](https://data.chc.ucsb.edu/products/CHIRPS-2.0/)")
    c1,c2=st.columns(2)
    chirps_start=c1.number_input("CHIRPS start year",min_value=2000,max_value=2025,value=2000,step=1,key="p23_cs")
    chirps_end=c2.number_input("CHIRPS end year",min_value=2000,max_value=2025,value=2000,step=1,key="p23_ce")
    month_mode=st.selectbox("Download scope",["One selected year range (monthly files)","Single calendar year only"],key="p23_mode")
    if month_mode=="Single calendar year only":
        chirps_end=chirps_start
    file_count=(int(chirps_end)-int(chirps_start)+1)*12
    st.warning(f"This will request {file_count} global monthly GeoTIFF files, then extract Kenya pixels. The files are not Kenya-clipped at source; total transfer can be several gigabytes for the full 26-year period. Start with 2000 only to test.")
    acknowledge=st.checkbox("I understand the download may be large and want to proceed.",key="p23_ack")
    if st.button("Download CHIRPS and calculate Kenya monthly means",type="primary",key="p23_chirps",disabled=not acknowledge):
        if chirps_start>chirps_end:
            st.error("Start year must be less than or equal to end year.")
        else:
            try:
                with st.spinner("Retrieving Kenya ADM0 boundary…"):
                    kenya_geom,boundary_source=p23_kenya_geojson()
                rows=[]; prog=st.progress(0.0); status=st.empty()
                total=file_count; done=0
                for yy in range(int(chirps_start),int(chirps_end)+1):
                    for mm in range(1,13):
                        status.write(f"Processing CHIRPS {yy}-{mm:02d} ({done+1}/{total})…")
                        mean_val,n_pixels,crs=p23_chirps_month(yy,mm,kenya_geom)
                        rows.append({"Year":yy,"Month":mm,"Year-Month":f"{yy}-{mm:02d}",
                                     "Kenya_mean_rainfall_mm":mean_val,"Valid_pixels":n_pixels,
                                     "CRS":crs,"Product":"CHIRPS v2.0 monthly"})
                        done+=1; prog.progress(done/total)
                cdf=pd.DataFrame(rows)
                cdf.to_csv(P23_DATA/"chirps_kenya_monthly_2000_2025.csv",index=False)
                st.session_state["p23_chirps_df"]=cdf
                st.session_state["p23_boundary_source"]=boundary_source
                status.success(f"Completed {len(cdf)} monthly Kenya rainfall summaries.")
            except Exception as e:
                st.error(f"CHIRPS retrieval/extraction failed: {e}")
            finally:
                pass
    if "p23_chirps_df" in st.session_state:
        cdf=st.session_state["p23_chirps_df"]
        st.dataframe(cdf,use_container_width=True,hide_index=True)
        st.download_button("Download Kenya CHIRPS monthly CSV",cdf.to_csv(index=False),
                           "chirps_kenya_monthly_rainfall.csv","text/csv")
        st.caption("Spatial summary uses the Kenya ADM0 GeoJSON boundary; the mean is the unweighted mean of valid 0.05-degree grid cells. For area-weighted national means, implement pixel-area weighting in the analysis stage.")
        st.caption(f"Boundary source identifier: {st.session_state.get('p23_boundary_source','')}")

with st.expander("C. Data harmonization preview",expanded=False):
    st.write("After both source datasets are retrieved, the system can aggregate monthly rainfall to annual totals/means and merge with FAOSTAT maize yield by year. This is a country-level ecological time series; it does not support farm-level causal claims.")
    if "p23_fao_df" in st.session_state and "p23_chirps_df" in st.session_state:
        fao=st.session_state["p23_fao_df"].copy()
        chir=st.session_state["p23_chirps_df"].copy()
        cols={c.lower().strip():c for c in fao.columns}
        year_col=cols.get("year"); element_col=cols.get("element"); value_col=cols.get("value")
        item_col=cols.get("item"); unit_col=cols.get("unit")
        if year_col and element_col and value_col:
            fao["Year_num"]=pd.to_numeric(fao[year_col],errors="coerce")
            fao["Value_num"]=pd.to_numeric(fao[value_col],errors="coerce")
            fao["Element_clean"]=fao[element_col].astype(str).str.casefold().str.strip()
            yield_rows=fao[fao["Element_clean"]=="yield"]
            annual_yield=yield_rows.groupby("Year_num",as_index=False)["Value_num"].mean().rename(columns={"Year_num":"Year","Value_num":"Maize_yield_FAOSTAT"})
            annual_rain=chir.groupby("Year",as_index=False)["Kenya_mean_rainfall_mm"].sum().rename(columns={"Kenya_mean_rainfall_mm":"CHIRPS_annual_rainfall_mm"})
            merged=annual_yield.merge(annual_rain,on="Year",how="inner").sort_values("Year")
            if not merged.empty:
                st.dataframe(merged,use_container_width=True,hide_index=True)
                st.download_button("Download harmonized annual dataset",merged.to_csv(index=False),
                                   "kenya_maize_yield_chirps_rainfall_annual.csv","text/csv")
                st.caption("Check FAOSTAT yield units and CHIRPS monthly units before interpreting this merged file. This is an exploratory merge, not yet a validated analysis dataset.")
            else:
                st.warning("No overlapping annual records were found for the selected period.")
        else:
            st.warning("FAOSTAT archive columns could not be mapped automatically; inspect the filtered CSV and revise the column mapping.")
    else:
        st.caption("Download both FAOSTAT and CHIRPS datasets to enable the harmonization preview.")


# ================= PHASE 3.1: UNIVERSAL RESEARCH WORKSPACE =================
# Additive module: leaves existing journal, literature, NASA POWER, FAOSTAT and CHIRPS
# code paths and tables intact. Research projects use their own SQLite table.
from datetime import datetime as _dt
from pathlib import Path as _Path

P31_DB = _Path(DB_PATH)
P31_DB.parent.mkdir(parents=True, exist_ok=True)

def p31_init():
    with sqlite3.connect(str(P31_DB)) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS research_projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            research_area TEXT NOT NULL,
            research_prompt TEXT NOT NULL,
            geography TEXT,
            study_period TEXT,
            status TEXT NOT NULL DEFAULT 'Idea',
            keywords TEXT,
            objectives TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        con.commit()

def p31_projects():
    with sqlite3.connect(str(P31_DB)) as con:
        return pd.read_sql_query(
            "SELECT project_id, title, research_area, geography, study_period, status, created_at, updated_at FROM research_projects ORDER BY updated_at DESC",
            con)

def p31_save_project(title, area, prompt, geography, period, status="Idea", keywords="", objectives="", notes=""):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(str(P31_DB)) as con:
        con.execute("""INSERT INTO research_projects
            (title,research_area,research_prompt,geography,study_period,status,keywords,objectives,notes,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (title,area,prompt,geography,period,status,keywords,objectives,notes,stamp,stamp))
        con.commit()

def p31_update_status(project_id, status):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(str(P31_DB)) as con:
        con.execute("UPDATE research_projects SET status=?, updated_at=? WHERE project_id=?",
                    (status,stamp,int(project_id)))
        con.commit()

def p31_clean_subject(prompt, geography=""):
    """Turn conversational instructions into a concise research subject."""
    s = re.sub(r"\s+", " ", (prompt or "").strip())
    s = re.sub(r"[.!?]+$", "", s)
    # Remove common conversational lead-ins.
    s = re.sub(r"^(i\s+)?(want|would like|wish|hope)\s+to\s+(investigate|study|examine|explore|research|analyse|analyze)\s+", "", s, flags=re.I)
    s = re.sub(r"^(i\s+)?(want|would like)\s+to\s+(look at|focus on)\s+", "", s, flags=re.I)
    s = re.sub(r"^(the\s+)?application of\s+", "", s, flags=re.I)
    s = re.sub(r"\s+in\s+" + re.escape(geography.strip()) + r"$", "", s, flags=re.I) if geography.strip() else s
    s = re.sub(r"\s+in\s+kenya$", "", s, flags=re.I) if geography.strip().lower() == "kenya" else s
    s = s.strip(" ,.;:")
    return s[:1].lower() + s[1:] if s else (prompt or "").strip()


def p31_is_research_task_request(prompt):
    """Detect instructions asking the assistant to perform a multi-step research task."""
    s=(prompt or "").strip().lower()
    task_verbs=r"(find|generate|suggest|identify|discover|recommend|search for|develop)"
    task_objects=r"(?:\d+\s+)?(?:research\s+)?topics|research gaps|datasets|journals|objectives|hypotheses"
    return bool(re.search(task_verbs+r".{0,100}"+task_objects,s)) or bool(
        re.search(r"(find|generate|suggest).{0,60}(topics|research ideas)",s)
    )


def p31_keywords(prompt, area):
    subject = p31_clean_subject(prompt)
    stop = {
        "this","that","with","from","into","using","among","their","study","analysis",
        "research","effect","effects","impact","impacts","want","would","like","investigate",
        "investigating","application","applying","the","and","for","under","in","on","of",
        "to","a","an","by","based","approach","using"
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", subject.lower())
    unique=[]
    for token in tokens:
        if token not in stop and token not in unique:
            unique.append(token)
    area_terms = {
        "Statistics and Data Science":["statistical modelling","data science","statistical inference"],
        "AI and Machine Learning":["machine learning","predictive modelling","model interpretability"],
        "Climate Analytics":["climate variability","climate impacts","climate modelling"],
        "Agroforestry and Food Security":["agricultural productivity","food security","climate-smart agriculture"],
        "Medical Biostatistics":["medical biostatistics","health outcomes","clinical prediction"],
        "Epidemiology and Demography":["epidemiology","population health","demographic analysis"]
    }
    phrases = area_terms.get(area, [])
    result=[]
    for term in unique + phrases:
        if term not in result:
            result.append(term)
    return result[:8]

def p31_title_candidates(area, prompt, geography):
    subject = p31_clean_subject(prompt, geography)
    place = geography.strip()
    area_l = area.lower()
    # Produce readable titles without repeating the user's conversational wording.
    if "agroforestry" in area_l or "food security" in area_l or any(x in subject.lower() for x in ["agricultural productivity","maize","crop yield"]):
        core = subject.replace("machine learning and statistical modelling in predicting", "machine-learning and statistical prediction of")
        return [
            f"Predicting {core}"+(f" in {place}" if place and place.lower() not in core.lower() else ""),
            f"Comparing statistical and machine-learning models for {core}"+(f" in {place}" if place and place.lower() not in core.lower() else ""),
            f"Climate variability and agricultural productivity: modelling patterns and predictors"+(f" in {place}" if place else ""),
            f"Explaining climate-related variation in agricultural productivity using interpretable machine learning"+(f" in {place}" if place else ""),
            f"Assessing the predictive value of climate indicators for agricultural productivity"+(f" in {place}" if place else "")
        ]
    suffix = f" in {place}" if place and place.lower() not in subject.lower() else ""
    return [
        f"Statistical analysis of {subject}{suffix}",
        f"Predictive modelling of {subject}: a comparative study{suffix}",
        f"Determinants and patterns of {subject}{suffix}",
        f"An explainable data-driven approach to {subject}{suffix}",
        f"Robustness and uncertainty assessment in modelling {subject}{suffix}"
    ]

def p31_objectives(prompt):
    subject = p31_clean_subject(prompt)
    return [
        f"To characterise the patterns and distribution of {subject} using an appropriate, documented dataset.",
        f"To identify and quantify the principal explanatory variables associated with {subject} using suitable statistical models.",
        f"To develop and compare relevant statistical and machine-learning models, using appropriate out-of-sample validation where prediction is the aim.",
        f"To assess model assumptions, predictive performance, uncertainty and robustness, and interpret the implications for research and practice."
    ]

p31_init()
st.divider()
st.header("🌐 Phase 3.1 · Universal Research Workspace")
st.caption("A shared workspace for research ideas, projects and researcher-approved next steps.")
st.info("This is the foundation layer. Existing Phase 1 and Phase 2 modules remain available above. This release adds persistent project management and a guided research brief; it does not yet connect to a hosted generative-AI model.")

p31_tab1, p31_tab2, p31_tab3 = st.tabs(["Research assistant", "My research projects", "System architecture"])

with p31_tab1:
    st.subheader("Start with a research instruction")
    st.write("Describe the research problem in ordinary language. You can begin with a broad idea; the assistant will structure it into a reviewable research brief.")
    with st.form("p31_new_project_form"):
        p31_prompt = st.text_area("What would you like to investigate?",
            placeholder="Example: I want to investigate factors associated with maternal health service utilisation using publicly available survey data.",
            height=110)
        p31_c1,p31_c2 = st.columns(2)
        p31_area = p31_c1.selectbox("Research discipline", list(AREAS.keys()), key="p31_area")
        p31_geo = p31_c2.text_input("Geographical scope", placeholder="e.g. Kenya, East Africa, global")
        p31_period = st.text_input("Study period (if known)", placeholder="e.g. 2000–2025 or leave blank")
        p31_submit = st.form_submit_button("Structure my research idea", type="primary")
    if p31_submit:
        if not p31_prompt.strip():
            st.error("Please enter a research idea or a research task.")
            st.session_state.pop("p31_task_request", None)
        elif p31_is_research_task_request(p31_prompt):
            # Do not misrepresent a multi-step instruction as a single research topic.
            st.session_state.pop("p31_current_brief", None)
            st.session_state["p31_task_request"] = {
                "prompt": p31_prompt.strip(),
                "area": p31_area,
                "geo": p31_geo.strip(),
                "period": p31_period.strip()
            }
        else:
            st.session_state.pop("p31_task_request", None)
            p31_generated = {
                "prompt":p31_prompt.strip(),"area":p31_area,"geo":p31_geo.strip(),
                "period":p31_period.strip(),
                "titles":p31_title_candidates(p31_area,p31_prompt,p31_geo),
                "objectives":p31_objectives(p31_prompt),
                "keywords":p31_keywords(p31_prompt,p31_area)
            }
            st.session_state["p31_current_brief"] = p31_generated
    task_request=st.session_state.get("p31_task_request")
    if task_request:
        st.divider()
        st.subheader("Research task recognised")
        st.success("This is a multi-step research request, not a single research topic. The system has correctly separated it from the draft-topic workflow.")
        st.markdown(f"**Requested task:** {task_request['prompt']}")
        st.markdown(f"**Research discipline:** {task_request['area']}")
        st.markdown(f"**Geography:** {task_request['geo'] or 'Not specified'}")
        st.markdown(f"**Study period:** {task_request['period'] or 'To be determined'}")
        st.warning("The Phase 3.1 brief builder structures an initial idea. Use the Phase 3.2 conversational assistant for further literature-informed exploration and evidence searches; independently verify every source, dataset and journal claim.")
    brief=st.session_state.get("p31_current_brief")
    if brief:
        st.divider()
        st.subheader("Research brief · Draft for your review")
        st.markdown(f"**Research discipline:** {brief['area']}")
        st.markdown(f"**Research idea:** {brief['prompt']}")
        st.markdown(f"**Geography:** {brief['geo'] or 'Not specified'}")
        st.markdown(f"**Study period:** {brief['period'] or 'To be determined'}")
        st.markdown("**Candidate working titles**")
        p31_selected_title=st.radio("Select a provisional title to save",
            brief["titles"],key="p31_title_choice")
        st.markdown("**Draft research objectives**")
        for idx,obj in enumerate(brief["objectives"],1):
            st.write(f"{idx}. {obj}")
        st.markdown("**Suggested keywords**")
        st.write(", ".join(brief["keywords"]))
        st.warning("These are structured starting drafts, not literature-validated research gaps or approved objectives. The next stage will verify literature, dataset availability and methodological feasibility.")
        if st.button("Save this research project",type="primary",key="p31_save_project"):
            p31_save_project(p31_selected_title,brief["area"],brief["prompt"],brief["geo"],
                             brief["period"],"Idea",", ".join(brief["keywords"]),
                             "\n".join(brief["objectives"]),
                             "Initial structured brief; requires literature and dataset validation.")
            st.success("Research project saved to your local project library.")
            st.session_state["p31_saved_notice"]=True

with p31_tab2:
    st.subheader("My research project library")
    projects=p31_projects()
    if projects.empty:
        st.info("No projects saved yet. Create your first research idea in the Research assistant tab.")
    else:
        st.metric("Saved research projects",len(projects))
        st.dataframe(projects,use_container_width=True,hide_index=True)
        p31_id=st.selectbox("Select a project to update its status",
            projects["project_id"].tolist(),
            format_func=lambda x: f"Project {x}: {projects.loc[projects.project_id==x,'title'].iloc[0]}")
        p31_status=st.selectbox("Project status",
            ["Idea","Literature review","Topic approved","Dataset search","Dataset approved","Analysis","Manuscript drafting","Journal selection","Completed"],
            key="p31_status_select")
        if st.button("Update project status",key="p31_update_status"):
            p31_update_status(p31_id,p31_status)
            st.success("Project status updated. Refresh the project list to see the change.")
        csv_projects=projects.to_csv(index=False)
        st.download_button("Export project register (CSV)",csv_projects,"research_project_register.csv","text/csv")

with p31_tab3:
    st.subheader("Modular architecture and preserved components")
    arch_rows=[
        {"Component":"Phase 1 — Journal discovery","Status":"Preserved","Role":"Journal search, scoring and verification records"},
        {"Component":"Phase 2 — Literature intelligence","Status":"Preserved","Role":"OpenAlex literature discovery and screening"},
        {"Component":"Phase 2.2 — NASA POWER","Status":"Preserved","Role":"Climate time-series data retrieval"},
        {"Component":"Phase 2.3 — FAOSTAT / CHIRPS","Status":"Preserved","Role":"Agriculture and rainfall data connectors"},
        {"Component":"Phase 3.1 — Project library","Status":"Implemented","Role":"Persistent research project register"},
        {"Component":"Phase 3.1 — Research brief","Status":"Starter implementation","Role":"Guided idea structuring, draft titles, objectives and keywords"},
        {"Component":"Phase 3.2 — Conversational AI","Status":"Implemented","Role":"OpenAI Responses API assistant with web search and researcher-approved project saving"},
        {"Component":"Phase 3.3 onward","Status":"Planned","Role":"Gap validation, dataset matching, R execution, LaTeX and journal fit"}
    ]
    st.dataframe(pd.DataFrame(arch_rows),use_container_width=True,hide_index=True)
    st.caption("Project records are stored locally in data/research_journals.db in a separate research_projects table. Existing journal records are not overwritten.")


# ================= PHASE 3.2: CONVERSATIONAL AI RESEARCH ASSISTANT =================
st.divider()
st.header("💬 Phase 3.2 · Conversational AI Research Assistant")
st.caption("Ask research questions, request literature-informed topic ideas, explore datasets, develop methods and draft research plans.")

import os as _os
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except Exception:
    pass

def p32_get_secret():
    key = _os.getenv("OPENAI_API_KEY", "").strip()
    try:
        if not key:
            key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        pass
    return key

P32_INSTRUCTIONS = """You are the Universal Research Intelligence Assistant (URIA), a rigorous research-development partner for a university researcher.
The researcher's areas are Statistics and Data Science; AI and Machine Learning; Climate Analytics; Agroforestry and Food Security; Medical Biostatistics; Epidemiology and Demography.

Core responsibilities:
- Understand whether the user is asking for topics, a literature review, objectives, hypotheses, keywords, datasets, methods, R code, manuscript drafting, or journal matching.
- For multi-topic requests, give distinct, properly scoped candidate topics rather than turning the user's instruction into a title.
- When web search is available, search scholarly and authoritative sources. Prefer original journal pages, DOI/Crossref, OpenAlex, PubMed, official data repositories and journal author guidelines.
- Distinguish verified facts, source-supported findings, reasoned suggestions and unknowns. Cite sources with working URLs/DOIs when available. Never invent papers, DOIs, datasets, journal policies, APCs, indexing status, results or acceptance probabilities.
- For research gaps, describe them as candidate gaps unless a sufficiently systematic review supports a stronger claim.
- For datasets, give the exact repository, landing page/download route, variables, geography, years, access conditions, licence if verified, and limitations. Do not claim a dataset is downloadable until verified.
- For R code, make it reproducible, comment assumptions, include package installation/loading, data checks, missing-data handling, diagnostics and outputs. Never fabricate analysis results.
- For manuscripts, use only supplied or genuinely analysed data. Mark placeholders clearly. Do not fabricate observations, methods, results or references.
- For journal recommendations, assess scope and verified author requirements, fees, indexing and article types; never promise acceptance.
- Ask one focused clarification only when essential. Otherwise state assumptions and proceed.
- The researcher retains approval. Do not imply that a topic, dataset, analysis, manuscript or submission has been approved merely because you proposed it.
Use clear academic English and organise substantial answers with useful headings and tables."""

p32_area = st.selectbox("Research discipline for this conversation", list(AREAS.keys()), key="p32_area")
p32_c1, p32_c2 = st.columns(2)
p32_geo = p32_c1.text_input("Geographical focus (optional)", value="Kenya", key="p32_geo")
p32_period = p32_c2.text_input("Study period (optional)", placeholder="e.g. 2000–2025", key="p32_period")
p32_model = st.text_input("OpenAI model", value=_os.getenv("URIA_MODEL", "gpt-5.5"), help="Uses a model enabled for your API project. You can change this if your API project uses another model.", key="p32_model")
p32_saved_key = p32_get_secret()
p32_api_key = p32_saved_key or st.text_input("OpenAI API key (session only)", type="password", help="Enter an API key from your OpenAI API project. It is not written to the project files or database.", key="p32_api_key_input")
if p32_saved_key:
    st.caption("API key loaded from the local environment or Streamlit secrets.")
else:
    st.caption("For repeated use, place OPENAI_API_KEY in a local .env file. Never commit that file to GitHub.")

if "p32_messages" not in st.session_state:
    st.session_state["p32_messages"] = []
if "p32_last_answer" not in st.session_state:
    st.session_state["p32_last_answer"] = ""

p32_chat_col, p32_control_col = st.columns([4,1])
with p32_control_col:
    if st.button("Clear conversation", key="p32_clear"):
        st.session_state["p32_messages"] = []
        st.session_state["p32_last_answer"] = ""
        st.rerun()

for _msg in st.session_state["p32_messages"]:
    with st.chat_message(_msg["role"]):
        st.markdown(_msg["content"])

p32_user_input = st.chat_input("Ask URIA to find topics, review literature, locate datasets, develop R code or prepare a manuscript…", key="p32_chat_input")
if p32_user_input:
    if not p32_api_key:
        st.error("Add your OpenAI API key above before sending a message. The API key is separate from a ChatGPT subscription.")
    else:
        try:
            from openai import OpenAI as _OpenAI
            _client = _OpenAI(api_key=p32_api_key)
            st.session_state["p32_messages"].append({"role":"user","content":p32_user_input})
            _context = (
                f"Current research discipline: {p32_area}. "
                f"Geographical focus: {p32_geo or 'not specified'}. "
                f"Study period: {p32_period or 'not specified'}. "
                "Treat these as defaults, not rigid constraints if the user says otherwise."
            )
            _input = [{"role":"developer","content":P32_INSTRUCTIONS + "\n\n" + _context}]
            _input += [{"role":m["role"],"content":m["content"]} for m in st.session_state["p32_messages"]]
            with st.spinner("URIA is analysing your request and searching for evidence…"):
                _response = _client.responses.create(
                    model=p32_model.strip() or "gpt-5.5",
                    instructions=P32_INSTRUCTIONS + "\n\n" + _context,
                    input=[{"role":m["role"],"content":m["content"]} for m in st.session_state["p32_messages"]],
                    tools=[{"type":"web_search"}],
                    store=False
                )
            _answer = (_response.output_text or "").strip()
            if not _answer:
                _answer = "The model returned no text. Please try again or check the API response and model access."
            st.session_state["p32_messages"].append({"role":"assistant","content":_answer})
            st.session_state["p32_last_answer"] = _answer
            st.rerun()
        except Exception as _err:
            if st.session_state["p32_messages"] and st.session_state["p32_messages"][-1]["role"] == "user":
                st.session_state["p32_messages"].pop()
            st.error(f"AI request failed: {_err}")
            st.info("Check that the API key is valid, billing/API access is enabled, the selected model is available to your API project, and web search is enabled for the request.")

if st.session_state.get("p32_last_answer"):
    st.divider()
    st.subheader("Researcher approval")
    st.caption("Save a conversation-derived project only after reviewing the assistant's proposal. Saving does not mean the research topic or evidence has been independently validated.")
    with st.expander("Review the latest assistant response"):
        st.markdown(st.session_state["p32_last_answer"])
    with st.form("p32_approve_project_form"):
        p32_project_title = st.text_input("Project title to save", placeholder="Enter an approved working title")
        p32_approve = st.checkbox("I have reviewed this proposal and approve saving it to my research project library.")
        p32_save = st.form_submit_button("Save approved proposal as a project", type="primary")
    if p32_save:
        if not p32_project_title.strip():
            st.error("Enter a project title before saving.")
        elif not p32_approve:
            st.error("Please confirm your review and approval.")
        else:
            _last_user = next((m["content"] for m in reversed(st.session_state["p32_messages"]) if m["role"]=="user"), "")
            p31_save_project(p32_project_title.strip(),p32_area,_last_user,p32_geo,p32_period,
                             "Researcher-approved proposal","",
                             "Saved from URIA conversational assistant",
                             st.session_state["p32_last_answer"])
            st.success("Approved proposal saved to your research project library.")

with st.expander("API setup and privacy"):
    st.markdown("""
**Recommended local setup**

1. Create a file named `.env` in your project folder.
2. Add the following lines, replacing the placeholder with your own API key:

```text
OPENAI_API_KEY=your_api_key_here
URIA_MODEL=gpt-5.5
```

3. Save the file and restart Streamlit.

The `.env` file must remain private and must not be uploaded to GitHub. API usage may incur separate charges under your API account. URIA sends the conversation content to the selected model provider when you submit a message. The API request uses `store=False`; do not enter confidential participant data or identifiable health information.
""")