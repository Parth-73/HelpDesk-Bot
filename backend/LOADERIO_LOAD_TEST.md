# Hosted readiness load test — 1,500 clients

[Public Loader.io report](https://loader.io/reports/8d6f19bfb3e4296c725dd5f17a310bf3/results/d47af46a3b461f450a26097e477ecd62) · [Original shared link](https://bit.ly/4iDliC8) · [Machine-readable result](artifacts/loaderio_1500_readiness.json)

Test: **Final readiness test – 1500 arrivals**. Run on **11 November 2026 at 1:52 PM IST** (08:22 UTC). The public report was read directly to verify the values below; these are measured hosted results, not mocked load figures.

The setup used `GET /api/ready` on `dpm-101-helpdesk.onrender.com`, with **Clients per test = 1,500**, **duration = 1 minute**, and **one target URL**. The endpoint/method come from the test setup in this session; the public summary exposes the test name and one URL count, but not its request path or method.

| Metric | Recorded result |
| --- | ---: |
| Clients distributed over the run | 1,500 |
| Duration | 60 seconds |
| Average arriving-client rate (derived) | 25 per second |
| Successful responses | 1,500 |
| Average response time | 170 ms |
| Timeouts | 0 |
| HTTP 4xx / 5xx responses | 0 / 0 |
| Network errors | 0 |
| Valid / invalid redirects | 1,500 / 0 |
| Observed error rate | 0% |

## Assessment wording

> The hosted readiness endpoint was tested with 1,500 client arrivals distributed over 60 seconds, averaging 170 ms response time, with 1,500 successful responses and no observed HTTP errors, timeouts or network failures. This checks readiness/database responsiveness and does not establish 1,500 simultaneous chat users or Gemini capacity.

## Interpretation and limits

`/api/ready` checks loaded course documents, database access and whether a Gemini key is configured. It does not submit a chat question, resolve conversation context, check answer accuracy or consume Gemini quota. Passing this run is evidence of responsiveness for the measured readiness workload; it is not a complete chatbot capacity test.

The client count is spread through the minute. It must not be reported as 1,500 concurrent requests or simultaneous students. The roughly 25-per-second figure refers to arriving clients, not a count of every underlying HTTP exchange: the report also records 1,500 followed redirects.

Loader.io includes followed redirects in its timing and statistics. The redirect destinations were valid, but this was not a direct HTTPS-only timing measurement. The shared report displays minimum/maximum as `0 / 0`; those values are not used as meaningful latency measurements. P95 is not provided in the shared summary. No CPU, memory, database saturation or Gemini quota telemetry was collected in this test.

This hosted result complements the source-grounding, caching, idempotency, conversation-isolation and provider-failure regression tests documented elsewhere. It does not replace them or broaden their measured scope. The complete chat-capacity question remains outside this test's evidence.
