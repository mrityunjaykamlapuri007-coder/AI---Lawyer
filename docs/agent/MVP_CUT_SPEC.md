# AI Lawyer: MVP Cut (overrides the v2.0 spec wherever they conflict)

Deadline: submit by 12:00 midnight IST today. Everything below must run end to end by ~6 PM, leaving time for the doc, raw outputs and (optional) video.
Rule: a narrow thing that works honestly beats the full architecture. Anything not listed here is DESIGN_ONLY and goes in the solution doc as "how it would scale".

## Scope (unchanged)
Unresolved e-commerce refund disputes in India. English text only. No voice, no OCR, no uploads in the MVP (pasted text of an email/SMS is fine).

## Build exactly this

1. **Corpus (hand-curated, official sources only)**
   - Consumer Protection Act 2019 and Consumer Protection (E-Commerce) Rules 2020, from official government sources.
   - A JSON file of 15-25 provisions the refund problem needs. Fields: provision_id, act, citation, original_text (verbatim, copied from the official source), source_url, retrieved_date, parent_id, notes on provisos/exceptions.
   - Do NOT write any legal text from memory. If a provision cannot be found in an official source, leave it out.
   - Do not hard-code any refund or grievance deadline unless it is in the verbatim text. Never present a grievance acknowledgement/redressal timeline as a refund payout deadline.

2. **Retrieval**: reuse FAISS + BM25 + RRF from research-rag-assistant (fixes: ordered dedup of queries, stable IDs, no scientific boosts or section mappings). Reranker optional; skip if time is short.

3. **One structured LLM call** (model behind a single adapter so it can be swapped via config/env: MODEL_ID, provider, API key). Input: user story + retrieved provisions (text + IDs). Output JSON, validated with Pydantic:
   - facts (each tagged user_reported), timeline, missing_information (max 3 questions, most decision-relevant first)
   - relevant_provision_ids (IDs only, never free-text citations)
   - application (conditional wording: "may apply if...")
   - outcome: one of no_legal_action_currently_required | informal_resolution_recommended | formal_grievance_recommended | formal_legal_proceedings_may_be_justified | needs_more_information | out_of_scope
   - lawyer_needed (bool + reason)

4. **Deterministic guard (plain Python, the "no invented law" answer)**
   - Every cited provision_id must exist in the corpus JSON, else the claim is dropped and flagged.
   - Citations rendered from the corpus (title + citation + verbatim text), never from model strings.
   - No retrieved provision relevant, or out of scope (not a refund dispute) => refuse politely, no legal claims, suggest a real lawyer where appropriate.
   - Key facts unknown => outcome needs_more_information and ask.
   - Never say the seller broke the law; never guarantee outcomes.

5. **One draft document**: refund support request / grievance letter from a template, with `[TO BE FILLED BY USER]` placeholders. No invented names, dates, order IDs, amounts or addresses. Labelled DRAFT.

6. **UI**: Streamlit chat, single backend call per message. Escape all user text. No secrets in the repo. Local-demo only.

## Tests (own test cases, raw outputs saved unedited in /raw_outputs)
12-15 synthetic cases in a JSONL file, run by one script that writes one output file per case:
- 3 clear delayed-refund cases with dates
- 2 refund approved, money not received
- 2 refund denied/partial
- 2 missing key dates (must ask, not conclude)
- 1 seller vs platform vs payment-provider confusion
- 1 informal-first case (user never contacted support)
- 2 out of scope (tenancy deposit, salary) => must refuse
- 1 prompt designed to bait an invented section number
Record honestly which cases fail and why.

## Explicitly NOT in the MVP (document in the solution doc only)
SQLite case history/snapshots, OCR/PDF evidence processing, multi-case matching, Jev, RAGAS, the 150-question benchmark, claim-level LLM verification, hierarchy parser, Consumer Commission complaint drafts.

## Working method
Read the repo first. Build in this order: corpus JSON -> retrieval -> LLM adapter + schema -> guard -> template -> UI -> test runner. Run each piece before the next. Report what was actually run, with commands and results. Label anything not run as untested. Do not print or reuse any token found in old notebooks.

## Deliverables
Repo with README (run steps, assumptions, limits), raw_outputs/, test cases file, `.env.example` with placeholders only.
