import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSessionLlmSelection } from "./useSessionLlmSelection";
import type {
  LlmProfile, ApprovalProfileState, MetadataProfileState, LlmLoadStatus,
  LlmProfileChangeEvent, LlmProfileDeleteResult,
} from "../types";

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : String(cause);

async function responseError(response: Response): Promise<Error> {
  const data = await response.json().catch(() => ({}));
  return new Error(typeof data.detail === "string" ? data.detail : `请求失败 (${response.status})`);
}

/** 写请求可能已到达服务端；编辑器必须先查询确认，不能盲目重试 POST。 */
export class LlmProfileMutationError extends Error {
  constructor(message: string, readonly uncertain: boolean) { super(message); }
}

async function mutateProfile<T>(method: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api/llm/profiles", {
      method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new LlmProfileMutationError("连接中断，保存结果尚未确认，请刷新确认后继续。", true);
  }
  if (!response.ok) {
    const error = await responseError(response);
    // 服务端 5xx 可能发生在持久化之后，保持不确定结果而不是重复提交。
    throw new LlmProfileMutationError(error.message, response.status >= 500);
  }
  try { return await response.json() as T; }
  catch { throw new LlmProfileMutationError("服务端响应不完整，请刷新确认保存结果。", true); }
}

/** 审批和元数据引用共享请求状态，不共享具体值。GET、PUT及广播统一用代际收敛。 */
function useGlobalProfileReference(endpoint: string) {
  const [state, setState] = useState<ApprovalProfileState>({ profile_name: null, model: null, available: false });
  const stateRef = useRef(state);
  const [status, setStatus] = useState<LlmLoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const generation = useRef(0);
  const publish = useCallback((value: ApprovalProfileState) => {
    stateRef.current = value;
    setState(value);
    setStatus("ready");
    setError(null);
  }, []);
  const receive = useCallback((value: ApprovalProfileState) => {
    generation.current++;
    publish(value);
  }, [publish]);
  const refresh = useCallback(async (): Promise<ApprovalProfileState> => {
    if (busyRef.current) return stateRef.current;
    const token = ++generation.current;
    setStatus("loading");
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) throw await responseError(response);
      const value = await response.json() as ApprovalProfileState;
      if (token === generation.current) publish(value);
      return value;
    } catch (cause) {
      if (token === generation.current) { setStatus("error"); setError(errorText(cause)); }
      throw cause;
    }
  }, [endpoint, publish]);
  const select = useCallback(async (profileName: string | null): Promise<ApprovalProfileState> => {
    if (busyRef.current) throw new Error("配置正在保存，请稍候。");
    busyRef.current = true;
    setBusy(true);
    const token = ++generation.current;
    try {
      const response = await fetch(endpoint, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: profileName }),
      });
      if (!response.ok) throw await responseError(response);
      const data = await response.json() as { state: ApprovalProfileState };
      if (token === generation.current) publish(data.state);
      return stateRef.current;
    } catch (cause) {
      if (token === generation.current) setError(errorText(cause));
      throw cause;
    } finally {
      busyRef.current = false;
      setBusy(false);
      // 广播可以先于 PUT 返回；最终 GET 重新取得权威值而非用迟到响应覆盖。
      void refresh().catch(() => {});
    }
  }, [endpoint, publish, refresh]);
  useEffect(() => {
    void refresh().catch(() => {});
    return () => { generation.current++; };
  }, [refresh]);
  return { state, status, error, busy, refresh, select, receive };
}

