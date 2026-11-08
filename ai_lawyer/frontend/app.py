"""Streamlit demo client.

Run the API first:
    uvicorn ai_lawyer.backend.main:app --reload
Then:
    streamlit run ai_lawyer/frontend/app.py

All user, document and corpus text is escaped before rendering.  This UI never
sends or files a document; drafts are local text for the user to review.
"""
from __future__ import annotations

import html
import os
from datetime import date

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("LAWYER_API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = int(os.environ.get("LAWYER_UI_TIMEOUT_S", "180"))
PLACEHOLDER = "[TO BE FILLED BY USER]"

st.set_page_config(
    page_title="AI Consumer Refund Dispute Assistant",
    page_icon="⚖️",
    layout="wide",
)


def escape(text: str) -> str:
    """Escape untrusted text for safe markdown rendering (HTML disabled)."""
    return html.escape(str(text or ""), quote=True)


def safe_markdown(text: str) -> str:
    escaped = escape(text)
    return escaped.replace(PLACEHOLDER, f"**{PLACEHOLDER}**")


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
    code = payload.get("error_code") or f"http_{response.status_code}"
    correlation = payload.get("correlation_id") or ""
    suffix = f" (reference: {correlation})" if correlation else ""
    return f"{message} [{code}]{suffix}"


def new_conversation() -> str | None:
    try:
        response = httpx.post(f"{API_BASE_URL}/conversations", timeout=15)
        response.raise_for_status()
        return response.json()["conversation_id"]
    except httpx.HTTPStatusError as exc:
        st.error(api_error(exc.response))
    except Exception:  # noqa: BLE001
        st.error("The API is not reachable. Start uvicorn and refresh.")
    return None


def send_message(conversation_id: str, message: str, uploads, case_id: str | None):
    files = []
    for upload in uploads or []:
        files.append(
            ("files", (upload.name, upload.getvalue(), upload.type or "application/octet-stream"))
        )
    data = {"message": message}
    if case_id:
        data["case_id"] = case_id
    try:
        response = httpx.post(
            f"{API_BASE_URL}/conversations/{conversation_id}/messages",
            data=data,
            files=files or None,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as exc:
        return None, api_error(exc.response)
    except Exception as exc:  # noqa: BLE001
        return None, f"The API call failed ({type(exc).__name__})."


def render_disclaimer(info: dict | None) -> None:
    fixture = bool(info and info.get("corpus", {}).get("fixture_data_not_real_law"))
    if fixture:
        st.error(
            "FIXTURE DATA, NOT REAL LAW — every citation comes from a synthetic test "
            "corpus. Do not rely on it as legal authority.",
            icon="⚠️",
        )
    elif info is None:
        st.warning(
            "Backend status is unknown. If it is running in fixture mode, its citations "
            "are synthetic and must not be relied on.",
            icon="⚠️",
        )
    else:
        corpus = info.get("corpus", {})
        index = info.get("index", {})
        llm = info.get("llm", {})
        # Plain text (st.text), so nothing from the API is rendered as markup.
        st.info(
            "REAL CORPUS. This tool is general information and a drafting aid, not legal advice.",
            icon="ℹ️",
        )
        st.text(
            f"Trust: {corpus.get('trust_note') or corpus.get('trust_level', 'unknown')}\n"
            f"Verified provisions in use: {corpus.get('usable', 0)}\n"
            f"LLM: {llm.get('model') or llm.get('provider', 'unknown')} "
            f"({llm.get('provider', 'unknown')})\n"
            f"Embedder: {index.get('embedder') or 'unknown'} "
            f"(hash {index.get('embedder_model_hash') or 'n/a'})"
        )
        gaps = corpus.get("known_gaps") or []
        if gaps:
            with st.expander(f"Known gaps in the legal corpus ({len(gaps)})"):
                st.text("\n".join(f"- {gap}" for gap in gaps))


def render_facts(response: dict) -> None:
    facts = response.get("extracted_facts") or []
    reported = [f for f in facts if f.get("status") == "user_reported"]
    supported = [f for f in facts if f.get("status") == "document_supported"]
    disputed = [f for f in facts if f.get("status") in {"disputed", "unknown"}]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Facts you reported")
        if reported:
            st.dataframe(
                [
                    {
                        "Fact": f.get("fact_type", "").replace("_", " "),
                        "Value": f.get("raw_value", ""),
                        "Inferred": bool(f.get("inferred")),
                    }
                    for f in reported
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("None extracted yet.")
    with col2:
        st.subheader("Facts supported by a document")
        if supported:
            st.dataframe(
                [
                    {
                        "Fact": f.get("fact_type", "").replace("_", " "),
                        "Value": f.get("raw_value", ""),
                        "Page": f.get("page_number"),
                    }
                    for f in supported
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No document-supported facts yet. Upload a text PDF or .txt file.")

    if disputed:
        st.warning("Facts with a conflict or unknown status:")
        for fact in disputed:
            st.write(
                f"- {escape(fact.get('fact_type', '').replace('_', ' '))}: "
                f"{escape(fact.get('raw_value', ''))}"
                + (" (conflict flagged)" if fact.get("ambiguity_flag") else "")
            )


def render_sources(response: dict) -> None:
    sources = response.get("legal_sources") or []
    st.subheader("Legal sources")
    if not sources:
        st.caption("No verified provision was accepted for this message.")
        return
    for source in sources:
        st.markdown(
            f"**{escape(source.get('citation', ''))}**  \n"
            f"Role: {escape(source.get('role', ''))} · "
            f"Applicability: {escape(source.get('applicability', ''))} · "
            f"Source validity: {escape(source.get('source_validity', ''))}"
        )
        st.caption(escape((source.get("excerpt") or "")[:600]))


def render_assessment(response: dict) -> None:
    assessment = response.get("assessment") or {}
    st.subheader("Assessment")
    st.markdown(f"**{escape(str(assessment.get('outcome', '')).replace('_', ' '))}**")
    for reason in assessment.get("reasons") or []:
        st.write(f"- {escape(reason)}")
    missing = response.get("missing_information") or []
    if missing:
        st.markdown("**What is still unknown**")
        for item in missing:
            st.write(f"- {escape(item)}")
    steps = response.get("next_steps") or []
    if steps:
        st.markdown("**Suggested next steps**")
        for i, step in enumerate(steps, start=1):
            st.write(f"{i}. {escape(step)}")
    verification = response.get("verification") or {}
    if verification:
        st.caption(
            "Verification: "
            + escape(str(verification.get("overall", "unverified")))
            + " — "
            + escape(str(verification.get("note", "")))
        )


def render_draft(response: dict) -> None:
    draft = response.get("document_draft")
    if not draft:
        return
    st.subheader("Document draft")
    st.warning(
        "This draft has NOT been sent or filed. Review every placeholder and fact "
        "before using it.",
        icon="📝",
    )
    content = draft.get("content") or ""
    st.text_area(
        "Editable draft",
        value=content,
        height=420,
        key=f"draft_{draft.get('draft_id', 'current')}",
        help="Edit locally. There is deliberately no send or file button.",
    )
    st.caption("Rendered preview (placeholders highlighted):")
    st.markdown(safe_markdown(content))
    st.code(content, language="markdown")


def main() -> None:
    st.title("AI Consumer Refund Dispute Assistant")
    st.caption(
        "Unresolved e-commerce refund disputes in India. English text only. "
        f"Demo user via API header; API: {API_BASE_URL}"
    )
    info = health()
    render_disclaimer(info)

    with st.sidebar:
        st.subheader("Session")
        if info:
            corpus = info.get("corpus", {})
            st.write(f"Corpus mode: **{escape(corpus.get('mode', 'unknown'))}**")
            st.write(f"Provisions: {corpus.get('provisions', 0)}")
            st.write(f"Usable: {corpus.get('usable', 0)}")
            st.write(f"LLM: `{escape(info.get('llm', {}).get('provider', 'unknown'))}`")
        else:
            st.write("API offline")
        if st.button("Start a new conversation"):
            st.session_state["conversation_id"] = None
            st.session_state["messages"] = []
            st.session_state["latest"] = None
            st.session_state.pop("case_id", None)
            st.rerun()
        st.divider()
        st.caption(
            "Limitation: this is general information and a drafting aid, not legal advice. "
            "It cannot guarantee an outcome and does not replace a qualified lawyer."
        )

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("latest", None)
    st.session_state.setdefault("case_id", None)

    for entry in st.session_state["messages"]:
        with st.chat_message(entry["role"]):
            if entry["role"] == "user":
                st.text(entry["content"])
            else:
                st.markdown(safe_markdown(entry["content"]))

    uploads = st.file_uploader(
        "Optional evidence (text PDF, .txt or .md; scanned images are not supported)",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
    )
    message = st.chat_input("Describe the refund problem, or answer the question above")

    if message:
        if not st.session_state.get("conversation_id"):
            conversation_id = new_conversation()
            if not conversation_id:
                st.stop()
            st.session_state["conversation_id"] = conversation_id

        st.session_state["messages"].append({"role": "user", "content": message})
        with st.chat_message("user"):
            st.text(message)

        with st.chat_message("assistant"):
            with st.spinner("Checking the facts and the legal corpus…"):
                response, error = send_message(
                    st.session_state["conversation_id"],
                    message,
                    uploads,
                    st.session_state.get("case_id"),
                )
            if error:
                st.error(error)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": f"Request failed: {error}"}
                )
            else:
                st.markdown(safe_markdown(response.get("assistant_message", "")))
                st.session_state["messages"].append(
                    {"role": "assistant", "content": response.get("assistant_message", "")}
                )
                st.session_state["latest"] = response
                if response.get("case_id"):
                    st.session_state["case_id"] = response["case_id"]
                st.caption(
                    f"Status: {escape(response.get('processing_status', ''))} · "
                    f"Case: {escape(str(response.get('case_id') or '—'))}"
                )

    latest = st.session_state.get("latest")
    if latest:
        st.divider()
        tabs = st.tabs(["Facts", "Sources", "Assessment", "Document draft"])
        with tabs[0]:
            render_facts(latest)
        with tabs[1]:
            render_sources(latest)
        with tabs[2]:
            render_assessment(latest)
        with tabs[3]:
            render_draft(latest)

    st.divider()
    st.caption(
        "Assessment date shown in answers is generated by the backend. "
        f"Today (client): {date.today().isoformat()}. "
        "Never upload evidence for a real dispute to a public demo deployment."
    )


if __name__ == "__main__":
    main()
