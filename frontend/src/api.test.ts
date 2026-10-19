import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisError, analyzeContract, checkFile } from "./api";

function respond(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

const file = new File(["x"], "s.docx");

afterEach(() => vi.unstubAllGlobals());

describe("analyzeContract", () => {
  it("surfaces the backend's error message", async () => {
    respond(400, { detail: { code: "empty_text", message: "No readable text was found in the uploaded file." } });

    await expect(analyzeContract(file, "", new AbortController().signal)).rejects.toThrow(
      "No readable text was found in the uploaded file.",
    );
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

  it("sends contract_type only when chosen", async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await analyzeContract(file, "", new AbortController().signal);
    await analyzeContract(file, "lease", new AbortController().signal);

    const sent = fetchMock.mock.calls.map(([, init]) => (init.body as FormData).get("contract_type"));
    expect(sent).toEqual([null, "lease"]);
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
