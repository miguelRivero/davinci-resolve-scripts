# DaVinci Resolve scripts

Scripts de Python para automatizar cosas en DaVinci Resolve. Cada script vive en su propia carpeta,
con su README.

| Script | Qué hace |
|---|---|
| [beat-mashup](beat-mashup/) | Trocea al azar los vídeos de una carpeta del Media Pool y los monta a ritmo sobre una canción (BPM que indicas o detectado del audio). Solo reescribe V1 y A1, así que los FX que pongas en V2+ se conservan al regenerar. |

## Instalación

1. Instala **Python 3 de 64 bits** ([python.org](https://www.python.org/downloads/)). Resolve lo usa
   para ejecutar los scripts `.py`.
2. Desde la raíz del repo:

   ```sh
   python tools/install.py
   ```

   Copia cada script a la carpeta de scripts de Resolve, en el menú que indique su cabecera
   (`Utility` si no dice nada):

   | Sistema | Carpeta |
   |---|---|
   | Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts` |
   | macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts` |
   | Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts` |

   `--list` muestra qué haría sin copiar nada y `--uninstall` los quita. Tras un `git pull` o un
   cambio en un script, vuelve a ejecutarlo.
3. Reinicia Resolve. Los scripts aparecen en **Workspace → Scripts**, y sus mensajes en
   **Workspace → Console**.

Algunos scripts tienen requisitos propios (por ejemplo ffmpeg); lo indica su README.

## Añadir un script

1. Copia `_template/` a una carpeta nueva en kebab-case, por ejemplo `render-queue-tools/`.
2. Renombra `script_template.py` en snake_case, por ejemplo `render_queue_tools.py`. Ese nombre es el
   que se ve en el menú de Resolve, y no puede repetirse entre carpetas.
3. Elige el menú con la línea `# resolve-menu:` de la cabecera: `Utility` (todas las páginas), `Edit`,
   `Color`, `Deliver` o `Comp` (Fusion).
4. Escribe el script en `run()` y rellena el README de la carpeta.
5. `python tools/install.py` y pruébalo en Resolve.

La plantilla ya incluye cómo obtener el objeto `resolve` (desde el menú, la consola o fuera de
Resolve), una ventana de opciones opcional y mensajes de error claros. Tal cual, muestra información
del proyecto abierto, así que sirve para comprobar que Resolve ejecuta tus scripts.

### Convenciones

- **Un solo archivo por script.** Resolve copia y ejecuta el `.py` suelto, así que no se pueden
  importar módulos del repo.
- **Ajustes en `CONFIG`**, al principio del archivo, y ventana de opciones solo si Resolve la ofrece
  (si no, se usan los de `CONFIG`).
- **No destruir trabajo manual.** Un script solo modifica lo que ha creado él y lo marca para poder
  reconocerlo, como hace beat-mashup con su marcador.
- **Mensajes en la consola** con `log()`, y errores para el usuario con `Abort('…')`.
- Compatible con Python 3.6 o posterior.

## Documentación de la API

Resolve trae la referencia de su API de scripting. Ábrela desde **Help → Documentation → Developer**
(en Windows está en `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`),
en `README.txt`.
