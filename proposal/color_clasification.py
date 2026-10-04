import os
import shutil
import cv2 # type: ignore
import numpy as np
from sklearn.cluster import KMeans # type: ignore

# Configuración de rutas
CARPETA_ORIGEN = r"E:\_Internal\2022\19. resources.local.images\2022-11 Twitter\2022-11-19 22"
CARPETA_DESTINO = r"E:\_Internal\2022\19. resources.local.images\2022-11 Twitter\2022-11-19 21"

def obtener_color_dominante(ruta_imagen, k=3):
    """Extrae el color predominante de una imagen usando K-Means."""
    img = cv2.imread(ruta_imagen)
    if img is None:
        return None
    
    # Redimensionar para acelerar el procesamiento de K-Means
    img = cv2.resize(img, (150, 150), interpolation=cv2.INTER_AREA)
    
    # Convertir de BGR (OpenCV) a RGB y aplanar los píxeles
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pixeles = img_rgb.reshape((-1, 3))
    
    # Encontrar los k colores principales
    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    kmeans.fit(pixeles)
    
    # Encontrar cuál de los clusters tiene más píxeles asignados
    etiquetas, conteos = np.unique(kmeans.labels_, return_counts=True)
    color_predominante = kmeans.cluster_centers_[np.argmax(conteos)]
    
    return color_predominante.astype(int)

def clasificar_tono_hsv(color_rgb):
    """Clasifica un color RGB en una categoría básica usando el matiz (Hue) de HSV."""
    # Convertir el color RGB individual a formato compatible con OpenCV (matriz 1x1 BGR)
    color_bgr = np.uint8([[[color_rgb[2], color_rgb[1], color_rgb[0]]]])
    color_hsv = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2HSV)[0][0]
    
    h, s, v = color_hsv[0], color_hsv[1], color_hsv[2]
    
    # Si la saturación o el brillo son muy bajos, se clasifica como escala de grises
    if s < 40:
        return "Blancos_Grisaceos" if v > 180 else "Negros_Oscuros"
    if v < 40:
        return "Negros_Oscuros"
        
    # Clasificación basada en el rango de Hue (Matiz) en OpenCV (0 a 179)
    if (0 <= h < 10) or (160 <= h <= 179):
        return "Rojo"
    elif 10 <= h < 25:
        return "Naranja"
    elif 25 <= h < 35:
        return "Amarillo"
    elif 35 <= h < 85:
        return "Verde"
    elif 85 <= h < 130:
        return "Azul"
    elif 130 <= h < 160:
        return "Morado_Rosa"
    
    return "Otros"

def organizar_imagenes():
    """Función principal para procesar y mover archivos."""
    if not os.path.exists(CARPETA_DESTINO):
        os.makedirs(CARPETA_DESTINO)
        
    extensiones_validas = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
     
    for archivo in os.listdir(CARPETA_ORIGEN):
        if archivo.lower().endswith(extensiones_validas):
            ruta_completa = os.path.join(CARPETA_ORIGEN, archivo)
            
            try:
                # 1. Detectar el color más importante
                color_dom = obtener_color_dominante(ruta_completa)
                if color_dom is None:
                    continue
                
                # 2. Asignarle una categoría de color
                categoria = clasificar_tono_hsv(color_dom)
                
                # 3. Crear la carpeta correspondiente si no existe y mover el archivo
                carpeta_categoria = os.path.join(CARPETA_DESTINO, categoria)
                os.makedirs(carpeta_categoria, exist_ok=True)
                
                shutil.move(ruta_completa, os.path.join(carpeta_categoria, archivo))
                print(f"✓ {archivo} movido a -> {categoria}")
                
            except Exception as e:
                print(f"❌ Error procesando {archivo}: {e}")

if __name__ == "__main__":
    # Asegúrate de colocar tus imágenes dentro de la carpeta definida en CARPETA_ORIGEN
    print("Iniciando la organización de imágenes por color...")
    organizar_imagenes()
    print("¡Proceso completado!")
