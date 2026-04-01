from __future__ import annotations

import argparse
import os
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable
from datetime import datetime

from PIL import Image, ImageOps
try:
    import torch
except Exception:  # pragma: no cover - fallback if torch is unavailable
    torch = None

if torch is not None:
    torch_lib = Path(torch.__file__).resolve().parent / "lib"
    if torch_lib.exists() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(torch_lib))

import onnxruntime as ort
from rembg import new_session, remove


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


ProgressCallback = Callable[[str], None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quita el fondo de imagenes en lote y guarda PNG con transparencia."
    )
    parser.add_argument(
        "input_root",
        nargs="?",
        default=".",
        help="Carpeta donde estan las imagenes originales.",
    )
    parser.add_argument(
        "--output-root",
        default="_sin_fondo",
        help="Carpeta de salida. Se crea sin tocar los originales.",
    )
    parser.add_argument(
        "--model",
        default="birefnet-portrait",
        help="Modelo de rembg. Para retratos suele ir bien birefnet-portrait.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Procesa solo N imagenes para hacer una prueba rapida.",
    )
    parser.add_argument(
        "--include-folder",
        action="append",
        default=[],
        help="Procesa solo carpetas que contengan este texto. Se puede repetir.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reemplaza PNG ya generados.",
    )
    parser.add_argument(
        "--no-subdirs",
        action="store_true",
        help="No busca en subcarpetas.",
    )
    parser.add_argument(
        "--alpha-matting",
        action="store_true",
        help="Refina bordes delicados. Es mas lento pero puede mejorar cabello y velos.",
    )
    parser.add_argument(
        "--alpha-matting-foreground-threshold",
        type=int,
        default=240,
        help="Umbral de primer plano para alpha matting.",
    )
    parser.add_argument(
        "--alpha-matting-background-threshold",
        type=int,
        default=10,
        help="Umbral de fondo para alpha matting.",
    )
    parser.add_argument(
        "--alpha-matting-erode-size",
        type=int,
        default=10,
        help="Tamano de erosion para alpha matting.",
    )
    parser.add_argument(
        "--autocrop",
        action="store_true",
        help="Recorta al sujeto con un margen extra.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.08,
        help="Margen extra al recortar alrededor del sujeto.",
    )
    parser.add_argument(
        "--reference",
        default=None,
        help="Imagen de referencia para usar su proporcion final.",
    )
    parser.add_argument(
        "--output-mode",
        choices=("transparent", "canvas"),
        default="transparent",
        help="transparent mantiene PNG recortado; canvas lo monta en un lienzo fijo.",
    )
    parser.add_argument(
        "--canvas-width",
        type=int,
        default=3600,
        help="Ancho del lienzo final cuando se usa output-mode canvas.",
    )
    parser.add_argument(
        "--canvas-height",
        type=int,
        default=4500,
        help="Alto del lienzo final cuando se usa output-mode canvas.",
    )
    parser.add_argument(
        "--subject-height",
        type=int,
        default=None,
        help="Altura objetivo del sujeto ya recortado al montarlo en canvas.",
    )
    parser.add_argument(
        "--bottom-margin",
        type=int,
        default=0,
        help="Margen inferior en pixeles dentro del lienzo final.",
    )
    parser.add_argument(
        "--top-margin",
        type=int,
        default=100,
        help="Margen superior minimo en pixeles dentro del lienzo final.",
    )
    parser.add_argument(
        "--allow-overflow-width",
        action="store_true",
        help="Permite que el sujeto sobrepase el ancho del lienzo al escalar por altura.",
    )
    return parser.parse_args()


def iter_images(
    input_root: Path, include_filters: list[str], recursive: bool
) -> Iterable[Path]:
    walker = input_root.rglob("*") if recursive else input_root.glob("*")
    filters = [item.lower() for item in include_filters]

    for path in walker:
        if not path.is_file():
            continue
        if path.name.startswith("._"):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative = str(path.relative_to(input_root)).lower()
        if filters and not any(token in relative for token in filters):
            continue
        yield path


def build_output_path(input_root: Path, output_root: Path, source: Path) -> Path:
    try:
        relative = source.relative_to(input_root)
    except ValueError:
        relative = Path(os.path.relpath(source, input_root))
    return output_root / relative.with_suffix(".png")


