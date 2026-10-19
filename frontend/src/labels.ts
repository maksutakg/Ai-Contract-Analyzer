import type { Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

const CATEGORY_LABEL: Record<string, string> = {
  cash_payment: "Cash payment",
  deposit_forfeiture: "Deposit forfeiture",
  termination: "Termination",
  penalty_clause: "Penalty clause",
  unlawful_entry: "Entry without consent",
  eviction_undertaking: "Eviction undertaking",
  rent_increase: "Rent increase",
  jurisdiction: "Jurisdiction",
  data_protection: "Personal data",
  intellectual_property: "Intellectual property",
  force_majeure: "Force majeure",
  payment_interest: "Late-payment interest",
  liability: "Liability",
  dispute_resolution: "Dispute resolution",
  general_risk: "General risk",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category.replaceAll("_", " ");
}
