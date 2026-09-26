import asyncio
import io

import speech_recognition as sr

from core.ffmpeg import convert_ogg_to_wav

_LANGUAGE_CODES = {
    "ru": "ru-RU",
    "en": "en-US",
    "uk": "uk-UA",
}


async def transcribe_audio(ogg_bytes: bytes, locale: str = "ru"):
    wav_bytes = await convert_ogg_to_wav(ogg_bytes)
    if wav_bytes is None:
        return None

    language = _LANGUAGE_CODES.get(locale, "ru-RU")

    def _run():
        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return None

    return await asyncio.to_thread(_run)
