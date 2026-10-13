export type MediaType = "image" | "audio" | "video";
export type MediaRole = "user" | "assistant" | "system" | "tool";

export interface SessionMediaItemDto {
  media_id: string;
  history_index: number;
  block_index: number;
  media_type: MediaType;
  role: MediaRole;
  character_name: string | null;
  source_path: string | null;
  tool_call_id: string | null;
  send_multimodal: boolean;
  has_forward_description: boolean;
  mime_type: string | null;
  inline_payload_chars: number | null;
  preview_available: boolean;
}

export interface SessionMediaListResponseDto {
  session_id: string;
  history_count: number;
  total_count: number;
  offset: number;
  limit: number;
  editable: boolean;
  items: SessionMediaItemDto[];
}

export interface SessionMediaUpdateResponseDto {
  session_id: string;
  item: SessionMediaItemDto;
}

export interface UseSessionMediaState {
  page: SessionMediaListResponseDto | null;
  offset: number;
  loading: boolean;
  error: string | null;
  stale: boolean;
  pendingIds: ReadonlySet<string>;
  itemErrors: Readonly<Record<string, string>>;
  refresh: () => Promise<void>;
  setOffset: (offset: number) => void;
  setEnabled: (item: SessionMediaItemDto, enabled: boolean) => Promise<void>;
}

export interface MediaGalleryTileProps {
  item: SessionMediaItemDto;
  sessionId: string;
  index: number;
  pending: boolean;
  hasError: boolean;
  onOpen: (anchor: HTMLButtonElement) => void;
}

export interface MediaDetailsWindowProps {
  item: SessionMediaItemDto;
  sessionId: string;
  disabled: boolean;
  pending: boolean;
  error: string | null;
  onSetEnabled: (enabled: boolean) => void;
  onClose: () => void;
}

export interface MediaPreviewProps {
  item: SessionMediaItemDto;
  sessionId: string;
  variant: "thumbnail" | "detail";
}
