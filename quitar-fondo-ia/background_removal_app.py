from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from batch_remove_background import process_batch


class BackgroundRemovalApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Quitar Fondo por Lote")
        self.root.geometry("860x620")
        self.root.minsize(760, 560)

        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.input_var = tk.StringVar(value=str(Path.cwd()))
        self.output_var = tk.StringVar(value=str(Path.cwd() / "_sin_fondo_final"))
        self.model_var = tk.StringVar(value="birefnet-portrait")
        self.limit_var = tk.StringVar(value="")
        self.alpha_var = tk.BooleanVar(value=True)
        self.autocrop_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._poll_messages()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(6, weight=1)

        title = ttk.Label(
            container,
            text="Herramienta de Quitar Fondo",
            font=("Segoe UI Semibold", 18),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        subtitle = ttk.Label(
            container,
            text="Elige la carpeta de origen y la carpeta de destino. La estructura interna se conserva.",
        )
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 18))

        self._path_row(container, 2, "Carpeta origen", self.input_var, self.pick_input)
        self._path_row(container, 3, "Carpeta destino", self.output_var, self.pick_output)

        options = ttk.LabelFrame(container, text="Opciones", padding=12)
        options.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)

        ttk.Label(options, text="Modelo").grid(row=0, column=0, sticky="w")
        model_box = ttk.Combobox(
            options,
            textvariable=self.model_var,
            state="readonly",
            values=("birefnet-portrait", "u2net_human_seg", "bria-rmbg", "u2net"),
        )
        model_box.grid(row=0, column=1, sticky="ew", padx=(8, 16))

        ttk.Label(options, text="Limite de prueba").grid(row=0, column=2, sticky="w")
        ttk.Entry(options, textvariable=self.limit_var, width=12).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )

        ttk.Checkbutton(
            options,
            text="Refinar bordes (alpha matting)",
            variable=self.alpha_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))

        ttk.Checkbutton(
            options,
            text="Autocrop al sujeto",
            variable=self.autocrop_var,
        ).grid(row=1, column=2, sticky="w", pady=(12, 0))

        ttk.Checkbutton(
            options,
            text="Sobrescribir si ya existe",
            variable=self.overwrite_var,
        ).grid(row=1, column=3, sticky="w", pady=(12, 0))

        actions = ttk.Frame(container)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        self.run_button = ttk.Button(actions, text="Procesar", command=self.start_processing)
        self.run_button.pack(side="left")

        ttk.Button(actions, text="Abrir destino", command=self.open_output_folder).pack(
            side="left", padx=(8, 0)
        )

        ttk.Button(actions, text="Limpiar log", command=self.clear_log).pack(
            side="left", padx=(8, 0)
        )

        self.status_var = tk.StringVar(value="Listo para procesar.")
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        log_frame = ttk.LabelFrame(container, text="Progreso", padding=10)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew")
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

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(12, 8), pady=(0, 10)
        )
        ttk.Button(parent, text="Elegir...", command=command).grid(
            row=row, column=2, sticky="ew", pady=(0, 10)
        )

    def pick_input(self) -> None:
        path = filedialog.askdirectory(initialdir=self.input_var.get() or str(Path.cwd()))
        if path:
            self.input_var.set(path)
            current_output = Path(self.output_var.get())
            if current_output == Path.cwd() / "_sin_fondo_final":
                self.output_var.set(str(Path(path) / "_sin_fondo_final"))

    def pick_output(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if path:
            self.output_var.set(path)

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def start_processing(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("En progreso", "Ya hay un proceso ejecutandose.")
            return

        input_dir = Path(self.input_var.get()).expanduser()
        output_dir = Path(self.output_var.get()).expanduser()
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Carpeta origen", "Selecciona una carpeta de origen valida.")
            return
        if not output_dir.parent.exists():
            messagebox.showerror("Carpeta destino", "La carpeta padre del destino no existe.")
            return

        limit_text = self.limit_var.get().strip()
        limit = None
        if limit_text:
            try:
                limit = int(limit_text)
            except ValueError:
                messagebox.showerror("Limite", "El limite debe ser un numero entero.")
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
            },
            daemon=True,
        )
        self.worker.start()

    def _run_batch(self, input_dir: Path, output_dir: Path, limit: int | None) -> None:
        try:
            exit_code = process_batch(
                input_root=input_dir,
                output_root=output_dir,
                model=self.model_var.get(),
                limit=limit,
                overwrite=self.overwrite_var.get(),
                alpha_matting=self.alpha_var.get(),
                autocrop=self.autocrop_var.get(),
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
        path = Path(self.output_var.get())
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        path = path.resolve()
        self.root.after(0, lambda: Path(path).mkdir(parents=True, exist_ok=True))
        import subprocess

        subprocess.Popen(["explorer", str(path)])


def main() -> None:
    root = tk.Tk()
    BackgroundRemovalApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
