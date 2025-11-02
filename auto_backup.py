import os
import shutil
import datetime
import logging

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
DB_PATH = os.path.join(os.path.dirname(__file__), "prenotafacile.db")
DB_FULL_PATH = os.path.join(os.path.dirname(__file__), "prenotafacile_full.db")

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'auto_backup.log')),
        logging.StreamHandler()
    ]
)

def make_backup():
    try:
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backups_created = []
        
        # Backup database MINIMAL
        if os.path.exists(DB_PATH):
            dest = os.path.join(BACKUP_DIR, f"prenotafacile_backup_{timestamp}.db")
            shutil.copy(DB_PATH, dest)
            logging.info(f"✅ Backup MINIMAL completato: {dest}")
            backups_created.append(dest)
        
        # Backup database FULL
        if os.path.exists(DB_FULL_PATH):
            dest_full = os.path.join(BACKUP_DIR, f"prenotafacile_full_backup_{timestamp}.db")
            shutil.copy(DB_FULL_PATH, dest_full)
            logging.info(f"✅ Backup FULL completato: {dest_full}")
            backups_created.append(dest_full)
        
        return backups_created if backups_created else None
    except Exception as e:
        logging.error(f"❌ Errore backup: {e}")
        return None

if __name__ == "__main__":
    make_backup()