def safe_relative_text(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.relpath(path, root)


def crop_to_subject(image: Image.Image, padding: float, target_ratio: float | None) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return image

    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    pad_x = int(width * padding)
    pad_y = int(height * padding)

    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(image.width, right + pad_x)
    bottom = min(image.height, bottom + pad_y)

    if target_ratio:
        crop_w = right - left
        crop_h = bottom - top
        current_ratio = crop_w / crop_h

        if current_ratio < target_ratio:
            desired_w = int(round(crop_h * target_ratio))
            extra = desired_w - crop_w
            left = max(0, left - extra // 2)
            right = min(image.width, right + extra - extra // 2)
        else:
            desired_h = int(round(crop_w / target_ratio))
            extra = desired_h - crop_h
            top = max(0, top - extra // 2)
            bottom = min(image.height, bottom + extra - extra // 2)

    return image.crop((left, top, right, bottom))


def trim_to_alpha(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def compose_on_canvas(
    image: Image.Image,
    *,
    canvas_width: int,
    canvas_height: int,
    subject_height: int | None,
    bottom_margin: int = 0,
    top_margin: int = 100,
    safe_width: bool = True,
) -> Image.Image:
    trimmed = trim_to_alpha(image)
    if trimmed.width == 0 or trimmed.height == 0:
        return Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))

    target_height = subject_height or canvas_height
    scale = target_height / trimmed.height

    if safe_width and round(trimmed.width * scale) > canvas_width:
        scale = canvas_width / trimmed.width

    available_height = canvas_height - bottom_margin - top_margin
    if available_height > 0 and round(trimmed.height * scale) > available_height:
        scale = available_height / trimmed.height

    resized_width = max(1, round(trimmed.width * scale))
    resized_height = max(1, round(trimmed.height * scale))
    resized = trimmed.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    x = (canvas_width - resized.width) // 2
    y = canvas_height - bottom_margin - resized.height
    y = max(top_margin, y)
    canvas.alpha_composite(resized, (x, y))
    return canvas


def load_normalized_image(source: Path) -> tuple[bytes, tuple[int, int] | None]:
    with Image.open(source) as image:
        normalized = ImageOps.exif_transpose(image)
        dpi = image.info.get("dpi")

        if normalized.mode not in {"RGB", "RGBA"}:
            normalized = normalized.convert("RGB")

        buffer = BytesIO()
        normalized.save(buffer, format="PNG")
        return buffer.getvalue(), dpi


def process_batch(
    input_root: str | Path,
    output_root: str | Path = "_sin_fondo",
    *,
    model: str = "birefnet-portrait",
    limit: int | None = None,
    include_folder: list[str] | None = None,
    overwrite: bool = False,
    no_subdirs: bool = False,
    alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 240,
    alpha_matting_background_threshold: int = 10,
    alpha_matting_erode_size: int = 10,
    autocrop: bool = False,
    padding: float = 0.08,
    reference: str | Path | None = None,
    output_mode: str = "transparent",
    canvas_width: int = 3600,
    canvas_height: int = 4500,
    subject_height: int | None = None,
    bottom_margin: int = 0,
    top_margin: int = 100,
    safe_width: bool = True,
    log_file: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> int:
    log_path: Path | None = None
    if log_file:
        log_path = Path(log_file)
    elif output_root:
        candidate_root = Path(output_root)
        if not candidate_root.is_absolute():
            candidate_root = (Path(input_root).resolve() / candidate_root).resolve()
        log_path = candidate_root / "log.txt"

    def log(message: str) -> None:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with log_path.open("a", encoding="utf-8") as file:
                file.write(f"[{timestamp}] {message}\n")
        if progress_callback is not None:
            progress_callback(message)
        else:
            print(message)

    input_root = Path(input_root).resolve()
    output_root = Path(output_root)
    if not output_root.is_absolute():
        output_root = (input_root / output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if "CUDAExecutionProvider" in ort.get_available_providers()
        else ["CPUExecutionProvider"]
    )

    target_ratio = None
    if reference:
        with Image.open(reference) as ref:
            target_ratio = ref.width / ref.height

    images = list(
        iter_images(
            input_root=input_root,
            include_filters=include_folder or [],
            recursive=not no_subdirs,
        )
    )
    if limit is not None:
        images = images[:limit]

    if not images:
        log("No encontre imagenes que coincidan con los filtros.")
        return 1

    session = new_session(model, providers=providers)
    total = len(images)
    done = 0
    skipped = 0

    log(f"Procesando {total} imagen(es) con modelo '{model}'...")
    log(f"Providers ONNX: {providers}")
    log(f"Salida: {output_root}")

    for index, source in enumerate(images, start=1):
        target = build_output_path(input_root, output_root, source)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and not overwrite:
            skipped += 1
            log(f"[{index}/{total}] Saltada: {source.name} (ya existe)")
            continue

        input_bytes, dpi = load_normalized_image(source)

        output_bytes = remove(
            input_bytes,
            session=session,
            alpha_matting=alpha_matting,
            alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=alpha_matting_background_threshold,
            alpha_matting_erode_size=alpha_matting_erode_size,
        )

        with Image.open(BytesIO(output_bytes)) as result:
            result = result.convert("RGBA")
            if autocrop:
                result = crop_to_subject(
                    result,
                    padding=padding,
                    target_ratio=target_ratio,
                )
            if output_mode == "canvas":
                result = compose_on_canvas(
                    result,
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                    subject_height=subject_height,
                    bottom_margin=bottom_margin,
                    top_margin=top_margin,
                    safe_width=safe_width,
                )
            save_kwargs = {"format": "PNG"}
            if dpi:
                save_kwargs["dpi"] = dpi
            result.save(target, **save_kwargs)

        done += 1
        log(f"[{index}/{total}] OK -> {safe_relative_text(target, input_root)}")

    log("")
    log(f"Listo. Generadas: {done} | Saltadas: {skipped} | Total vistas: {total}")
    return 0


def main() -> int:
    args = parse_args()
    return process_batch(
        input_root=args.input_root,
        output_root=args.output_root,
        model=args.model,
        limit=args.limit,
        include_folder=args.include_folder,
        overwrite=args.overwrite,
        no_subdirs=args.no_subdirs,
        alpha_matting=args.alpha_matting,
        alpha_matting_foreground_threshold=args.alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=args.alpha_matting_background_threshold,
        alpha_matting_erode_size=args.alpha_matting_erode_size,
        autocrop=args.autocrop,
        padding=args.padding,
        reference=args.reference,
        output_mode=args.output_mode,
        canvas_width=args.canvas_width,
        canvas_height=args.canvas_height,
        subject_height=args.subject_height,
        bottom_margin=args.bottom_margin,
        top_margin=args.top_margin,
        safe_width=not args.allow_overflow_width,
    )


if __name__ == "__main__":
    raise SystemExit(main())
