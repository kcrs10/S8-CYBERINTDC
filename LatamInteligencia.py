#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de Reputación Empresarial (LATAM) - Pipeline OSINT con interfaz gráfica

Requisitos:  pip install feedparser requests pandas
Ejecución:   python monitor_latam_gui.py

"""

import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

import feedparser
import pandas as pd
import requests

# --------------------------------------------------------------------------
# CONFIGURACIÓN DEL PIPELINE
# --------------------------------------------------------------------------
FEEDS = {
    "Google News (Chile)": "https://news.google.com/rss/search?q=LATAM+Airlines+Group&hl=es-419&gl=CL&ceid=CL:es-419",
    "Google News (Perú)": "https://news.google.com/rss/search?q=LATAM+Airlines+Group&hl=es-419&gl=PE&ceid=PE:es-419",
    "Google News (Brasil)": "https://news.google.com/rss/search?q=LATAM+Airlines+Group&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "Bing News (Corp)": "https://www.bing.com/news/search?q=latam+airlines+group&format=rss",
}
PALABRAS_RIESGO = [
    "retraso", "huelga", "sernac", "indecopi", "acciones", "cancelación", "emergencia",
    "falla", "reclamo", "atraso", "greve", "cancelamento",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
COLUMNAS = ["Fuente", "Título", "Fecha", "Estado", "Riesgo_Detectado", "Enlace"]
CARPETA_SALIDA = "resultados"

# --------------------------------------------------------------------------
# PALETA
# --------------------------------------------------------------------------
BG, PANEL, PANEL2, BORDER = "#0b1220", "#141c2e", "#1b2540", "#2a3552"
TEXT, MUTED = "#e5eaf5", "#8b97b3"
ACCENT, RED, GREEN, AMBER = "#3b82f6", "#ef4444", "#22c55e", "#f59e0b"
FUENTE_UI = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
FUENTE_MONO = "Consolas" if sys.platform.startswith("win") else "Courier"


def parsear_fecha(entrada) -> str:
    crudo = entrada.get("published") or entrada.get("updated")
    if crudo:
        try:
            return parsedate_to_datetime(crudo).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(crudo)
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def detectar_riesgo(titulo: str) -> list:
    t = titulo.lower()
    return [p for p in PALABRAS_RIESGO if re.search(r"\b" + re.escape(p), t)]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor de Reputación Empresarial · LATAM · OSINT")
        self.geometry("1200x760")
        self.minsize(1000, 640)
        self.configure(bg=BG)
        self.cola = queue.Queue()
        self.df = pd.DataFrame(columns=COLUMNAS)
        self.orden_col, self.orden_inv = None, False
        self.escaneando = False
        self._estilos()
        self._construir()
        self.after(100, self._procesar_cola)

    # ------------------------------------------------------------------ estilos
    def _estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=(FUENTE_UI, 10))
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("TButton", background=PANEL2, foreground=TEXT, borderwidth=0,
                    padding=(14, 8), font=(FUENTE_UI, 10))
        s.map("TButton", background=[("active", BORDER), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=(FUENTE_UI, 10, "bold"), padding=(18, 9))
        s.map("Accent.TButton", background=[("active", "#2563eb"), ("disabled", "#1e3a6e")],
              foreground=[("disabled", "#9db4de")])
        s.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=PANEL2, darkcolor=PANEL2,
                    padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
              foreground=[("readonly", TEXT)], selectbackground=[("readonly", PANEL2)],
              selectforeground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", PANEL2)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=30, borderwidth=0)
        s.map("Treeview", background=[("selected", "#27407a")], foreground=[("selected", "white")])
        s.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, relief="flat",
                    font=(FUENTE_UI, 9, "bold"), padding=8)
        s.map("Treeview.Heading", background=[("active", BORDER)])
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook", lightcolor=BG, darkcolor=BG, bordercolor=BG)
        s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 9), borderwidth=0,
                    lightcolor=BG, darkcolor=BG, bordercolor=BG)
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        s.configure("Horizontal.TProgressbar", troughcolor=PANEL2, background=ACCENT,
                    bordercolor=PANEL2, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
        for orient in ("Vertical", "Horizontal"):
            s.configure(f"{orient}.TScrollbar", background=BORDER, troughcolor=PANEL,
                        bordercolor=PANEL, lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=MUTED, relief="flat", gripcount=0)
            s.map(f"{orient}.TScrollbar", background=[("active", MUTED)])
        s.configure("Treeview", bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ---------------------------------------------------------------------- UI
    def _construir(self):
        raiz = ttk.Frame(self, padding=(22, 18))
        raiz.pack(fill="both", expand=True)

        # Encabezado
        cab = ttk.Frame(raiz)
        cab.pack(fill="x")
        izq = ttk.Frame(cab)
        izq.pack(side="left")
        tk.Label(izq, text="Monitor de Reputación Empresarial", bg=BG, fg=TEXT,
                 font=(FUENTE_UI, 18, "bold")).pack(anchor="w")
        tk.Label(izq, text="LATAM Airlines Group  ·  OSINT sobre feeds RSS públicos",
                 bg=BG, fg=MUTED, font=(FUENTE_UI, 10)).pack(anchor="w")
        self.estado_var = tk.StringVar(value="● Listo")
        self.estado_lbl = tk.Label(cab, textvariable=self.estado_var, bg=PANEL2, fg=GREEN,
                                   font=(FUENTE_UI, 10, "bold"), padx=14, pady=6)
        self.estado_lbl.pack(side="right")

        # Barra de herramientas
        barra = ttk.Frame(raiz)
        barra.pack(fill="x", pady=(16, 10))
        self.btn_scan = ttk.Button(barra, text="▶  Iniciar escaneo", style="Accent.TButton",
                                   command=self.iniciar)
        self.btn_scan.pack(side="left")
        self.btn_csv = ttk.Button(barra, text="Exportar CSV", command=lambda: self.exportar("csv"))
        self.btn_csv.pack(side="left", padx=(8, 0))
        self.btn_json = ttk.Button(barra, text="Exportar JSON", command=lambda: self.exportar("json"))
        self.btn_json.pack(side="left", padx=(8, 0))
        ttk.Button(barra, text="Abrir carpeta", command=self.abrir_carpeta).pack(side="left", padx=(8, 0))

        self.busqueda = tk.StringVar()
        self.busqueda.trace_add("write", lambda *_: self._refrescar_tabla())
        ttk.Entry(barra, textvariable=self.busqueda, width=26).pack(side="right")
        tk.Label(barra, text="Buscar", bg=BG, fg=MUTED).pack(side="right", padx=(14, 6))
        self.filtro = tk.StringVar(value="Todas")
        cb = ttk.Combobox(barra, textvariable=self.filtro, state="readonly", width=13,
                          values=["Todas", "Alerta Alta", "Informativo"])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refrescar_tabla())
        tk.Label(barra, text="Estado", bg=BG, fg=MUTED).pack(side="right", padx=(14, 6))

        # Tarjetas de métricas
        tarjetas = ttk.Frame(raiz)
        tarjetas.pack(fill="x")
        self.m_total = self._tarjeta(tarjetas, "NOTICIAS RELEVANTES", ACCENT)
        self.m_alta = self._tarjeta(tarjetas, "ALERTAS ALTAS", RED)
        self.m_info = self._tarjeta(tarjetas, "INFORMATIVAS", GREEN)
        self.m_feeds = self._tarjeta(tarjetas, "FEEDS ACTIVOS", AMBER)
        for i in range(4):
            tarjetas.columnconfigure(i, weight=1, uniform="t")

        self.progreso = ttk.Progressbar(raiz, mode="determinate", maximum=len(FEEDS))
        self.progreso.pack(fill="x", pady=(14, 10))

        # Pestañas
        nb = ttk.Notebook(raiz)
        nb.pack(fill="both", expand=True)
        self.tab_res = ttk.Frame(nb, style="Panel.TFrame")
        self.tab_est = ttk.Frame(nb, style="Panel.TFrame")
        self.tab_log = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(self.tab_res, text="Resultados")
        nb.add(self.tab_est, text="Estadísticas")
        nb.add(self.tab_log, text="Registros")
        self._tab_resultados()

        self.txt_est = tk.Text(self.tab_est, bg=PANEL, fg=TEXT, bd=0, padx=22, pady=18,
                               font=(FUENTE_MONO, 10), wrap="word", state="disabled",
                               highlightthickness=0)
        self.txt_est.pack(fill="both", expand=True)
        self.txt_est.tag_configure("h", foreground=ACCENT, font=(FUENTE_UI, 11, "bold"),
                                   spacing1=12, spacing3=4)
        self.txt_est.tag_configure("m", foreground=MUTED)

        self.consola = scrolledtext.ScrolledText(self.tab_log, bg="#070b14", fg="#4ade80", bd=0,
                                                 padx=14, pady=12, font=(FUENTE_MONO, 10),
                                                 insertbackground="#4ade80", highlightthickness=0)
        self.consola.pack(fill="both", expand=True)
        self._log("Sistema listo. Presione «Iniciar escaneo OSINT» para comenzar la recolección.")

    def _tarjeta(self, padre, titulo, color):
        col = padre.grid_size()[0]
        f = tk.Frame(padre, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        f.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 10, 0))
        tk.Frame(f, bg=color, height=3).pack(fill="x")
        var = tk.StringVar(value="—")
        tk.Label(f, textvariable=var, bg=PANEL, fg=color, font=(FUENTE_UI, 26, "bold")).pack(
            anchor="w", padx=16, pady=(10, 0))
        tk.Label(f, text=titulo, bg=PANEL, fg=MUTED, font=(FUENTE_UI, 8, "bold")).pack(
            anchor="w", padx=16, pady=(0, 12))
        return var

    def _tab_resultados(self):
        marco = ttk.Frame(self.tab_res, style="Panel.TFrame")
        marco.pack(fill="both", expand=True, padx=2, pady=2)
        cols = ("Estado", "Fuente", "Fecha", "Título", "Riesgo")
        self.tabla = ttk.Treeview(marco, columns=cols, show="headings", selectmode="browse")
        anchos = {"Estado": 105, "Fuente": 150, "Fecha": 125, "Título": 560, "Riesgo": 170}
        for c in cols:
            self.tabla.heading(c, text=c, command=lambda c=c: self._ordenar(c))
            self.tabla.column(c, width=anchos[c], anchor="w", stretch=(c == "Título"))
        vs = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        hs = ttk.Scrollbar(marco, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tabla.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)
        self.tabla.tag_configure("alta", foreground="#fca5a5")
        self.tabla.tag_configure("info", foreground=TEXT)
        self.tabla.tag_configure("par", background="#171f35")
        self.tabla.bind("<<TreeviewSelect>>", self._mostrar_detalle)
        self.tabla.bind("<Double-1>", self._abrir_enlace)

        self.detalle = tk.StringVar(value="Seleccione una noticia para ver el detalle · doble clic abre el enlace.")
        tk.Label(marco, textvariable=self.detalle, bg=PANEL2, fg=MUTED, anchor="w", justify="left",
                 wraplength=1050, padx=14, pady=10, font=(FUENTE_UI, 9)).grid(
            row=2, column=0, columnspan=2, sticky="ew")

    # ----------------------------------------------------------------- acciones
    def _log(self, texto):
        self.consola.insert(tk.END, texto + "\n")
        self.consola.see(tk.END)

    def _estado(self, texto, color):
        self.estado_var.set(texto)
        self.estado_lbl.config(fg=color)

    def iniciar(self):
        if self.escaneando:
            return
        self.escaneando = True
        self.btn_scan.config(state="disabled")
        self.progreso["value"] = 0
        self._estado("● Escaneando…", AMBER)
        self._log("\n[*] Iniciando monitorización de reputación para LATAM...")
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _pipeline(self):
        """Corre en un hilo; solo se comunica con la UI mediante la cola."""
        noticias, ok = [], 0
        for i, (fuente, url) in enumerate(FEEDS.items(), 1):
            self.cola.put(("log", f"[*] Extrayendo datos de: {fuente}"))
            try:
                r = requests.get(url, headers=HEADERS, timeout=12)
                r.raise_for_status()
                feed = feedparser.parse(r.content)
                n = 0
                for e in feed.entries:
                    titulo = (e.get("title") or "").strip()
                    if "latam" not in titulo.lower():
                        continue
                    riesgo = detectar_riesgo(titulo)
                    noticias.append({
                        "Fuente": fuente, "Título": titulo, "Fecha": parsear_fecha(e),
                        "Estado": "Alerta Alta" if riesgo else "Informativo",
                        "Riesgo_Detectado": ", ".join(riesgo) if riesgo else "Ninguno",
                        "Enlace": e.get("link", ""),
                    })
                    n += 1
                ok += 1
                self.cola.put(("log", f"    [+] {len(feed.entries)} entradas leídas · {n} relevantes"))
            except Exception as exc:  # noqa: BLE001
                self.cola.put(("log", f"[!] Error de conexión con {fuente}: {exc}"))
            self.cola.put(("progreso", i))
        df = pd.DataFrame(noticias, columns=COLUMNAS)
        df = df.drop_duplicates(subset="Título").reset_index(drop=True)
        self.cola.put(("fin", df, ok))

    def _procesar_cola(self):
        try:
            while True:
                msg = self.cola.get_nowait()
                if msg[0] == "log":
                    self._log(msg[1])
                elif msg[0] == "progreso":
                    self.progreso["value"] = msg[1]
                elif msg[0] == "fin":
                    self._finalizar(msg[1], msg[2])
        except queue.Empty:
            pass
        self.after(100, self._procesar_cola)

    def _finalizar(self, df, feeds_ok):
        self.df = df
        altas = int((df["Estado"] == "Alerta Alta").sum()) if not df.empty else 0
        self.m_total.set(str(len(df)))
        self.m_alta.set(str(altas))
        self.m_info.set(str(len(df) - altas))
        self.m_feeds.set(f"{feeds_ok}/{len(FEEDS)}")
        self._log("\n" + "=" * 46 + "\n          ESTADÍSTICAS DE INTELIGENCIA\n" + "=" * 46)
        self._log(f"[+] Total de noticias procesadas: {len(df)}")
        if df.empty:
            self._log("[-] No se registraron menciones de la empresa.")
            self._estado("● Sin resultados", MUTED)
        else:
            self._log(f"[!] Total de alertas críticas (Riesgo): {altas}")
            self._autoguardar()
            self._estado("● Alerta alta" if altas else "● Completado", RED if altas else GREEN)
        self._refrescar_tabla()
        self._refrescar_estadisticas()
        self.escaneando = False
        self.btn_scan.config(state="normal")

    def _autoguardar(self):
        os.makedirs(CARPETA_SALIDA, exist_ok=True)
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(CARPETA_SALIDA, f"reporte_OSINT_latam_{sello}")
        self.df.to_csv(base + ".csv", index=False, encoding="utf-8-sig")
        self.df.to_json(base + ".json", orient="records", force_ascii=False, indent=2)
        self._log(f"\n[+] Archivos exportados con éxito:\n    {base}.csv\n    {base}.json")

    # ------------------------------------------------------------------- tabla
    def _vista(self):
        df = self.df
        if df.empty:
            return df
        if self.filtro.get() != "Todas":
            df = df[df["Estado"] == self.filtro.get()]
        q = self.busqueda.get().strip().lower()
        if q:
            df = df[df["Título"].str.lower().str.contains(q, regex=False)
                    | df["Fuente"].str.lower().str.contains(q, regex=False)]
        if self.orden_col:
            col = {"Riesgo": "Riesgo_Detectado"}.get(self.orden_col, self.orden_col)
            df = df.sort_values(col, ascending=not self.orden_inv, kind="stable")
        else:
            df = df.sort_values(["Estado", "Fecha"], ascending=[True, False])
        return df

    def _refrescar_tabla(self):
        for i in self.tabla.get_children():
            self.tabla.delete(i)
        for n, (idx, f) in enumerate(self._vista().iterrows()):
            tags = ("alta" if f["Estado"] == "Alerta Alta" else "info",) + (("par",) if n % 2 else ())
            self.tabla.insert("", "end", iid=str(idx), tags=tags,
                              values=(f["Estado"], f["Fuente"], f["Fecha"], f["Título"],
                                      f["Riesgo_Detectado"]))

    def _ordenar(self, col):
        self.orden_inv = (not self.orden_inv) if self.orden_col == col else False
        self.orden_col = col
        self._refrescar_tabla()

    def _mostrar_detalle(self, _e=None):
        sel = self.tabla.selection()
        if sel:
            f = self.df.loc[int(sel[0])]
            self.detalle.set(f"{f['Título']}\n{f['Fuente']} · {f['Fecha']} · Riesgo: "
                             f"{f['Riesgo_Detectado']}\n{f['Enlace']}")

    def _abrir_enlace(self, _e=None):
        sel = self.tabla.selection()
        if sel and self.df.loc[int(sel[0])]["Enlace"]:
            webbrowser.open(self.df.loc[int(sel[0])]["Enlace"])

    # ------------------------------------------------------------ estadísticas
    def _refrescar_estadisticas(self):
        t = self.txt_est
        t.config(state="normal")
        t.delete("1.0", tk.END)
        df = self.df
        if df.empty:
            t.insert(tk.END, "Sin datos. Ejecute un escaneo.", "m")
        else:
            def barras(titulo, conteo):
                t.insert(tk.END, titulo + "\n", "h")
                mx = max(conteo.values()) or 1
                for k, v in conteo.items():
                    t.insert(tk.END, f"{str(k)[:28]:<30}{'█' * max(1, round(v / mx * 30)):<32} {v}\n")
            barras("Noticias por fuente", df["Fuente"].value_counts().to_dict())
            barras("Distribución por estado", df["Estado"].value_counts().to_dict())
            riesgos = Counter(p for s in df["Riesgo_Detectado"] if s != "Ninguno" for p in s.split(", "))
            if riesgos:
                barras("Palabras de riesgo más frecuentes", dict(riesgos.most_common(10)))
            else:
                t.insert(tk.END, "Palabras de riesgo más frecuentes\n", "h")
                t.insert(tk.END, "No se detectaron términos de riesgo en esta ejecución.\n", "m")
        t.config(state="disabled")

    # ------------------------------------------------------------------ export
    def exportar(self, formato):
        if self.df.empty:
            messagebox.showwarning(
                "Sin datos para exportar",
                "Todavía no hay resultados.\n\nEjecute un escaneo primero. Si ya lo hizo y no "
                "aparecen noticias, revise la pestaña «Registro» para ver si algún feed falló.")
            return
        ruta = filedialog.asksaveasfilename(
            parent=self, title=f"Exportar {formato.upper()}", defaultextension="." + formato,
            filetypes=[(formato.upper(), "*." + formato), ("Todos los archivos", "*.*")],
            initialfile=f"reporte_OSINT_latam_{datetime.now():%Y%m%d_%H%M%S}.{formato}")
        if not ruta:
            return
        try:
            if formato == "csv":
                self.df.to_csv(ruta, index=False, encoding="utf-8-sig")
            else:
                self.df.to_json(ruta, orient="records", force_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror("No se pudo guardar",
                                 f"{exc}\n\nSi el archivo está abierto en Excel, ciérrelo e intente de nuevo.")
            return
        self._log(f"[+] Exportado: {ruta}")
        messagebox.showinfo("Exportación", f"Archivo guardado en:\n{ruta}")

    def abrir_carpeta(self):
        os.makedirs(CARPETA_SALIDA, exist_ok=True)
        ruta = os.path.abspath(CARPETA_SALIDA)
        if sys.platform.startswith("win"):
            os.startfile(ruta)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", ruta])
        else:
            subprocess.Popen(["xdg-open", ruta])


if __name__ == "__main__":
    try:  # nitidez en pantallas HiDPI de Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    App().mainloop()