"""Streamlit chat UI for the refund assistant.

Run the API first:
    uvicorn ai_lawyer.backend.main:app
Then:
    streamlit run ai_lawyer/frontend/app.py

Safety: Streamlit never renders raw HTML from st.markdown unless asked, and this
app only enables HTML for its own static stylesheet.  Text that comes from the
user, a document, the corpus or the model is shown as escaped markdown or plain
text.  The UI never sends or files anything; drafts are for the user to review.
"""
from __future__ import annotations

import os
import re
from datetime import date

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("LAWYER_API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = int(os.environ.get("LAWYER_UI_TIMEOUT_S", "240"))
PLACEHOLDER = "[TO BE FILLED BY USER]"

st.set_page_config(page_title="Refund Help · AI Consumer Refund Dispute Assistant", page_icon="⚖️", layout="wide")

# Our own static stylesheet (no user content), so unsafe_allow_html is safe here.
st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem; max-width: 1150px;}
[data-testid="stChatMessage"] {border-radius: 14px; padding: 0.6rem 0.9rem;}
.small-muted {color: #6b7280; font-size: 0.85rem;}
.hero {padding: 1.1rem 1.3rem; border-radius: 16px; background: linear-gradient(135deg,#eef4ff,#f7f3ff);
       border: 1px solid #e3e8f5; margin-bottom: 0.8rem;}
.hero h3 {margin: 0 0 0.3rem 0;}
@media (prefers-color-scheme: dark) {
  .hero {background: linear-gradient(135deg,#1c2433,#231d33); border-color: #2d3748;}
  .small-muted {color: #9ca3af;}
}
</style>
""",
    unsafe_allow_html=True,
)

OUTCOME = {
    "no_legal_action_currently_required": ("success", "✅", "Wait for now: your refund is still within the seller's own promised time."),
    "informal_resolution_recommended": ("info", "💬", "Contact the seller or platform's customer support first, in writing."),
    "formal_grievance_recommended": ("warning", "📨", "Send a formal grievance to the platform's grievance officer."),
    "formal_legal_proceedings_may_be_justified": ("error", "⚖️", "Formal proceedings may be justified, but no outcome is certain."),
    "needs_more_information": ("info", "❓", "I need a little more information before I can recommend a next step."),
    "out_of_scope": ("info", "🚫", "This is outside what I can help with."),
}
FACT_LABELS = {
    "platform_name": "Platform",
    "merchant_name": "Seller",
    "order_id": "Order",
    "transaction_id": "Transaction",
    "refund_amount": "Amount",
    "payment_method": "Paid by",
    "purchase_date": "Ordered",
    "cancellation_date": "Cancelled",
    "return_requested_date": "Return requested",
    "return_approved_date": "Return approved",
    "pickup_date": "Picked up",
    "refund_initiated_date": "Refund initiated",
    "refund_status": "Refund status",
    "support_contact_made": "Contacted support",
    "support_contact_date": "Support contacted on",
    "grievance_officer_contacted": "Contacted grievance officer",
    "grievance_contact_date": "Grievance officer contacted on",
    "merchant_promised_timeline_days": "Seller's promised timeline",
    "bank_credit_confirmed": "Money reached your account",
}
STATUS_WORDS = {
    "not_received": "not received", "pending": "pending", "initiated": "initiated by the seller",
    "processed": "marked processed (not proof the money arrived)", "partial": "only partly refunded",
    "denied": "refused", "reversed": "reversed", "received": "received", "credited": "received",
}
APPLICABILITY_WORDS = {
    "applicable": "Applies to the facts you gave",
    "unknown": "May apply, depending on facts not yet confirmed",
    "not_applicable": "Does not seem to apply",
}
EXAMPLES = [
    "I cancelled an order on Flipkart on 5 November 2026 and paid ₹2,499 by UPI. The refund has not come "
    "and I have not contacted support yet.",
    "Amazon picked up my return on 20 October 2026 and said the refund was initiated, but nothing has "
    "reached my account. I emailed their support twice and they keep saying wait.",
    "The seller sent me the wrong product. I asked for a refund on 2 November 2026 and they rejected it "
    "without any reason, even after I called customer care.",
]


def md(text: object) -> str:
    """Escape markdown control characters in untrusted text (HTML is never rendered)."""
    return re.sub(r"([\\`*_{}\[\]<>()#+|!~])", r"\\\1", str(text or ""))


@st.cache_data(ttl=30, show_spinner=False)
def health() -> dict | None:
    try:
        response = httpx.get(f"{API_BASE_URL}/health", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception:  # noqa: BLE001 - the UI shows an offline state
        return None


def api_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {}
    message = payload.get("user_safe_message") or "The request failed."
    correlation = payload.get("correlation_id") or ""
    return message + (f" (reference: {correlation})" if correlation else "")


def new_conversation() -> str | None:
    try:
        response = httpx.post(f"{API_BASE_URL}/conversations", timeout=15)
        response.raise_for_status()
        return response.json()["conversation_id"]
    except httpx.HTTPStatusError as exc:
        st.error(api_error(exc.response))
    except Exception:  # noqa: BLE001
        st.error("The assistant's server is not reachable. Start the API and refresh.")
    return None


def send_message(conversation_id: str, message: str, uploads, case_id: str | None):
    files = [("files", (u.name, u.getvalue(), u.type or "application/octet-stream")) for u in uploads or []]
    data = {"message": message}
    if case_id:
        data["case_id"] = case_id
    try:
        response = httpx.post(
            f"{API_BASE_URL}/conversations/{conversation_id}/messages",
            data=data, files=files or None, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as exc:
        return None, api_error(exc.response)
    except httpx.TimeoutException:
        return None, "The model took too long to answer. Please try again in a moment."
    except Exception as exc:  # noqa: BLE001
        return None, f"The request failed ({type(exc).__name__})."


# ---------------------------------------------------------------- rendering ---
def render_status_banner(info: dict | None) -> None:
    if info and info.get("corpus", {}).get("fixture_data_not_real_law"):
        st.error(
            "FIXTURE DATA, NOT REAL LAW — this is the offline test mode with a synthetic corpus. "
            "Do not rely on its citations.",
            icon="⚠️",
        )
    elif info is None:
        st.warning(
            "Backend status is unknown: the assistant's server is not reachable. Start the API and refresh.",
            icon="⚠️",
        )
    else:
        st.caption(
            f"🔒 Real law: {info.get('corpus', {}).get('usable', 0)} verified provisions of the Consumer "
            "Protection (E-Commerce) Rules, 2020 · machine-verified, not reviewed by a lawyer · "
            "general information, not legal advice"
        )


def _summary_from_message(message: str) -> str:
    match = re.search(r"## What I understood\s*\n+(.+?)(?:\n\s*\n|\n##|$)", message or "", re.S)
    return match.group(1).strip() if match else ""


def _readable(fact: dict) -> str:
    value = fact.get("normalised_value")
    ftype = fact.get("fact_type", "")
    if ftype == "refund_amount" and isinstance(value, int):
        return f"₹{value / 100:,.2f}"
    if ftype.endswith("_date") and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).strftime("%d %b %Y")
    if ftype == "refund_status":
        return STATUS_WORDS.get(str(value), str(fact.get("raw_value", "")))
    if isinstance(value, bool):
        return "yes" if value else "no"
    if ftype == "merchant_promised_timeline_days" and isinstance(value, int):
        return f"{value} days"
    return str(fact.get("raw_value") or value or "")


def render_facts(response: dict) -> None:
    facts = [f for f in response.get("extracted_facts") or [] if f.get("fact_type") in FACT_LABELS]
    if not facts:
        return
    seen: dict[str, dict] = {}
    for fact in facts:  # the latest fact of each type wins
        seen[fact["fact_type"]] = fact
    lines = []
    for ftype in FACT_LABELS:
        fact = seen.get(ftype)
        if not fact:
            continue
        source = ""
        if fact.get("status") == "document_supported":
            source = " · 📄 from your document" + (f", page {fact['page_number']}" if fact.get("page_number") else "")
        flag = " · ⚠️ conflicting" if fact.get("ambiguity_flag") else ""
        lines.append(f"- **{FACT_LABELS[ftype]}:** {md(_readable(fact))}{source}{flag}")
    st.markdown("**What I picked up from your message**\n\n" + "\n".join(lines))
    if any("ocr" in (e.get("methods") or []) for e in response.get("evidence_processing") or []):
        st.caption("Text from images is read by OCR on this machine and can misread digits: check amounts and dates.")


def _short_citation(citation: str) -> str:
    return (citation or "").replace("Consumer Protection (E-Commerce) Rules, 2020", "E-Commerce Rules 2020") \
        .replace("Consumer Protection (E-Commerce) (Amendment) Rules, 2021", "E-Commerce (Amendment) Rules 2021")


def render_sources(response: dict) -> None:
    sources = response.get("legal_sources") or []
    if not sources:
        return
    st.markdown("**The law that may apply** · verified text, shown word for word")
    for source in sources:
        label = APPLICABILITY_WORDS.get(source.get("applicability"), "May apply")
        with st.expander(f"📘 {_short_citation(source.get('citation', ''))} — {label}"):
            st.markdown("> " + md(" ".join((source.get("excerpt") or "").split())))


def render_answer(response: dict, *, latest: bool) -> None:
    assessment = response.get("assessment") or {}
    outcome = assessment.get("outcome") or ""
    # Greetings, intake questions, order-split questions and refusals are plain
    # conversational replies: show the message itself, not an assessment card.
    if outcome == "out_of_scope" or not (response.get("legal_sources") or response.get("extracted_facts")):
        st.markdown(response.get("assistant_message", ""))
        return
    # The document check comes first: was the upload readable and useful?
    doc_block = re.search(r"### Your document\s*\n+((?:- .+\n?)+)", response.get("assistant_message", ""))
    if doc_block:
        for line in doc_block.group(1).splitlines():
            note = line[2:].strip()
            if note.startswith("✅"):
                st.success(note)
            elif note.startswith("⚠️"):
                st.warning(note)
            elif note:
                st.error(note)

    kind, icon, headline = OUTCOME.get(outcome, ("info", "ℹ️", "Here is what I found."))
    getattr(st, kind)(f"**{headline}**", icon=icon)

    summary = _summary_from_message(response.get("assistant_message", ""))
    if summary and outcome != "out_of_scope":
        st.markdown(f"_{md(summary)}_")

    reasons = assessment.get("reasons") or []
    if reasons:
        st.markdown("**Why**\n\n" + "\n".join(f"- {md(r)}" for r in reasons))
    steps = response.get("next_steps") or assessment.get("next_steps") or []
    if steps:
        st.markdown("**What to do next**\n\n" + "\n".join(f"{i}. {md(s)}" for i, s in enumerate(steps, 1)))
    missing = response.get("missing_information") or []
    if missing:
        st.info("**I need from you:**\n\n" + "\n".join(f"- {md(q)}" for q in missing), icon="✍️")

    render_facts(response)
    render_sources(response)

    draft = response.get("document_draft")
    if draft and latest:
        content = draft.get("content") or ""
        st.markdown(f"**Draft {md((draft.get('draft_type') or 'letter').replace('_', ' '))}** · not sent; "
                    f"fill every {md(PLACEHOLDER)} before using it")
        st.text_area("Edit your draft", value=content, height=300, key=f"draft_{draft.get('draft_id', 'current')}")
        st.download_button("⬇️ Download draft (.txt)", data=content, file_name="refund_letter_draft.txt",
                           mime="text/plain", key=f"dl_{draft.get('draft_id', 'current')}")
    elif draft:
        st.caption("A draft was prepared for this message.")

    with st.expander("Full answer (as generated)"):
        st.markdown(response.get("assistant_message", ""))
    if assessment.get("lawyer_needed"):
        st.caption("⚖️ You may want to speak to a qualified lawyer"
                   + (f": {md(assessment.get('lawyer_reason'))}" if assessment.get("lawyer_reason") else "."))


def render_welcome() -> None:
    st.markdown(
        '<div class="hero"><h3>Did an online refund never come?</h3>'
        "Tell me what happened, in your own words. I will work out the key facts, show you the rules from the "
        "Consumer Protection (E-Commerce) Rules, 2020 that may apply, suggest a sensible next step and draft "
        "the letter for you. You can attach a screenshot of the refund message as proof.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("**Try an example**")
    cols = st.columns(len(EXAMPLES))
    for i, (col, text) in enumerate(zip(cols, EXAMPLES)):
        with col:
            st.caption(text)
            if st.button("Use this example", key=f"example_{i}", use_container_width=True):
                st.session_state["pending"] = text
                st.rerun()


# --------------------------------------------------------------------- main ---
def main() -> None:
    info = health()
    st.title("⚖️ Refund Help · AI Consumer Refund Dispute Assistant")
    render_status_banner(info)

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("latest", None)
    st.session_state.setdefault("case_id", None)
    st.session_state.setdefault("uploader_key", 0)

    with st.sidebar:
        st.subheader("Conversation")
        if st.button("🆕 New conversation", use_container_width=True):
            for key in ("conversation_id", "case_id", "latest", "pending"):
                st.session_state.pop(key, None)
            st.session_state["messages"] = []
            st.rerun()
        st.divider()
        st.subheader("System")
        if info:
            corpus, llm, index = info.get("corpus", {}), info.get("llm", {}), info.get("index", {})
            st.caption(f"Mode: {md(corpus.get('mode', 'unknown'))} · verified provisions: {corpus.get('usable', 0)}")
            st.caption(f"Model: {md(llm.get('model') or llm.get('provider', 'unknown'))}")
            if index.get("embedder"):
                st.caption(f"Search: {md(index.get('embedder'))}")
            gaps = corpus.get("known_gaps") or []
            if gaps:
                with st.expander(f"What it does not cover yet ({len(gaps)})"):
                    st.markdown("\n".join(f"- {md(g)}" for g in gaps))
        else:
            st.caption("Server offline")
        st.divider()
        st.caption("General information and a drafting aid, not legal advice. It never sends anything. "
                   "Answers take about a minute (the model runs on a free GPU). "
                   "Do not enter real personal data on a public demo.")

    if not st.session_state["messages"]:
        render_welcome()

    for idx, entry in enumerate(st.session_state["messages"]):
        with st.chat_message(entry["role"], avatar="🧑" if entry["role"] == "user" else "⚖️"):
            if entry["role"] == "user":
                st.markdown(md(entry["content"]))
                for name in entry.get("files", []):
                    st.caption(f"📎 {md(name)}")
            elif entry.get("payload"):
                render_answer(entry["payload"], latest=idx == len(st.session_state["messages"]) - 1)
            else:
                st.error(entry["content"])

    read_files = False
    with st.expander("📎 Attach a screenshot, photo or PDF of the order or refund message",
                     expanded=bool(st.session_state.get("messages"))):
        uploads = st.file_uploader(
            "PNG, JPG or PDF up to 10 MB. Images are read by OCR on this machine.",
            type=["png", "jpg", "jpeg", "pdf", "txt", "md"],
            accept_multiple_files=True,
            key=f"uploads_{st.session_state['uploader_key']}",
        )
        if uploads:
            st.caption("Type a message below, or just press the button to have the file read.")
            read_files = st.button("📄 Read my document", use_container_width=True)
    typed = st.chat_input("Describe your refund problem, or answer my question…")
    message = typed or st.session_state.pop("pending", None)
    if not message and read_files and uploads:
        message = "Please read the attached document about my refund."
    if not message:
        return

    if not st.session_state.get("conversation_id"):
        conversation_id = new_conversation()
        if not conversation_id:
            st.stop()
        st.session_state["conversation_id"] = conversation_id

    names = [u.name for u in uploads or []]
    st.session_state["messages"].append({"role": "user", "content": message, "files": names})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(md(message))
        for name in names:
            st.caption(f"📎 {md(name)}")
    with st.chat_message("assistant", avatar="⚖️"):
        with st.spinner("Reading your story, checking the verified law and preparing an answer…"):
            response, error = send_message(
                st.session_state["conversation_id"], message, uploads, st.session_state.get("case_id")
            )
        if error:
            st.error(error)
            st.session_state["messages"].append({"role": "assistant", "content": error})
            return
        st.session_state["messages"].append({"role": "assistant", "content": response.get("assistant_message", ""),
                                             "payload": response})
        st.session_state["latest"] = response
        if response.get("case_id"):
            st.session_state["case_id"] = response["case_id"]
        render_answer(response, latest=True)
    st.session_state["uploader_key"] += 1  # clear attachments after sending


if __name__ == "__main__":
    main()
