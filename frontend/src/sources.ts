// What Yargı MCP can reach. Bedesten counts were measured on 2026-10-14 as total_records per
// court type; the GİB figure is the MCP tool's own description. Re-measure before changing them.
export const MEASURED_AT = "14 October 2026";

export interface McpSource {
  // Value the backend puts in YargiDecision.court; absent for sources the analysis never queries.
  court?: string;
  name: string;
  detail: string;
  searched: boolean;
}

export const MCP_SOURCES: McpSource[] = [
  { court: "Yargıtay", name: "Court of Cassation (Yargıtay)", detail: "10,016,220 decisions", searched: true },
  { court: "Danıştay", name: "Council of State (Danıştay)", detail: "420,158 decisions", searched: true },
  { court: "Bölge Adliye Mahkemesi", name: "Regional courts of appeal", detail: "248,732 decisions", searched: true },
  { court: "Yerel mahkeme", name: "First-instance courts", detail: "613,732 decisions", searched: true },
  { court: "KVKK", name: "Data Protection Authority (KVKK)", detail: "Board decisions and summaries", searched: true },
  { court: "UYAP Emsal", name: "UYAP precedent archive", detail: "Selected precedent decisions", searched: true },
  { name: "Constitutional Court", detail: "Norm review and individual applications", searched: false },
  { name: "Competition Authority", detail: "Competition law decisions", searched: false },
  { name: "Public Procurement Authority", detail: "Procurement dispute decisions", searched: false },
  { name: "Revenue Administration (GİB)", detail: "18,000+ tax rulings", searched: false },
  {
    name: "Five more authorities",
    detail: "Court of Accounts, Court of Jurisdictional Disputes, BDDK, BTK, Insurance Arbitration",
    searched: false,
  },
];

export const SEARCHED_SOURCES = MCP_SOURCES.filter((source) => source.searched);

export function courtName(court: string | null): string {
  return MCP_SOURCES.find((source) => source.court === court)?.name ?? court ?? "Other source";
}
