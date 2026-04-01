# Quitar Fondo IA

Herramienta de escritorio para quitar fondo por lote manteniendo la estructura original de carpetas.

## Archivos principales

- `background_removal_app.py`: interfaz grafica.
- `batch_remove_background.py`: motor de procesamiento.
- `abrir_herramienta_quitar_fondo.ps1`: lanzador en PowerShell.
- `abrir_herramienta_quitar_fondo.bat`: lanzador con doble clic.

## Uso

1. Abre `abrir_herramienta_quitar_fondo.bat` o `abrir_herramienta_quitar_fondo.ps1`.
2. Elige la carpeta de origen.
3. Elige la carpeta de destino.
4. Si quieres una prueba, coloca un limite de imagenes.
5. Pulsa `Procesar`.

## Recomendacion de opciones

- Modelo: `birefnet-portrait`
- Refinar bordes: activado
- Autocrop: activado

## Notas

- La herramienta guarda PNG con transparencia.
- Los originales no se modifican.
- La estructura interna de carpetas se conserva.
- Casos dificiles como soportes, reflejos o objetos pegados al birrete conviene revisarlos manualmente.

## Dependencias

Si hace falta reinstalar el entorno:

```powershell
python -m pip install -r requirements.txt
```
