export type ApplicationStatus =
  | "discovered"
  | "drafting"
  | "ready_to_submit"
  | "submitted"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export const STATUSES: ApplicationStatus[] = [
  "discovered",
  "drafting",
  "ready_to_submit",
  "submitted",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
];

export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  discovered: "Discovered",
  drafting: "Drafting",
  ready_to_submit: "Ready",
  submitted: "Submitted",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface Job {
  id: string;
  source: string;
  title: string;
  company: string | null;
  location: string | null;
  url: string;
}

export interface Application {
  id: string;
  status: ApplicationStatus;
  notes: string | null;
  job: Job;
  cv_version_id: string | null;
  keyword_coverage: number | null;
  needs_credentials: boolean;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApplicationEvent {
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ApplicationDetail extends Application {
  cover_letter: string | null;
  has_tailored_cv: boolean;
  prefilled_answers: Record<string, string>;
  missing_fields: string[];
  has_screenshot: boolean;
  events: ApplicationEvent[];
}

export interface CvVersion {
  id: string;
  label: string;
  original_filename: string | null;
  parsed: Record<string, unknown> | null;
  is_default: boolean;
  created_at: string;
}

export interface AnswerBank {
  field: string | null;
  data: Record<string, unknown>;
  updated_at: string | null;
}

export interface NotificationSettings {
  telegram_chat_id: string | null;
  enabled: boolean;
  telegram_configured: boolean;
}

export interface DiscoveryPrefs {
  ksa_only: boolean;
  auto_apply_enabled: boolean;
  auto_apply_threshold: number;
}

export interface JobMatch {
  job: Job;
  relevance_score: number;
  tracked: boolean;
}

export interface PortalCredential {
  id: string;
  host: string;
  username: string;
  label: string | null;
  created_at: string;
  updated_at: string;
  has_secret: boolean;
}

export const PLATFORMS = [
  "greenhouse",
  "lever",
  "ashby",
  "linkedin",
  "bayt",
  "company",
  "company_site",
  "gov_portals",
  "email_alerts",
] as const;
export type Platform = (typeof PLATFORMS)[number];

export interface SavedSearch {
  id: string;
  name: string;
  platform: Platform;
  query: string | null;
  filters: Record<string, unknown>;
  enabled: boolean;
  last_run_at: string | null;
}
