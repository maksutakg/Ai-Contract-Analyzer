// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AnalysisError,
  AuthenticationError,
  analyzeContract,
  checkFile,
  clearStoredToken,
  fetchCurrentUser,
  getStoredToken,
  loginUser,
  registerUser,
  setStoredToken,
} from "./api";

function respond(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

const file = new File(["x"], "s.docx");

beforeEach(() => clearStoredToken());
afterEach(() => {
  clearStoredToken();
  vi.unstubAllGlobals();
});

describe("auth API and token storage", () => {
  it("stores token on registerUser and loginUser", async () => {
    respond(201, { token: "tok-1", user: { id: 1, email: "a@b.com" } });
    const reg = await registerUser("a@b.com", "password123");
    expect(reg.user.email).toBe("a@b.com");
    expect(getStoredToken()).toBe("tok-1");

    respond(200, { token: "tok-2", user: { id: 1, email: "a@b.com" } });
    const login = await loginUser("a@b.com", "password123");
    expect(login.token).toBe("tok-2");
    expect(getStoredToken()).toBe("tok-2");
  });

  it("fetches current user with stored Bearer token and clears token on 401", async () => {
    setStoredToken("valid-token");
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ id: 7, email: "u@b.com" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = await fetchCurrentUser();
    expect(user).toEqual({ id: 7, email: "u@b.com" });
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      headers: { Authorization: "Bearer valid-token" },
    });

    respond(401, { detail: { code: "authentication_required", message: "Expired" } });
    await expect(fetchCurrentUser()).rejects.toBeInstanceOf(AuthenticationError);
    expect(getStoredToken()).toBeNull();
  });
});

describe("analyzeContract", () => {
  it("surfaces the backend's error message", async () => {
    respond(400, { detail: { code: "empty_text", message: "No readable text was found in the uploaded file." } });

    await expect(analyzeContract(file, "", new AbortController().signal)).rejects.toThrow(
      "No readable text was found in the uploaded file.",
    );
  });

  it("clears token and throws AuthenticationError on 401", async () => {
    setStoredToken("expired-tok");
    respond(401, { detail: { code: "authentication_required", message: "Please sign in." } });

    await expect(analyzeContract(file, "", new AbortController().signal)).rejects.toBeInstanceOf(
      AuthenticationError,
    );
    expect(getStoredToken()).toBeNull();
  });

  it("reads FastAPI validation errors", async () => {
    respond(422, { detail: [{ loc: ["body", "contract_type"], msg: "Input should be 'service' or 'lease'" }] });

    await expect(analyzeContract(file, "", new AbortController().signal)).rejects.toThrow("Input should be");
  });

  it("explains an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));

    const error = await analyzeContract(file, "", new AbortController().signal).catch((e) => e);
    expect(error).toBeInstanceOf(AnalysisError);
    expect(error.message).toContain("did not respond");
  });

  it("sends contract_type only when chosen and attaches Authorization header when token is stored", async () => {
    setStoredToken("my-jwt");
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await analyzeContract(file, "", new AbortController().signal);
    await analyzeContract(file, "lease", new AbortController().signal);

    const sent = fetchMock.mock.calls.map(([, init]) => (init.body as FormData).get("contract_type"));
    expect(sent).toEqual([null, "lease"]);
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({ Authorization: "Bearer my-jwt" });
  });
});

describe("checkFile", () => {
  it("accepts pdf and docx, rejects others and oversized files", () => {
    expect(checkFile(new File(["x"], "a.PDF"))).toBeNull();
    expect(checkFile(new File(["x"], "a.txt"))).toContain("PDF and DOCX");
    const big = new File(["x"], "a.docx");
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });
    expect(checkFile(big)).toContain("10 MB");
  });
});
