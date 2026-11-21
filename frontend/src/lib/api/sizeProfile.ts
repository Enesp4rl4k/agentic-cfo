import { apiClient } from "@/lib/api/client";
import type { SizeProfile } from "@/lib/nav-focus";

export type { SizeProfile };

export type SizeOption = { value: string; label: string };

export type SizeAnswers = {
  monthly_outflow_band: string | null;
  headcount_band: string | null;
  has_inhouse_finance: boolean | null;
};

export type SizeSuggestion = {
  profile: SizeProfile;
  /** The answer that decided: volume wins when both are given. */
  decided_by: "volume" | "headcount";
  disagreement: boolean;
};

export type SizeProfileState = SizeAnswers & {
  size_profile: SizeProfile | null;
  focus_mode: boolean;
  suggestion: SizeSuggestion | null;
  options: { monthly_outflow_band: SizeOption[]; headcount_band: SizeOption[] };
  /** Only on the confirm response: whether confirming turned focus mode on or off. */
  focus_mode_changed?: boolean;
};

type Envelope = { data: SizeProfileState; error: string | null };

export async function getSizeProfile(): Promise<SizeProfileState> {
  return (await apiClient.get<Envelope>("/org/me/size-profile")).data.data;
}

export async function saveSizeAnswers(answers: SizeAnswers): Promise<SizeProfileState> {
  return (await apiClient.put<Envelope>("/org/me/size-profile", answers)).data.data;
}

export async function confirmSizeProfile(profile: SizeProfile): Promise<SizeProfileState> {
  return (await apiClient.post<Envelope>("/org/me/size-profile/confirm", { profile })).data.data;
}

/** The one-click undo of the simplified menu. It is a person's own choice of focus mode, so it sticks. */
export async function setFocusMode(on: boolean): Promise<void> {
  await apiClient.patch("/org/me", { focus_mode: on });
}
