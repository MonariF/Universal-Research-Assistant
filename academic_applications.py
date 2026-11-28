"""Phase 4: Academic Opportunities & Application Intelligence for URIA."""
import os
import re
import json
import sqlite3
import smtplib
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from docx import Document
from openai import OpenAI

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data" / "academic_applications"
DOC_DIR = DATA_DIR / "documents"
DB_FILE = DATA_DIR / "applications.sqlite3"
DOC_DIR.mkdir(parents=True, exist_ok=True)

DOC_TYPES = [
    "ATS-compliant academic CV",
    "Conference abstract",
    "Research/grant proposal",
    "Motivation letter",
    "Cover letter",
    "Research statement",
    "Grant budget and justification",
    "Application compliance report",
]

PROFILE_STARTER = """Dr. Fred Nyamitago Monari, PhD
Lecturer and Research Fellow, Department of Mathematics, Kisii University, Kenya.
Assistant Mathematics Postgraduate Coordinator.
PhD in Applied Statistics, Jomo Kenyatta University of Agriculture and Technology (2021).
MSc in Applied Statistics, JKUAT (2010–2012).
BSc Mathematics (Statistics Major), Egerton University (2001–2006).
Currently pursuing a Master of Data Science at the Open University of Kenya.
Research areas: applied statistics, statistical modelling, AI and machine learning, data science, climate analytics, agroforestry, food security, medical biostatistics, epidemiology and computational mathematics.
Software: R, Python, SPSS, Stata, SAS, SQL and KoboCollect.
Professional memberships: Kenya National Statistical Society; International Biometric Society.
Use the uploaded master CV and verified publication list as the authoritative source for detailed dates, publications, DOIs, grants, awards and achievements. Do not infer missing details.
"""

def _db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, title TEXT, category TEXT,
        deadline TEXT, requirements TEXT, analysis TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id INTEGER, doc_type TEXT,
        filename TEXT, filepath TEXT, content TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY CHECK (id=1), profile_text TEXT, updated_at TEXT)""")
    con.commit()
    return con

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _get_profile():
    con = _db()
    row = con.execute("SELECT profile_text FROM profile WHERE id=1").fetchone()
    con.close()
    return row[0] if row else PROFILE_STARTER

def _save_profile(value):
    con = _db()
    con.execute("INSERT OR REPLACE INTO profile(id,profile_text,updated_at) VALUES(1,?,?)",
                (value, _now()))
    con.commit()
    con.close()

def _extract_upload(upload):
    if not upload:
        return ""
    name = upload.name.lower()
    raw = upload.getvalue()
    if name.endswith(".docx"):
        import io
        doc = Document(io.BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if name.endswith(".pdf"):
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="replace")
    raise ValueError("Upload a DOCX, PDF, TXT or Markdown file.")

def _fetch_page(url):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a complete http:// or https:// opportunity link.")
    response = requests.get(url.strip(), timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; URIA-AcademicAssistant/1.0)"
    })
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else parsed.netloc
    text = soup.get_text("\n", strip=True)
    return title, re.sub(r"\n{3,}", "\n\n", text)[:30000]

def _ai_client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    try:
        if not key:
            key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        pass
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in your private .env file or Streamlit secrets.")
    return OpenAI(api_key=key)

def _model():
    return os.getenv("URIA_MODEL", "gpt-5.5")

def _analyse(client, title, url, page_text):
    prompt = f"""Analyse this real conference/grant/fellowship/scholarship opportunity for Dr. Fred Nyamitago Monari, a Kenyan university lecturer and applied statistician.

Opportunity URL: {url}
Page title: {title}
Page text:
{page_text}

