# Validation record

Validated locally on macOS arm64 with Python 3.12, using the pinned dependency snapshot.

- 17 automated tests passed: telemetry boundaries, invalid numeric values, redaction patterns, routing reasons, local retrieval, network-free fixture execution, local outage without cloud fallback, malformed JSON, configured API model selection, cloud enablement/consent/routing gates, cloud egress redaction, endpoint restrictions, and the Streamlit diagnosis/support-handoff workflow.
- The live Streamlit interface was opened in a browser and a CPU-saturation simulation was submitted successfully. The page displayed SIMULATION, 82% fixture confidence, LOCAL routing and measured fixture latency.
- The 13-case synthetic simulation benchmark completed with zero cloud requests. Simulation category accuracy was 10/13 and routing agreement was 11/13; the deliberately simple fixture does not diagnose text-only issues. These are test-fixture results, not LLM quality measurements.
- No real Nano inference, cloud provider call, Docker build or GPU performance measurement was performed. Run the real benchmark on the assigned Nano before presenting model or hardware claims.

Benchmark output is generated under ignored `reports/`. Reproduce the validation using the README commands. Original incident data and event credentials were not copied into the project.
