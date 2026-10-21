import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SignInPage, SignUpPage } from "./AuthPages";

const auth = vi.hoisted(() => ({
  configured: true,
  loading: false,
  session: null as object | null,
  user: null,
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));

describe("authentication pages", () => {
  beforeEach(() => {
    auth.session = null;
    auth.signIn.mockReset();
    auth.signUp.mockReset();
  });

  it("shows the email-verification state after signup", async () => {
    auth.signUp.mockResolvedValue(true);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/sign-up"]}><SignUpPage /></MemoryRouter>);
    await user.type(screen.getByLabelText("Display name"), "Pilot User");
    await user.type(screen.getByLabelText("Email"), "pilot@example.test");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(auth.signUp).toHaveBeenCalledWith("pilot@example.test", "password123", "Pilot User");
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  });

  it("signs in and returns to the requested protected route", async () => {
    auth.signIn.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[{ pathname: "/sign-in", state: { from: "/cases/case-1" } }]}>
        <Routes>
          <Route path="/sign-in" element={<SignInPage />} />
          <Route path="/cases/:caseId" element={<h1>Requested case</h1>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("Email"), "pilot@example.test");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(auth.signIn).toHaveBeenCalledWith("pilot@example.test", "password123");
    expect(await screen.findByRole("heading", { name: "Requested case" })).toBeInTheDocument();
  });
});
