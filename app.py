"""
ACTS-AI MVP — Physician Review Interface
Capstone: AI in Healthcare | Daily ICU progress note for mechanically
ventilated adult patients.

Run with:  streamlit run app.py
"""

import json
import os
import time

import streamlit as st
from openai import OpenAI

import core
from prompt import SYSTEM_PROMPT, USER_TEMPLATE, PROMPT_VERSION

st.set_page_config(page_title="ACTS-AI — ICU Note Review", layout="wide")

# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
for key, default in [
    ("ai_output", None), ("draft_note", ""), ("case", None),
    ("gen_time", None), ("trace", None), ("saved", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# --------------------------------------------------------------------------
# Sidebar — configuration
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    # Optional convenience: pick up a key from .streamlit/secrets.toml or an
    # environment variable so it survives page reloads. Falls back to manual
    # entry, which keeps the key in session memory only.
    preset_key = ""
    try:
        preset_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:  # noqa: BLE001 - no secrets file present
        preset_key = ""
    preset_key = preset_key or os.environ.get("OPENAI_API_KEY", "")

    api_key = st.text_input(
        "OpenAI API key", type="password", value=preset_key,
        help="Loaded from secrets/environment if configured; otherwise session only.",
    )
    if preset_key:
        st.caption("Key loaded from local configuration.")
    model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-4.1"], index=0)
    REVIEWERS = [
        "Dr. Mohamed Samy",
        "Dr. Ahmad Abdelhady",
        "Dr. Dina Elsamman",
        "Dr. Moustafa Badr",
        "Dr. Nefertiti El-Nikhely",
        "Dr. Shariffa Garwan",
    ]
    reviewer_choice = st.selectbox(
        "Reviewing physician", REVIEWERS + ["Other…"],
        help="Select the reviewing physician. Choose 'Other…' to enter a name.",
    )
    if reviewer_choice == "Other…":
        reviewer = st.text_input("Enter reviewer name", value="Dr. ")
    else:
        reviewer = reviewer_choice

    st.divider()
    cases = core.list_cases()
    if not cases:
        st.error("No case files found in ./cases/")
        st.stop()
    case_file = st.selectbox("Synthetic case", cases)

    st.divider()
    st.caption(f"Prompt {PROMPT_VERSION}")
    st.caption("Synthetic data only. Never enter real patient data.")

case = core.load_case(case_file)
meta = case.get("case_metadata", {})

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("ACTS-AI — Daily ICU Progress Note")
st.caption(
    "AI drafts. The physician decides. No note enters the record without sign-off."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Case", meta.get("case_id", "?"))
c2.metric("Type", meta.get("case_type", "?"))
c3.metric("ICU day", meta.get("icu_day", "?"))
c4.metric("Cut-off", meta.get("data_cutoff_time", "?"))

with st.expander("View structured input data (what the AI receives)"):
    sanitised = core.strip_test_metadata(case)
    st.caption(
        "Evaluation-design keys are stripped before the model sees the case, "
        "so planted test answers cannot leak into the prompt."
    )
    st.json(sanitised)

st.divider()

# --------------------------------------------------------------------------
# Step 1 — Generate
# --------------------------------------------------------------------------
st.subheader("1. Generate draft")

if st.button("Generate draft note", type="primary", disabled=not api_key):
    sanitised = core.strip_test_metadata(case)
    try:
        client = OpenAI(api_key=api_key)
        started = time.time()
        with st.spinner("Generating draft…"):
            resp = client.chat.completions.create(
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_TEMPLATE.format(
                        case_json=json.dumps(sanitised, indent=2))},
                ],
            )
        elapsed = round(time.time() - started, 1)
        output = json.loads(resp.choices[0].message.content)

        st.session_state.ai_output = output
        st.session_state.case = case
        st.session_state.trace = core.validate_traceability(output, sanitised)
        st.session_state.draft_note = core.assemble_note(output, case)
        st.session_state.gen_case_file = case_file
        st.session_state.gen_time = time.time()
        st.session_state.saved = None
        st.success(f"Draft generated in {elapsed}s")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Generation failed: {exc}")

if not api_key:
    st.info("Enter your OpenAI API key in the sidebar to enable generation.")

output = st.session_state.ai_output
if not output:
    st.stop()

# Patient-mismatch guard. If the case selection changed after generation, the
# draft on screen belongs to a different patient than the one now selected.
# Displaying the two together is a wrong-patient hazard, so the draft is
# withheld until it is regenerated or the original case is reselected.
if st.session_state.get("gen_case_file") and st.session_state.gen_case_file != case_file:
    st.error(
        "**Case selection changed — draft withheld.**\n\n"
        f"The draft on screen was generated from `{st.session_state.gen_case_file}`, "
        f"but `{case_file}` is now selected. Showing a note alongside a different "
        "patient's details is unsafe, so it is not displayed."
    )
    st.info(
        "Select **Generate draft note** to produce a note for the currently "
        "selected case, or switch the case selector back to the original case."
    )
    st.stop()

# --------------------------------------------------------------------------
# Step 2 — Scope gate result
# --------------------------------------------------------------------------
st.divider()
st.subheader("2. Scope check")

if not output.get("in_scope", False):
    st.error("**OUT OF SCOPE — no note generated**")
    st.write(output.get("scope_reason", ""))
    st.info(
        "Correct safety behaviour: the system refuses rather than producing a "
        "plausible but invalid note for a patient outside the validated "
        "pilot population."
    )
    if st.button("Log this refusal to the audit trail"):
        core.append_audit({
            "timestamp": core.now_iso(),
            "case_id": output.get("case_id", meta.get("case_id")),
            "case_type": meta.get("case_type"),
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "in_scope": False,
            "trajectory": "",
            "decision": "out_of_scope_refusal",
            "reviewer": reviewer,
            "total_statements": 0,
            "traceability_pct": "",
            "unsupported_count": 0,
            "missing_data_count": 0,
            "contradictions_count": 0,
            "percent_changed": "",
            "review_seconds": "",
            "reviewer_comment": "Scope gate refusal — no note produced.",
        })
        st.success("Logged to audit_log.csv")
    st.stop()

st.success(f"In scope — {output.get('scope_reason', '')}")

# --------------------------------------------------------------------------
# Step 3 — Quality signals
# --------------------------------------------------------------------------
st.divider()
st.subheader("3. ACTS quality signals")

trace = st.session_state.trace
missing = output.get("missing_data", []) or []
contradictions = output.get("contradictions", []) or []

q1, q2, q3, q4 = st.columns(4)
q1.metric("Statements", trace["total_statements"])
q2.metric("Traceability", f"{trace['traceability_pct']}%")
q3.metric("Unsupported", trace["unsupported_count"],
          delta=None if trace["unsupported_count"] == 0 else "review",
          delta_color="inverse")
q4.metric("Trajectory", output.get("trajectory", "?"))

if trace["unsupported_count"]:
    with st.expander("Unsupported statements (automated check)", expanded=True):
        for section, text in trace["untagged"]:
            st.warning(f"**{section}** — no source cited: {text}")
        for section in trace.get("empty_statements", []):
            st.warning(
                f"**{section}** — the model returned a statement with no text. "
                "Malformed output; regenerate if this section matters."
            )
        for section, text, bad in trace["invalid_refs"]:
            st.error(f"**{section}** — cites unknown source {bad}: {text}")
else:
    st.success(
        "Every statement cites a source_id that exists in the input data "
        "(automated traceability check passed)."
    )

col_missing, col_contra = st.columns(2)
with col_missing:
    st.markdown(f"**Missing data flagged ({len(missing)})**")
    if missing:
        for m in missing:
            st.markdown(f"- **{m.get('item','')}** — {m.get('why_it_matters','')}")
    else:
        st.caption("None flagged.")
with col_contra:
    st.markdown(f"**Contradictions flagged ({len(contradictions)})**")
    if contradictions:
        for c in contradictions:
            st.markdown(
                f"- {c.get('description','')} "
                f"`{', '.join(c.get('source_ids') or [])}`"
            )
    else:
        st.caption("None flagged.")

# --------------------------------------------------------------------------
# Step 4 — Draft with evidence links
# --------------------------------------------------------------------------
st.divider()
st.subheader("4. Draft note with evidence")

show_tags = st.checkbox("Show source tags", value=True)
valid_ids = core.collect_source_ids(core.strip_test_metadata(case))

st.markdown(core.patient_header(case))
for section in output.get("note_sections", []) or []:
    st.markdown(f"**{section.get('title','')}**")
    statements = section.get("statements", []) or []
    if not statements:
        st.caption("No data provided for this system.")
    for st_item in statements:
        kind = st_item.get("type", "fact")
        marker = "🔵" if kind == "fact" else "🟠"
        raw_text = st_item.get("text") or ""
        text = raw_text.strip() if isinstance(raw_text, str) else ""
        if core._is_blank(raw_text):
            st.markdown(
                "<div style='background:#fff3cd;padding:4px;border-radius:4px'>"
                "⚠️ <i>The model returned a statement with no text. Malformed "
                "output — regenerate if this section matters.</i></div>",
                unsafe_allow_html=True)
            continue
        ids = st_item.get("source_ids") or []
        bad = [i for i in ids if i not in valid_ids and i != "NO_DATA"]
        tag = f" `[{', '.join(ids)}]`" if (show_tags and ids) else ""
        line = f"{marker} {text}{tag}"
        if bad or not ids:
            st.markdown(
                f"<div style='background:#fff3cd;padding:4px;border-radius:4px'>"
                f"⚠️ {line}</div>", unsafe_allow_html=True)
        else:
            st.markdown(line)
    st.write("")

st.caption("🔵 fact (restates input data)  |  🟠 interpretation (clinical synthesis)")

# --------------------------------------------------------------------------
# Step 5 — Physician review
# --------------------------------------------------------------------------
st.divider()
st.subheader("5. Physician review and sign-off")

edited = st.text_area(
    "Edit the note as required, then approve or reject.",
    value=st.session_state.draft_note,
    height=420,
)

comment = st.text_input("Reviewer comment (optional)")

metrics = core.diff_metrics(st.session_state.draft_note, edited)
m1, m2, m3 = st.columns(3)
m1.metric("Draft changed", f"{metrics['percent_changed']}%")
m2.metric("Draft words", metrics["draft_words"])
m3.metric("Final words", metrics["final_words"])

if edited.strip() != st.session_state.draft_note.strip():
    with st.expander("View differences (AI draft vs. your version)", expanded=False):
        st.markdown(
            core.render_diff_html(st.session_state.draft_note, edited),
            unsafe_allow_html=True,
        )
        st.caption("Red struck-through = removed from draft · Green = physician addition")

# ---- Post-edit consistency check -----------------------------------------
sanitised_case = core.strip_test_metadata(case)
check = core.check_edited_note(edited, sanitised_case)
acknowledged = True

st.markdown("**Post-edit consistency check**")
if check["total_flags"] == 0:
    st.success(
        "No consistency issues detected. Every statement cites a valid source, "
        "no statement asserts content the input marks as absent, and no source "
        "is described as both present and absent."
    )
else:
    st.warning(
        f"{check['total_flags']} item(s) need your attention. These are flags, "
        "not blocks — you may sign after reviewing them."
    )

    for section, body, tag in check["absence_conflicts"]:
        st.markdown(
            f"⚠️ **Asserts content the source marks as absent** — *{section}*: "
            f"“{body}” cites `{tag}`, which is recorded as not documented in the "
            "input data. If this is your own clinical knowledge, consider stating "
            "it as a physician entry rather than citing the source tag."
        )

    for tag, present, absent in check["cross_section"]:
        pres_txt = "; ".join(f"*{s}*: “{b}”" for s, b in present)
        abs_txt = "; ".join(f"*{s}*: “{b}”" for s, b in absent)
        st.markdown(
            f"⚠️ **Internal contradiction on `{tag}`** — asserted in {pres_txt} "
            f"but described as absent in {abs_txt}. Update both places so the "
            "note is internally consistent."
        )

    for section, body, bad in check["unknown_tags"]:
        st.markdown(
            f"❌ **Unknown source tag** — *{section}*: “{body}” cites {bad}, "
            "which does not exist in the input data."
        )

    for section, body in check["untagged_additions"]:
        st.markdown(
            f"ℹ️ **Untraceable statement** — *{section}*: “{body}” has no source "
            "tag. Physician-added clinical knowledge is legitimate; consider "
            "marking it as such for the audit trail."
        )

    acknowledged = st.checkbox(
        "I have reviewed the consistency flags above and accept responsibility "
        "for the final content."
    )

approve_col, reject_col = st.columns(2)


def _fire_n8n_webhook(payload):
    """
    Send the review decision to the n8n workflow via its webhook, so the
    decision is recorded in the persistent cloud audit table.

    The URL is read from secrets/environment so it is not hard-coded in the
    public repository. Failure never blocks sign-off — the local audit write
    has already happened; this is an additional, best-effort push.
    Returns (ok: bool, message: str) for display.
    """
    import urllib.request
    import urllib.error

    url = ""
    try:
        url = st.secrets.get("N8N_WEBHOOK_URL", "")
    except Exception:  # noqa: BLE001
        url = ""
    url = url or os.environ.get("N8N_WEBHOOK_URL", "")
    if not url:
        return False, "No n8n webhook configured (N8N_WEBHOOK_URL not set)."

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True, "Sent to n8n audit workflow."
    except urllib.error.HTTPError as exc:
        return False, f"n8n returned HTTP {exc.code}."
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach n8n webhook: {exc}"


def _log(decision):
    review_seconds = (
        round(time.time() - st.session_state.gen_time)
        if st.session_state.gen_time else ""
    )
    audit_row = {
        "timestamp": core.now_iso(),
        "case_id": output.get("case_id", meta.get("case_id")),
        "case_type": meta.get("case_type"),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "in_scope": True,
        "trajectory": output.get("trajectory", ""),
        "decision": decision,
        "reviewer": reviewer,
        "total_statements": trace["total_statements"],
        "traceability_pct": trace["traceability_pct"],
        "unsupported_count": trace["unsupported_count"],
        "missing_data_count": len(missing),
        "contradictions_count": len(contradictions),
        "percent_changed": metrics["percent_changed"],
        "review_seconds": review_seconds,
        "edit_unknown_tags": len(check["unknown_tags"]),
        "edit_absence_conflicts": len(check["absence_conflicts"]),
        "edit_cross_section_conflicts": len(check["cross_section"]),
        "edit_untagged_additions": len(check["untagged_additions"]),
        "flags_acknowledged": "yes" if check["total_flags"] and acknowledged else (
            "n/a" if not check["total_flags"] else "no"),
        "reviewer_comment": comment,
    }
    written, note = core.append_audit(audit_row)
    st.session_state.saved = decision
    st.session_state.audit_path = written
    st.session_state.audit_note = note

    # Best-effort push to the n8n persistent audit workflow
    ok, msg = _fire_n8n_webhook(audit_row)
    st.session_state.n8n_ok = ok
    st.session_state.n8n_msg = msg


with approve_col:
    if st.button("✅ Approve and sign", type="primary", use_container_width=True,
                 disabled=not acknowledged):
        _log("approved")
with reject_col:
    if st.button("❌ Reject draft", use_container_width=True):
        _log("rejected")

if not acknowledged:
    st.caption(
        "Sign-off is held until the consistency flags are acknowledged. "
        "Rejection remains available at any time."
    )

if st.session_state.saved:
    audit_path = st.session_state.get("audit_path")
    audit_note = st.session_state.get("audit_note")
    if audit_path:
        st.success(
            f"Recorded as **{st.session_state.saved}** in `{audit_path}` "
            f"({metrics['percent_changed']}% of the draft changed). "
            "The audit trail stores what the AI proposed, what the physician "
            "changed, and who signed."
        )
    else:
        st.error(f"Decision **{st.session_state.saved}** was NOT saved.")
    if audit_note:
        st.warning(audit_note)

    # Show the result of the n8n webhook push (persistent cloud audit)
    n8n_ok = st.session_state.get("n8n_ok")
    n8n_msg = st.session_state.get("n8n_msg", "")
    if n8n_ok:
        st.info(f"📤 {n8n_msg} The decision is now in the persistent audit table.")
    elif n8n_msg:
        st.caption(f"n8n audit push: {n8n_msg}")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "⬇️ Verification copy (with evidence tags)",
            data=edited,
            file_name=f"{output.get('case_id','case')}_approved_traceable.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            "⬇️ Clean clinical note (no tags)",
            data=core.strip_source_tags(edited),
            file_name=f"{output.get('case_id','case')}_approved_clean.md",
            mime="text/markdown",
            use_container_width=True,
        )
    st.caption(
        "Keep the verification copy as the audit artefact; the clean copy is the "
        "version that would be filed in the record."
    )
