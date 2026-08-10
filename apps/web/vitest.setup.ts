import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom implements neither of these, and both run in normal component paths.
if (!("createObjectURL" in URL)) {
  Object.defineProperty(URL, "createObjectURL", { value: () => "blob:mock", writable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => undefined, writable: true });
}
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => undefined);

// next/navigation is not available in a bare jsdom environment.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useParams: () => ({}),
}));
