/**
 * The IP allow-list card: who may reach the company at all.
 *
 * The owner edits it; an admin reads it. A list that would lock people out is refused by the server with a
 * preview, and nothing is saved until the owner confirms that preview explicitly. The server's refusals are
 * shown in its own words.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useSession } from "next-auth/react";

const { api } = vi.hoisted(() => ({ api: { getIpAllowList: vi.fn(), saveIpAllowList: vi.fn() } }));
vi.mock("@/lib/api/security", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api/security")>("@/lib/api/security")),
  ...api,
}));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { IpAllowListCard } from "@/components/org/IpAllowListCard";
import { renderWithQuery } from "./dashboard-mocks";

const as = (role: string) =>
  vi.mocked(useSession).mockReturnValue({
    data: { user: { id: "u", email: "o@x.com", role, orgId: "o" }, accessToken: "tok" },
    status: "authenticated",
  } as unknown as ReturnType<typeof useSession>);

const off = { enabled: false, cidrs: [] as string[], caller_ip: "198.51.100.7" };
const refused = (status: number, message: string) => Object.assign(new Error(message), { status });
const LOCKOUT =
  "Kaydedilmedi. Siz kilitlenirsiniz (şu anki adresiniz 198.51.100.7 listede değil) / You would be locked out; " +
  "adresi bilinmeyen üyeler / members with no known address: 2. Şirketin sahibi (owner) listeyi izin verilen bir adresten değiştirebilir. " +
  "Yine de kaydetmek için confirm_lockout=true gönderin. / Not saved. Send confirm_lockout=true to save anyway.";

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  as("owner");
});

async function addEntry(text: string) {
  fireEvent.change(await screen.findByLabelText("Adres veya ağ (CIDR)"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Listeye ekle" }));
}

describe("states", () => {
  it("says the list is off, empty, and which address the server sees for the caller", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    expect(await screen.findByText(/Durum: kapalı/)).toBeInTheDocument();
    expect(screen.getByText("Listede adres yok.")).toBeInTheDocument();
    expect(screen.getByText("Sunucunun sizin için gördüğü adres: 198.51.100.7")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "IP izin listesini etkinleştir" })).not.toBeChecked();
  });

  it("says so when the list could not be read, never a blank", async () => {
    api.getIpAllowList.mockRejectedValue(refused(500, "boom"));
    renderWithQuery(<IpAllowListCard />);
    expect(await screen.findByText("IP izin listesi verisi alınamadı.")).toBeInTheDocument();
  });

  it("says who may see it when the server answers 403", async () => {
    api.getIpAllowList.mockRejectedValue(refused(403, "Sadece admin ve owner erişebilir"));
    renderWithQuery(<IpAllowListCard />);
    expect(await screen.findByText(/yalnızca şirketin sahibi ve yöneticileri görebilir/)).toBeInTheDocument();
  });

  it("says the address could not be read when the server did not send it", async () => {
    api.getIpAllowList.mockResolvedValue({ enabled: false, cidrs: [] });
    renderWithQuery(<IpAllowListCard />);
    expect(await screen.findByText("Sunucunun sizin için gördüğü adres alınamadı.")).toBeInTheDocument();
  });
});

describe("role gating", () => {
  it("shows an admin the state and the list and no control to change them", async () => {
    as("admin");
    api.getIpAllowList.mockResolvedValue({ enabled: true, cidrs: ["203.0.113.5/32"], caller_ip: "203.0.113.5" });
    renderWithQuery(<IpAllowListCard />);
    expect(await screen.findByText("203.0.113.5/32")).toBeInTheDocument();
    expect(screen.getByText(/Durum: açık/)).toBeInTheDocument();
    expect(screen.getByText(/yalnızca şirketin sahibi değiştirebilir/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kaydet" })).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByLabelText("Adres veya ağ (CIDR)")).toBeNull();
    expect(screen.queryByRole("button", { name: /listeden kaldır/ })).toBeNull();
  });

  it.each(["cfo", "smmm", "analyst", "viewer"])("offers %s no control either", async (role) => {
    as(role);
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    await screen.findByText(/Durum: kapalı/);
    expect(screen.queryByRole("button", { name: "Kaydet" })).toBeNull();
  });
});

describe("editing", () => {
  it("validates an entry on the client the way the server does, and keeps nothing invalid", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    await addEntry("10.0.0.5/8");
    expect(await screen.findByText("Geçersiz CIDR biçimi: '10.0.0.5/8'")).toBeInTheDocument();
    await addEntry("0.0.0.0/0");
    expect(await screen.findByText(/herkese izin verir/)).toBeInTheDocument();
    await addEntry("::ffff:10.0.0.1");
    expect(await screen.findByText(/IPv4 olarak yazın/)).toBeInTheDocument();
    expect(screen.getByText("Listede adres yok.")).toBeInTheDocument();
    expect(api.saveIpAllowList).not.toHaveBeenCalled();
  });

  it("adds a bare address as /32, refuses a duplicate, and removes an entry", async () => {
    api.getIpAllowList.mockResolvedValue({ enabled: false, cidrs: ["10.0.0.0/8"], caller_ip: "198.51.100.7" });
    renderWithQuery(<IpAllowListCard />);
    await addEntry("203.0.113.5");
    expect(await screen.findByText("203.0.113.5/32")).toBeInTheDocument();
    expect(screen.getByText("Kaydedilmemiş değişiklikler var.")).toBeInTheDocument();
    await addEntry("203.0.113.5");
    expect(await screen.findByText("Bu adres listede zaten var: 203.0.113.5/32")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "10.0.0.0/8 adresini listeden kaldır" }));
    expect(screen.queryByText("10.0.0.0/8")).toBeNull();
  });

  it("adds the caller's own address in one click, and stops offering it once it is on the list", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Adresimi ekle (198.51.100.7)" }));
    expect(await screen.findByText("198.51.100.7/32")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Adresimi ekle/ })).toBeNull();
  });

  it("does not let an empty list be switched on", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    fireEvent.click(await screen.findByRole("switch", { name: "IP izin listesini etkinleştir" }));
    expect(screen.getByText("Etkin bir liste en az bir adres içermeli.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });

  it("saves, shows the saved list and says it was recorded", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    api.saveIpAllowList.mockResolvedValue({ enabled: true, cidrs: ["198.51.100.7/32"] });
    renderWithQuery(<IpAllowListCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Adresimi ekle (198.51.100.7)" }));
    fireEvent.click(screen.getByRole("switch", { name: "IP izin listesini etkinleştir" }));
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(api.saveIpAllowList).toHaveBeenCalledWith({ cidrs: ["198.51.100.7/32"], enabled: true, confirmLockout: false }),
    );
    expect(await screen.findByText(/karar kaydına yazıldı/)).toBeInTheDocument();
    expect(screen.getByText(/Durum: açık/)).toBeInTheDocument();
    expect(screen.getByText("Sunucunun sizin için gördüğü adres: 198.51.100.7")).toBeInTheDocument();
  });
});

describe("the lock-out confirmation", () => {
  async function draftThatLocksOut() {
    api.getIpAllowList.mockResolvedValue(off);
    renderWithQuery(<IpAllowListCard />);
    await addEntry("203.0.113.5");
    fireEvent.click(screen.getByRole("switch", { name: "IP izin listesini etkinleştir" }));
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    return await screen.findByText("Kaydedilmedi: erişim kesilebilir");
  }

  it("shows who would be locked out as the server wrote it, and saves nothing until confirmed", async () => {
    api.saveIpAllowList.mockRejectedValue(refused(409, LOCKOUT));
    await draftThatLocksOut();
    const box = screen.getByRole("alert");
    expect(within(box).getByText(/Siz kilitlenirsiniz \(şu anki adresiniz 198\.51\.100\.7 listede değil\)/)).toBeInTheDocument();
    expect(within(box).getByText(/members with no known address: 2/)).toBeInTheDocument();
    expect(within(box).getByText(/Şirketin sahibi \(owner\) listeyi izin verilen bir adresten değiştirebilir/)).toBeInTheDocument();
    // the instruction to API clients is not a sentence for a person
    expect(screen.queryByText(/confirm_lockout/)).toBeNull();
    expect(api.saveIpAllowList).toHaveBeenCalledTimes(1);
    expect(api.saveIpAllowList).toHaveBeenLastCalledWith({ cidrs: ["203.0.113.5/32"], enabled: true, confirmLockout: false });
    // the draft cannot move while the preview is open: what is confirmed is what was previewed
    expect(screen.getByRole("switch", { name: "IP izin listesini etkinleştir" })).toBeDisabled();
    expect(screen.getByLabelText("Adres veya ağ (CIDR)")).toBeDisabled();
  });

  it("saves with confirm_lockout only after the explicit confirmation", async () => {
    api.saveIpAllowList.mockRejectedValueOnce(refused(409, LOCKOUT)).mockResolvedValueOnce({ enabled: true, cidrs: ["203.0.113.5/32"] });
    await draftThatLocksOut();
    fireEvent.click(screen.getByRole("button", { name: "Anladım, yine de kaydet" }));
    await waitFor(() => expect(api.saveIpAllowList).toHaveBeenCalledTimes(2));
    expect(api.saveIpAllowList).toHaveBeenLastCalledWith({ cidrs: ["203.0.113.5/32"], enabled: true, confirmLockout: true });
    expect(await screen.findByText(/karar kaydına yazıldı/)).toBeInTheDocument();
    expect(screen.queryByText("Kaydedilmedi: erişim kesilebilir")).toBeNull();
  });

  it("changes nothing when the owner cancels", async () => {
    api.saveIpAllowList.mockRejectedValue(refused(409, LOCKOUT));
    await draftThatLocksOut();
    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));
    expect(screen.queryByText("Kaydedilmedi: erişim kesilebilir")).toBeNull();
    expect(api.saveIpAllowList).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Durum: kapalı/)).toBeInTheDocument(); // the stored state is untouched
  });
});

describe("the server's refusals, as written", () => {
  it("shows the proxy refusal verbatim and is not the lock-out confirmation", async () => {
    const proxy =
      "İstek bir ters vekil (reverse proxy) üzerinden geliyor ama TRUSTED_PROXY_COUNT / TRUSTED_PROXY_CIDRS ayarlı değil: istemci adresi güvenilir biçimde bilinemez.";
    api.getIpAllowList.mockResolvedValue(off);
    api.saveIpAllowList.mockRejectedValue(refused(409, proxy));
    renderWithQuery(<IpAllowListCard />);
    await addEntry("198.51.100.7");
    fireEvent.click(screen.getByRole("switch", { name: "IP izin listesini etkinleştir" }));
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByText(proxy)).toBeInTheDocument();
    expect(screen.getByText("Sunucu kaydı reddetti")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anladım, yine de kaydet" })).toBeNull();
  });

  it("says the server could not be reached when there is no answer at all", async () => {
    api.getIpAllowList.mockResolvedValue(off);
    api.saveIpAllowList.mockRejectedValue(new Error("Network Error"));
    renderWithQuery(<IpAllowListCard />);
    await addEntry("198.51.100.7");
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByText("Kaydedilemedi: sunucuya ulaşılamadı.")).toBeInTheDocument();
  });
});
