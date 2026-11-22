"""Печатает новый мастер-ключ для DATA_MASTER_KEYS (Render → Environment).

Первый запуск:  DATA_MASTER_KEYS=1:<ключ>
Ротация:        DATA_MASTER_KEYS=2:<новый>,1:<старый>   (новый — первым; старый убрать, когда
                в логе очистки vault_keys_rewrapped станет 0 и перезапуск прошёл без ошибок)
КОПИЮ ключа храните вне Render (менеджер паролей): без него данные не восстановить."""

import base64
import os
import sys

version = sys.argv[1] if len(sys.argv) > 1 else "1"
print(f"{version}:{base64.urlsafe_b64encode(os.urandom(32)).decode()}")
