/*
  The wire shapes, mirroring backend/app/schemas/scan.py.

  Two of these types carry invariants rather than just data, and the comments say so
  because a future edit that "simplifies" them would quietly undo work the backend
  does deliberately:

    - Assessment has both a standing verdict and the automated one. Neither may hide
      the other, so neither is optional.
    - Finding.decided is true only for PASS and FAIL. NEEDS_REVIEW is an open question,
      not a result, and must never be rendered as a settled outcome.
*/

export type FindingStatus = "PASS" | "FAIL" | "NEEDS_REVIEW" | "NA";
export type Verdict = "COMPLIANT" | "NON_COMPLIANT" | "INCONCLUSIVE";
export type Severity = "CRITICAL" | "MAJOR" | "MINOR";

export interface Evidence {
  located: boolean;
  field_key: string | null;
  raw_text: string | null;
  confidence: number | null;
  bbox: [number, number, number, number] | null;
  image_id: string | null;
  note: string | null;
}

export interface Override {
  original_status: FindingStatus;
  reason: string | null;
  overridden_by_id: string | null;
  overridden_at: string | null;
}

export interface Finding {
  rule_id: string;
  title: string;
  citation: string;
  status: FindingStatus;
  severity: Severity;
  message: string;
  remediation: string | null;
  detail: Record<string, unknown>;
  evidence: Evidence;
  /** True only for PASS and FAIL. Never render an undecided finding as a result. */
  decided: boolean;
  override: Override | null;
}

export interface Assessment {
  /** Where the record stands now, after any officer overrides. */
  verdict: Verdict;
  score: number | null;
  /** What the software decided, before a human touched it. Immutable. */
  automated_verdict: Verdict;
  automated_score: number | null;
  rules_decided: number;
  rules_applicable: number;
  failed: number;
  needs_review: number;
  overridden: number;
  exemption_id: string | null;
}

export interface Calibration {
  /** No millimetre figure anywhere means anything unless this is true. */
  calibrated: boolean;
  source: string;
  mm_per_px: number | null;
  confidence: number;
  detail: string;
  pdp_area_cm2: number | null;
  panel_method: string;
}

export interface ExtractedField {
  field_key: string;
  raw_text: string | null;
  parsed: Record<string, unknown> | null;
  confidence: number;
  bbox: [number, number, number, number] | null;
  image_id: string | null;
  glyph_height_mm: number | null;
  glyph_width_mm: number | null;
}

export interface ScanImage {
  image_id: string;
  kind: string;
  filename: string | null;
  width: number;
  height: number;
  blocks_read: number;
}

export interface ScanRevision {
  revision: number;
  reason: string;
  detail: string | null;
  superseded_at: string | null;
  superseded_by_id: string | null;
  /** The whole prior ScanResult, including any officer decisions of that reading. */
  snapshot: ScanResult;
}

export interface Retention {
  /**
   * The officer's answer to "is a case still open on this scan?".
   * null  � not answered. Never auto-deleted; silence is not consent.
   * true  � a case is open. Never auto-deleted, at any age.
   * false � no case is open. Auto-deletable once the window has run from `decided_at`.
   */
  case_open: boolean | null;
  decided_at: string | null;
  decided_by_id: string | null;
  /** Only ever true when case_open is false and the retention window has elapsed. */
  eligible_for_deletion: boolean;
  /** The date it becomes eligible; null unless case_open is false. */
  eligible_on: string | null;
  /** A sentence to show the officer. */
  summary: string;
}

export interface ScanResult {
  scan_id: string;
  product_id: string | null;
  product_name: string | null;
  channel: string;
  scan_date: string;
  created_at: string | null;
  ruleset_version: string;
  extractor_version: string;
  /** Above 1 means the photographs were edited and the scan re-judged. */
  revision: number;
  retention: Retention;
  /** Set once the scan has been soft-deleted. The row, its images and its findings
   *  stay in the database; it is only withheld from the working repository. */
  deleted_at: string | null;
  deleted_reason: string | null;
  assessment: Assessment;
  calibration: Calibration;
  findings: Finding[];
  fields: ExtractedField[];
  images: ScanImage[];
  /** What the scan could not do, in the officer's words. Never hide these. */
  notes: string[];
}

export interface ScanSummary {
  scan_id: string;
  product_id: string;
  product_name: string | null;
  scan_date: string;
  created_at: string | null;
  verdict: Verdict;
  score: number | null;
  rules_decided: number;
  rules_applicable: number;
  failed: number;
  needs_review: number;
  ruleset_version: string | null;
  /** The retention answer, surfaced so the repository can show what is retained. */
  case_open: boolean | null;
  eligible_for_deletion: boolean;
  /** True for a soft-deleted scan. Only ever present when the caller asked to
   *  include deleted scans in the listing. */
  deleted: boolean;
}

export interface ScanPage {
  total: number;
  limit: number;
  offset: number;
  scans: ScanSummary[];
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  jurisdiction: string | null;
  is_active: boolean;
}

export interface Health {
  status: string;
  environment: string;
  ocr_engine: string;
  rulesets: string[];
  database: string;
  database_detail: string;
}

// --------------------------------------------------------------------- dashboard

export interface DashboardTotals {
  scans: number;
  compliant: number;
  non_compliant: number;
  inconclusive: number;
  concluded: number;
  /** Null when no scan in the window concluded. Never render this as 0%. */
  compliance_rate: number | null;
  open_reviews: number;
  officer_decisions: number;
}

export interface TopViolation {
  rule_id: string;
  title: string;
  citation: string;
  severity: Severity;
  count: number;
}

export interface CategoryRow {
  category: string;
  scans: number;
  compliant: number;
  non_compliant: number;
  inconclusive: number;
  compliance_rate: number | null;
}

export interface CalibrationSummary {
  scans: number;
  calibrated: number;
  uncalibrated: number;
  calibrated_rate: number | null;
}

export interface DayRow {
  date: string;
  scans: number;
  compliant: number;
  non_compliant: number;
  inconclusive: number;
}

export interface Dashboard {
  window: { since: string; until: string; days: number };
  totals: DashboardTotals;
  top_violations: TopViolation[];
  by_category: CategoryRow[];
  calibration: CalibrationSummary;
  daily: DayRow[];
}
