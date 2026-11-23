/**
 * A live connection (chat, alerts) the server closes as "not allowed" (code 1008: the IP allow-list or a removed
 * membership): the screen says so, with the server's own recovery sentence when it gives one and the general
 * sentence when it does not, and the feed is not retried in a loop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { LiveRefusalNotice } from "@/components/ui/live-refusal-notice";
import { useAlertWebSocket } from "@/hooks/useAlertWebSocket";
import { useWSChat } from "@/hooks/useWSChat";
import { explainRefusal } from "@/lib/liveRefusal";

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((e: { code: number; wasClean: boolean }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  sent: string[] = [];
  constructor(public url: string) {
    FakeSocket.all.push(this);
  }
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  closeWith(code: number, wasClean = true) { this.readyState = 3; this.onclose?.({ code, wasClean }); }
}

const SENTENCE =
  "Bu şirket erişimi IP adresine göre kısıtlıyor ve şu anki adresiniz izin listesinde değil. / This company restricts access by IP address. " +
  "Şirketin sahibi (owner) listeyi izin verilen bir adresten değiştirebilir.";
const refused403 = () => Object.assign(new Error(SENTENCE), { status: 403 });

beforeEach(() => {
  FakeSocket.all = [];
  get.mockReset();
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => vi.unstubAllGlobals());

describe("explainRefusal", () => {
  it("returns the server's own 403 sentence", async () => {
    get.mockRejectedValue(refused403());
    expect(await explainRefusal()).toBe(SENTENCE);
  });

  it("returns nothing when a plain request is not refused (it was not a refusal), or fails some other way", async () => {
    get.mockResolvedValue({ data: {} });
    expect(await explainRefusal()).toBeNull();
    get.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    expect(await explainRefusal()).toBeNull();
  });
});

describe("LiveRefusalNotice", () => {
  it("draws nothing while the connection is fine", () => {
    const { container } = render(<LiveRefusalNotice refusal={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the server's sentence as written", () => {
    render(<LiveRefusalNotice refusal={{ sentence: SENTENCE }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Canlı bağlantı kapatıldı");
    expect(screen.getByText(SENTENCE)).toBeInTheDocument();
  });

  it("shows the general sentence and the recovery steps when the server gave none", () => {
    render(<LiveRefusalNotice refusal={{ sentence: null }} />);
    expect(screen.getByText(/yetkisizlik nedeniyle kapattı/)).toBeInTheDocument();
    expect(screen.getByText(/platform yöneticinizden isteyin/)).toBeInTheDocument();
  });
});

describe("the chat socket", () => {
  it("shows the refusal when the server closes it with 1008, with the server's sentence once asked", async () => {
    get.mockRejectedValue(refused403());
    const { result } = renderHook(() => useWSChat());
    let sending: Promise<void>;
    act(() => {
      sending = result.current.send({ question: "Nakit durumum?" });
    });
    await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
    await act(async () => {
      FakeSocket.all[0].open();
      await sending;
    });
    act(() => FakeSocket.all[0].closeWith(1008));
    expect(result.current.refusal).not.toBeNull();
    await waitFor(() => expect(result.current.refusal?.sentence).toBe(SENTENCE));
  });

  it("asks why when the connect itself is refused (no close code reaches a browser)", async () => {
    get.mockRejectedValue(refused403());
    const { result } = renderHook(() => useWSChat());
    act(() => {
      void result.current.send({ question: "Nakit durumum?" });
    });
    await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
    act(() => FakeSocket.all[0].onerror?.());
    await waitFor(() => expect(result.current.refusal?.sentence).toBe(SENTENCE));
  });
});

describe("the alerts socket", () => {
  it("stops retrying on 1008 and says why instead of connecting again and again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      get.mockRejectedValue(refused403());
      const { result } = renderHook(() => useAlertWebSocket("org1"));
      await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
      act(() => FakeSocket.all[0].open());
      act(() => FakeSocket.all[0].closeWith(1008));
      expect(result.current.refusal).not.toBeNull();
      await waitFor(() => expect(result.current.refusal?.sentence).toBe(SENTENCE));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(120_000);
      });
      expect(FakeSocket.all).toHaveLength(1); // no reconnect, no loop
    } finally {
      vi.useRealTimers();
    }
  });

  it("treats a refused connect (abnormal close, no code) as a refusal when the server refuses a plain request too", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      get.mockRejectedValue(refused403());
      const { result } = renderHook(() => useAlertWebSocket("org1"));
      await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
      act(() => FakeSocket.all[0].closeWith(1006, false));
      await waitFor(() => expect(result.current.refusal?.sentence).toBe(SENTENCE));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(120_000);
      });
      expect(FakeSocket.all).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps its backoff retry when the close was only the network", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      get.mockResolvedValue({ data: {} });
      const { result } = renderHook(() => useAlertWebSocket("org1"));
      await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
      act(() => FakeSocket.all[0].closeWith(1006, false));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(result.current.refusal).toBeNull();
      expect(FakeSocket.all.length).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
