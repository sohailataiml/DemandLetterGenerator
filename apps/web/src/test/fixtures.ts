/**
 * Fixtures shaped exactly like the FastAPI responses.
 *
 * These are generic on purpose — the UI must work for any case, so nothing here
 * is special-cased by name anywhere in the components under test.
 */

import type {
  Bill,
  DocumentPage,
  PageGeometry,
  CaseRecord,
  CaseSummary,
  Damages,
  Demand,
  Fact,
  LetterTemplate,
  LetterTemplateDetail,
  Party,
  SourceDocumentDetail,
  UploadLimits,
} from "@/lib/api/types";

export const CASE_ID = "case_test0001";
export const DEMAND_ID = "dmnd_test0001";

export const caseRecord: CaseRecord = {
  id: CASE_ID,
  reference: "AB-2025-0001",
  client_display_name: "Rosa Delgado",
  status: "demand_prep",
  notes: null,
  created_at: "2026-01-05T10:00:00",
  updated_at: "2026-02-05T10:00:00",
};

export const caseSummary: CaseSummary = {
  id: CASE_ID,
  reference: "AB-2025-0001",
  client_display_name: "Rosa Delgado",
  status: "demand_prep",
  claim_number: "884120993",
  date_of_loss: "2025-04-12",
  carrier_name: "Northline Mutual",
  demand: {
    id: DEMAND_ID,
    version: 2,
    status: "draft",
    letter_date: "2026-02-01",
    locked: false,
    approved_at: null,
    updated_at: "2026-02-05T10:00:00",
  },
  validation: {
    blocking: 1,
    warning: 2,
    info: 0,
    last_validated_at: "2026-02-05T10:00:00",
  },
  updated_at: "2026-02-05T10:00:00",
};

export const parties: Party[] = [
  {
    id: "pty_client",
    case_id: CASE_ID,
    full_name: "Rosa Delgado",
    date_of_birth: null,
    phone: null,
    email: null,
    address: null,
    organization: null,
    notes: null,
    role_assignments: [{ role: "client", relationship_note: null }],
  },
  {
    id: "pty_insured",
    case_id: CASE_ID,
    full_name: "Carol Bush",
    date_of_birth: null,
    phone: null,
    email: null,
    address: null,
    organization: null,
    notes: null,
    role_assignments: [
      { role: "insured", relationship_note: "Policyholder and registered owner." },
      { role: "vehicle_owner", relationship_note: null },
    ],
  },
  {
    id: "pty_driver",
    case_id: CASE_ID,
    full_name: "Larry L. Lawhorn",
    date_of_birth: null,
    phone: null,
    email: null,
    address: null,
    organization: null,
    notes: null,
    role_assignments: [{ role: "driver", relationship_note: "Permissive user." }],
  },
];

export const bills: Bill[] = [
  {
    id: "bill_known",
    provider_name: "Santee Chiropractic Clinic",
    description: "12 visits",
    amount: "6480.00",
    status: "KNOWN",
    billed_on: "2025-07-09",
    provider_id: "prv_1",
    source_document_id: null,
  },
  {
    id: "bill_pending",
    provider_name: "Coastal Pain and Spinal Diagnostics",
    description: "injection billing not yet received",
    amount: null,
    status: "PENDING",
    billed_on: null,
    provider_id: "prv_2",
    source_document_id: null,
  },
];

export const damages: Damages = {
  current_medical_expenses: "9980.00",
  pending_bills: [
    {
      bill_id: "bill_pending",
      provider_name: "Coastal Pain and Spinal Diagnostics",
      description: "injection billing not yet received",
    },
  ],
  estimated_bill_total: "0.00",
  future_medical_low: "8400.00",
  future_medical_high: "11200.00",
  general_damages: "0.00",
  other_damages: "3120.00",
  known_claimed_damages_low: "21500.00",
  known_claimed_damages_high: "24300.00",
  line_items: [
    {
      kind: "medical_bill",
      id: "bill_known",
      provider_name: "Santee Chiropractic Clinic",
      description: "12 visits",
      status: "KNOWN",
      amount: "6480.00",
    },
    {
      kind: "medical_bill",
      id: "bill_pending",
      provider_name: "Coastal Pain and Spinal Diagnostics",
      description: "injection billing not yet received",
      status: "PENDING",
      amount: null,
    },
    {
      kind: "future_treatment",
      id: "fut_1",
      description: "Epidural steroid injection series",
      provider_name: "Coastal Pain and Spinal Diagnostics",
      quantity: 2,
      amount: "4200.00",
      amount_high: "5600.00",
    },
  ],
};

