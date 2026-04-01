from __future__ import annotations

import json
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw
import pystray

from batch_remove_background import process_batch


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "tool_settings.json"
APP_NAME = "Studio PNG"

DEFAULT_SETTINGS = {
    "models": ["birefnet-portrait", "u2net_human_seg", "bria-rmbg", "u2net"],
    "presets": {
        "normal": {
            "label": "Foto Normal",
            "canvas_width": 3600,
            "canvas_height": 4500,
            "subject_height": 4500,
            "bottom_margin": 0,
            "top_margin": 100,
            "safe_width": True,
        },
        "cuadro": {
            "label": "Foto Cuadro",
            "canvas_width": 3600,
            "canvas_height": 4500,
            "subject_height": 4500,
            "bottom_margin": 0,
            "top_margin": 100,
            "safe_width": True,
        },
    },
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    with SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(DEFAULT_SETTINGS, file, indent=2, ensure_ascii=False)
    return DEFAULT_SETTINGS


def save_settings(settings: dict) -> None:
    with SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, ensure_ascii=False)


def clean_path(value: str) -> str:
    return value.strip().strip('"').strip("'").strip()


class BackgroundRemovalApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x760")
        self.root.minsize(860, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self.settings = load_settings()
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.tray_icon: pystray.Icon | None = None

        self.input_var = tk.StringVar(value=str(Path.cwd()))
        self.output_var = tk.StringVar(value=str(Path.cwd() / "_sin_fondo_final"))
        self.model_var = tk.StringVar(value=self.settings["models"][0])
        self.limit_var = tk.StringVar(value="")
        self.alpha_var = tk.BooleanVar(value=True)
        self.autocrop_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.output_mode_var = tk.StringVar(value="transparent")
        self.preset_var = tk.StringVar(value="normal")
        self.canvas_width_var = tk.StringVar()
        self.canvas_height_var = tk.StringVar()
        self.subject_height_var = tk.StringVar()
        self.bottom_margin_var = tk.StringVar(value="0")
        self.top_margin_var = tk.StringVar(value="100")
        self.safe_width_var = tk.BooleanVar(value=True)

        self._apply_preset("normal")
        self._build_ui()
        self._setup_tray()
        self._toggle_canvas_options()
        self._poll_messages()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(6, weight=1)

        ttk.Label(
            container,
            text=APP_NAME,
            font=("Segoe UI Semibold", 18),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            container,
            text="Interfaz local para quitar fondo por lote y dejar salidas listas para Photoshop.",
        ).grid(row=1, column=0, sticky="w", pady=(4, 16))

        paths = ttk.LabelFrame(container, text="Carpetas", padding=12)
        paths.grid(row=2, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        self._path_row(paths, 0, "Carpeta origen", self.input_var, self.pick_input)
        self._path_row(paths, 1, "Carpeta destino", self.output_var, self.pick_output)

        options = ttk.LabelFrame(container, text="Opciones generales", padding=12)
        options.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for col in range(4):
            options.columnconfigure(col, weight=1)

        ttk.Label(options, text="Modelo").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.model_var,
            state="readonly",
            values=tuple(self.settings["models"]),
        ).grid(row=0, column=1, sticky="ew", padx=(8, 16))

        ttk.Label(options, text="Límite de prueba").grid(row=0, column=2, sticky="w")
        ttk.Entry(options, textvariable=self.limit_var, width=12).grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )

        ttk.Checkbutton(options, text="Refinar bordes", variable=self.alpha_var).grid(
            row=1, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Checkbutton(options, text="Limpiar aire sobrante", variable=self.autocrop_var).grid(
            row=1, column=1, sticky="w", pady=(12, 0)
        )
        ttk.Checkbutton(options, text="Sobrescribir si existe", variable=self.overwrite_var).grid(
            row=1, column=2, sticky="w", pady=(12, 0)
        )

        output = ttk.LabelFrame(container, text="Formato de salida", padding=12)
        output.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        for col in range(4):
            output.columnconfigure(col, weight=1)

        ttk.Radiobutton(
            output,
            text="PNG transparente",
            value="transparent",
            variable=self.output_mode_var,
            command=self._toggle_canvas_options,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            output,
            text="Preparar graduación",
            value="canvas",
            variable=self.output_mode_var,
            command=self._toggle_canvas_options,
        ).grid(row=0, column=1, sticky="w")

        self.canvas_frame = ttk.Frame(output)
        self.canvas_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        for col in range(4):
            self.canvas_frame.columnconfigure(col, weight=1)

        ttk.Label(self.canvas_frame, text="Preset").grid(row=0, column=0, sticky="w")
        preset_box = ttk.Combobox(
            self.canvas_frame,
            textvariable=self.preset_var,
            state="readonly",
            values=("normal", "cuadro", "custom"),
        )
        preset_box.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        preset_box.bind("<<ComboboxSelected>>", self._on_preset_change)

        ttk.Label(self.canvas_frame, text="Ancho lienzo").grid(row=0, column=2, sticky="w")
        ttk.Entry(self.canvas_frame, textvariable=self.canvas_width_var).grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )

        ttk.Label(self.canvas_frame, text="Alto lienzo").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(self.canvas_frame, textvariable=self.canvas_height_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 16), pady=(12, 0)
        )

        ttk.Label(self.canvas_frame, text="Altura sujeto").grid(row=1, column=2, sticky="w", pady=(12, 0))
        ttk.Entry(self.canvas_frame, textvariable=self.subject_height_var).grid(
            row=1, column=3, sticky="ew", padx=(8, 0), pady=(12, 0)
        )

        ttk.Label(self.canvas_frame, text="Margen inferior").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(self.canvas_frame, textvariable=self.bottom_margin_var).grid(
            row=2, column=1, sticky="ew", padx=(8, 16), pady=(12, 0)
        )
        ttk.Label(self.canvas_frame, text="Margen superior").grid(row=2, column=2, sticky="w", pady=(12, 0))
        ttk.Entry(self.canvas_frame, textvariable=self.top_margin_var).grid(
            row=2, column=3, sticky="ew", padx=(8, 0), pady=(12, 0)
        )
        ttk.Checkbutton(
            self.canvas_frame,
            text="Evitar recorte lateral",
            variable=self.safe_width_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))

        ttk.Button(self.canvas_frame, text="Guardar como Foto Normal", command=lambda: self._save_preset("normal")).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0), padx=(0, 8)
        )
        ttk.Button(self.canvas_frame, text="Guardar como Foto Cuadro", command=lambda: self._save_preset("cuadro")).grid(
            row=4, column=2, columnspan=2, sticky="ew", pady=(12, 0)
        )

        actions = ttk.Frame(container)
        actions.grid(row=5, column=0, sticky="ew", pady=(12, 12))

        self.run_button = ttk.Button(actions, text="Procesar", command=self.start_processing)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="Abrir destino", command=self.open_output_folder).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Limpiar log", command=self.clear_log).pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Listo para procesar.")
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        log_frame = ttk.LabelFrame(container, text="Progreso", padding=10)
        log_frame.grid(row=6, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            wrap="word",
            font=("Consolas", 10),
            state="disabled",
            bg="#111111",
            fg="#f2f2f2",
            insertbackground="#f2f2f2",
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=(0, 10))
        ttk.Button(parent, text="Elegir...", command=command).grid(row=row, column=2, sticky="ew", pady=(0, 10))

    def _apply_preset(self, preset_name: str) -> None:
        preset = self.settings["presets"][preset_name]
        self.canvas_width_var.set(str(preset["canvas_width"]))
        self.canvas_height_var.set(str(preset["canvas_height"]))
        self.subject_height_var.set(str(preset["subject_height"]))
        self.bottom_margin_var.set(str(preset["bottom_margin"]))
        self.top_margin_var.set(str(preset.get("top_margin", 100)))
        self.safe_width_var.set(bool(preset["safe_width"]))

    def _save_preset(self, preset_name: str) -> None:
        try:
            self.settings["presets"][preset_name].update(
                {
                    "canvas_width": int(self.canvas_width_var.get()),
                    "canvas_height": int(self.canvas_height_var.get()),
                    "subject_height": int(self.subject_height_var.get()),
                    "bottom_margin": int(self.bottom_margin_var.get()),
                    "top_margin": int(self.top_margin_var.get()),
                    "safe_width": bool(self.safe_width_var.get()),
                }
            )
        except ValueError:
            messagebox.showerror("Preset", "Los valores del preset deben ser números enteros.")
            return
        save_settings(self.settings)
        messagebox.showinfo("Preset", f"Preset {preset_name} guardado.")

    def _on_preset_change(self, _event=None) -> None:
        if self.preset_var.get() in {"normal", "cuadro"}:
            self._apply_preset(self.preset_var.get())

    def _toggle_canvas_options(self) -> None:
        state = "normal" if self.output_mode_var.get() == "canvas" else "disabled"
        for child in self.canvas_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def pick_input(self) -> None:
        path = filedialog.askdirectory(initialdir=clean_path(self.input_var.get()) or str(Path.cwd()))
        if path:
            self.input_var.set(path)
            current_output = clean_path(self.output_var.get())
            if not current_output or current_output.endswith("_sin_fondo_final"):
                self.output_var.set(str(Path(path) / "_sin_fondo_final"))

    def pick_output(self) -> None:
        path = filedialog.askdirectory(initialdir=clean_path(self.output_var.get()) or str(Path.cwd()))
        if path:
            self.output_var.set(path)

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _create_tray_image(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=16, fill=(22, 122, 138, 255))
        draw.rounded_rectangle((18, 16, 46, 48), radius=10, fill=(246, 248, 250, 255))
        draw.rectangle((24, 20, 40, 26), fill=(22, 122, 138, 255))
        draw.rectangle((24, 30, 40, 36), fill=(22, 122, 138, 255))
        draw.rectangle((24, 40, 34, 44), fill=(22, 122, 138, 255))
        return image

    def _setup_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Studio PNG", self._tray_open),
            pystray.MenuItem("Salir", self._tray_exit),
        )
        self.tray_icon = pystray.Icon(APP_NAME, self._create_tray_image(), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _tray_open(self, icon=None, item=None) -> None:
        self.root.after(0, self.show_from_tray)

    def _tray_exit(self, icon=None, item=None) -> None:
        self.root.after(0, self.exit_app)

    def hide_to_tray(self) -> None:
        self.root.withdraw()

    def show_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_app(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def start_processing(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("En progreso", "Ya hay un proceso ejecutandose.")
            return

        input_dir = Path(clean_path(self.input_var.get())).expanduser()
        output_dir = Path(clean_path(self.output_var.get())).expanduser()
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Carpeta origen", "Selecciona una carpeta de origen valida.")
            return
        if not output_dir.parent.exists():
            messagebox.showerror("Carpeta destino", "La carpeta padre del destino no existe.")
            return

        limit = None
        if self.limit_var.get().strip():
            try:
                limit = int(self.limit_var.get().strip())
            except ValueError:
                messagebox.showerror("Limite", "El limite debe ser un numero entero.")
                return

        try:
            canvas_width = int(self.canvas_width_var.get() or "3600")
            canvas_height = int(self.canvas_height_var.get() or "4500")
            subject_height = int(self.subject_height_var.get() or str(canvas_height))
            bottom_margin = int(self.bottom_margin_var.get() or "0")
            top_margin = int(self.top_margin_var.get() or "100")
        except ValueError:
            messagebox.showerror("Graduación", "Los valores de graduación deben ser números enteros.")
            return

        self.run_button.configure(state="disabled")
        self.status_var.set("Procesando...")
        self.append_log("")
        self.append_log("Inicio de proceso")
        self.append_log(f"Origen: {input_dir}")
        self.append_log(f"Destino: {output_dir}")

        self.worker = threading.Thread(
            target=self._run_batch,
            kwargs={
                "input_dir": input_dir,
                "output_dir": output_dir,
                "limit": limit,
                "canvas_width": canvas_width,
                "canvas_height": canvas_height,
                "subject_height": subject_height,
                "bottom_margin": bottom_margin,
                "top_margin": top_margin,
            },
            daemon=True,
        )
        self.worker.start()

    def _run_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        limit: int | None,
        canvas_width: int,
        canvas_height: int,
        subject_height: int,
        bottom_margin: int,
        top_margin: int,
    ) -> None:
        try:
            exit_code = process_batch(
                input_root=input_dir,
                output_root=output_dir,
                model=self.model_var.get(),
                limit=limit,
                overwrite=self.overwrite_var.get(),
                alpha_matting=self.alpha_var.get(),
                autocrop=self.autocrop_var.get(),
                output_mode=self.output_mode_var.get(),
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                subject_height=subject_height,
                bottom_margin=bottom_margin,
                top_margin=top_margin,
                safe_width=self.safe_width_var.get(),
                progress_callback=lambda message: self.messages.put(("log", message)),
            )
            if exit_code == 0:
                self.messages.put(("done", f"Proceso terminado. Salida en {output_dir}"))
            else:
                self.messages.put(("error", "No se encontraron imagenes para procesar."))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "done":
                    self.run_button.configure(state="normal")
                    self.status_var.set("Completado")
                    self.append_log(payload)
                    messagebox.showinfo("Proceso completado", payload)
                elif kind == "error":
                    self.run_button.configure(state="normal")
                    self.status_var.set("Error")
                    self.append_log(f"ERROR: {payload}")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_messages)

    def open_output_folder(self) -> None:
        path = Path(clean_path(self.output_var.get())).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(path.resolve())])


def main() -> None:
    root = tk.Tk()
    BackgroundRemovalApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
