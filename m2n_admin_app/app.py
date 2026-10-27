import os
import sys
import json
import sqlite3
import threading
import time
from datetime import datetime
import urllib.request
import webview

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Dynamic PyInstaller paths: Data is kept next to the exe, UI assets bundled
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    ASSETS_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSETS_DIR = BASE_DIR

DB_PATH = os.path.join(BASE_DIR, 'leads.db')
UI_DIR = os.path.join(ASSETS_DIR, 'ui')
INDEX_HTML = os.path.join(UI_DIR, 'index.html')

CLOUD_POLL_URL = 'https://ntfy.sh/m2n_leads_prod_live_2026/json?poll=1&since=all'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id TEXT UNIQUE,
            full_name TEXT NOT NULL,
            company TEXT NOT NULL,
            email TEXT,
            phone TEXT NOT NULL,
            service_interest TEXT,
            budget TEXT,
            message TEXT,
            status TEXT DEFAULT 'Yeni',
            notes TEXT DEFAULT '',
            is_starred INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def insert_lead(msg_id, lead_dict):
    full_name = (lead_dict.get('fullName') or lead_dict.get('full_name') or 'İsimsiz').strip()
    company = (lead_dict.get('company') or '-').strip()
    email = (lead_dict.get('email') or '').strip()
    phone = (lead_dict.get('phone') or '').strip()
    service_interest = (lead_dict.get('serviceInterest') or lead_dict.get('service_interest') or 'Belirtilmedi').strip()
    budget = (lead_dict.get('budget') or '-').strip()
    message = (lead_dict.get('message') or '').strip()
    created_at = lead_dict.get('timestamp') or datetime.now().strftime('%d.%m.%Y %H:%M:%S')

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO leads (msg_id, full_name, company, email, phone, service_interest, budget, message, status, notes, is_starred, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Yeni', '', 1, ?)
        ''', (msg_id, full_name, company, email, phone, service_interest, budget, message, created_at))
        conn.commit()
        lead_id = cursor.lastrowid
        conn.close()
        return lead_id
    except sqlite3.IntegrityError:
        # Already exists by msg_id
        conn.close()
        return None


# Background Rapid Cloud Poller: Polls every 0.7s without buffer delays for sub-second arrival
def fast_cloud_poll_loop():
    seen_ids = set()
    # Pre-fill seen_ids from database
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT msg_id FROM leads WHERE msg_id IS NOT NULL')
        for r in cursor.fetchall():
            if r['msg_id']:
                seen_ids.add(r['msg_id'])
        conn.close()
    except Exception:
        pass

    while True:
        try:
            req = urllib.request.Request(
                CLOUD_POLL_URL,
                headers={'User-Agent': 'M2N-Desktop-Vault/1.0', 'Cache-Control': 'no-cache'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                content = resp.read().decode('utf-8')
                for line in content.strip().split('\n'):
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        msg_id = obj.get('id')
                        if msg_id and msg_id not in seen_ids and obj.get('event') == 'message' and 'message' in obj:
                            seen_ids.add(msg_id)
                            raw_msg = obj['message']
                            lead_data = json.loads(raw_msg)
                            insert_lead(msg_id, lead_data)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(0.7)


# PyWebView JS API Bridge
class M2NJsApi:
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def get_leads(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM leads ORDER BY is_starred DESC, id DESC')
        rows = cursor.fetchall()
        leads = [dict(row) for row in rows]
        conn.close()
        return leads

    def update_status(self, lead_id, new_status):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE leads SET status = ? WHERE id = ?', (new_status, lead_id))
        conn.commit()
        conn.close()
        return {'success': True}

    def update_notes(self, lead_id, notes):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE leads SET notes = ? WHERE id = ?', (notes, lead_id))
        conn.commit()
        conn.close()
        return {'success': True}

    def toggle_star(self, lead_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE leads SET is_starred = CASE WHEN is_starred = 1 THEN 0 ELSE 1 END WHERE id = ?', (lead_id,))
        conn.commit()
        conn.close()
        return {'success': True}

    def delete_lead(self, lead_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM leads WHERE id = ?', (lead_id,))
        conn.commit()
        conn.close()
        return {'success': True}

    def export_csv(self):
        import csv
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM leads ORDER BY id DESC')
        rows = cursor.fetchall()
        conn.close()

        desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
        csv_filename = f"M2N_Basvurular_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = os.path.join(desktop_path, csv_filename)

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Ad Soyad', 'Şirket', 'E-Posta', 'Telefon', 'İlgilendiği Hizmet', 'Bütçe', 'Mesaj', 'Durum', 'Notlar', 'Yıldızlı', 'Tarih'])
            for row in rows:
                writer.writerow([
                    row['id'], row['full_name'], row['company'], row['email'],
                    row['phone'], row['service_interest'], row['budget'],
                    row['message'], row['status'], row['notes'],
                    'Evet' if row['is_starred'] else 'Hayır', row['created_at']
                ])

        return {'success': True, 'path': csv_path, 'filename': csv_filename}


def main():
    init_db()

    # Background fast poller (polls every 0.7s without buffer latency)
    cloud_thread = threading.Thread(target=fast_cloud_poll_loop, daemon=True)
    cloud_thread.start()

    api = M2NJsApi()
    window = webview.create_window(
        title='M2N Tech — Gelen Başvurular Yönetim Paneli',
        url=INDEX_HTML,
        js_api=api,
        width=1280,
        height=840,
        min_size=(960, 620),
        background_color='#0A0A0A'
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == '__main__':
    main()
