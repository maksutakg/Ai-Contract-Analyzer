import type { AuthSession, AuthUser, ContractReport, ContractType } from "./types";

export const ANALYZE_URL = "/api/v1/contracts/analyze";
export const REGISTER_URL = "/api/v1/auth/register";
export const LOGIN_URL = "/api/v1/auth/login";
export const ME_URL = "/api/v1/auth/me";
export const TOKEN_STORAGE_KEY = "law_rag_auth_token";
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

export class AnalysisError extends Error {}
export class AuthenticationError extends AnalysisError {}

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Ignore storage errors in restricted environments.
  }
}

export function clearStoredToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Ignore storage errors in restricted environments.
  }
}

export function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Only PDF and DOCX files can be analyzed.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "The file is larger than 10 MB. Choose a smaller file.";
  }
  return null;
}

async function submitAuth(url: string, email: string, password: string): Promise<AuthSession> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new AnalysisError(
      "The analysis server did not respond. Make sure it is running (start.cmd).",
    );
  }
  if (!response.ok) {
    throw new AnalysisError(await errorMessage(response, "Authentication failed"));
  }
  const session = (await response.json()) as AuthSession;
  setStoredToken(session.token);
  return session;
}

export async function registerUser(email: string, password: string): Promise<AuthSession> {
  return submitAuth(REGISTER_URL, email, password);
}

export async function loginUser(email: string, password: string): Promise<AuthSession> {
  return submitAuth(LOGIN_URL, email, password);
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const token = getStoredToken();
  if (!token) {
    throw new AuthenticationError("Authentication is required. Please sign in.");
  }
  let response: Response;
  try {
    response = await fetch(ME_URL, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new AnalysisError(
      "The analysis server did not respond. Make sure it is running (start.cmd).",
    );
  }
  if (response.status === 401) {
    clearStoredToken();
    throw new AuthenticationError(await errorMessage(response, "Authentication is required"));
  }
  if (!response.ok) {
    throw new AnalysisError(await errorMessage(response, "Could not verify session"));
  }
  return (await response.json()) as AuthUser;
}

export async function analyzeContract(
  file: File,
  contractType: ContractType | "",
  signal: AbortSignal,
): Promise<ContractReport> {
  const body = new FormData();
  body.append("file", file);
  if (contractType) body.append("contract_type", contractType);

  const token = getStoredToken();
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  let response: Response;
  try {
    response = await fetch(ANALYZE_URL, { method: "POST", body, headers, signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new AnalysisError(
      "The analysis server did not respond. Make sure it is running (start.cmd).",
    );
  }
  if (response.status === 401) {
    clearStoredToken();
    throw new AuthenticationError(await errorMessage(response, "Authentication is required"));
  }
  if (!response.ok) throw new AnalysisError(await errorMessage(response));
  return (await response.json()) as ContractReport;
}

async function errorMessage(
  response: Response,
  prefix = "The analysis could not be completed",
): Promise<string> {
  const fallback = `${prefix} (HTTP ${response.status}).`;
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