Return a structured report with:
1. Opportunity name, organiser, type and official source.
2. Eligibility: explicit criteria, whether the applicant appears eligible, and any unknowns.
3. Deadline, timezone and submission route. Never guess a missing deadline.
4. Funding, travel support, fees and benefits, distinguishing confirmed from unclear.
5. Required documents and exact format/word/page limits.
6. Selection criteria, themes and keywords.
7. Submission instructions and required declarations.
8. Risks, missing information and questions to verify with the organiser.
9. A tailored application strategy matching the applicant's verified profile.
10. A checklist of all required actions.

Cite only information present in the page text; label anything not available as "Not stated—verify with organiser". Do not invent facts or assume eligibility."""
    response = client.responses.create(
        model=_model(),
        instructions="You are a meticulous academic grants and conference application analyst. Be evidence-led and explicit about unknowns. Never fabricate eligibility, deadlines, benefits or requirements.",
        input=prompt,
        tools=[{"type": "web_search"}],
        store=False,
    )
    return (response.output_text or "").strip()

def _save_opportunity(url, title, category, deadline, requirements, analysis):
    con = _db()
    cur = con.execute("""INSERT INTO opportunities
        (url,title,category,deadline,requirements,analysis,created_at)
        VALUES(?,?,?,?,?,?,?)""",
        (url, title, category, deadline, requirements, analysis, _now()))
    oid = cur.lastrowid
    con.commit()
    con.close()
    return oid

def _generate(client, doc_type, opportunity, profile, master_cv, extra_notes):
    prompt = f"""Prepare a high-quality, tailored application document for Dr. Fred Nyamitago Monari.

DOCUMENT TYPE: {doc_type}

OPPORTUNITY ANALYSIS AND REQUIREMENTS:
{opportunity}

MASTER PROFILE:
{profile}

MASTER CV / PUBLICATION RECORD (authoritative source):
{master_cv[:45000]}

APPLICANT'S ADDITIONAL INSTRUCTIONS:
{extra_notes or "None supplied."}

