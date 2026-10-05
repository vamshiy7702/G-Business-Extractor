/**
 * The exact workflow from the bug report, on the real page + real backend:
 * add category -> add location (cascading dialog) -> Get data -> data must appear.
 * (The backend used here simulates the OpenStreetMap servers; see the backend test-suite for that simulation.)
 */
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MainExtractor from "@/app/page";

class FakeEventSource { addEventListener() {} close() {} }
(globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;   // polling covers live updates in tests

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("lead-extractor-gbusiness-settings", JSON.stringify({ autoExport: false, extractEmails: false, resultsPerTile: 25, maxPlaces: 50 }));
});

async function pick(user: ReturnType<typeof userEvent.setup>, label: string, typed: string, name: RegExp | string) {
  const input = screen.getByRole("combobox", { name: new RegExp(label, "i") });
  await user.click(input);
  await user.clear(input);
  await user.type(input, typed);
  await user.click(await screen.findByRole("option", { name }));
}

describe("Get data workflow", () => {
  it("creates a task from the selected category + location and extracts data (no duplicates on a second click)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const { container } = render(<QueryClientProvider client={client}><MainExtractor /></QueryClientProvider>);

    // category
    await user.click(screen.getByRole("button", { name: "Add Category" }));
    await user.type(await screen.findByPlaceholderText("e.g. dentist"), "hotel");
    await user.click(screen.getByRole("button", { name: /Ok/ }));

    // location through the cascading dialog
    await user.click(screen.getByRole("button", { name: "Add Location" }));
    await pick(user, "Country", "India", "India");
    await waitFor(() => expect((screen.getByRole("combobox", { name: /State/i }) as HTMLInputElement).disabled).toBe(false));
    await pick(user, "State", "Karnataka", "Karnataka");
    await waitFor(() => expect((screen.getByRole("combobox", { name: /City/i }) as HTMLInputElement).disabled).toBe(false));
    await pick(user, "City", "Bengaluru", /^Bengaluru$/);
    await user.click(screen.getByRole("button", { name: /Ok/ }));
    expect(await screen.findByText("India, Karnataka, Bengaluru, All zip codes")).toBeTruthy();

    // run
    await user.click(screen.getByRole("button", { name: /Get data/ }));
    await waitFor(() => expect(container.querySelector(".gb-st-done")).not.toBeNull(), { timeout: 15000 });

    const taskTable = container.querySelector(".gb-task-table") as HTMLElement;
    const rows = within(taskTable).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    const cells = within(rows[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[1]).toBe("hotel");
    expect(cells[6]).toBe("done");
    expect(Number(cells[7])).toBeGreaterThan(0);                                   // data WAS extracted
    expect((await screen.findAllByText(/Test Hotel/)).length).toBeGreaterThan(0);  // and is shown in the results grid

    // second click must not create a duplicate task
    await user.click(screen.getByRole("button", { name: /Get data/ }));
    expect(await screen.findByText(/already existed/)).toBeTruthy();
    expect(within(taskTable).getAllByRole("row").slice(1)).toHaveLength(1);
  });

  it("explains instead of silently failing when 'All countries' is selected", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><MainExtractor /></QueryClientProvider>);
    await user.click(screen.getByRole("button", { name: "Add Category" }));
    await user.type(await screen.findByPlaceholderText("e.g. dentist"), "hotel");
    await user.click(screen.getByRole("button", { name: /Ok/ }));
    await user.click(screen.getByRole("button", { name: "Add Location" }));
    await user.click(screen.getByRole("button", { name: /Ok/ }));                     // leave everything on "All"
    await user.click(screen.getByRole("button", { name: /Get data/ }));
    expect(await screen.findByText(/cannot be searched as one area/)).toBeTruthy();
  });
});
