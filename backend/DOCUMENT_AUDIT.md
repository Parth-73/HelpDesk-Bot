# Document audit

The authoritative inputs remain in `SD_Assessment/SD_Assessment/course_docs/`. No root-level `course_docs/` exists; the default configuration points to the existing folder. All four original files are read as bytes and hashed before creating derived text. No original file is rewritten.

| File | Actual metadata | Relevant finding |
| --- | --- | --- |
| `01_course_handbook.txt` | Last updated 15 August 2026; official course document | Course overview, weekly effort, assessment weights, certificate tracks and upgrade cutoff. |
| `02_grading_policy_v1.txt` | Version 1; last updated 10 January 2026; January cohort headings | Earlier passing, late-submission and capstone policies; explicitly superseded as a document. |
| `03_grading_policy_v2.txt` | Version 2; last updated 05 October 2026; current active policy; effective October 2026 | Explicitly supersedes `02_grading_policy_v1.txt`. Current overall threshold is 60% plus 40% separately in the final exam. No late submissions; one missed quiz allowed because best five of six count. Capstone extended to 15 November 2026, 11:59 PM IST. |
| `04_exam_rules_and_faq.txt` | Last updated 25 October 2026 | Official exam and technical sections say closed book, 20 November 2026, with desktop/laptop requirements. Section 3 is explicitly unmoderated and unofficial. It includes an adversarial instruction falsely claiming an open-book exam and a December date. The entire unofficial section is excluded before indexing. |

There are no separate publication dates in these documents. `LAST UPDATED` is recorded as `last_updated_date`, not invented as a publication date. The effective month in v2 is represented as the start of October; the text itself remains unchanged. Original deadlines preserve IST and their written date/time. Filesystem modification times never determine precedence.

Ingestion supports UTF-8/BOM, UTF-16/BOM and a Windows-1252 fallback; current originals decode as UTF-8. Derived text joins wrapped bullet lines, keeping qualifications with the policy. Numbered headings define sections. Supersession notices are retained as metadata, outside the section body. The combined SHA-256 version includes filenames and individual original-byte hashes.

The resolver first removes explicitly superseded documents, then resolves conflicting sections by policy topic using applicable effective dates, explicit publication dates, revision dates, and (when dates tie) comparable versions. Missing or tied metadata without explicit supersession leads to a transparent conflict abstention. Unrelated older sections remain available unless the entire document is explicitly superseded. Unknown layouts are traceable but are not automatically promoted to authoritative versions of a known topic.

## Twelve assessment questions

| Questions | Expected retrieval outcome |
| --- | --- |
| 1–3: passing threshold and repetition/paraphrase | v2 passing section; exact normalized repetition uses cache; paraphrases retrieve equivalent evidence but are not automatically treated as identical cache keys. |
| 4: one-day-late capstone | v2 late-submission policy. |
| 5: capstone deadline | v2 capstone deadline. |
| 6: exam book rule and schedule | Official section 1 of exam rules; no forum evidence. |
| 7: iPad or mobile exam | Official technical requirements. |
| 8: certificate fee | Handbook certificate tracks. |
| 9: refund after paying and dropping | Abstain: no refund policy is provided. |
| 10: quiz count and missing one | Handbook assessment weights plus v2 late/quiz exception. |
| 11: SQL indexing and Kubernetes | Abstain: those topics are not supported by the supplied overview. |
| 12: cricket result | Abstain: off-topic. |

No unresolved conflict exists in the supplied current policies after explicit v2 supersession and exclusion of unofficial comments. Synthetic tests exercise missing metadata, ambiguous conflicts and other effective dates without changing the originals.

The FAQ extension also indexes each document's original `COURSE:` header as a traceable `:header` passage. Identical current headers resolve to a single authoritative course-identity passage, enabling course-name questions without inventing source text. The original file hashes remain unchanged. Current extraction therefore uses ten authoritative passages; one unmoderated section and four passages from the explicitly superseded v1 document are excluded from the current FAQ source set. See `FAQ_PIPELINE.md` for extraction/review details.
