/**
 * Drives the REAL location dialog against a REAL running backend (bundled location database).
 * Start the backend first:  python -m uvicorn leadx.api:app --port 8000   (NEXT_PUBLIC_API_URL defaults to :8000)
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GBAddLocationModal, { type GLocation } from "@/components/GBAddLocationModal";

function setup(initialValue?: GLocation) {
  const onSave = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={client}>
      <GBAddLocationModal open initialValue={initialValue} onCancel={() => {}} onSave={onSave} />
    </QueryClientProvider>,
  );
  return { onSave, user };
}

const box = (label: string) => screen.getByRole("combobox", { name: new RegExp(label, "i") }) as HTMLInputElement;
const optionTexts = () => screen.queryAllByRole("option").map((o) => o.textContent ?? "");

async function choose(user: ReturnType<typeof userEvent.setup>, label: string, typed: string, optionName: RegExp | string) {
  const input = box(label);
  await user.click(input);
  await user.clear(input);
  await user.type(input, typed);
  const opt = await screen.findByRole("option", { name: optionName });
  await user.click(opt);
}

describe("cascading location picker (real backend data)", () => {
  it("offers every country, and State/City/ZIP stay locked until the level above is chosen", async () => {
    const { user } = setup();
    await waitFor(() => expect(box("Country").disabled).toBe(false));
    expect(box("State").disabled).toBe(true);
    expect(box("City").disabled).toBe(true);
    expect(box("Zip").disabled).toBe(true);

    await user.click(box("Country"));
    await waitFor(() => expect(optionTexts().length).toBeGreaterThan(100));   // list is capped for rendering, search finds the rest
    for (const name of ["Zimbabwe", "Vietnam", "Mauritius", "Bhutan"]) {      // last-in-alphabet + small countries are present
      await user.clear(box("Country"));
      await user.type(box("Country"), name);
      expect(await screen.findByRole("option", { name })).toBeTruthy();
    }
  });

  it("India -> Karnataka -> Bengaluru -> ZIPs that belong only to Bengaluru, then saves ids + names", async () => {
    const { user, onSave } = setup();
    await choose(user, "Country", "India", "India");
    await waitFor(() => expect(box("State").disabled).toBe(false));

    // State list = India's states only
    await user.click(box("State"));
    await user.clear(box("State"));
    await user.type(box("State"), "Gujarat");
    expect(await screen.findByRole("option", { name: "Gujarat" })).toBeTruthy();
    await user.clear(box("State"));
    await user.type(box("State"), "California");
    expect(screen.queryByRole("option", { name: "California" })).toBeNull();     // a US state must not appear for India
    await user.clear(box("State"));
    await user.type(box("State"), "Karnataka");
    await user.click(await screen.findByRole("option", { name: "Karnataka" }));

    // City list = Karnataka's cities only
    await waitFor(() => expect(box("City").disabled).toBe(false));
    await user.click(box("City"));
    await user.clear(box("City"));
    await user.type(box("City"), "Surat");
    await waitFor(() => expect(screen.queryByRole("option", { name: "Surat" })).toBeNull()); // Surat is in Gujarat
    await user.clear(box("City"));
    await user.type(box("City"), "Bengaluru");
    await user.click(await screen.findByRole("option", { name: /^Bengaluru$/ }));

    // ZIP list = Bengaluru's PIN codes only
    await waitFor(() => expect(box("Zip").disabled).toBe(false));
    await user.click(box("Zip"));
    await user.type(box("Zip"), "5600");
    const zipOpt = await screen.findByRole("option", { name: /^560001/ });
    expect(zipOpt).toBeTruthy();
    expect(optionTexts().every((t) => t === "All zip codes" || t.startsWith("560"))).toBe(true);
    await user.clear(box("Zip"));
    await user.type(box("Zip"), "400001");                                       // a Mumbai PIN
    await waitFor(() => expect(screen.queryByRole("option", { name: /^400001/ })).toBeNull());
    await user.clear(box("Zip"));
    await user.type(box("Zip"), "560001");
    await user.click(await screen.findByRole("option", { name: /^560001/ }));

    await user.click(screen.getByRole("button", { name: /Ok/ }));
    expect(onSave).toHaveBeenCalledTimes(1);
    const saved = onSave.mock.calls[0][0] as GLocation[];
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ country: "India", countryCode: "IN", state: "Karnataka", city: "Bengaluru", postalCode: "560001" });
    expect(typeof saved[0].stateId).toBe("number");
    expect(typeof saved[0].cityId).toBe("number");
  });

  it("changing the country clears the lower levels", async () => {
    const { user } = setup();
    await choose(user, "Country", "India", "India");
    await waitFor(() => expect(box("State").disabled).toBe(false));
    await choose(user, "State", "Karnataka", "Karnataka");
    expect(box("State").value).toBe("Karnataka");
    await choose(user, "Country", "Germany", "Germany");
    await waitFor(() => expect(box("State").value).toBe("All states"));
    expect(box("City").disabled).toBe(true);
    await user.click(box("State"));
    await user.type(box("State"), "Bavaria");
    expect(await screen.findByRole("option", { name: "Bavaria" })).toBeTruthy();
  });

  it("leaving State/City/ZIP on 'All' saves a whole-country location with its country code", async () => {
    const { user, onSave } = setup();
    await choose(user, "Country", "Italy", "Italy");
    await user.click(screen.getByRole("button", { name: /Ok/ }));
    expect(onSave.mock.calls[0][0][0]).toMatchObject({ country: "Italy", countryCode: "IT", state: "All states", city: "All cities", postalCode: "All zip codes" });
  });

  it("several states can be added at once, one location each", async () => {
    const { user, onSave } = setup();
    await choose(user, "Country", "India", "India");
    const filter = await screen.findByPlaceholderText("Filter states…");
    await user.type(filter, "Gujarat");
    await user.click(await screen.findByLabelText("Gujarat"));
    await user.clear(filter);
    await user.type(filter, "Kerala");
    await user.click(await screen.findByLabelText("Kerala"));
    await user.click(screen.getByRole("button", { name: /Ok/ }));
    const saved = onSave.mock.calls[0][0] as GLocation[];
    expect(saved.map((s) => s.state).sort()).toEqual(["Gujarat", "Kerala"]);
    expect(saved.every((s) => s.country === "India" && s.city === "All cities")).toBe(true);
  });

  it("re-opens a saved location without ids (e.g. from a file) by matching names", async () => {
    const { user, onSave } = setup({ id: "x", country: "India", state: "Gujarat", city: "Surat", postalCode: "All zip codes", selected: true });
    await waitFor(() => expect(box("City").value).toBe("Surat"), { timeout: 10000 });
    expect(box("State").value).toBe("Gujarat");
    await user.click(screen.getByRole("button", { name: /Ok/ }));
    expect(onSave.mock.calls[0][0][0]).toMatchObject({ country: "India", countryCode: "IN", state: "Gujarat", city: "Surat" });
  });
});
