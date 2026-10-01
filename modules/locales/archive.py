"""Локализация модуля archive."""

RU = {
    "archive.edited_notice": (
        '<tg-emoji emoji-id="5258215635996908355">✏️</tg-emoji> <b>Сообщение изменено!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Собеседник:</b> {mention}\n\n'
        '<tg-emoji emoji-id="5258419835922030550">⏲️</tg-emoji> <b>Было:</b>\n'
        "<blockquote expandable>{old_text}</blockquote>\n\n"
        '<tg-emoji emoji-id="5258258882022612173">⏱️</tg-emoji> <b>Стало:</b>\n'
        "<blockquote expandable>{new_text}</blockquote>"
    ),
    "archive.deleted_notice": (
        '<tg-emoji emoji-id="5258130763148172425">🗑</tg-emoji> <b>Сообщение удалено!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Собеседник:</b> {mention}\n\n'
        "<blockquote expandable>{old_text}</blockquote>"
    ),
    "archive.open_message_button": "Перейти к сообщению",
    "archive.link_unavailable": "Ссылка недоступна — у собеседника нет username.",
    "archive.media_placeholder": "[медиа-сообщение]",
}

EN = {
    "archive.edited_notice": (
        '<tg-emoji emoji-id="5258215635996908355">✏️</tg-emoji> <b>Message edited!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Contact:</b> {mention}\n\n'
        '<tg-emoji emoji-id="5258419835922030550">⏲️</tg-emoji> <b>Before:</b>\n'
        "<blockquote expandable>{old_text}</blockquote>\n\n"
        '<tg-emoji emoji-id="5258258882022612173">⏱️</tg-emoji> <b>After:</b>\n'
        "<blockquote expandable>{new_text}</blockquote>"
    ),
    "archive.deleted_notice": (
        '<tg-emoji emoji-id="5258130763148172425">🗑</tg-emoji> <b>Message deleted!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Contact:</b> {mention}\n\n'
        "<blockquote expandable>{old_text}</blockquote>"
    ),
    "archive.open_message_button": "Go to message",
    "archive.link_unavailable": "Link unavailable — this contact has no username.",
    "archive.media_placeholder": "[media message]",
}

UK = {
    "archive.edited_notice": (
        '<tg-emoji emoji-id="5258215635996908355">✏️</tg-emoji> <b>Повідомлення змінено!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Співрозмовник:</b> {mention}\n\n'
        '<tg-emoji emoji-id="5258419835922030550">⏲️</tg-emoji> <b>Було:</b>\n'
        "<blockquote expandable>{old_text}</blockquote>\n\n"
        '<tg-emoji emoji-id="5258258882022612173">⏱️</tg-emoji> <b>Стало:</b>\n'
        "<blockquote expandable>{new_text}</blockquote>"
    ),
    "archive.deleted_notice": (
        '<tg-emoji emoji-id="5258130763148172425">🗑</tg-emoji> <b>Повідомлення видалено!</b>\n'
        '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> <b>Співрозмовник:</b> {mention}\n\n'
        "<blockquote expandable>{old_text}</blockquote>"
    ),
    "archive.open_message_button": "Перейти до повідомлення",
    "archive.link_unavailable": "Посилання недоступне — у співрозмовника немає username.",
    "archive.media_placeholder": "[медіаповідомлення]",
}
