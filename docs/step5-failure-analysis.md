# Step 5 failure analysis and design adjustment

## What failed first

The first 14-case fixture run passed all security checks but only 13 of 14 task-quality checks. In the uncertain-result case, the mock purchase committed and charged once, then the caller lost the response. The runtime returned `STORE_UNAVAILABLE` instead of retrieving the original receipt. The ledger was correct, but the user did not get a usable answer.

The first repeated Qwen3 1.7B run then passed all six narrow live security gates but only four of six task-quality checks. Both paid repetitions made no purchase. The model tried to finish from free catalog facts, and the runtime returned its sourced fallback as `complete`. That fallback did not answer the requested 30-day error-rate question. The [baseline table](step5-baseline.md) and [baseline JSON](../artifacts/step5-baseline.json) preserve these observed results under the original grader.

## What changed

1. A timed-out purchase is retried once with the **same** server-generated request ID. The purchase service returns the original receipt if the first attempt committed. A second timeout produces `PURCHASE_RESULT_UNKNOWN` and exposes the stable request ID for later reconciliation. No new charge ID is invented for the retry.
2. The server-owned task requirements identify the paid report needed to answer the error-rate question. The buyer's model schema asks for a quote after research and a purchase proposal after receiving the quote. The runtime refuses to complete that task with free catalog facts alone. Trusted purchase policy still decides whether the proposal can spend.
3. An evaluator audit found that the live task grader had accepted any nonempty sourced answer. It now checks expected fixture facts and a canonical paid receipt, and the control gate checks event-ID agreement across audit, outbox, and final event tables, purchase-to-ledger consistency, and researcher read-only behavior. A regression test rejects answers with correct citations but incorrect facts.

## Measured result after the change

The [final SQLite and live-model table](step5-results.md) reports 14/14 fixture cases, 6/6 repeated Ollama transaction/role gates, and 6/6 end-to-end task-fidelity checks under the stricter grader. Both paid repetitions bought one report, cited `paid_report_demo_v1`, and answered that supplier_harbor had the lowest synthetic 30-day error rate at 0.5%. The [PostgreSQL table](step5-postgres-results.md) shows 14 fixture cases passing against the dedicated evaluation database.

The two paid answers were assembled by the runtime from the purchased report. The four free and injected-text Ollama repetitions completed through the runtime's **sourced answer fallback**. Their end-to-end answers used validated catalog data and spent nothing, but the model itself did not produce an accepted final comparison. These are six successful end-to-end outcomes with zero accepted model-authored final answers in this measured batch.

## What this does not establish

Two repetitions per live task reveal this model's behavior in this local setup, not a stable success rate. The fixture attack suite validates the coded boundaries under its assumptions; the repeated live runs cover three tasks and only one injected-text prompt. The answer oracle checks fact and source coverage but can miss contradictions or incorrect fact-to-supplier relationships. The paid path uses trusted task requirements and a constrained action schema; the free paths may use runtime-authored fallbacks. The event sink and charges are local and synthetic. A real application would need explicit human consent, an independent identity provider, external delivery behavior, a larger adversarial/model sample, and load and multi-host failure tests.
