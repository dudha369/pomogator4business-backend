import asyncio
import os
import tempfile
from pathlib import Path

_FFMPEG_TIMEOUT = 30


def _read_if_exists(path):
    """Содержимое файла или None, если ffmpeg его не создал."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


async def apply_audio_filter(input_bytes, filter_str):
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, "in.ogg")
        out_path = os.path.join(tmpdir, "out.ogg")

        await asyncio.to_thread(Path(in_path).write_bytes, input_bytes)

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
        except TimeoutError:
            process.kill()
            return None

        if process.returncode != 0:
            return None
        return await asyncio.to_thread(_read_if_exists, out_path)


async def convert_ogg_to_wav(input_bytes):
    """16kHz моно WAV — стандартный формат для распознавания речи (STT)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, "in.ogg")
        out_path = os.path.join(tmpdir, "out.wav")

        await asyncio.to_thread(Path(in_path).write_bytes, input_bytes)

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
        except TimeoutError:
            process.kill()
            return None

        if process.returncode != 0:
            return None
        return await asyncio.to_thread(_read_if_exists, out_path)
