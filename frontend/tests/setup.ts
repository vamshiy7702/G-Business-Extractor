import { randomUUID } from "node:crypto";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

if (!globalThis.crypto?.randomUUID) Object.defineProperty(globalThis, "crypto", { value: { randomUUID }, configurable: true });
afterEach(() => cleanup());      // unmount dialogs between tests (not automatic without vitest globals)
