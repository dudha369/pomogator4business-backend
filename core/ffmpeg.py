import asyncio
import os
import tempfile

_FFMPEG_TIMEOUT = 30


async def apply_audio_filter(input_bytes, filter_str):
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, "in.ogg")
        out_path = os.path.join(tmpdir, "out.ogg")

        with open(in_path, "wb") as f:
            f.write(input_bytes)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-filter:a",
            filter_str,
            "-c:a",
            "libopus",
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=_FFMPEG_TIMEOUT)
        except asyncio.TimeoutError:
            process.kill()
            return None

        if process.returncode != 0 or not os.path.exists(out_path):
            return None

        with open(out_path, "rb") as f:
            return f.read()


async def convert_ogg_to_wav(input_bytes):
    """16kHz моно WAV — стандартный формат для распознавания речи (STT)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, "in.ogg")
        out_path = os.path.join(tmpdir, "out.wav")

        with open(in_path, "wb") as f:
            f.write(input_bytes)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=_FFMPEG_TIMEOUT)
        except asyncio.TimeoutError:
            process.kill()
            return None

        if process.returncode != 0 or not os.path.exists(out_path):
            return None

        with open(out_path, "rb") as f:
            return f.read()
