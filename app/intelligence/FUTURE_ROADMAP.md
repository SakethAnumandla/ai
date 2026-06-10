# Intelligence — Future Roadmap (Post Phase 5)

Planned capabilities after manager workflows, analytics, and operational dashboards.  
**Not implemented in production** — extension points live under `app/intelligence/` for incremental delivery.

| # | Capability | Priority | Extension point |
|---|------------|----------|-----------------|
| 1 | Receipt embedding fingerprints | 🟠 Future | `receipt/fingerprint.py` |
| 2 | OCR explainability | 🟡 Future | `receipt/explainability.py` |
| 3 | Voice biometric safety | 🔵 Future advanced | `voice/biometric.py` |
| 4 | Multi-language OCR normalization | 🟠 Future | `receipt/locale_normalizer.py` |
| 5 | Human review queues (finance dashboard) | 🟠 Future | `receipt/review_queue.py` |

---

## 1. Receipt embedding fingerprints 🟠

**Goal:** Visual similarity matching beyond file hash and text semantics — detect manipulated duplicates, altered receipts, and fraud clusters.

**Use cases:**
- Same receipt re-photographed with different crop/lighting (complements `ReceiptDuplicateSimilarityChecker`)
- Digitally altered totals or vendor name on an otherwise similar image
- Cluster suspicious uploads across users (finance ops)

**Proposed design:**

```
Upload → preprocess (deskew, grayscale) → embedding model
       → store vector + expense_id in receipt_fingerprints (pgvector or external index)
       → nearest-neighbor search at ingest + nightly batch
```

| Component | Notes |
|-----------|--------|
| `BaseReceiptFingerprintProvider` | `compute_embedding(bytes) → vector`, `similarity(a, b) → float` |
| Implementations | CLIP/ViT (on-prem), OpenAI embeddings on thumbnail, AWS Rekognition CompareFaces-style (receipt-specific fine-tune later) |
| Storage | `receipt_fingerprints(id, tenant_id, expense_id, model_version, embedding, created_at)` |
| Threshold | Tenant-configurable; default conservative (flag, not auto-reject) |
| Integration | Runs after OCR in `ReceiptIntelligencePipeline`; adds `FraudCheckResult(check="visual_similarity")` |

**Constraints:** No Pinecone requirement in core path — Postgres `pgvector` or Redis-backed approximate index for MVP.

**Config (future):** `RECEIPT_FINGERPRINT_ENABLED`, `RECEIPT_FINGERPRINT_MODEL`, `RECEIPT_FINGERPRINT_SIMILARITY_THRESHOLD`

---

## 2. OCR explainability 🟡

**Goal:** Tell users *why* a field confidence is low, e.g. *"Total amount confidence is low because the receipt image is blurred."*

**Proposed design:**

| Signal source | Example reason |
|---------------|----------------|
| Image quality (blur, contrast, resolution) | Blur / low DPI |
| OCR engine confidence | Tesseract word-level scores |
| Layout (missing label near amount) | "Total not found near 'Total' label" |
| Cross-field consistency | "Subtotal + tax ≠ total" |
| Provider-specific | Textract `Confidence` blocks |

**API surface:** `FieldConfidence.confidence_reason` on each field; aggregated `ocr_explanations[]` on `ReceiptPipelineResult`.

**Implementation phases:**
1. ✅ Rule-based reasons from scorer metadata (`OCRExplainabilityBuilder`)
2. Image quality heuristics (Laplacian variance, brightness)
3. Optional GPT-4o Vision one-liner for review UI only (never auto-approve)

**Config:** `OCR_EXPLAINABILITY_ENABLED` (default on for rule-based)

---

## 3. Voice biometric safety 🔵 (not now)

**Goal:** Speaker verification for high-security enterprises — ensure voice commands match enrolled user.

**Explicitly out of scope** until enterprise tier; document only.

| Component | Notes |
|-----------|--------|
| `SpeakerVerificationProvider` | `enroll(user_id, samples)`, `verify(user_id, audio) → score` |
| Vendors | Azure Speaker Recognition, AWS Voice ID, on-prem ECAPA-TDNN |
| Integration | Gate `POST /intelligence/voice/chat` when `tenant.voice_biometric_required` |
| Fallback | Push confirmation to mobile app if verify score < threshold |

**Privacy:** Store voiceprints encrypted; separate retention policy from transcription audits.

---

## 4. Multi-language OCR normalization 🟠

**Goal:** Multilingual invoices → canonical fields; locale-aware dates, amounts, and currency.

**Proposed design:**

```
Raw OCR text + detected locale → LocaleNormalizer
  → normalized merchant, ISO date, decimal amount, ISO 4217 currency
  → feed ReceiptEntities + fraud checks
```

| Piece | Notes |
|-------|--------|
| Language detection | `langdetect` or provider locale from Textract/Vision |
| Number parsing | `babel` / `price-parser` — handle `1.234,56` vs `1,234.56` |
| Date parsing | `dateparser` with locale hint |
| Currency | Symbol + country inference → INR/USD/EUR |
| GST/tax IDs | Country-specific regex packs |

**Config:** `OCR_DEFAULT_LOCALE`, `OCR_SUPPORTED_LOCALES`

**Integration:** Hook in `BaseOCRProvider.normalize()` before `OCRConfidenceScorer`.

---

## 5. Human review queues (finance dashboard) 🟠

**Goal:** Operations dashboard for finance reviewers — queue of low-confidence receipts, fraud flags, anomalous claims.

**Proposed design:**

| Queue type | Filter |
|------------|--------|
| `low_confidence` | `overall_confidence < threshold` |
| `fraud_flagged` | Any failed `FraudCheckResult` |
| `anomaly` | Links to `GET /ai/memory/anomalies` + receipt context |
| `pending_review` | `review_status = pending_review` |

**Tables (future migration):**

```sql
receipt_review_queue_items (
  id, tenant_id, expense_id, ocr_bill_id,
  queue_type, priority, assigned_to,
  review_status, review_token,
  payload_json, created_at, resolved_at
)
```

**APIs (future):**

- `GET /intelligence/review-queue` — paginated, filter by type/tenant/assignee
- `PATCH /intelligence/review-queue/{id}` — assign, approve, reject, request info
- Webhook / Slack notify on high-severity fraud

**Current state:** `ReviewQueueService` stub lists candidates from `OCRBill.extracted_fields` until dedicated table exists.

**RBAC:** `finance_reviewer`, `finance_admin` roles only.

---

## Phase 5 manager improvements (implemented)

| Item | Module |
|------|--------|
| Bulk dry-run CSV/HTML export | `manager/dry_run_export.py` |
| Approval simulation | `manager/simulation.py` |
| Risk score explainability | `manager/risk_explainability.py` |
| Queue prioritization | `manager/prioritization.py` |
| Manager workload analytics | `manager/workload_analytics.py` (Phase 6 foundation) |

## Manager / analytics Phase 6+

See [`app/manager/FUTURE_ROADMAP.md`](../manager/FUTURE_ROADMAP.md) for forecasting, policy impact, behavioral risk, export signatures, and SLA prediction.

## Suggested build order (after Phase 5)

1. Human review queues (unblocks finance ops immediately)
2. OCR explainability phase 2 (image quality)
3. Multi-language normalization (international rollout)
4. Receipt embedding fingerprints (fraud maturity)
5. Voice biometrics (enterprise contract)
