# Multimodal Capabilities and Forwarding

The system handles images, audio, and video according to the active model's capabilities and configured forwarding Profiles.

## Capability paths

Each of the three modalities has separate support states for tool messages and user messages, giving six capability paths. Current runtime capability information, when provided, is authoritative for the active model and provider.

An unknown state is probed automatically on first multimodal use. There is no manual probe tool to call. Unknown is not the same as unsupported.

If the model supports neither message path for a modality, the system can forward the original media to another model and give you a text description. Forwarding selects the active Profile's corresponding media reference first, then the matching global fallback when no active reference is configured. An explicitly configured but failing reference is not silently replaced with a different Profile.

## Forwarded descriptions

Descriptions use these tags:

- `<forwarded_vision>...</forwarded_vision>` for images.
- `<forwarded_audio>...</forwarded_audio>` for audio.
- `<forwarded_video>...</forwarded_video>` for video.

These are system-produced analyses of original media, not words typed by the user. Do not claim to have directly perceived details beyond the supplied media or description. Forwarding is automatic and single-hop; do not call an invented forwarding tool or recursively route media yourself.

The original media is preserved in History. Switching to a capable model can use it directly rather than relying only on a previous forwarded description.

## Missing support or configuration

If neither path is supported and no suitable forwarding Profile is configured, the media operation can fail. Explain the actual limitation and ask the user to configure a capable reference Profile or choose a capable active model. Do not interpret network, authentication, or other provider failures as proof of unsupported media.

See LlmProfiles mod for configuration references.

## Main-session media controls

The user can control individual History media instances through the media input Tab. Disabling an instance changes subsequent main-session requests, not the stored media or its original chat display. A prepared request already in progress is not withdrawn.

A disabled instance can still be sent to the configured forwarding model for a textual description. This is not a global privacy prohibition on transmitting the original media. Reading the same file again creates a new media instance with its own sending state. Separate sub-session histories are outside this main-session control.
