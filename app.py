import os
import shutil
import tempfile
import threading
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

# Le site autorisé à utiliser ce serveur
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://resumo-green.vercel.app")
# Seuls ces sites sont acceptés (évite que le serveur serve à autre chose)
ALLOWED_HOSTS = ("facebook.com", "fb.watch", "fb.com", "tiktok.com")
MAX_BYTES = 300 * 1024 * 1024  # 300 Mo maximum par téléchargement
slots = threading.Semaphore(2)  # 2 téléchargements en même temps au maximum


def host_ok(url):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    h = u.hostname.lower()
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


@app.after_request
def cors(resp):
    origin = request.headers.get("Origin", "")
    if origin == ALLOWED_ORIGIN or origin.startswith("http://localhost"):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


@app.get("/")
def home():
    return "Résumo serveur OK"


@app.get("/audio")
def audio():
    url = request.args.get("url", "").strip()
    if not host_ok(url):
        return jsonify(error="Lien non pris en charge (Facebook ou TikTok seulement)."), 400
    if not slots.acquire(blocking=False):
        return jsonify(error="Serveur occupé, réessaie dans une minute."), 429

    tmp = tempfile.mkdtemp()
    handed_over = False
    try:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp, "media.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_BYTES,
            "socket_timeout": 30,
            "retries": 2,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = os.listdir(tmp)
        if not files:
            return jsonify(error="Vidéo introuvable ou trop lourde (limite 300 Mo)."), 502
        resp = send_file(os.path.join(tmp, files[0]), as_attachment=False)
        # Nettoyage une fois la réponse envoyée
        resp.call_on_close(lambda: (shutil.rmtree(tmp, ignore_errors=True), slots.release()))
        handed_over = True
        return resp
    except yt_dlp.utils.DownloadError:
        return jsonify(error="Impossible de récupérer cette vidéo (privée, supprimée, ou bloquée par le site)."), 502
    except Exception:
        return jsonify(error="Erreur du serveur."), 500
    finally:
        if not handed_over:
            shutil.rmtree(tmp, ignore_errors=True)
            slots.release()
