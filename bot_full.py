"""
DEPRECATION NOTICE

Il contenuto della versione "full" è stato integrato in un unico file: bot_completo.py.
Questo file rimane solo come shim per compatibilità: eseguirà la variante FULL
del bot usando bot_completo.py.

Per usare direttamente il file principale, preferisci:
  - PowerShell (Windows):
      $env:BOT_VARIANT = "full"; .\.venv\Scripts\python.exe .\prenotafacile-bot-progetto-n2\bot_completo.py
"""

import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prenotafacile_full_shim")


def _run():
    # Forza la variante FULL e delega a bot_completo
    os.environ["BOT_VARIANT"] = "full"
    try:
        from bot_completo import main as _main
    except Exception as e:
        logger.error("Impossibile importare bot_completo.main: %s", e)
        raise SystemExit(1)
    # Esegui il main del file unico
    _main()


if __name__ == "__main__":
    _run()
