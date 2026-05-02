"""
BitTune Backend v3 - FastAPI + yt-dlp + FFmpeg (via imageio-ffmpeg)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import threading
from pathlib import Path
import time

# ---- Instala FFmpeg via imageio-ffmpeg (funciona en Render free) ----
try:
    import imageio_ffmpeg
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = str(Path(ffmpeg_path).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"[ffmpeg] encontrado en: {ffmpeg_path}")
except Exception as e:
    print(f"[ffmpeg] no se pudo cargar imageio-ffmpeg: {e}")
# ---------------------------------------------------------------------

app = FastAPI(title="BitTune API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path("/tmp/bittune")
DOWNLOAD_DIR.mkdir(exist_ok=True)

download_jobs: dict = {}


class SearchQuery(BaseModel):
    query: str
    max_results: int = 8


class DownloadRequest(BaseModel):
    video_id: str
    title: str
    format: str = "flac"


def limpiar_viejos():
    ahora = time.time()
    for f in DOWNLOAD_DIR.glob("*"):
        try:
            if ahora - f.stat().st_mtime > 3600:
                f.unlink(missing_ok=True)
        except:
            pass


def segundos_a_tiempo(seg):
    if not seg:
        return "0:00"
    m, s = divmod(int(seg), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@app.get("/")
def root():
    return {"app": "BitTune API", "version": "3.0.0", "status": "online"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def buscar(req: SearchQuery):
    try:
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "default_search": f"ytsearch{req.max_results}",
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.query, download=False)

        resultados = []
        entradas = info.get("entries", []) if info else []

        for entry in entradas:
            if not entry:
                continue
            vid_id = entry.get("id", "")
            resultados.append({
                "id": vid_id,
                "title": entry.get("title", "Sin titulo"),
                "artist": entry.get("uploader", entry.get("channel", "Desconocido")),
                "duration": segundos_a_tiempo(entry.get("duration")),
                "duration_sec": entry.get("duration", 0),
                "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
                "url": f"https://youtube.com/watch?v={vid_id}",
                "views": entry.get("view_count", 0),
            })

        return {"results": resultados, "total": len(resultados)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def hacer_descarga(job_id: str, video_url: str, title: str, fmt: str):
    try:
        download_jobs[job_id]["status"] = "downloading"

        output_path = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

        if fmt == "flac":
            pp = [{"key": "FFmpegExtractAudio", "preferredcodec": "flac", "preferredquality": "0"}]
        else:
            pp = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}]

        pp.append({"key": "FFmpegMetadata", "add_metadata": True})

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_path,
            "postprocessors": pp,
            "quiet": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        ext = "flac" if fmt == "flac" else "mp3"
        archivo = DOWNLOAD_DIR / f"{job_id}.{ext}"

        if not archivo.exists():
            posibles = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
            if posibles:
                archivo = posibles[0]
                ext = archivo.suffix.lstrip(".")
            else:
                raise FileNotFoundError("Archivo no encontrado tras descarga")

        download_jobs[job_id].update({
            "status": "done",
            "filename": archivo.name,
            "extension": ext,
            "size_mb": round(archivo.stat().st_size / (1024 * 1024), 2),
        })

    except Exception as e:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["error"] = str(e)
        print(f"[ERROR] {job_id}: {e}")


@app.post("/download")
def iniciar_descarga(req: DownloadRequest):
    limpiar_viejos()
    job_id = str(uuid.uuid4())
    video_url = f"https://youtube.com/watch?v={req.video_id}"

    download_jobs[job_id] = {
        "status": "queued",
        "title": req.title,
        "format": req.format,
    }

    hilo = threading.Thread(
        target=hacer_descarga,
        args=(job_id, video_url, req.title, req.format),
        daemon=True,
    )
    hilo.start()

    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}")
def estado(job_id: str):
    if job_id not in download_jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return download_jobs[job_id]


@app.get("/file/{job_id}")
def obtener_archivo(job_id: str):
    if job_id not in download_jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    job = download_jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Estado: {job['status']}")

    archivo = DOWNLOAD_DIR / job["filename"]
    if not archivo.exists():
        raise HTTPException(status_code=404, detail="Archivo no disponible")

    titulo_limpio = job["title"].replace("/", "-").replace("\\", "-")[:60]
    nombre = f"{titulo_limpio}.{job['extension']}"

    return FileResponse(path=str(archivo), media_type="application/octet-stream", filename=nombre)


@app.delete("/job/{job_id}")
def eliminar_job(job_id: str):
    if job_id in download_jobs:
        job = download_jobs[job_id]
        if "filename" in job:
            (DOWNLOAD_DIR / job["filename"]).unlink(missing_ok=True)
        del download_jobs[job_id]
    return {"deleted": job_id}