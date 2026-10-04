import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.context import CommandContext
from core.i18n import t
from core.registry import command

router = Router(name="quiz")

QUESTIONS = [
    ("Столица Австралии?", ["Сидней", "Канберра", "Мельбурн", "Перт"], 1),
    ("Самая длинная река в мире?", ["Амазонка", "Нил", "Янцзы", "Миссисипи"], 1),
    ("Сколько костей в теле взрослого человека?", ["186", "206", "226", "246"], 1),
    ('Кто написал "Войну и мир"?', ["Достоевский", "Чехов", "Толстой", "Тургенев"], 2),
    ("Какая планета ближе всех к Солнцу?", ["Венера", "Земля", "Меркурий", "Марс"], 2),
    (
        "В каком году человек впервые полетел в космос?",
        ["1957", "1961", "1969", "1965"],
        1,
    ),
    ("Сколько цветов в радуге?", ["5", "6", "7", "8"], 2),
    (
        "Самый большой океан на Земле?",
        ["Атлантический", "Индийский", "Северный Ледовитый", "Тихий"],
        3,
    ),
    (
        "Какой газ преобладает в атмосфере Земли?",
        ["Кислород", "Азот", "Углекислый газ", "Водород"],
        1,
    ),
    (
        'Автор картины "Мона Лиза"?',
        ["Рафаэль", "Микеланджело", "да Винчи", "Донателло"],
        2,
    ),
    ("Столица Японии?", ["Осака", "Киото", "Токио", "Иокогама"], 2),
    ("Сколько дней в високосном году?", ["364", "365", "366", "367"], 2),
    (
        "Самое большое млекопитающее?",
        ["Слон", "Синий кит", "Жираф", "Белый медведь"],
        1,
    ),
    ("Химический символ золота?", ["Ag", "Au", "Gd", "Go"], 1),
    ("Сколько сторон у шестиугольника?", ["5", "6", "7", "8"], 1),
]


def _keyboard(question_index, options):
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"quiz:{question_index}:{i}")]
        for i, opt in enumerate(options)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@command(name="quiz", module="quiz", owner_only=False)
async def cmd_quiz(ctx: CommandContext):
    index = random.randrange(len(QUESTIONS))
    question, options, _correct = QUESTIONS[index]

    await ctx.edit_command_message(
        f"❓ {question}", reply_markup=_keyboard(index, options)
    )


@router.callback_query(F.data.startswith("quiz:"))
async def on_quiz_callback(call: CallbackQuery):
    _, q_index_raw, choice_raw = call.data.split(":")
    q_index, choice = int(q_index_raw), int(choice_raw)

    if q_index >= len(QUESTIONS):
        await call.answer()
        return

    question, options, correct = QUESTIONS[q_index]

    connection = await db.get_connection(call.message.business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    if choice == correct:
        result = t("quiz.correct", locale)
    else:
        result = t("quiz.wrong", locale, answer=options[correct])

    text = f"❓ {question}\n\n{result}"
    await call.message.edit_text(text)
    await call.answer()
