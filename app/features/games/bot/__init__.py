from aiogram import Router

# импорт регистрирует текстовые команды (@command) — без него их не будет в registry
from . import city, guess_number, hangman, wordle  # noqa: F401
from .checkers import router as chk_router
from .g2048 import router as g2048_router
from .minesweeper import router as ms_router
from .quiz import router as quiz_router
from .rps import router as rps_router
from .ttt import router as ttt_router

router = Router(name="games")
router.include_router(ttt_router)
router.include_router(chk_router)
router.include_router(ms_router)
router.include_router(rps_router)
router.include_router(quiz_router)
router.include_router(g2048_router)
