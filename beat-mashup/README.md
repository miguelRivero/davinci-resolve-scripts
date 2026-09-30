# Beat mashup para DaVinci Resolve

`beat_mashup.py` trocea al azar los vídeos de una carpeta del Media Pool y los monta a ritmo
sobre una canción, listo para exportar como videoclip.

- Cada corte empieza en un beat y dura 1, 2 o 4 beats, elegidos al azar con pesos 45 / 35 / 20. Los de 2
  y 4 beats solo empiezan donde encajan con el compás, así que en la práctica salen más cortes de 1 beat.
- El BPM lo escribes tú o se detecta de la canción que tengas en el Media Pool. También detecta dónde
  cae el primer beat.
- El mismo vídeo nunca sale dos veces seguidas, y el script intenta no repetir el mismo trozo.
- Cada vez que lo ejecutas sale un montaje distinto. Si quieres repetir uno, usa su semilla.

## Tus FX se conservan

El script solo reescribe **V1** (los cortes) y **A1** (la canción) de su timeline, que por defecto se
llama *Beat mashup*. Pon tus filtros y efectos en **adjustment clips en V2 o más arriba**, y los
títulos, overlays o sonidos extra en V2+ y A2+. Al volver a generar el montaje todo eso se queda como
está, y tus marcadores también.

No pongas efectos directamente en los cortes de V1: se rehacen cada vez.

El timeline lleva un marcador color crema llamado *Beat mashup*, con el BPM y la semilla usados. El
script lo usa para saber que ese timeline es suyo. Si lo borras, no volverá a tocar ese timeline.
Tampoco toca nunca un timeline con el mismo nombre que no haya creado él.

## Instalación

1. Instala **Python 3 de 64 bits** desde [python.org](https://www.python.org/downloads/) si no lo tienes.
   Resolve lo necesita para los scripts `.py`.
2. Desde la raíz del repo, ejecuta `python tools/install.py`. Copia el script a la carpeta de scripts
   de Resolve (en Windows, `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`).
   También puedes copiar `beat_mashup.py` ahí a mano.
3. Opcional: **ffmpeg** en el PATH, para detectar el BPM de MP3, M4A o AIFF. Con WAV no hace falta.
   Si ffmpeg no está en el PATH, pon su ruta en `CONFIG['ffmpeg']`.
4. Opcional: `pip install numpy`, que acelera el análisis.
5. Reinicia Resolve. El script aparece en **Workspace → Scripts → beat_mashup**.

## Uso

1. Crea una carpeta en el Media Pool con los vídeos que quieras mezclar y **ábrela** (selecciónala).
2. Importa la canción al Media Pool. Puede estar en esa carpeta o en cualquier otra.
3. **Workspace → Scripts → beat_mashup**. Sale una ventana con las opciones; si tu Resolve no la
   muestra, el script usa los valores de `CONFIG`, al principio del archivo.
4. Revisa el timeline, añade tus FX en V2+ y exporta desde **Deliver**.
5. ¿No te gusta el montaje? Vuelve a ejecutarlo: los cortes cambian y tus FX se quedan.

Los mensajes y el BPM detectado aparecen en **Workspace → Console**.

## Opciones

| Opción | Qué hace |
|---|---|
| BPM | `0` = detectarlo de la canción. Si sale la mitad o el doble del real, escríbelo aquí. |
| Primer beat (s) | `-1` = detectarlo. Segundos desde el inicio de la canción hasta el primer beat. |
| Desplazar compás | `-1` = adivinarlo. Si los cortes largos empiezan en el beat 2, 3 o 4 del compás en vez de en el 1, prueba con 1, 2 o 3. |
| Duración | `0` = lo que dure la canción (60 s si no hay canción). |
| Pesos 1/2/4 beats | Proporción de cada tipo de corte. Pon `0` para quitar un tipo; por ejemplo solo 4 = un corte por compás. |
| Semilla | Vacío = aleatoria. La usada queda en la consola y en el marcador crema; escríbela para repetir un montaje. |
| Marcador cada N compases | Marcadores azules para ayudarte a colocar FX a tiempo (`0` = ninguno). |
| Timeline | Nombre del timeline. Usa otro nombre para tener varias versiones a la vez, cada una con sus FX. |
| Evitar repetir trozos | Intenta no usar dos veces la misma parte de un vídeo. |

En `CONFIG` hay además: `audio_clip` (qué canción usar si hay varias), `include_subfolders`
(usar también las subcarpetas), `tempo_range` (rango de BPM al detectar) y `show_dialog`.

## Límites

- Probado contra una **simulación** de la API de scripting de Resolve, no dentro de Resolve.
  En la simulación salieron cortes seguidos sin huecos, siempre a ±1 fotograma del beat, con vídeos a
  distinto frame rate, y las pistas V2+ y los marcadores propios se conservaron al regenerar.
  La ventana de opciones solo la pude probar con una imitación de la interfaz de Resolve.
- Hace falta una versión de Resolve que admita `recordFrame` en `AppendToTimeline` (las actuales lo
  hacen). Si no, el script se para con un aviso y quita lo que había añadido.
- La detección de tempo supone un **tempo constante**. En pistas de prueba a 87, 100,5, 120, 128 y 140
  BPM acertó el tempo (como mucho 0,01 BPM de diferencia) y el primer beat (unos 5 ms de error). Con 174 BPM (drum and bass) dio 87,
  la mitad, que es la ambigüedad típica; los cortes siguen cayendo a tiempo, pero cada 2 beats. Si pasa,
  escribe el BPM. El inicio del compás es una estimación: si los cortes largos caen desplazados, usa
  *Desplazar compás*.
- Solo usa la imagen de los vídeos; su audio original no entra en el montaje.
- Si los vídeos tienen distinto frame rate que el timeline, algún corte puede quedar un fotograma antes
  o después del beat. El script lo corrige en el corte siguiente, así que el error no se acumula.
