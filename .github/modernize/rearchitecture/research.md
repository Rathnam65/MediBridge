# Planning Research and Decisions

## Confirmed constraints

- **Model hosting**: local inference only; do not send clinical text or embeddings to an external model API.
- **Intended environment**: production with real clinical users/data is the eventual target.
- **Current authorization**: engineering planning only. Real-data launch is explicitly blocked until the institution's clinical-governance, privacy, security, and regulatory owners approve the system and its controls.
- **Human oversight**: coding suggestions remain suggestions; the current coder decision workflow must not be bypassed.
- **Evaluation data**: Synthea is synthetic and useful for pipeline/import testing, but it is not sufficient by itself as a clinically adjudicated coding-accuracy gold standard.

## Technical decisions for the plan

- Isolate inference behind a local model adapter, configured to a loopback/private model-server endpoint with outbound network disabled for clinical content. Select the concrete model only after hardware, latency, and clinician-reviewed task benchmarks.
- Keep embeddings local. Add a vector-store abstraction and select a persistent local implementation after indexing the complete synthetic corpus and measuring retrieval quality, memory, and recovery behavior. Do not send text or embeddings to hosted vector services.
- Use LangGraph for explicit stateful workflow orchestration only after analysis, retrieval, and validation are independently testable services.
- Keep a deterministic lexical retrieval path as a transparent fallback; never silently convert model failure into a successful-looking recommendation.
- Preserve versioned source provenance (catalog/version/code/note/source location) in retrieval and recommendation outputs.

## Unresolved external approval

No approved project constitution, clinical governance policy, or formal security/privacy requirements were found in the repository. This plan therefore includes a release-blocking approval gate; it does not assert HIPAA compliance, clinical validity, or authorization to process real PHI.
