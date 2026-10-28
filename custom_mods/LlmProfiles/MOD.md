# LLM Profiles

LLM Profiles define model connections and related configuration. The authoritative registry is `ws:llm_profiles.es`. You may inspect it using supported read interfaces, but must not directly modify the persisted file. The frontend manages Profiles through the Gateway.

## Persisted model

The supported easysave key is `v2`, with an `LLMProfileData` root containing:

- `profiles`: the root list of `LLMProfile` instances.
- `approval_profile`: the approval model for handsfree mode.
- `metadata_profile`: the global model for session title, tags, and summary generation.
- `toolchain_summary_profile`: the global model for compressed tool-chain summaries.
- `global_vision_image_profile`, `global_audio_profile`, and `global_vision_video_profile`: independent global media forwarding fallbacks.

Optional Profile references are either `None` or references to instances in the root `profiles` list. They are not persisted names or UIDs.

Each Profile includes `name`, `llm_client_name`, `base_url`, `model`, `api_key`, `temperature`, `max_output_tokens`, `reasoning_effort`, `max_context_tokens`, and `soul_file`. Its `vision_image_profile`, `audio_profile`, and `vision_video_profile` fields refer to other instances in the same root list.

HTTP payloads represent these references as Profile names or JSON null. Do not confuse that wire representation with the persisted object graph. The file uses type-preserving easysave serialization, not plain JSON.

## Frontend workflow

Use the model profiles Tab to manage Profile definitions. Global configuration references select approval, metadata, tool-chain summary, and modality fallback Profiles.

The header is the session's pending Profile selection entry. Selecting a Profile there does not immediately update the server's current selection. Sending a main-session message or requesting regeneration submits the selected name; resume uses the server's current Profile and does not submit a new selection.

The user may change Profiles between turns. Treat current runtime configuration as authoritative and do not assume a prior turn's model remains active.

## Related features

- Approval mod explains approval modes and the approval Profile.
- Multimodal mod explains media forwarding and fallback selection.
- Identity mod explains the selected SOUL text and runtime character name.

When reporting configuration, avoid unnecessarily reproducing API keys or other credentials.