export const facts: Fact[] = [
  {
    id: "fact_verified",
    case_id: CASE_ID,
    fact_type: "imaging_finding",
    value: { level: "L5-S1" },
    summary: "MRI showed a disc extrusion at L5-S1",
    status: "VERIFIED",
    confidence: 1,
    created_at: "2026-01-10T09:00:00",
    revision: 1,
    supersedes_id: null,
    superseded_by_id: null,
    proposed_by: "para_7",
    reviewed_by: "attorney_1",
    reviewed_at: "2026-01-11T09:00:00",
    rejection_reason: null,
    extraction_metadata: null,
    sources: [
      {
        id: "fsrc_1",
        fact_id: "fact_verified",
        document_id: "doc_1",
        page_number: 2,
        excerpt: "disc extrusion at L5-S1",
        start_offset: 12,
        end_offset: 35,
        quoted_text_sha256: "a".repeat(64),
        match_kind: "exact",
        citation_status: "EXACT",
        // Two lines of the original page, so multi-box rendering is exercised.
        bounding_boxes: [
          { x: 0.18, y: 0.51, width: 0.61, height: 0.03 },
          { x: 0.12, y: 0.55, width: 0.24, height: 0.03 },
        ],
        confidence: 1,
      },
    ],
  },
  {
    id: "fact_proposed",
    case_id: CASE_ID,
    fact_type: "treatment_event",
    value: {},
    summary: "Treated at Santee Chiropractic Clinic for twelve visits",
    status: "PROPOSED",
    confidence: 0.82,
    created_at: "2026-01-12T09:00:00",
    revision: 1,
    supersedes_id: null,
    superseded_by_id: null,
    proposed_by: "extractor",
    reviewed_by: null,
    reviewed_at: null,
    rejection_reason: null,
    extraction_metadata: {
      provider: "pattern",
      model: null,
      prompt_version: "extraction_v1",
      document_id: "doc_1",
      page_number: 1,
      match_kind: "exact",
      low_confidence: false,
    },
    sources: [
      {
        id: "fsrc_2",
        fact_id: "fact_proposed",
        document_id: "doc_1",
        page_number: 1,
        excerpt: null,
        start_offset: null,
        end_offset: null,
        quoted_text_sha256: null,
        match_kind: null,
        citation_status: "UNRESOLVED",
        bounding_boxes: null,
        confidence: null,
      },
    ],
  },
];

export const demand: Demand = {
  id: DEMAND_ID,
  case_id: CASE_ID,
  version: 2,
  status: "draft",
  letter_date: "2026-02-01",
  template_version: "policy_limits_v1",
  provider_name: "stub",
  model_name: null,
  prompt_version: "narrative_v1",
  generated_at: "2026-02-01T12:00:00",
  docx_sha256: null,
  pdf_sha256: null,
  approved_by: null,
  approved_at: null,
  locked: false,
  created_by: "attorney_1",
  template_id: null,
  template_sha256: null,
  fidelity_report: null,
  claim_report: {
    claims_checked: 6,
    supported: 6,
    partially_supported: 0,
    unsupported: 0,
    sections: ["liability", "medical_summary"],
    unsupported_claims: [],
  },
  sections: [
    {
      id: "sec_1",
      key: "claim_metadata",
      title: "Claim Information",
      position: 1,
      body: "Our Client   : Rosa Delgado\nClaim Number : 884120993",
      source: "template",
      used_fact_ids: [],
      edited_by: null,
    },
    {
      id: "sec_2",
      key: "imaging_summary",
      title: "Diagnostic Imaging Findings",
      position: 2,
      body: "MRI showed a disc extrusion at L5-S1.",
      source: "ai",
      used_fact_ids: ["fact_verified"],
      edited_by: null,
    },
  ],
  issues: [
    {
      code: "DATE_001",
      severity: "BLOCKING",
      message: "Demand expiration (2026-01-29) is not after the letter date (2026-02-01).",
      section_key: "demand_title",
      details: { expires_on: "2026-01-29", letter_date: "2026-02-01" },
    },
    {
      code: "PARTY_001",
      severity: "WARNING",
      message:
        "Named insured (Carol Bush) and driver (Larry L. Lawhorn) are different people, but no relationship is recorded on either role.",
      section_key: null,
      details: { insured: "Carol Bush", driver: "Larry L. Lawhorn" },
    },
  ],
};

export const documentDetail: SourceDocumentDetail = {
  id: "doc_1",
  case_id: CASE_ID,
  document_type: "MRI_REPORT",
  provider_name: "Harbor Imaging",
  document_date: "2026-01-05",
  original_filename: "mri-report.pdf",
  mime_type: "application/pdf",
  size_bytes: 20480,
  page_count: 2,
  sha256: "a".repeat(64),
  storage_key: "cases/x/documents/a.pdf",
  status: "extracted",
  extraction_note: null,
  uploaded_by: "para_7",
  created_at: "2026-01-06T08:00:00",
  pages: [
    { page_number: 1, text: "Patient presented with lumbar pain." },
    { page_number: 2, text: "Impression: disc extrusion at L5-S1 measuring 9 x 10 x 5 mm." },
  ],
};

/** Page-level responses: what the evidence viewer fetches, page by page. */
export const documentPages: Record<number, DocumentPage> = {
  1: {
    page_number: 1,
    text: "Patient presented with lumbar pain.",
    width: 612,
    height: 792,
    extraction_method: "native",
    word_count: 5,
    has_geometry: true,
  },
  2: {
    page_number: 2,
    text: "Impression: disc extrusion at L5-S1 measuring 9 x 10 x 5 mm.",
    width: 612,
    height: 792,
    extraction_method: "native",
    word_count: 11,
    has_geometry: true,
  },
};

