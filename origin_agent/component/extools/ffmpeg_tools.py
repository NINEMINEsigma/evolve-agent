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
            timeout=5,
        )
        return True
    except Exception:
        return False


def _ffprobe_available() -> bool:
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            timeout=5,
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
    timeout: int = 300,
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


def _handle_media_info(args: Dict[str, Any]) -> dict:
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


def _handle_convert_media(args: Dict[str, Any]) -> dict:
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


def _handle_extract_audio(args: Dict[str, Any]) -> dict:
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


def _handle_trim_media(args: Dict[str, Any]) -> dict:
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


def _handle_concat_media(args: Dict[str, Any]) -> dict:
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


def _handle_compress_media(args: Dict[str, Any]) -> dict:
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
        # 使用 ffprobe 读取媒体文件的详细信息，包括：
        # 格式、时长、视频流（分辨率、fps、编码）、
        # 音频流（采样率、声道、编码）等。
        "description": (
            "Read detailed media file info using ffprobe: "
            "format, duration, video streams (resolution, fps, codec), "
            "audio streams (sample rate, channels, codec), etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 媒体文件逻辑路径（ws: 或 fork: 前缀）。
                    "description": "Media file logical path (ws: or fork: prefix).",
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
        # 使用 ffmpeg 转换媒体文件格式。自动根据输出文件扩展名选择编码器。
        # 通过 extra_args 可传递额外 ffmpeg 参数。
        "description": (
            "Convert media file format using ffmpeg. "
            "Auto-selects encoder based on output file extension. "
            "Pass extra ffmpeg arguments via extra_args."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": "Input file logical path.",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径（扩展名决定目标格式）。
                    "description": "Output file logical path (extension determines target format).",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 附加 ffmpeg 参数列表（可选），例如 ['-b:v', '2M', '-vf', 'scale=1280:720']。
                    "description": "Extra ffmpeg arguments (optional), e.g. ['-b:v', '2M', '-vf', 'scale=1280:720'].",
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
        # 从视频文件中提取音频轨道。支持指定编码器、采样率和声道数。默认输出 MP3 格式。
        "description": (
            "Extract audio track from a video file. "
            "Supports specifying codec, sample rate, and channel count. "
            "Default output format is MP3."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入视频文件逻辑路径。
                    "description": "Input video file logical path.",
                },
                "output": {
                    "type": "string",
                    # 输出音频文件逻辑路径。
                    "description": "Output audio file logical path.",
                },
                "codec": {
                    "type": "string",
                    # 音频编码器（默认 libmp3lame）。常见选项：libmp3lame, aac, libvorbis, pcm_s16le。
                    "description": "Audio codec (default libmp3lame). Common options: libmp3lame, aac, libvorbis, pcm_s16le.",
                    "default": "libmp3lame",
                },
                "sample_rate": {
                    "type": "integer",
                    # 采样率（Hz），例如 44100、48000。0 表示使用源文件采样率。
                    "description": "Sample rate (Hz), e.g. 44100, 48000. 0 means use source sample rate.",
                    "default": 0,
                },
                "channels": {
                    "type": "integer",
                    # 声道数，例如 1（单声道）、2（立体声）。0 表示使用源文件声道数。
                    "description": "Number of channels, e.g. 1 (mono), 2 (stereo). 0 means use source channel count.",
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
        # 裁剪音视频片段。使用流复制（-c copy）实现快速无损裁剪。
        # 至少需要指定 start、duration 或 end 之一。
        "description": (
            "Trim an audio/video clip. Uses stream copy (-c copy) "
            "for fast lossless trimming. "
            "At least one of start, duration, or end must be specified."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": "Input file logical path.",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": "Output file logical path.",
                },
                "start": {
                    "type": "number",
                    # 起始时间（秒），从该时间点开始裁剪。
                    "description": "Start time (seconds), trim from this point.",
                },
                "duration": {
                    "type": "number",
                    # 裁剪时长（秒）。
                    "description": "Duration to trim (seconds).",
                },
                "end": {
                    "type": "number",
                    # 结束时间（秒），与 start 一起使用。
                    "description": "End time (seconds), used together with start.",
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
        # 拼接多个音视频文件。使用 ffmpeg concat demuxer，
        # 执行流复制（-c copy），无需重编码。
        # 所有文件需使用相同编码参数（同格式、同分辨率等）。
        "description": (
            "Concatenate multiple media files. "
            "Uses ffmpeg concat demuxer with stream copy (-c copy), "
            "no re-encoding needed. "
            "All files must use identical encoding parameters "
            "(same format, resolution, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 输入文件逻辑路径列表（至少 2 个）。
                    "description": "List of input file logical paths (at least 2).",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": "Output file logical path.",
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
        # 压缩视频文件（降低码率/分辨率）。
        # 支持设置 CRF（0-51，越低质量越好）、视频比特率、
        # 编码器和缩放分辨率。
        "description": (
            "Compress a video file (reduce bitrate/resolution). "
            "Supports setting CRF (0-51, lower = better quality), "
            "video bitrate, codec, and scaling resolution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    # 输入文件逻辑路径。
                    "description": "Input file logical path.",
                },
                "output": {
                    "type": "string",
                    # 输出文件逻辑路径。
                    "description": "Output file logical path.",
                },
                "video_codec": {
                    "type": "string",
                    # 视频编码器（默认 libx264）。
                    "description": "Video codec (default libx264).",
                    "default": "libx264",
                },
                "crf": {
                    "type": "integer",
                    # CRF 值（0-51），越低质量越好。默认 23。仅对 libx264/libx265/libvpx-vp9 有效。
                    "description": "CRF value (0-51), lower = better quality. Default 23. Only effective for libx264/libx265/libvpx-vp9.",
                    "default": 23,
                },
                "video_bitrate": {
                    "type": "string",
                    # 视频目标比特率，例如 '2M'、'500k'。
                    "description": "Target video bitrate, e.g. '2M', '500k'.",
                },
                "audio_codec": {
                    "type": "string",
                    # 音频编码器（默认 aac）。
                    "description": "Audio codec (default aac).",
                    "default": "aac",
                },
                "audio_bitrate": {
                    "type": "string",
                    # 音频比特率（默认 128k）。
                    "description": "Audio bitrate (default 128k).",
                    "default": "128k",
                },
                "scale": {
                    "type": "string",
                    # 缩放分辨率，例如 '1280:720'、'640:-1'（等比例缩放）。
                    "description": "Scale resolution, e.g. '1280:720', '640:-1' (proportional scaling).",
                },
            },
            "required": ["input", "output"],
        },
    },
    handler=_handle_compress_media,
    check_fn=_ffmpeg_available,
    emoji="🗜️",
)