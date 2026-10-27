import os
import sys
import json
import sqlite3
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
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

    # Pre-populate sample starter leads if table is empty
    cursor.execute('SELECT COUNT(*) FROM leads')
    if cursor.fetchone()[0] == 0:
        sample_leads = [
            (
                "Kadir Demir", "Demir Lojistik A.Ş.", "kadir@demirlojistik.com", "+90 532 411 90 20",
                "Şirket İçi Yönetim Panelleri (CRM / ERP)", "150.000 ₺ - 300.000 ₺",
                "45 adet tır ve 60 kişilik saha personelimiz var. Excel takibini bırakıp anlık GPS ve sefer puantaj takip paneli istiyoruz.",
                "Yeni", "Yüksek öncelikli KOBİ, yarın aranacak.", 1, "2026-10-27 10:15:00"
            ),
            (
                "Selin Acar", "Acar Butik & Tasarım", "selin@acarbutik.com", "+90 544 890 12 34",
                "Mobil Uygulama Geliştirme (iOS & Android)", "75.000 ₺ - 150.000 ₺",
                "Instagram ve web sitemizdeki ürünlerin mobil uygulamadan satışı ve sadakat puan sistemi için teklif almak istiyoruz.",
                "İnceleniyor", "Örnek e-ticaret demo ekranı paylaşıldı.", 0, "2026-10-27 11:42:00"
            ),
            (
                "Kemal Arslan", "Arslan Perakende Zinciri", "k.arslan@arslangrup.com.tr", "+90 533 710 45 60",
                "Süreç Otomasyonu & Entegrasyon", "300.000 ₺+",
                "12 mağazamızdaki kasalar ile merkez muhasebe arasında anlık stok ve ciro mutabakat otomasyonu kurulması gerekiyor.",
                "Teklif Verildi", "Teklif sunumu iletildi, Perşembe Zoom toplantısı var.", 1, "2026-10-27 13:05:00"
            )
        ]
        cursor.executemany('''
            INSERT INTO leads (full_name, company, email, phone, service_interest, budget, message, status, notes, is_starred, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', sample_leads)
        conn.commit()
    conn.close()


# Background HTTP Server for receiving website form posts
class LeadReceiverHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/leads':
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads ORDER BY created_at DESC')
            leads = [dict(row) for row in cursor.fetchall()]
            conn.close()

            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(leads, ensure_ascii=False).encode('utf-8'))
        elif self.path == '/api/health':
            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'online', 'service': 'M2N Lead Receiver'}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/leads':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                full_name = data.get('fullName') or data.get('full_name') or 'İsimsiz'
                company = data.get('company') or '-'
                email = data.get('email') or ''
                phone = data.get('phone') or ''
                service_interest = data.get('serviceInterest') or data.get('service_interest') or 'Belirtilmedi'
                budget = data.get('budget') or 'Belirtilmedi'
                message = data.get('message') or ''

                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO leads (full_name, company, email, phone, service_interest, budget, message, status, notes, is_starred, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Yeni', '', 1, ?)
                ''', (full_name, company, email, phone, service_interest, budget, message, now))
                lead_id = cursor.lastrowid
                conn.commit()
                conn.close()

                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'lead_id': lead_id, 'created_at': now}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence HTTP console logs
        return


def start_http_server():
    server = HTTPServer(('127.0.0.1', 4848), LeadReceiverHandler)
    server.serve_forever()


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

    def add_lead(self, data):
        full_name = data.get('full_name', '').strip()
        company = data.get('company', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        service_interest = data.get('service_interest', '')
        budget = data.get('budget', '')
        message = data.get('message', '').strip()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO leads (full_name, company, email, phone, service_interest, budget, message, status, notes, is_starred, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Yeni', '', 1, ?)
        ''', (full_name, company, email, phone, service_interest, budget, message, now))
        lead_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {'success': True, 'id': lead_id}

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

    # Launch background HTTP receiver on port 4848
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    api = M2NJsApi()
    window = webview.create_window(
        title='M2N Tech — Lead & Proje Yönetim Paneli',
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
