import os
import subprocess
import datetime
import logging

# =======================
#  CONFIGURAZIONE BASE
# =======================
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_NAME = "prenotafacile-bot-progetto-n2"

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(PROJECT_DIR, 'auto_commit.log')),
        logging.StreamHandler()
    ]
)

# =======================
#  FUNZIONE DI COMMIT
# =======================
def commit_to_github():
    try:
        os.chdir(PROJECT_DIR)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"Auto commit PrenotaFacileBot - {now}"

        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push"], check=True)

        logging.info(f"✅ Commit automatico completato: {message}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Errore nel commit automatico: {e}")
        return False
    except Exception as e:
        logging.error(f"⚠️ Eccezione durante il commit automatico: {e}")
        return False

if __name__ == "__main__":
    commit_to_github()