export const pageGeometry: PageGeometry = {
  document_id: "doc_1",
  page_number: 2,
  width: 612,
  height: 792,
  extraction_method: "native",
  words: [
    { text: "disc", start: 12, end: 16, bbox: { x: 0.18, y: 0.51, width: 0.05, height: 0.02 } },
    {
      text: "extrusion",
      start: 17,
      end: 26,
      bbox: { x: 0.24, y: 0.51, width: 0.09, height: 0.02 },
    },
    { text: "at", start: 27, end: 29, bbox: { x: 0.34, y: 0.51, width: 0.03, height: 0.02 } },
    { text: "L5-S1", start: 30, end: 35, bbox: { x: 0.38, y: 0.51, width: 0.07, height: 0.02 } },
  ],
};

export const uploadLimits: UploadLimits = {
  max_upload_bytes: 50 * 1024 * 1024,
  allowed_mime_types: [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
  ],
  allowed_extensions: [".docx", ".pdf", ".txt"],
  max_template_bytes: 20 * 1024 * 1024,
  template_mime_types: [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ],
  template_extensions: [".docx"],
};

export const letterTemplate: LetterTemplate = {
  id: "tmpl_1",
  case_id: CASE_ID,
  name: "Firm demand template",
  original_filename: "demand-template.docx",
  sha256: "b".repeat(64),
  structure_sha256: "c".repeat(64),
  size_bytes: 38400,
  block_count: 16,
  slot_names: ["section.liability", "client_full_name"],
  uploaded_by: "attorney_1",
  created_at: "2026-01-04T09:00:00",
};

export const letterTemplateDetail: LetterTemplateDetail = {
  ...letterTemplate,
  slots: [
    {
      name: "client_full_name",
      kind: "inline",
      block_index: 2,
      section_key: null,
      fields: [],
      resolvable: true,
    },
    {
      name: "section.liability",
      kind: "block",
      block_index: 7,
      section_key: "liability",
      fields: [],
      resolvable: true,
    },
  ],
  sections: [
    { key: "liability", title: "LIABILITY", start_index: 6, end_index: 8 },
    { key: "medical_treatment", title: "MEDICAL TREATMENT", start_index: 9, end_index: 12 },
  ],
  header_parts: ["word/header1.xml"],
  footer_parts: ["word/footer1.xml"],
  page_setup: { width: 12240, height: 15840 },
  unknown_slots: [],
};

/** Route table covering everything the case workspace requests. */
export const workspaceRoutes = {
  "/v1/case-summaries": { body: [caseSummary] },
  [`/v1/cases/${CASE_ID}`]: { body: caseRecord },
  [`/v1/cases/${CASE_ID}/claim`]: {
    body: {
      id: "clm_1",
      claim_number: "884120993",
      date_of_loss: "2025-04-12",
      policy_number: "NL-1",
      policy_limit: "50000.00",
      policy_limit_confirmed: true,
      carrier: {
        id: "carr_1",
        name: "Northline Mutual",
        adjuster_name: "J. Okonkwo",
        adjuster_email: null,
        adjuster_phone: null,
        address: null,
      },
    },
  },
  [`/v1/cases/${CASE_ID}/settlement-terms`]: {
    body: {
      id: "stl_1",
      demand_type: "policy_limits",
      demand_amount: null,
      demand_is_policy_limits: true,
      expires_at: "2026-01-29T17:00:00",
      delivery_method: "email",
      conditions: [],
    },
  },
  [`/v1/cases/${CASE_ID}/parties`]: { body: parties },
  [`/v1/cases/${CASE_ID}/bills`]: { body: bills },
  [`/v1/cases/${CASE_ID}/damages`]: { body: damages },
  [`/v1/cases/${CASE_ID}/facts`]: { body: facts },
  [`/v1/cases/${CASE_ID}/demands`]: { body: [demand] },
  [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
  [`/v1/cases/${CASE_ID}/medical-timeline`]: { body: [] },
  [`/v1/cases/${CASE_ID}/vehicles`]: { body: [] },
  [`/v1/cases/${CASE_ID}/accident`]: { status: 404, body: { detail: "no accident record on file" } },
  [`/v1/cases/${CASE_ID}/audit`]: { body: [] },
  [`/v1/cases/${CASE_ID}/templates`]: { body: [letterTemplate] },
  [`/v1/cases/${CASE_ID}/jobs`]: { body: [] },
  "/v1/templates/tmpl_1": { body: letterTemplateDetail },
  "/v1/upload-limits": { body: uploadLimits },
  "/v1/documents/doc_1": { body: documentDetail },
  "/v1/documents/doc_1/pages/1": { body: documentPages[1] },
  "/v1/documents/doc_1/pages/2": { body: documentPages[2] },
  "/v1/documents/doc_1/pages/2/geometry": { body: pageGeometry },
};
