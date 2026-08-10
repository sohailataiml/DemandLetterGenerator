/**
 * Types mirroring the FastAPI schemas in apps/api/app/domain/schemas.py.
 *
 * Money is always a string. The backend serializes exact Decimals as strings so
 * no value passes through a float on either side of the wire — the UI formats
 * these for display and never does arithmetic on them.
 */

export type Money = string;

export type UserRole = "admin" | "attorney" | "paralegal" | "reviewer" | "readonly";

export type CaseStatus = "intake" | "treating" | "demand_prep" | "demand_sent" | "closed";

export type DemandStatus = "draft" | "in_review" | "approved" | "sent" | "void";

export type Severity = "BLOCKING" | "WARNING" | "INFO";

export type FactStatus = "PROPOSED" | "VERIFIED" | "REJECTED" | "SUPERSEDED";

export type FactType =
  | "diagnosis"
  | "imaging_finding"
  | "treatment_event"
  | "medical_expense"
  | "future_treatment"
  | "liability"
  | "functional_limitation"
  | "policy_limit"
  | "other";

export type BillStatus = "KNOWN" | "PENDING" | "ESTIMATED";

export type PartyRole =
  | "client"
  | "insured"
  | "driver"
  | "vehicle_owner"
  | "adjuster"
  | "attorney"
  | "witness";

export type SectionSource = "template" | "ai" | "human";

export interface CaseRecord {
  id: string;
  reference: string;
  client_display_name: string;
  status: CaseStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ValidationCounts {
  blocking: number;
  warning: number;
  info: number;
  last_validated_at: string | null;
}

export interface DemandSummary {
  id: string;
  version: number;
  status: DemandStatus;
  letter_date: string;
  locked: boolean;
  approved_at: string | null;
  updated_at: string;
}

export interface CaseSummary {
  id: string;
  reference: string;
  client_display_name: string;
  status: CaseStatus;
  claim_number: string | null;
  date_of_loss: string | null;
  carrier_name: string | null;
  demand: DemandSummary | null;
  validation: ValidationCounts | null;
  updated_at: string;
}

export interface Carrier {
  id: string;
  name: string;
  adjuster_name: string | null;
  adjuster_email: string | null;
  adjuster_phone: string | null;
  address: string | null;
}

export interface Claim {
  id: string;
  claim_number: string;
  date_of_loss: string;
  policy_number: string | null;
  policy_limit: Money | null;
  policy_limit_confirmed: boolean;
  carrier: Carrier | null;
}

export interface Accident {
  id: string;
  occurred_on: string;
  occurred_time: string | null;
  location: string | null;
  description: string | null;
  police_report_number: string | null;
  impact_type: string | null;
}

export interface Vehicle {
  id: string;
  year: number | null;
  make: string | null;
  model: string | null;
  plate: string | null;
  owner_party_id: string | null;
  driver_party_id: string | null;
  is_client_vehicle: boolean;
}

export interface PartyRoleAssignment {
  role: PartyRole;
  relationship_note: string | null;
}

export interface Party {
  id: string;
  case_id: string;
  full_name: string;
  date_of_birth: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  organization: string | null;
  notes: string | null;
  role_assignments: PartyRoleAssignment[];
}

export interface SettlementTerms {
  id: string;
  demand_type: string;
  demand_amount: Money | null;
  demand_is_policy_limits: boolean;
  expires_at: string;
  delivery_method: string;
  conditions: string[];
}

export interface Provider {
  id: string;
  name: string;
  provider_type: string | null;
  address: string | null;
  phone: string | null;
}

export interface TimelineEntry {
  entry_date: string;
  kind: string;
  title: string;
  provider: string | null;
  detail: string | null;
  diagnoses: string[];
  cost: Money | null;
  source_document_ids: string[];
}

export interface Bill {
  id: string;
  provider_name: string;
  description: string | null;
  amount: Money | null;
  status: BillStatus;
  billed_on: string | null;
  provider_id: string | null;
  source_document_id: string | null;
}

export interface PendingBill {
  bill_id: string;
  provider_name: string;
  description: string | null;
}

export interface DamagesLineItem {
  kind: "medical_bill" | "future_treatment" | "damage_claim";
  id: string;
  provider_name?: string | null;
  description?: string | null;
  status?: string;
  category?: string;
  quantity?: number;
  amount: Money | null;
  amount_high?: Money | null;
}

export interface Damages {
  current_medical_expenses: Money;
  pending_bills: PendingBill[];
  estimated_bill_total: Money;
  future_medical_low: Money;
  future_medical_high: Money;
  general_damages: Money;
  other_damages: Money;
  known_claimed_damages_low: Money;
  known_claimed_damages_high: Money;
  line_items: DamagesLineItem[];
}

export interface SourceDocument {
  id: string;
  case_id: string;
  document_type: string;
  provider_name: string | null;
  document_date: string | null;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number;
  sha256: string;
  storage_key: string;
  status: string;
  extraction_note: string | null;
  uploaded_by: string;
  created_at: string;
}

export interface DocumentPage {
  page_number: number;
  text: string;
}

export interface SourceDocumentDetail extends SourceDocument {
  pages: DocumentPage[];
}

export interface FactSource {
  id: string;
  document_id: string;
  page_number: number | null;
  excerpt: string | null;
}

export interface Fact {
  id: string;
  case_id: string;
  fact_type: FactType;
  value: Record<string, unknown>;
  summary: string;
  status: FactStatus;
  confidence: number | null;
  created_at: string;
  revision: number;
  supersedes_id: string | null;
  superseded_by_id: string | null;
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  sources: FactSource[];
}

export interface DemandSection {
  id: string;
  key: string;
  title: string;
  position: number;
  body: string;
  source: SectionSource;
  used_fact_ids: string[];
  edited_by: string | null;
}

export interface ValidationIssue {
  code: string;
  severity: Severity;
  message: string;
  section_key: string | null;
  details: Record<string, unknown>;
}

export interface Demand {
  id: string;
  case_id: string;
  version: number;
  status: DemandStatus;
  letter_date: string;
  template_version: string | null;
  provider_name: string | null;
  model_name: string | null;
  prompt_version: string | null;
  generated_at: string | null;
  docx_sha256: string | null;
  pdf_sha256: string | null;
  approved_by: string | null;
  approved_at: string | null;
  locked: boolean;
  created_by: string;
  sections: DemandSection[];
  issues: ValidationIssue[];
}

export interface AuditEvent {
  id: string;
  created_at: string;
  event: string;
  actor: string;
  actor_role: string | null;
  case_id: string | null;
  demand_id: string | null;
  subject_id: string | null;
  payload: Record<string, unknown>;
}
