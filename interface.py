"""
BitTune v3 - Frontend Flet 0.84
Busqueda tipo Spotify con resultados visuales
"""

import flet as ft
import httpx
import threading
import time
import os
import sys
from pathlib import Path

API_URL = "https://bittune-api.onrender.com"

CARPETA_MUSICA = Path.home() / "Music" / "BitTune"
CARPETA_MUSICA.mkdir(parents=True, exist_ok=True)

# ---- Keepalive: despierta Render cada 50 segundos ----
def _keepalive():
    while True:
        try:
            httpx.get(f"{API_URL}/health", timeout=15)
            print("[keepalive] servidor despierto OK")
        except Exception as e:
            print(f"[keepalive] sin respuesta: {e}")
        time.sleep(50)

threading.Thread(target=_keepalive, daemon=True).start()
# -------------------------------------------------------

# Colores
BG          = "#0A0E13"
SURFACE     = "#111820"
CARD        = "#161E28"
CARD_HOVER  = "#1C2633"
BORDER      = "#1F2D3D"
ACCENT      = "#1ED760"
ACCENT2     = "#FF6B00"
GOLD        = "#F5A623"
TEXT        = "#E8F0F7"
MUTED       = "#4A6072"
ERROR       = "#FF4757"
SUCCESS     = "#1ED760"


