import type { ContractReport, ContractType } from "./types";

export const ANALYZE_URL = "/api/v1/contracts/analyze";
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

export class AnalysisError extends Error {}

export function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Yalnız PDF ve DOCX dosyaları incelenebilir.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "Dosya 10 MB'tan büyük. Daha küçük bir dosya seçin.";
  }
  return null;
}

export async function analyzeContract(
  file: File,
  contractType: ContractType | "",
  signal: AbortSignal,
): Promise<ContractReport> {
  const body = new FormData();
  body.append("file", file);
  if (contractType) body.append("contract_type", contractType);

  let response: Response;
  try {
    response = await fetch(ANALYZE_URL, { method: "POST", body, signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new AnalysisError(
      "Analiz sunucusuna ulaşılamadı. Sunucunun çalıştığından emin olun (uv run python main.py).",
    );
  }
  if (!response.ok) throw new AnalysisError(await errorMessage(response));
  return (await response.json()) as ContractReport;
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `Analiz tamamlanamadı (HTTP ${response.status}).`;
  try {
    const { detail } = await response.json();
    if (typeof detail?.message === "string") return detail.message;
    // FastAPI validation errors arrive as a list of {msg, loc}.
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  } catch {
    // Non-JSON body (e.g. a proxy error page): the status line is all we have.
  }
  return fallback;
}
