# AGENTS.md: instructions for the coding agent (read this first, every session)

Project: AI Consumer Refund Dispute Assistant for India (Kuku assignment, Problem 2).
Deadline: submittable by 12:00 midnight IST, 8 Nov 2026. Core integrated by 17:00 IST.

## Files you must read, in order
1. `AGENT_EXECUTION_SPEC.md`: the v3 spec (scope, pipeline, schemas, rules). Authoritative for Tier 1.
2. `IMPLEMENTATION_PLAN.md`: the ordered task list you execute. Work tasks in order.
3. `AGENT_EXECUTION_SPEC_v4_ADVANCED.md`: Tier 2/3 extras. Do NOT start these until the 17:00 gate in the plan passes, unless the user says otherwise.

## Hard rules
- Never write legal text, section numbers, deadlines, fees, case names or URLs from memory. Real law comes only from `ai_lawyer/legal_corpus/provisions.json` supplied by the user. Tests use the fake fixture corpus.
- Do not claim anything works unless you ran it. After every task, run the task's test command and paste the real result. Label status: IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / MOCKED_FOR_TESTING / DESIGN_ONLY / BLOCKED.
- One task at a time. Do not start the next task until the current task's "Done when" is true. If a task fails twice, stop and report the blocker instead of working around it.
- Do not modify the original research-RAG files. Work in `ai_lawyer/` on branch `ai-lawyer-mvp`. No push, force-push, history rewrite or public deploy without asking the user.
- Never print or reuse any token found in old notebooks or files. Secrets only via `.env` (git-ignored). `.env.example` has placeholders only.
- No model download, network call or GPU use in unit tests. Modules must import without loading any model (lazy loaders).
- Python owns workflow gates and the final assessment outcome. The LLM drafts and extracts; it cannot override guards.
- Do not expand scope beyond unresolved e-commerce refund disputes in India (English, text).
- Keep a `PROGRESS.md` updated after each task: task id, status label, test command, result, blockers.

## Commands (create and keep these working)
- Install: `python -m venv .venv && pip install -r requirements.txt`
- Tests: `pytest -q`
- API: `uvicorn ai_lawyer.backend.main:app --reload`
- UI: `streamlit run ai_lawyer/frontend/app.py`
- Build index: `python -m ai_lawyer.legal_rag.index_manager build`
- Retrieval eval: `python -m ai_lawyer.evaluation.run_retrieval_eval`
- Behaviour eval: `python -m ai_lawyer.evaluation.run_behavior_eval`