def main(page: ft.Page):
    page.title = "BitTune"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window_width = 560
    page.window_height = 860
    page.window_resizable = True
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 0
    page.scroll = ft.ScrollMode.HIDDEN

    estado = {
        "formato": "flac",
        "buscando": False,
        "cola": [],
        "descargando": False,
        "historial": [],
        "servidor_listo": False,
    }

    # ================================================================
    # HELPERS
    # ================================================================
    def fmt_views(n):
        if not n:
            return ""
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M vistas"
        if n >= 1_000:
            return f"{n/1_000:.0f}K vistas"
        return f"{n} vistas"

    # ================================================================
    # HEADER
    # ================================================================
    status_text = ft.Text("Conectando al servidor...", color=MUTED, size=12, text_align=ft.TextAlign.CENTER)
    progress_ring = ft.ProgressRing(visible=True, color=ACCENT, width=16, height=16, stroke_width=2)

    header = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text("Bit", size=28, weight=ft.FontWeight.W_900, color=TEXT),
                                ft.Text("Tune", size=28, weight=ft.FontWeight.W_900, color=ACCENT),
                            ],
                            spacing=0,
                        ),
                        ft.Text("Free Music · Ultra HD Quality", size=10, color=MUTED),
                    ],
                    spacing=1,
                ),
                ft.Container(expand=True),
                ft.Row(
                    [progress_ring, status_text],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE,
        padding=ft.padding.symmetric(horizontal=24, vertical=16),
    )

    # ================================================================
    # BUSCADOR
    # ================================================================
    search_field = ft.TextField(
        hint_text="Buscar cancion, artista...",
        hint_style=ft.TextStyle(color=MUTED),
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        cursor_color=ACCENT,
        bgcolor=CARD,
        border_radius=30,
        content_padding=ft.padding.only(left=20, right=12, top=14, bottom=14),
        on_submit=lambda _: hacer_busqueda(),
        on_change=lambda e: on_search_change(e),
        expand=True,
    )

    btn_buscar = ft.Container(
        content=ft.Text("Buscar", color="#000", weight=ft.FontWeight.BOLD, size=13),
        bgcolor=ACCENT,
        border_radius=30,
        padding=ft.padding.symmetric(horizontal=20, vertical=14),
        on_click=lambda _: hacer_busqueda(),
        ink=True,
    )

    search_row = ft.Row(
        [search_field, btn_buscar],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Selector formato
    btn_flac = ft.Container(
        content=ft.Text("FLAC", size=11, weight=ft.FontWeight.BOLD, color="#000"),
        bgcolor=ACCENT,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=14, vertical=6),
        on_click=lambda _: set_formato("flac"),
        ink=True,
        tooltip="Sin perdida de calidad",
    )
    btn_mp3 = ft.Container(
        content=ft.Text("MP3 320k", size=11, weight=ft.FontWeight.BOLD, color=MUTED),
        bgcolor=CARD,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=14, vertical=6),
        on_click=lambda _: set_formato("mp3"),
        ink=True,
        tooltip="Alta calidad comprimida",
    )

    def set_formato(fmt):
        estado["formato"] = fmt
        if fmt == "flac":
            btn_flac.bgcolor = ACCENT
            btn_flac.content.color = "#000"
            btn_mp3.bgcolor = CARD
            btn_mp3.content.color = MUTED
        else:
            btn_mp3.bgcolor = ACCENT2
            btn_mp3.content.color = "#000"
            btn_flac.bgcolor = CARD
            btn_flac.content.color = MUTED
        page.update()

    formato_row = ft.Row(
        [
            ft.Text("Formato:", size=11, color=MUTED),
            btn_flac,
            btn_mp3,
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # ================================================================
    # RESULTADOS DE BUSQUEDA
    # ================================================================
    resultados_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    resultados_container = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("RESULTADOS", size=10, color=MUTED, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Text("YouTube Music", size=10, color=MUTED),
                    ]
                ),
                ft.Container(height=6),
                resultados_column,
            ]
        ),
        visible=False,
        bgcolor=SURFACE,
        border_radius=16,
        padding=16,
    )

    def build_resultado_card(track):
        vid_id = track["id"]
        titulo = track["title"]
        artista = track["artist"]
        duracion = track["duration"]
        thumbnail = track["thumbnail"]
        views = fmt_views(track.get("views", 0))

        btn_dl = ft.Container(
            content=ft.Text("⬇", size=18, color=ACCENT2),
            on_click=lambda _, t=titulo, a=artista, v=vid_id: descargar_uno(v, t, a),
            ink=True,
            border_radius=8,
            padding=6,
            tooltip="Descargar",
        )

        btn_cola = ft.Container(
            content=ft.Text("+", size=20, color=MUTED, weight=ft.FontWeight.BOLD),
            on_click=lambda _, t=titulo, a=artista, v=vid_id: agregar_cola(v, t, a),
            ink=True,
            border_radius=8,
            padding=6,
            tooltip="Agregar a la cola",
        )

        titulo_corto = titulo[:44] + "..." if len(titulo) > 44 else titulo
        artista_corto = artista[:30] + "..." if len(artista) > 30 else artista

        card = ft.Container(
            content=ft.Row(
                [
                    # Thumbnail
                    ft.Container(
                        content=ft.Image(
                            src=thumbnail,
                            width=54,
                            height=54,
                            fit=ft.ImageFit.COVER,
                            error_content=ft.Container(
                                content=ft.Text("🎵", size=22),
                                width=54,
                                height=54,
                                bgcolor=CARD,
                                alignment=ft.alignment.center,
                                border_radius=8,
                            ),
                        ),
                        border_radius=8,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        width=54,
                        height=54,
                    ),
                    # Info
                    ft.Column(
                        [
                            ft.Text(titulo_corto, color=TEXT, size=13, weight=ft.FontWeight.W_600),
                            ft.Text(artista_corto, color=MUTED, size=11),
                            ft.Text(views, color=MUTED, size=10) if views else ft.Container(height=0),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    # Controles derecha
                    ft.Column(
                        [
                            ft.Text(duracion, size=10, color=MUTED),
                            ft.Row([btn_cola, btn_dl], spacing=0),
                        ],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            bgcolor=CARD,
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ink=True,
        )
        return card

    # ================================================================
    # COLA DE DESCARGAS
    # ================================================================
    cola_column = ft.Column(spacing=6)

    cola_container = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("COLA", size=10, color=MUTED, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Container(
                            content=ft.Text("⬇  Descargar todo", size=11, color="#000", weight=ft.FontWeight.BOLD),
                            bgcolor=ACCENT2,
                            border_radius=20,
                            padding=ft.padding.symmetric(horizontal=12, vertical=5),
                            on_click=lambda _: descargar_cola_completa(),
                            ink=True,
                        ),
                    ]
                ),
                ft.Container(height=8),
                cola_column,
            ]
        ),
        visible=False,
        bgcolor=SURFACE,
        border_radius=16,
        padding=16,
    )

    def actualizar_cola_ui():
        cola_column.controls.clear()
        for i, item in enumerate(estado["cola"]):
            titulo_c = item["title"][:38] + "..." if len(item["title"]) > 38 else item["title"]
            fila = ft.Container(
                content=ft.Row(
                    [
                        ft.Text(str(i + 1), size=10, color=MUTED, width=18),
                        ft.Text("🎵", size=12),
                        ft.Column(
                            [
                                ft.Text(titulo_c, color=TEXT, size=12),
                                ft.Text(item["artist"], color=MUTED, size=10),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(item["format"].upper(), size=9, color="#000", weight=ft.FontWeight.BOLD),
                            bgcolor=ACCENT if item["format"] == "flac" else ACCENT2,
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        ),
                        ft.Container(
                            content=ft.Text("✕", color=ERROR, size=12),
                            on_click=lambda _, idx=i: quitar_cola(idx),
                            ink=True,
                            border_radius=6,
                            padding=4,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=CARD,
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
            )
            cola_column.controls.append(fila)
        cola_container.visible = len(estado["cola"]) > 0
        page.update()

    def agregar_cola(vid_id, titulo, artista):
        estado["cola"].append({
            "id": vid_id,
            "title": titulo,
            "artist": artista,
            "format": estado["formato"],
        })
        actualizar_cola_ui()
        status_text.value = f"'{titulo[:25]}' en cola"
        status_text.color = ACCENT2
        page.update()

    def quitar_cola(idx):
        if 0 <= idx < len(estado["cola"]):
            estado["cola"].pop(idx)
            actualizar_cola_ui()

    # ================================================================
    # HISTORIAL
    # ================================================================
    historial_column = ft.Column(spacing=6)

    historial_container = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("DESCARGADAS", size=10, color=MUTED, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Container(
                            content=ft.Text("Abrir carpeta 📁", size=11, color=MUTED),
                            on_click=lambda _: abrir_carpeta(),
                            ink=True,
                            border_radius=6,
                            padding=4,
                        ),
                    ]
                ),
                ft.Container(height=8),
                historial_column,
            ]
        ),
        visible=False,
        bgcolor=SURFACE,
        border_radius=16,
        padding=16,
    )

    def agregar_historial(titulo, artista, size_mb, ext):
        titulo_c = titulo[:38] + "..." if len(titulo) > 38 else titulo
        artista_c = artista[:24] + "..." if len(artista) > 24 else artista
        badge_bg = ACCENT if ext == "flac" else ACCENT2

        item = ft.Container(
            content=ft.Row(
                [
                    ft.Text("✓", color=SUCCESS, size=14, weight=ft.FontWeight.BOLD),
                    ft.Column(
                        [
                            ft.Text(titulo_c, color=TEXT, size=12, weight=ft.FontWeight.W_600),
                            ft.Text(artista_c, color=MUTED, size=10),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Column(
                        [
                            ft.Container(
                                content=ft.Text(ext.upper(), size=9, color="#000", weight=ft.FontWeight.BOLD),
                                bgcolor=badge_bg,
                                border_radius=4,
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            ),
                            ft.Text(f"{size_mb} MB", color=MUTED, size=10),
                        ],
                        spacing=3,
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            bgcolor=CARD,
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
        )
        historial_column.controls.insert(0, item)
        if len(historial_column.controls) > 20:
            historial_column.controls.pop()
        historial_container.visible = True
        page.update()

    # ================================================================
    # DESCARGA
    # ================================================================
    progress_bar = ft.ProgressBar(
        visible=False, color=ACCENT, bgcolor=BORDER, height=2, border_radius=1
    )

    def poll_y_guardar(job_id, titulo, artista, fmt):
        max_intentos = 180  # 6 minutos max
        for _ in range(max_intentos):
            try:
                r = httpx.get(f"{API_URL}/status/{job_id}", timeout=15)
                data = r.json()
                s = data.get("status", "")

                if s == "downloading":
                    status_text.value = f"Convirtiendo a {fmt.upper()}..."
                    page.update()

                elif s == "done":
                    status_text.value = "Guardando en tu PC..."
                    page.update()

                    archivo_r = httpx.get(f"{API_URL}/file/{job_id}", timeout=300)
                    ext = data.get("extension", fmt)
                    titulo_limpio = titulo.replace("/", "-").replace("\\", "-")[:60]
                    ruta = CARPETA_MUSICA / f"{titulo_limpio}.{ext}"
                    ruta.write_bytes(archivo_r.content)

                    size_mb = round(ruta.stat().st_size / (1024 * 1024), 2)
                    httpx.delete(f"{API_URL}/job/{job_id}", timeout=10)

                    status_text.value = "✓ Descargado"
                    status_text.color = SUCCESS
                    progress_ring.visible = False
                    progress_bar.visible = False
                    agregar_historial(titulo, artista, size_mb, ext)
                    estado["descargando"] = False

                    if estado["cola"]:
                        siguiente = estado["cola"].pop(0)
                        actualizar_cola_ui()
                        time.sleep(0.5)
                        _lanzar_job(siguiente["id"], siguiente["title"], siguiente["artist"], siguiente["format"])
                    page.update()
                    return

                elif s == "error":
                    status_text.value = f"Error: {data.get('error','')[:50]}"
                    status_text.color = ERROR
                    progress_ring.visible = False
                    progress_bar.visible = False
                    estado["descargando"] = False
                    page.update()
                    return

            except Exception as ex:
                status_text.value = "Esperando servidor..."
                page.update()

            time.sleep(2)

        status_text.value = "Tiempo agotado"
        status_text.color = ERROR
        progress_ring.visible = False
        progress_bar.visible = False
        estado["descargando"] = False
        page.update()

    def _lanzar_job(vid_id, titulo, artista, fmt):
        estado["descargando"] = True
        progress_ring.visible = True
        progress_bar.visible = True
        status_text.value = f"Descargando: {titulo[:30]}..."
        status_text.color = MUTED
        page.update()

        try:
            r = httpx.post(
                f"{API_URL}/download",
                json={"video_id": vid_id, "title": titulo, "format": fmt},
                timeout=60,
            )
            job_id = r.json()["job_id"]
            hilo = threading.Thread(
                target=poll_y_guardar,
                args=(job_id, titulo, artista, fmt),
                daemon=True,
            )
            hilo.start()
        except Exception as e:
            status_text.value = "No se pudo conectar al servidor"
            status_text.color = ERROR
            progress_ring.visible = False
            progress_bar.visible = False
            estado["descargando"] = False
            page.update()

    def descargar_uno(vid_id, titulo, artista):
        if estado["descargando"]:
            agregar_cola(vid_id, titulo, artista)
            return
        _lanzar_job(vid_id, titulo, artista, estado["formato"])

    def descargar_cola_completa():
        if not estado["cola"] or estado["descargando"]:
            return
        primera = estado["cola"].pop(0)
        actualizar_cola_ui()
        _lanzar_job(primera["id"], primera["title"], primera["artist"], primera["format"])

    # ================================================================
    # BUSQUEDA
    # ================================================================
    no_results_text = ft.Text("", color=MUTED, size=13, text_align=ft.TextAlign.CENTER, visible=False)

    _search_timer = [None]

    def on_search_change(e):
        if _search_timer[0]:
            _search_timer[0].cancel()
        if len(e.control.value.strip()) >= 3:
            _search_timer[0] = threading.Timer(0.9, hacer_busqueda)
            _search_timer[0].start()

    def hacer_busqueda():
        query = search_field.value.strip()
        if not query or estado["buscando"]:
            return

        estado["buscando"] = True
        resultados_column.controls.clear()
        no_results_text.visible = False
        resultados_container.visible = True
        status_text.value = "Buscando..."
        status_text.color = MUTED
        progress_ring.visible = True
        page.update()

        def _buscar():
            try:
                r = httpx.post(
                    f"{API_URL}/search",
                    json={"query": query, "max_results": 8},
                    timeout=60,   # 60s para dar tiempo a que despierte Render
                )
                data = r.json()
                resultados = data.get("results", [])

                resultados_column.controls.clear()

                if not resultados:
                    no_results_text.value = "Sin resultados"
                    no_results_text.visible = True
                else:
                    for track in resultados:
                        card = build_resultado_card(track)
                        resultados_column.controls.append(card)

                status_text.value = f"{len(resultados)} resultados"
                status_text.color = MUTED

            except httpx.TimeoutException:
                status_text.value = "Servidor tardando, reintenta en 10s"
                status_text.color = ACCENT2
            except Exception as e:
                status_text.value = f"Error: {str(e)[:40]}"
                status_text.color = ERROR

            finally:
                estado["buscando"] = False
                progress_ring.visible = False
                page.update()

        threading.Thread(target=_buscar, daemon=True).start()

    # ================================================================
    # VERIFICAR SERVIDOR AL INICIO
    # ================================================================
    def verificar_servidor():
        for intento in range(6):  # intenta hasta 60s
            try:
                r = httpx.get(f"{API_URL}/health", timeout=12)
                if r.status_code == 200:
                    status_text.value = "Listo para buscar"
                    status_text.color = SUCCESS
                    progress_ring.visible = False
                    estado["servidor_listo"] = True
                    page.update()
                    return
            except:
                status_text.value = f"Despertando servidor... ({intento+1}/6)"
                status_text.color = ACCENT2
                progress_ring.visible = True
                page.update()
            time.sleep(10)

        status_text.value = "Servidor no responde — reintenta"
        status_text.color = ERROR
        progress_ring.visible = False
        page.update()

    threading.Thread(target=verificar_servidor, daemon=True).start()

    # ================================================================
    # UTILS
    # ================================================================
    def abrir_carpeta():
        if os.name == "nt":
            os.startfile(str(CARPETA_MUSICA))
        elif sys.platform == "darwin":
            os.system(f'open "{CARPETA_MUSICA}"')
        else:
            os.system(f'xdg-open "{CARPETA_MUSICA}"')

    # ================================================================
    # LAYOUT
    # ================================================================
    contenido = ft.Column(
        [
            ft.Container(height=10),
            formato_row,
            ft.Container(height=12),
            search_row,
            ft.Container(height=4),
            progress_bar,
            ft.Container(height=8),
            no_results_text,
            resultados_container,
            ft.Container(height=10),
            cola_container,
            ft.Container(height=10),
            historial_container,
            ft.Container(height=20),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=0,
    )

    page.add(
        ft.Column(
            [
                header,
                ft.Container(
                    content=contenido,
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=20, vertical=0),
                ),
            ],
            expand=True,
            spacing=0,
        )
    )


if __name__ == "__main__":
    ft.app(target=main)