export function useLlmProfiles(sessionId: string) {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const profilesRef = useRef<LlmProfile[]>([]);
  const hasSnapshot = useRef(false);
  const requestGeneration = useRef(0);
  const mutationRevision = useRef(0);
  const [profilesStatus, setProfilesStatus] = useState<LlmLoadStatus>("loading");
  const [profilesError, setProfilesError] = useState<string | null>(null);
  const [profilesWarning, setProfilesWarning] = useState<string | null>(null);
  const notificationWarningRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [availableClients, setAvailableClients] = useState<string[]>([]);
  const [clientsStatus, setClientsStatus] = useState<LlmLoadStatus>("loading");
  const [clientsError, setClientsError] = useState<string | null>(null);
  const clientsGeneration = useRef(0);
  const approval = useGlobalProfileReference("/api/approval/profile");
  const metadata = useGlobalProfileReference("/api/metadata/profile");
  const selection = useSessionLlmSelection({ sessionId, profiles, profilesStatus });
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  const publishProfiles = useCallback((next: LlmProfile[]) => {
    profilesRef.current = next;
    hasSnapshot.current = true;
    setProfiles(next);
    setProfilesStatus("ready");
    setProfilesError(null);
  }, []);
  const invalidateDirectory = useCallback(() => {
    requestGeneration.current++;
    mutationRevision.current++;
  }, []);
  const refreshProfiles = useCallback(async (): Promise<LlmProfile[]> => {
    const token = ++requestGeneration.current;
    const revision = mutationRevision.current;
    if (!hasSnapshot.current) setProfilesStatus("loading");
    try {
      const response = await fetch("/api/llm/profiles", { cache: "no-store" });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      if (!Array.isArray(data.profiles)) throw new Error("服务端返回的 Profile 列表格式无效");
      if (token !== requestGeneration.current || revision !== mutationRevision.current) {
        throw new DOMException("目录请求已被更新的请求取代", "AbortError");
      }
      publishProfiles(data.profiles as LlmProfile[]);
      setProfilesWarning(notificationWarningRef.current);
      return data.profiles as LlmProfile[];
    } catch (cause) {
      if (token === requestGeneration.current && revision === mutationRevision.current) {
        if (hasSnapshot.current) {
          setProfilesStatus("ready");
          setProfilesWarning(`配置刷新失败，保留已读取的数据：${errorText(cause)}`);
        } else {
          setProfilesStatus("error");
          setProfilesError(errorText(cause));
        }
      }
      throw cause;
    }
  }, [publishProfiles]);
  const refreshClients = useCallback(async (): Promise<void> => {
    const token = ++clientsGeneration.current;
    setClientsStatus("loading");
    try {
      const response = await fetch("/api/llm/clients", { cache: "no-store" });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      if (!Array.isArray(data.clients) || data.clients.some((client: unknown) => typeof client !== "string")) {
        throw new Error("客户端列表格式无效");
      }
      if (token !== clientsGeneration.current) return;
      setAvailableClients(data.clients);
      setClientsStatus("ready");
      setClientsError(null);
    } catch (cause) {
      if (token === clientsGeneration.current) { setClientsStatus("error"); setClientsError(errorText(cause)); }
      throw cause;
    }
  }, []);
  useEffect(() => {
    void refreshProfiles().catch(() => {});
    void refreshClients().catch(() => {});
    return () => { requestGeneration.current++; clientsGeneration.current++; };
  }, [refreshProfiles, refreshClients]);

  const refreshReferences = useCallback(() => {
    void approval.refresh().catch(() => {});
    void metadata.refresh().catch(() => {});
  }, [approval.refresh, metadata.refresh]);
  const afterMutation = useCallback((failures?: string[]) => {
    setError(null);
    notificationWarningRef.current = failures?.length ? "配置已保存，但部分会话通知失败；请刷新受影响页面。" : null;
    setProfilesWarning(notificationWarningRef.current);
    void refreshProfiles().catch(() => {});
    refreshReferences();
  }, [refreshProfiles, refreshReferences]);

  const saveProfile = useCallback(async (originalName: string | null, profile: LlmProfile): Promise<LlmProfile> => {
    invalidateDirectory();
    try {
      const result = await mutateProfile<{ profile: LlmProfile; notification_failures?: string[] }>(
        originalName === null ? "POST" : "PUT",
        originalName === null ? profile : { profile_name: originalName, profile },
      );
      if (!result.profile || typeof result.profile.name !== "string") {
        throw new LlmProfileMutationError("保存响应缺少配置，请刷新确认。", true);
      }
      invalidateDirectory();
      if (originalName !== null && originalName !== result.profile.name) {
        selectionRef.current.handleProfileNameChange({ operation: "renamed", old_name: originalName, new_name: result.profile.name });
      }
      publishProfiles([
        ...profilesRef.current.filter((item) => item.name !== originalName && item.name !== result.profile.name),
        result.profile,
      ]);
      afterMutation(result.notification_failures);
      return result.profile;
    } catch (cause) { setError(errorText(cause)); throw cause; }
  }, [invalidateDirectory, publishProfiles, afterMutation]);
  const createProfile = useCallback((profile: LlmProfile) => saveProfile(null, profile), [saveProfile]);
  const updateProfile = useCallback((originalName: string, profile: LlmProfile) => saveProfile(originalName, profile), [saveProfile]);
  const deleteProfile = useCallback(async (profileName: string, replacementProfileName: string | null): Promise<LlmProfileDeleteResult> => {
    invalidateDirectory();
    try {
      const result = await mutateProfile<LlmProfileDeleteResult>("DELETE", {
        profile_name: profileName, replacement_profile_name: replacementProfileName,
      });
      if (!result.deleted) throw new Error("服务端未确认配置已删除");
      invalidateDirectory();
      selectionRef.current.handleProfileNameChange({ operation: "deleted", old_name: profileName, new_name: result.replacement_profile_name });
      publishProfiles(profilesRef.current.filter((profile) => profile.name !== profileName));
      afterMutation(result.notification_failures);
      return result;
    } catch (cause) { setError(errorText(cause)); throw cause; }
  }, [invalidateDirectory, publishProfiles, afterMutation]);

  const handleProfileChanged = useCallback((event: LlmProfileChangeEvent) => {
    invalidateDirectory();
    selectionRef.current.handleProfileNameChange(event);
    // 名称广播的确定信息先反映到已有快照；即使随后 GET 失败，也不把新名称误当过期本地选择。
    if (event.old_name && hasSnapshot.current) {
      const target = event.new_name ?? null;
      const next = profilesRef.current
        .filter((profile) => !(event.operation === "deleted" && profile.name === event.old_name))
        .map((profile) => ({
          ...profile,
          name: event.operation !== "deleted" && profile.name === event.old_name && target ? target : profile.name,
          vision_image_profile: profile.vision_image_profile === event.old_name ? target : profile.vision_image_profile,
          audio_profile: profile.audio_profile === event.old_name ? target : profile.audio_profile,
          vision_video_profile: profile.vision_video_profile === event.old_name ? target : profile.vision_video_profile,
        }));
      publishProfiles(next);
    }
    setProfilesStatus("loading");
    void refreshProfiles().catch(() => {});
  }, [invalidateDirectory, publishProfiles, refreshProfiles]);
  const handleApprovalProfileChanged = useCallback((msg: {
    approval_profile_name?: string | null; approval_profile_model?: string | null; approval_profile_available?: boolean;
  }) => approval.receive({
    profile_name: msg.approval_profile_name ?? null, model: msg.approval_profile_model ?? null,
    available: msg.approval_profile_available ?? false,
  }), [approval.receive]);
  const handleMetadataProfileChanged = useCallback((msg: {
    metadata_profile_name?: string | null; metadata_profile_model?: string | null; metadata_profile_available?: boolean;
  }) => metadata.receive({
    profile_name: msg.metadata_profile_name ?? null, model: msg.metadata_profile_model ?? null,
    available: msg.metadata_profile_available ?? false,
  }), [metadata.receive]);
  const activeProfile = useMemo(() => selection.selectionStatus === "ready"
    ? profiles.find((profile) => profile.name === selection.activeProfileName) ?? null : null,
  [profiles, selection.activeProfileName, selection.selectionStatus]);

  return {
    ...selection, profiles, profilesStatus, profilesError, profilesWarning, activeProfile,
    availableClients, clientsStatus, clientsError, error,
    refreshProfiles, refreshClients, createProfile, updateProfile, deleteProfile, handleProfileChanged,
    dismissProfilesWarning: () => { notificationWarningRef.current = null; setProfilesWarning(null); },
    approvalProfileState: approval.state, approvalProfileName: approval.state.profile_name,
    approvalProfile: profiles.find((profile) => profile.name === approval.state.profile_name) ?? null,
    approvalStatus: approval.status, approvalError: approval.error, approvalBusy: approval.busy,
    fetchApprovalProfile: approval.refresh, setApprovalProfile: approval.select, handleApprovalProfileChanged,
    metadataProfileState: metadata.state as MetadataProfileState, metadataProfileName: metadata.state.profile_name,
    metadataProfile: profiles.find((profile) => profile.name === metadata.state.profile_name) ?? null,
    metadataStatus: metadata.status, metadataError: metadata.error, metadataBusy: metadata.busy,
    fetchMetadataProfile: metadata.refresh, setMetadataProfile: metadata.select, handleMetadataProfileChanged,
  };
}

export type LlmProfileManager = ReturnType<typeof useLlmProfiles>;
