export type Priority = "daily" | "gaming" | "camera" | "battery";
export type OS = "all" | "Android" | "iOS" | "HarmonyOS";
export type SortOrder =
  | "recommended"
  | "newest"
  | "match"
  | "price_asc"
  | "price_desc";
export type PurchaseMode = "new" | "used";

export interface Preferences {
  budget_min: number;
  budget_max: number | null;
  brands: string[];
  os: OS;
  priorities: Priority[];
  compact: boolean;
  min_storage: number;
  include_history: boolean;
  query: string;
  sort: SortOrder;
  purchase_mode: PurchaseMode;
}

export interface QualityIssue {
  field: string;
  code: string;
  severity: string;
  message: string;
}

export interface FieldSource {
  origin: string;
  source_url?: string | null;
  fetched_at?: string | null;
}

export interface Phone {
  id: string;
  name: string;
  brand: string;
  family_key: string;
  price: number | null;
  ram_gb: number | null;
  storage_gb: number | null;
  soc: string | null;
  battery_mah: number | null;
  charging_w: number | null;
  camera_mp: number | null;
  display_inches: number | null;
  refresh_hz: number | null;
  weight_g: number | null;
  thickness_mm: number | null;
  release_date: string | null;
  release_year?: number | null;
  release_month?: number | null;
  release_precision?: "day" | "month" | "year" | null;
  os: string | null;
  nfc: boolean | null;
  five_g: boolean | null;
  waterproof: string | null;
  image_url: string | null;
  source_url: string | null;
  fetched_at: string | null;
  availability: "listed" | "historical" | "unknown" | "announced";
  origin: "zol" | "legacy" | "official";
  platform?: string | null;
  price_from?: number | null;
  new_from_source?: boolean;
  current_source?: boolean;
  new_release_catalog_url?: string | null;
  discovery_reasons?: string[];
  discovery_codes?: string[];
  catalogue_reasons?: string[];
  catalogue_codes?: string[];
  catalogue_status?: string;
  catalogue_variant_count?: number;
  discovery_status?: string;
  quality_score: number;
  issues?: QualityIssue[];
  specs?: Record<string, unknown>;
  field_sources?: Record<string, FieldSource>;
  specs_sources?: Record<string, FieldSource>;
  os_family?: string | null;
  cleaning_version?: string;
  score?: number;
  recommendation_score?: number;
  ranking_breakdown?: {
    usage: number;
    value: number;
    recency: number;
    brand: number;
    weights: Record<string, number>;
  };
  ranking_reasons?: string[];
  reasons?: string[];
  tradeoffs?: string[];
  metrics?: Record<string, unknown>;
  budget_warning?: string | null;
  chat_warnings?: string[];
  score_applicable?: boolean;
  recommendation_eligible?: boolean;
}

export interface Meta {
  brands: string[];
  summary: Record<string, unknown>;
  priorities: { id: Priority; label: string }[];
  model: string;
  api_configured: boolean;
}

export interface Recommendations {
  phones: Phone[];
  total: number;
  coverage: {
    records?: number;
    current_records?: number;
    unknown_price?: number;
    returned?: number;
    excluded?: Record<string, number>;
    budget_suggestion?: number | null;
  };
  discovery?: { phones: Phone[]; total: number; returned: number };
  catalogue?: { phones: Phone[]; total: number; returned: number };
  updated_at: string | null;
}

export interface SyncStatus {
  state: "idle" | "running" | "completed" | "failed";
  stage?: string;
  discovered?: number;
  completed?: number;
  failed?: number;
  message?: string;
  report?: Record<string, unknown>;
}

export interface QualityReport {
  summary: Record<string, unknown>;
  issues?: (QualityIssue & { name?: string; id?: string })[];
  issue_count?: number;
  report?: Record<string, unknown> | null;
  official_coverage?: Record<
    string,
    {
      catalog_url?: string;
      discovered?: number;
      collected?: number;
      records?: number;
      pending?: number;
      errors?: unknown[];
    }
  > | null;
}