NON-NEGOTIABLE RULES:
- Tailor the document to the opportunity's actual eligibility rules, themes, selection criteria, keywords, format and word/page limits.
- Never invent degrees, employment dates, publications, DOI links, grants, awards, collaborators, results, budgets, institutional approvals or achievements.
- If a fact is missing, insert [APPLICANT TO CONFIRM: ...] rather than guessing.
- Preserve the distinction between completed qualifications and ongoing studies.
- For a CV, use ATS-friendly plain text structure, conventional headings, reverse chronological order where dates are known, simple bullets, no tables, columns, icons, graphics, headers/footers or text boxes. Include relevant keywords naturally without keyword stuffing.
- For abstracts/proposals, follow the opportunity's specified structure and word limit. Do not fabricate findings; label planned work and expected outcomes accurately.
- For budgets, use only eligible cost categories and stated funder limits. Mark unprovided prices as estimates requiring confirmation; show calculations and currency.
- For compliance reports, make a requirement-by-requirement pass/fail/needs-confirmation checklist with evidence.
- Use professional academic English, clear headings and concise writing.
- Return only the complete document text, with no prefatory commentary.
"""
    response = client.responses.create(
        model=_model(),
        instructions="You are an expert academic grant writer, conference application editor and ATS CV specialist. Accuracy and compliance outrank persuasive language. Do not make unsupported claims.",
        input=prompt,
        store=False,
    )
    return (response.output_text or "").strip()

def _docx_bytes(title, body):
    import io
    doc = Document()
    doc.add_heading(title, 0)
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith(("- ", "• ")):
            doc.add_paragraph(s[2:], style="List Bullet")
        elif re.match(r"^\d+[\.)]\s+", s):
            doc.add_paragraph(re.sub(r"^\d+[\.)]\s+", "", s), style="List Number")
        else:
            doc.add_paragraph(s)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()

def _ats_check(text):
    low = text.lower()
    checks = {
        "Contact details present": any(x in low for x in ["email", "phone", "telephone"]),
        "Education heading": "education" in low or "academic qualifications" in low,
        "Experience heading": any(x in low for x in ["experience", "employment", "professional appointments"]),
        "Skills heading": any(x in low for x in ["skills", "technical competencies", "software"]),
        "Readable text structure": bool(re.search(r"\n", text)),
        "No obvious table/column markers": not any(x in low for x in ["|---", "column 1", "column 2"]),
    }
    return checks

def _archive_document(oid, doc_type, content):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", doc_type).strip("_").lower()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"opp_{oid}_{safe}_{stamp}.docx"
    path = DOC_DIR / filename
    path.write_bytes(_docx_bytes(doc_type, content))
    con = _db()
    con.execute("""INSERT INTO documents
        (opportunity_id,doc_type,filename,filepath,content,created_at)
        VALUES(?,?,?,?,?,?)""",
        (oid, doc_type, filename, str(path), content, _now()))
    con.commit()
    con.close()
    return filename, path

def _send_email(recipient, subject, body, paths):
    sender = os.getenv("URIA_EMAIL_SENDER", "").strip()
    password = os.getenv("URIA_EMAIL_APP_PASSWORD", "").strip().replace(" ", "")
    if not sender or not password:
        raise RuntimeError("Email is not configured. Set URIA_EMAIL_SENDER and URIA_EMAIL_APP_PASSWORD in your private .env file.")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    for path in paths:
        mime, _ = mimetypes.guess_type(str(path))
        main, sub = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)

def render_academic_applications():
    st.divider()
    st.header("🎓 Phase 4 · Academic Opportunities & Application Intelligence")
    st.caption("Paste an official opportunity link, analyse its requirements, prepare tailored documents, run compliance checks and archive the application.")
    intake, profile_tab, archive_tab = st.tabs([
        "🔗 New opportunity", "👤 Master academic profile", "🗂️ Application archive"
    ])

    with profile_tab:
        st.subheader("Your permanent academic profile")
        st.write("This profile is the baseline for tailoring. Keep it factual and update it when your CV, publications, roles or qualifications change.")
        current = _get_profile()
        edited = st.text_area("Master profile", value=current, height=260, key="p4_profile_text")
        cv_upload = st.file_uploader("Upload your latest master CV (DOCX, PDF, TXT or MD)", type=["docx", "pdf", "txt", "md"], key="p4_master_cv")
        pub_upload = st.file_uploader("Optional: upload a separate publication list (DOCX, PDF, TXT or MD)", type=["docx", "pdf", "txt", "md"], key="p4_publications")
        if st.button("Save master profile", type="primary", key="p4_save_profile"):
            _save_profile(edited)
            st.success("Master profile saved.")
        if cv_upload:
            try:
                extracted = _extract_upload(cv_upload)
                st.session_state["p4_master_cv_text"] = extracted
                st.success(f"Master CV read: {cv_upload.name} ({len(extracted.split())} words).")
            except Exception as exc:
                st.error(f"Could not read CV: {exc}")
        if pub_upload:
            try:
                pub_text = _extract_upload(pub_upload)
                st.session_state["p4_publication_text"] = pub_text
                st.success(f"Publication list read: {pub_upload.name}.")
            except Exception as exc:
                st.error(f"Could not read publication list: {exc}")
        st.caption("Uploaded source documents remain in this Streamlit session unless you explicitly generate and archive an application document. The master profile is stored locally in the application's SQLite database.")

    with intake:
        st.subheader("1. Enter the opportunity")
        with st.form("p4_opportunity_form"):
            url = st.text_input("Official conference / grant / fellowship URL", placeholder="https://...")
            category = st.selectbox("Opportunity type", ["Conference", "Research grant", "Fellowship", "Scholarship", "Training / workshop", "Research visit", "Other"])
            notes = st.text_area("Anything you want URIA to consider (optional)", placeholder="For example: preferred research angle, host institution, budget constraints or particular call section.")
            analyse = st.form_submit_button("Fetch and analyse opportunity", type="primary")
        if analyse:
            if not url.strip():
                st.error("Paste the opportunity link first.")
            else:
                try:
                    with st.spinner("Reading the official opportunity page and checking its requirements…"):
                        page_title, page_text = _fetch_page(url)
                        client = _ai_client()
                        analysis = _analyse(client, page_title, url, page_text)
                    oid = _save_opportunity(url.strip(), page_title, category, "", page_text[:12000], analysis)
                    st.session_state["p4_current_opportunity"] = {
                        "id": oid, "url": url.strip(), "title": page_title,
                        "category": category, "analysis": analysis, "notes": notes
                    }
                    st.success(f"Opportunity analysed and saved to the archive (Application #{oid}).")
                except Exception as exc:
                    st.error(f"Opportunity analysis failed: {exc}")
                    st.info("Some portals block automated reading or require login. In that case, paste the call text or upload its PDF in the section below.")

        with st.expander("If the opportunity page cannot be read"):
            pasted_call = st.text_area("Paste the call text or requirements", height=180, key="p4_manual_call")
            manual_title = st.text_input("Opportunity name", key="p4_manual_title")
            if st.button("Analyse pasted call", key="p4_manual_analyse"):
                try:
                    if not pasted_call.strip():
                        st.error("Paste the call text first.")
                    else:
                        client = _ai_client()
                        analysis = _analyse(client, manual_title or "Pasted opportunity call", "User-supplied call text", pasted_call[:30000])
                        oid = _save_opportunity("", manual_title or "Pasted opportunity call", "Other", "", pasted_call[:12000], analysis)
                        st.session_state["p4_current_opportunity"] = {
                            "id": oid, "url": "", "title": manual_title or "Pasted opportunity call",
                            "category": "Other", "analysis": analysis, "notes": ""
                        }
                        st.success(f"Call analysed and saved (Application #{oid}).")
                except Exception as exc:
                    st.error(f"Analysis failed: {exc}")

        opportunity = st.session_state.get("p4_current_opportunity")
        if opportunity:
            st.divider()
            st.subheader(f"2. Opportunity analysis · Application #{opportunity['id']}")
            st.markdown(opportunity["analysis"])
            st.download_button("Download opportunity analysis", opportunity["analysis"], file_name=f"opportunity_{opportunity['id']}_analysis.md", mime="text/markdown")
            st.subheader("3. Prepare tailored documents")
            profile = _get_profile()
            master_cv = st.session_state.get("p4_master_cv_text", "")
            publication_text = st.session_state.get("p4_publication_text", "")
            if publication_text:
                master_cv += "\n\nVERIFIED PUBLICATION LIST:\n" + publication_text
            if not master_cv.strip():
                st.warning("Upload your latest master CV in the Master academic profile tab before generating a tailored CV or proposal. The profile summary alone is not a complete publication record.")
            with st.form("p4_generate_form"):
                selected_docs = st.multiselect("Documents to prepare", DOC_TYPES, default=["ATS-compliant academic CV", "Cover letter", "Application compliance report"])
                extra = st.text_area("Document-specific instructions", value=opportunity.get("notes", ""), height=90)
                max_words = st.number_input("Abstract / statement word limit (if applicable; 0 = use call instructions)", min_value=0, max_value=20000, value=0, step=50)
                generate = st.form_submit_button("Generate selected documents", type="primary")
            if generate:
                if not selected_docs:
                    st.error("Select at least one document.")
                elif not master_cv.strip() and any("CV" in d or "proposal" in d.lower() for d in selected_docs):
                    st.error("Upload your master CV/publication record first. This prevents unsupported claims.")
                else:
                    client = _ai_client()
                    saved_paths = []
                    for doc_type in selected_docs:
                        try:
                            instruction = extra
                            if max_words and ("abstract" in doc_type.lower() or "statement" in doc_type.lower()):
                                instruction += f"\nStrict maximum word count: {int(max_words)} words."
                            with st.spinner(f"Preparing {doc_type}…"):
                                text = _generate(client, doc_type, opportunity["analysis"], profile, master_cv, instruction)
                            if not text:
                                st.warning(f"No text was returned for {doc_type}.")
                                continue
                            filename, path = _archive_document(opportunity["id"], doc_type, text)
                            saved_paths.append(path)
                            st.session_state.setdefault("p4_generated", {})[filename] = {
                                "type": doc_type, "text": text, "path": str(path)
                            }
                            st.success(f"Prepared and archived: {filename}")
                            st.download_button(f"Download {doc_type} (DOCX)", path.read_bytes(), file_name=filename,
                                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                               key="download_" + filename)
                            if doc_type == "ATS-compliant academic CV":
                                checks = _ats_check(text)
                                st.markdown("**ATS readability checks**")
                                for label, passed in checks.items():
                                    st.write(("✅ " if passed else "⚠️ ") + label)
                            if doc_type == "Application compliance report":
                                st.info("Review every item marked needs confirmation before submission.")
                        except Exception as exc:
                            st.error(f"Could not generate {doc_type}: {exc}")
                    if saved_paths:
                        st.session_state["p4_last_paths"] = [str(p) for p in saved_paths]
                        st.success(f"{len(saved_paths)} document(s) saved in the local application archive.")

            if st.session_state.get("p4_last_paths"):
                st.subheader("4. Email copies for filing")
                recipient = st.text_input("Email address to receive these documents", value=os.getenv("URIA_EMAIL_RECIPIENT", ""), key="p4_recipient")
                st.caption("Email delivery uses Gmail SMTP with an app password stored privately in your local .env file; the password is never saved in the application database.")
                if st.button("Email me the latest generated documents", key="p4_email_docs"):
                    try:
                        paths = [Path(p) for p in st.session_state["p4_last_paths"] if Path(p).exists()]
                        if not recipient.strip():
                            st.error("Enter the email address for filing.")
                        elif not paths:
                            st.error("No generated files are available to attach.")
                        else:
                            _send_email(recipient.strip(), f"URIA application documents – {opportunity['title']}",
                                        f"Attached are the generated documents for Application #{opportunity['id']}.\n\nOpportunity: {opportunity['title']}\nSource: {opportunity['url']}\n\nPlease retain these copies and review all placeholders before submission.", paths)
                            st.success(f"Sent {len(paths)} document(s) to {recipient}.")
                    except Exception as exc:
                        st.error(f"Email delivery failed: {exc}")
                        st.info("For Gmail, enable 2-Step Verification and create an App Password. Add URIA_EMAIL_SENDER, URIA_EMAIL_APP_PASSWORD and URIA_EMAIL_RECIPIENT to your private .env file.")

    with archive_tab:
        st.subheader("Saved applications and documents")
        con = _db()
        opportunities = con.execute("SELECT id,title,category,deadline,url,created_at FROM opportunities ORDER BY id DESC").fetchall()
        docs = con.execute("SELECT id,opportunity_id,doc_type,filename,filepath,created_at FROM documents ORDER BY id DESC").fetchall()
        con.close()
        st.metric("Applications recorded", len(opportunities))
        if opportunities:
            st.dataframe([{"Application ID":r[0],"Opportunity":r[1],"Type":r[2],"Deadline":r[3] or "Not captured","Created":r[5],"Link":r[4]} for r in opportunities],
                         use_container_width=True, hide_index=True)
        else:
            st.info("No applications saved yet.")
        if docs:
            st.markdown("**Generated document archive**")
            for row in docs:
                did, oid, dtype, filename, filepath, created = row
                col1, col2 = st.columns([4,1])
                col1.write(f"Application #{oid} · {dtype} · {created[:10]}")
                file_path = Path(filepath)
                if file_path.exists():
                    col2.download_button("Download", file_path.read_bytes(), file_name=filename, key=f"archive_download_{did}")
                else:
                    col2.caption("File unavailable")
        else:
            st.info("Generated documents will appear here.")
