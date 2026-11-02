// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthPanel } from "./AuthPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AuthPanel", () => {
  it("switches between Sign in and Create account modes and submits credentials", async () => {
    const fetchMock = vi.fn(
      async (_url?: RequestInfo | URL) =>
        new Response(
          JSON.stringify({ token: "tok-123", user: { id: 1, email: "user@example.com" } }),
          { status: 201 },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const onAuthenticated = vi.fn();
    render(<AuthPanel onAuthenticated={onAuthenticated} />);

    // Default mode is Sign in; switch to Create account
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" },
    });

    fireEvent.click(screen.getByRole("button", { name: /create account & continue/i }));

    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledWith({
        token: "tok-123",
        user: { id: 1, email: "user@example.com" },
      });
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/register");
  });

  it("displays server error messages in an alert", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: { code: "invalid_credentials", message: "Invalid email or password." },
            }),
            { status: 401 },
          ),
      ),
    );

    render(<AuthPanel onAuthenticated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrongpassword" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in to continue/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Invalid email or password.");
  });
});
