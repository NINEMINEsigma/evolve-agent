"""FFmpeg 工具集 — 基于命令行调用 ffmpeg/ffprobe 处理音视频。

模块导入时通过 ``registry.register()`` 注册。
要求系统中已安装 ffmpeg（含 ffprobe）。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from component.tools.filesystem import _s as _get_sandbox
from entity.constant import FFMPEG_DEFAULT_TIMEOUT, SUBPROCESS_SHORT_TIMEOUT_DEFAULT
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 可用性检查
# ---------------------------------------------------------------------------


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=SUBPROCESS_SHORT_TIMEOUT_DEFAULT,
        )
        return True
    except Exception:
        return False


def _ffprobe_available() -> bool:
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            timeout=SUBPROCESS_SHORT_TIMEOUT_DEFAULT,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 路径辅助
# ---------------------------------------------------------------------------


def _resolve_input(path: str) -> str:
    """解析输入文件为真实路径（只读权限）。"""
    sandbox = _get_sandbox()
    return str(sandbox.resolve_read(path).real)


def _resolve_output(path: str) -> str:
    """解析输出文件为真实路径并确保父目录存在。"""
    sandbox = _get_sandbox()
    r = sandbox.resolve_write(path)
    r.real.parent.mkdir(parents=True, exist_ok=True)
    return str(r.real)


def _run_ffmpeg(
    args: list[str],
    timeout: int = FFMPEG_DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令并返回结果。"""
    logger.info("ffmpeg %s", " ".join(args))
    proc = subprocess.run(
        ["ffmpeg", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc


# ---------------------------------------------------------------------------
# Handler: media_info — 使用 ffprobe 读取媒体信息
# ---------------------------------------------------------------------------


def _handle_media_info(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required")

    try:
        real_in: str = _resolve_input(path)
    except Exception as e:
        return tool_error(str(e), path=path)

    # ffprobe 输出 JSON 格式的媒体信息
    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            real_in,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if proc.returncode != 0:
        return tool_error(
            f"ffprobe failed (exit {proc.returncode}): {proc.stderr.strip()}",
            path=path,
        )

    try:
        data: dict = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return tool_error("ffprobe returned invalid JSON", path=path)

    # 提取关键信息
    streams: list[dict[str, Any]] = data.get("streams", [])
    fmt: dict[str, Any] = data.get("format", {})

    # 分类流
    video_streams: list[dict] = []
    audio_streams: list[dict] = []
    subtitle_streams: list[dict] = []
    other_streams: list[dict] = []

    for s in streams:
        codec_type: str = s.get("codec_type", "unknown")
        entry: dict = {
            "index": s.get("index"),
            "codec": s.get("codec_name"),
            "codec_long": s.get("codec_long_name"),
        }
        if codec_type == "video":
            entry.update({
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": _eval_fps(s.get("r_frame_rate", "0/1")),
                "bitrate_kbps": _parse_bitrate(s.get("bit_rate")),
                "pixel_format": s.get("pix_fmt"),
            })
            video_streams.append(entry)
        elif codec_type == "audio":
            entry.update({
                "sample_rate": s.get("sample_rate"),
                "channels": s.get("channels"),
                "channel_layout": s.get("channel_layout"),
                "bitrate_kbps": _parse_bitrate(s.get("bit_rate")),
            })
            audio_streams.append(entry)
        elif codec_type == "subtitle":
            subtitle_streams.append(entry)
        else:
            other_streams.append(entry)

    return tool_result(
        path=path,
        format=fmt.get("format_name", ""),
        duration_sec=_parse_duration(fmt.get("duration", "0")),
        size_bytes=int(fmt.get("size", 0)),
        bitrate_kbps=_parse_bitrate(fmt.get("bit_rate")),
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        other_streams=other_streams,
        total_streams=len(streams),
    )


def _eval_fps(fps_str: str) -> float | None:
    """解析分数形式的 fps（如 '30000/1001'）。"""
    try:
        parts = fps_str.split("/")
        if len(parts) == 2:
            return round(float(parts[0]) / float(parts[1]), 3)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return None


def _parse_bitrate(bit_rate: str | None) -> int | None:
    """将比特率字符串（bps）转为 kbps。"""
    if not bit_rate:
        return None
    try:
        return round(int(bit_rate) / 1000)
    except (ValueError, TypeError):
        return None


def _parse_duration(duration_str: str) -> float | None:
    """将时长字符串（秒）转为 float。"""
    try:
        return round(float(duration_str), 3)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Handler: convert_media — 格式转换
# ---------------------------------------------------------------------------


def _handle_convert_media(args: dict[str, Any]) -> dict:
    input_path: str = str(args.get("input", "")).strip()
    output_path: str = str(args.get("output", "")).strip()

    if not input_path or not output_path:
        return tool_error("input and output are required")

    try:
        real_in: str = _resolve_input(input_path)
        real_out: str = _resolve_output(output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    extra_args: list[str] = args.get("extra_args", [])

    cmd = [
        "-y",  # 覆盖输出
        "-i", real_in,
        *extra_args,
        real_out,
    ]

    try:
        proc = _run_ffmpeg(cmd)
    except subprocess.TimeoutExpired:
        return tool_error("ffmpeg timed out", input=input_path, output=output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    if proc.returncode != 0:
        return tool_error(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}",
            input=input_path, output=output_path,
        )

    return tool_result(
        input=input_path,
        output=output_path,
        success=True,
        stderr=proc.stderr.strip()[:500],
    )


# ---------------------------------------------------------------------------
# Handler: extract_audio — 从视频中提取音频
# ---------------------------------------------------------------------------


def _handle_extract_audio(args: dict[str, Any]) -> dict:
    input_path: str = str(args.get("input", "")).strip()
    output_path: str = str(args.get("output", "")).strip()

    if not input_path or not output_path:
        return tool_error("input and output are required")

    try:
        real_in: str = _resolve_input(input_path)
        real_out: str = _resolve_output(output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    codec: str = str(args.get("codec", "libmp3lame"))
    sample_rate: int = int(args.get("sample_rate", 0))
    channels: int = int(args.get("channels", 0))

    cmd = ["-y", "-i", real_in, "-vn"]  # -vn: 丢弃视频流

    if sample_rate > 0:
        cmd.extend(["-ar", str(sample_rate)])
    if channels > 0:
        cmd.extend(["-ac", str(channels)])

    cmd.extend(["-acodec", codec, real_out])

    try:
        proc = _run_ffmpeg(cmd)
    except subprocess.TimeoutExpired:
        return tool_error("ffmpeg timed out", input=input_path, output=output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    if proc.returncode != 0:
        return tool_error(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}",
            input=input_path, output=output_path,
        )

    return tool_result(
        input=input_path,
        output=output_path,
        codec=codec,
        success=True,
    )


# ---------------------------------------------------------------------------
# Handler: trim_media — 裁剪音视频片段
# ---------------------------------------------------------------------------


def _handle_trim_media(args: dict[str, Any]) -> dict:
    input_path: str = str(args.get("input", "")).strip()
    output_path: str = str(args.get("output", "")).strip()

    if not input_path or not output_path:
        return tool_error("input and output are required")

    start: float | None = None
    duration: float | None = None
    end: float | None = None

    raw_start = args.get("start")
    raw_duration = args.get("duration")
    raw_end = args.get("end")

    if raw_start is not None:
        start = float(raw_start)
    if raw_duration is not None:
        duration = float(raw_duration)
    if raw_end is not None:
        end = float(raw_end)

    if start is None and duration is None and end is None:
        return tool_error("at least one of start, duration, or end is required")

    try:
        real_in: str = _resolve_input(input_path)
        real_out: str = _resolve_output(output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    cmd = ["-y"]

    if start is not None and start > 0:
        cmd.extend(["-ss", str(start)])

    cmd.extend(["-i", real_in])

    if duration is not None:
        cmd.extend(["-t", str(duration)])
    elif end is not None and start is not None:
        cmd.extend(["-t", str(end - start)])

    # 复制编码（无重编码）— 快速裁剪
    cmd.extend(["-c", "copy", real_out])

    try:
        proc = _run_ffmpeg(cmd)
    except subprocess.TimeoutExpired:
        return tool_error("ffmpeg timed out", input=input_path, output=output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    if proc.returncode != 0:
        return tool_error(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}",
            input=input_path, output=output_path,
        )

    return tool_result(
        input=input_path,
        output=output_path,
        start=start,
        duration=duration,
        end=end,
        reencode=False,
        success=True,
    )


# ---------------------------------------------------------------------------
# Handler: concat_media — 拼接多个媒体文件
# ---------------------------------------------------------------------------


def _handle_concat_media(args: dict[str, Any]) -> dict:
    inputs: list[str] = args.get("inputs", [])
    output_path: str = str(args.get("output", "")).strip()

    if not inputs or len(inputs) < 2:
        return tool_error("at least 2 input files are required for concatenation")
    if not output_path:
        return tool_error("output is required")

    try:
        real_inputs: list[str] = [_resolve_input(p) for p in inputs]
        real_out: str = _resolve_output(output_path)
    except Exception as e:
        return tool_error(str(e), output=output_path)

    # 使用 concat demuxer — 需要先创建文件列表
    import tempfile

    list_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            list_path = f.name
            for rp in real_inputs:
                f.write(f"file '{rp}'\n")

        cmd = [
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            real_out,
        ]

        proc = _run_ffmpeg(cmd)
    except subprocess.TimeoutExpired:
        return tool_error("ffmpeg timed out", inputs=inputs, output=output_path)
    except Exception as e:
        return tool_error(str(e), inputs=inputs, output=output_path)
    finally:
        if list_path is not None:
            import os as _os
            try:
                _os.unlink(list_path)
            except Exception:
                pass

    if proc.returncode != 0:
        return tool_error(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}",
            inputs=inputs, output=output_path,
        )

    return tool_result(
        inputs=inputs,
        output=output_path,
        file_count=len(inputs),
        success=True,
    )


# ---------------------------------------------------------------------------
# Handler: compress_media — 压缩视频（降低分辨率/码率）
# ---------------------------------------------------------------------------


def _handle_compress_media(args: dict[str, Any]) -> dict:
    input_path: str = str(args.get("input", "")).strip()
    output_path: str = str(args.get("output", "")).strip()

    if not input_path or not output_path:
        return tool_error("input and output are required")

    try:
        real_in: str = _resolve_input(input_path)
        real_out: str = _resolve_output(output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    video_codec: str = str(args.get("video_codec", "libx264"))
    video_bitrate: str = str(args.get("video_bitrate", "")).strip()
    audio_codec: str = str(args.get("audio_codec", "aac"))
    audio_bitrate: str = str(args.get("audio_bitrate", "128k")).strip()
    scale: str = str(args.get("scale", "")).strip()
    crf: int = int(args.get("crf", 23))

    cmd = ["-y", "-i", real_in]

    video_args: list[str] = ["-c:v", video_codec]

    if crf >= 0 and video_codec in ("libx264", "libx265", "libvpx-vp9"):
        video_args.extend(["-crf", str(crf)])

    if video_bitrate:
        video_args.extend(["-b:v", video_bitrate])

    if scale:
        video_args.extend(["-vf", f"scale={scale}"])

    cmd.extend(video_args)
    cmd.extend(["-c:a", audio_codec, "-b:a", audio_bitrate, real_out])

    try:
        proc = _run_ffmpeg(cmd)
    except subprocess.TimeoutExpired:
        return tool_error("ffmpeg timed out", input=input_path, output=output_path)
    except Exception as e:
        return tool_error(str(e), input=input_path, output=output_path)

    if proc.returncode != 0:
        return tool_error(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}",
            input=input_path, output=output_path,
        )

    return tool_result(
        input=input_path,
        output=output_path,
        video_codec=video_codec,
        crf=crf,
        scale=scale or "original",
        success=True,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


# -- media_info
registry.register(
    name="media_info",
    toolset="extools",
    schema={
        # 使用 ffprobe 读取媒体文件的详细信息。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg（含 ffprobe）。
        # path 必须使用命名空间前缀（如 ws:、fork:）。
        #
        # ## 调用效果
        # 返回格式、时长、大小、比特率以及视频/音频/字幕流的编解码器、分辨率、帧率、采样率等信息。
        #
        # ## 返回
        # ```json
        # {"path": "ws:videos/sample.mp4", "format": "mov,mp4,m4a,3gp,3g2,mj2", "duration_sec": 120.5, "size_bytes": 10485760, "bitrate_kbps": 1024, "video_streams": [{"index": 0, "codec": "h264", "width": 1920, "height": 1080, "fps": 30}], "audio_streams": [...], "subtitle_streams": [...], "total_streams": 2}
        # ```
        #
        # ## 何时使用
        # - 检查媒体文件格式和参数。
        # - 确认分辨率、码率、时长后再进行转码或剪辑。
        #
        # ## 副作用/注意
        # - 只读操作，不会修改源文件。
        # - 损坏或格式不支持的文件可能返回错误。
        "description": """Read detailed media file info using ffprobe.

## Prerequisites
ffmpeg (including ffprobe) must be installed on the system. The path must use a namespace prefix (e.g. ws:, fork:).

## Effect
Returns the format, duration, size, bitrate, and stream details (codec, resolution, frame rate, sample rate, channels, etc.) for video, audio, and subtitle streams.

## Returns
```json
{"path": "ws:videos/sample.mp4", "format": "mov,mp4,m4a,3gp,3g2,mj2", "duration_sec": 120.5, "size_bytes": 10485760, "bitrate_kbps": 1024, "video_streams": [{"index": 0, "codec": "h264", "width": 1920, "height": 1080, "fps": 30}], "audio_streams": [...], "subtitle_streams": [...], "total_streams": 2}
```

## When to Use
- Inspect media file format and parameters.
- Confirm resolution, bitrate, and duration before transcoding or trimming.

## Side Effects / Notes
- Read-only operation; does not modify the source file.
- Corrupted or unsupported files may return an error.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 媒体文件逻辑路径（ws: 或 fork: 前缀）。
                    "description": """Media file logical path (ws: or fork: prefix).""",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_media_info,
    check_fn=_ffprobe_available,
    emoji="🎞️",
)

# -- convert_media
registry.register(
    name="convert_media",
    toolset="extools",
    schema={
        # 使用 ffmpeg 转换媒体文件格式。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg。
        # input 和 output 必须使用命名空间前缀。
        #
        # ## 调用效果
        # 根据 output 文件扩展名自动选择编码器，也可通过 extra_args 传入额外 ffmpeg 参数。
        # 默认覆盖已存在的输出文件。
        #
        # ## 返回
        # ```json
        # {"input": "ws:videos/input.avi", "output": "ws:videos/output.mp4", "success": true, "stderr": "..."}
        # ```
        #
        # ## 何时使用
        # - 将视频/音频转换为另一种格式。
        # - 通过 extra_args 自定义编码参数。
        #
        # ## 副作用/注意
        # - 会写入新文件，可能覆盖同名输出。
        # - 大文件转换可能耗时较长。
        "description": """Convert a media file to another format using ffmpeg.

## Prerequisites
ffmpeg must be installed on the system. input and output must use namespace prefixes.

## Effect
Converts the input file to the format implied by the output extension. Extra ffmpeg arguments can be passed via extra_args. Existing output files are overwritten by default.

## Returns
```json
{"input": "ws:videos/input.avi", "output": "ws:videos/output.mp4", "success": true, "stderr": "..."}
```

## When to Use
- Convert a video or audio file to another format.
- Customize encoding parameters via extra_args.

## Side Effects / Notes
- Writes a new file and may overwrite an existing output file with the same name.
- Large file conversions may take a long time.""",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": """Input file logical path.""",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径（扩展名决定目标格式）。
                    "description": """Output file logical path (extension determines target format).""",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 附加 ffmpeg 参数列表（可选），例如 ['-b:v', '2M', '-vf', 'scale=1280:720']。
                    "description": """Extra ffmpeg arguments (optional), e.g. ['-b:v', '2M', '-vf', 'scale=1280:720'].""",
                },
            },
            "required": ["input", "output"],
        },
    },
    handler=_handle_convert_media,
    check_fn=_ffmpeg_available,
    emoji="🔄",
    danger_level="write",
)

# -- extract_audio
registry.register(
    name="extract_audio",
    toolset="extools",
    schema={
        # 从视频文件中提取音频轨道。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg。
        # input 和 output 必须使用命名空间前缀。
        #
        # ## 调用效果
        # 从 input 视频提取音频并保存为 output。默认编码器为 libmp3lame，输出 MP3。
        # 可通过 codec、sample_rate、channels 调整编码参数。
        #
        # ## 返回
        # ```json
        # {"input": "ws:videos/video.mp4", "output": "ws:audio/audio.mp3", "codec": "libmp3lame", "success": true}
        # ```
        #
        # ## 何时使用
        # - 从视频中提取背景音乐或对白。
        # - 将视频转为纯音频文件。
        #
        # ## 副作用/注意
        # - 会写入新音频文件。
        # - sample_rate 和 channels 为 0 时使用源文件值。
        "description": """Extract the audio track from a video file.

## Prerequisites
ffmpeg must be installed on the system. input and output must use namespace prefixes.

## Effect
Extracts audio from the input video and saves it to output. Default codec is libmp3lame, producing MP3. Codec, sample rate, and channel count can be customized.

## Returns
```json
{"input": "ws:videos/video.mp4", "output": "ws:audio/audio.mp3", "codec": "libmp3lame", "success": true}
```

## When to Use
- Extract background music or dialogue from a video.
- Convert a video to an audio-only file.

## Side Effects / Notes
- Writes a new audio file.
- sample_rate and channels of 0 mean use the source values.""",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入视频文件逻辑路径。
                    "description": """Input video file logical path.""",
                },
                "output": {
                    "type": "string",
                    # 输出音频文件逻辑路径。
                    "description": """Output audio file logical path.""",
                },
                "codec": {
                    "type": "string",
                    # 音频编码器（默认 libmp3lame）。常见选项：libmp3lame, aac, libvorbis, pcm_s16le。
                    "description": """Audio codec (default libmp3lame). Common options: libmp3lame, aac, libvorbis, pcm_s16le.""",
                    "default": "libmp3lame",
                },
                "sample_rate": {
                    "type": "integer",
                    # 采样率（Hz），例如 44100、48000。0 表示使用源文件采样率。
                    "description": """Sample rate in Hz, e.g. 44100, 48000. 0 means use source sample rate.""",
                    "default": 0,
                },
                "channels": {
                    "type": "integer",
                    # 声道数，例如 1（单声道）、2（立体声）。0 表示使用源文件声道数。
                    "description": """Number of channels, e.g. 1 (mono), 2 (stereo). 0 means use source channel count.""",
                    "default": 0,
                },
            },
            "required": ["input", "output"],
        },
    },
    handler=_handle_extract_audio,
    check_fn=_ffmpeg_available,
    emoji="🎵",
    danger_level="write",
)

# -- trim_media
registry.register(
    name="trim_media",
    toolset="extools",
    schema={
        # 裁剪音视频片段。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg。
        # input 和 output 必须使用命名空间前缀。
        # 必须提供 start、duration、end 中的至少一个。
        #
        # ## 调用效果
        # 使用 ffmpeg 的流复制模式（-c copy）快速无损裁剪片段。
        # 可通过 start、duration、end 控制时间范围（单位：秒）。
        #
        # ## 返回
        # ```json
        # {"input": "ws:videos/video.mp4", "output": "ws:videos/clip.mp4", "start": 10, "duration": 30, "end": null, "reencode": false, "success": true}
        # ```
        #
        # ## 何时使用
        # - 从长视频中截取片段。
        # - 快速剪辑而不重新编码。
        #
        # ## 副作用/注意
        # - 会写入新文件。
        # - 流复制要求片段起止在关键帧附近，否则可能产生短暂黑屏或音画不同步。
        "description": """Trim an audio/video clip.

## Prerequisites
ffmpeg must be installed on the system. input and output must use namespace prefixes. At least one of start, duration, or end must be provided.

## Effect
Performs fast lossless trimming using ffmpeg stream copy mode (-c copy). Time range is controlled by start, duration, and end (all in seconds).

## Returns
```json
{"input": "ws:videos/video.mp4", "output": "ws:videos/clip.mp4", "start": 10, "duration": 30, "end": null, "reencode": false, "success": true}
```

## When to Use
- Extract a segment from a long video.
- Quickly clip media without re-encoding.

## Side Effects / Notes
- Writes a new file.
- Stream copy requires cut points near keyframes; otherwise brief black frames or A/V desync may occur.""",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": """Input file logical path.""",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": """Output file logical path.""",
                },
                "start": {
                    "type": "number",
                    # 起始时间（秒），从该时间点开始裁剪。
                    "description": """Start time in seconds, trim from this point.""",
                },
                "duration": {
                    "type": "number",
                    # 裁剪时长（秒）。
                    "description": """Duration to trim in seconds.""",
                },
                "end": {
                    "type": "number",
                    # 结束时间（秒），与 start 一起使用。
                    "description": """End time in seconds, used together with start.""",
                },
            },
            "required": ["input", "output"],
        },
    },
    handler=_handle_trim_media,
    check_fn=_ffmpeg_available,
    emoji="✂️",
)

# -- concat_media
registry.register(
    name="concat_media",
    toolset="extools",
    schema={
        # 拼接多个媒体文件。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg。
        # inputs 必须至少包含 2 个使用命名空间前缀的逻辑路径。
        # 所有输入文件必须使用相同的编码参数（格式、分辨率等）。
        #
        # ## 调用效果
        # 使用 ffmpeg concat demuxer 和流复制模式拼接文件，无需重新编码。
        #
        # ## 返回
        # ```json
        # {"inputs": ["ws:a.mp4", "ws:b.mp4"], "output": "ws:output.mp4", "file_count": 2, "success": true}
        # ```
        #
        # ## 何时使用
        # - 将多个同格式视频/音频合并为一个文件。
        # - 拼接分段录制的媒体。
        #
        # ## 副作用/注意
        # - 会写入新文件。
        # - 输入文件编码参数不一致可能导致拼接失败或异常。
        "description": """Concatenate multiple media files.

## Prerequisites
ffmpeg must be installed on the system. inputs must contain at least 2 logical paths with namespace prefixes. All input files must use identical encoding parameters (format, resolution, etc.).

## Effect
Concatenates the input files using the ffmpeg concat demuxer with stream copy mode, avoiding re-encoding.

## Returns
```json
{"inputs": ["ws:a.mp4", "ws:b.mp4"], "output": "ws:output.mp4", "file_count": 2, "success": true}
```

## When to Use
- Merge multiple files of the same format into one.
- Combine segmented recordings.

## Side Effects / Notes
- Writes a new file.
- Mismatched encoding parameters among inputs may cause concatenation failures or artifacts.""",
        "parameters": {
            "type": "object",
            "properties": {
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 输入文件逻辑路径列表（至少 2 个）。
                    "description": """List of input file logical paths (at least 2).""",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": """Output file logical path.""",
                },
            },
            "required": ["inputs", "output"],
        },
    },
    handler=_handle_concat_media,
    check_fn=_ffmpeg_available,
    emoji="📎",
)

# -- compress_media
registry.register(
    name="compress_media",
    toolset="extools",
    schema={
        # 压缩视频文件（降低分辨率/码率）。
        #
        # ## 前置条件
        # 系统中必须已安装 ffmpeg。
        # input 和 output 必须使用命名空间前缀。
        #
        # ## 调用效果
        # 通过设置 CRF、视频码率、编码器、缩放分辨率等参数压缩视频。
        # CRF 越低质量越好（0-51），默认 23。仅对 libx264/libx265/libvpx-vp9 有效。
        #
        # ## 返回
        # ```json
        # {"input": "ws:videos/input.mp4", "output": "ws:videos/output.mp4", "video_codec": "libx264", "crf": 23, "scale": "1280:720", "success": true}
        # ```
        #
        # ## 何时使用
        # - 缩小视频文件体积以便传输或存储。
        # - 调整视频分辨率或码率。
        #
        # ## 副作用/注意
        # - 会写入新文件，可能覆盖同名输出。
        # - 压缩是有损操作，会降低画质。
        # - 大文件压缩可能耗时较长。
        "description": """Compress a video file (reduce bitrate/resolution).

## Prerequisites
ffmpeg must be installed on the system. input and output must use namespace prefixes.

## Effect
Compresses the video by setting CRF, video bitrate, codec, and scale resolution. Lower CRF means better quality (0-51), default 23. CRF is only effective for libx264, libx265, and libvpx-vp9.

## Returns
```json
{"input": "ws:videos/input.mp4", "output": "ws:videos/output.mp4", "video_codec": "libx264", "crf": 23, "scale": "1280:720", "success": true}
```

## When to Use
- Reduce video file size for transfer or storage.
- Adjust video resolution or bitrate.

## Side Effects / Notes
- Writes a new file and may overwrite an existing output file with the same name.
- Compression is lossy and reduces visual quality.
- Large file compression may take a long time.""",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": """Input file logical path.""",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": """Output file logical path.""",
                },
                "video_codec": {
                    "type": "string",
                    # 视频编码器（默认 libx264）。
                    "description": """Video codec (default libx264).""",
                    "default": "libx264",
                },
                "crf": {
                    "type": "integer",
                    # CRF 值（0-51），越低质量越好。默认 23。仅对 libx264/libx265/libvpx-vp9 有效。
                    "description": """CRF value (0-51), lower = better quality. Default 23. Only effective for libx264/libx265/libvpx-vp9.""",
                    "default": 23,
                },
                "video_bitrate": {
                    "type": "string",
                    # 视频目标比特率，例如 '2M'、'500k'。
                    "description": """Target video bitrate, e.g. '2M', '500k'.""",
                },
                "audio_codec": {
                    "type": "string",
                    # 音频编码器（默认 aac）。
                    "description": """Audio codec (default aac).""",
                    "default": "aac",
                },
                "audio_bitrate": {
                    "type": "string",
                    # 音频比特率（默认 128k）。
                    "description": """Audio bitrate (default 128k).""",
                    "default": "128k",
                },
                "scale": {
                    "type": "string",
                    # 缩放分辨率，例如 '1280:720'、'640:-1'（等比例缩放）。
                    "description": """Scale resolution, e.g. '1280:720', '640:-1' (proportional scaling).""",
                },
            },
            "required": ["input", "output"],
        },
    },
    handler=_handle_compress_media,
    check_fn=_ffmpeg_available,
    emoji="🗜️",
)