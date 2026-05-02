"""
BitTune Backend v3 - FastAPI + yt-dlp + FFmpeg
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

# ---- FFmpeg via imageio-ffmpeg ----
try:
    import imageio_ffmpeg
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = str(Path(ffmpeg_path).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"[ffmpeg] OK: {ffmpeg_path}")
except Exception as e:
    print(f"[ffmpeg] error: {e}")

app = FastAPI(title="BitTune API", version="3.1.0")

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
    return {"app": "BitTune API", "version": "3.1.0", "status": "online"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def buscar(req: SearchQuery):
    try:
        resultados = []

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }

        search_url = f"ytsearch{req.max_results}:{req.query}"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)

        entradas = []
        if info:
            if "entries" in info:
                entradas = [e for e in info["entries"] if e]
            elif info.get("id"):
                entradas = [info]

        for entry in entradas:
            vid_id = entry.get("id", "")
            if not vid_id:
                continue
            resultados.append({
                "id": vid_id,
                "title": entry.get("title") or "Sin titulo",
                "artist": entry.get("uploader") or entry.get("channel") or "Desconocido",
                "duration": segundos_a_tiempo(entry.get("duration")),
                "duration_sec": entry.get("duration") or 0,
                "thumbnail": (
                    entry.get("thumbnail")
                    or (entry.get("thumbnails") or [{}])[-1].get("url", "")
                    or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
                ),
                "url": f"https://youtube.com/watch?v={vid_id}",
                "views": entry.get("view_count") or 0,
            })

        print(f"[search] '{req.query}' -> {len(resultados)} resultados")
        return {"results": resultados, "total": len(resultados)}

    except Exception as e:
        print(f"[search ERROR] {e}")
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
                raise FileNotFoundError("Archivo no encontrado")

        download_jobs[job_id].update({
            "status": "done",
            "filename": archivo.name,
            "extension": ext,
            "size_mb": round(archivo.stat().st_size / (1024 * 1024), 2),
        })
        print(f"[download] done: {archivo.name}")

    except Exception as e:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["error"] = str(e)
        print(f"[download ERROR] {job_id}: {e}")


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

    threading.Thread(
        target=hacer_descarga,
        args=(job_id, video_url, req.title, req.format),
        daemon=True,
    ).start()

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