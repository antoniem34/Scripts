# Studio PNG

Herramienta local para quitar fondo por lote manteniendo la estructura original de carpetas.

## Archivos principales

- `background_removal_app.py`: interfaz de escritorio principal.
- `web_background_app.py`: interfaz web local opcional.
- `batch_remove_background.py`: motor de procesamiento.
- `Studio PNG.ps1`: lanzador en PowerShell.
- `Studio PNG.bat`: lanzador con doble clic.
- `Studio PNG Consola.bat`: lanzador con consola para depuración.
- `procesar_quitar_fondo_terminal.ps1`: modo guiado por terminal.

## Uso

1. Abre `Studio PNG.bat` o `Studio PNG.ps1`.
2. Elige la carpeta de origen.
3. Elige la carpeta de destino.
4. Si quieres una prueba, coloca un limite de imagenes.
5. Elige si quieres `PNG Transparente` o `Preparar Graduación`.
6. Pulsa `Procesar`.

## Recomendacion de opciones

- Modelo: `birefnet-portrait`
- Refinar bordes: activado
- Autocrop: activado
- Para graduación: usar preset `Foto Normal` o `Foto Cuadro`

## Notas

- La herramienta guarda PNG con transparencia.
- Los originales no se modifican.
- La estructura interna de carpetas se conserva.
- Casos dificiles como soportes, reflejos o objetos pegados al birrete conviene revisarlos manualmente.
- En modo `Preparar Graduación`, el sujeto se recorta por transparencia, se escala, se centra y se pega al borde inferior del lienzo.
- La app limpia comillas pegadas en las rutas para evitar errores al copiar y pegar.

## Dependencias

Si hace falta reinstalar el entorno:

```powershell
python -m pip install -r requirements.txt
```
