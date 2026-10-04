import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QWidgetAction, QWidget, QHBoxLayout, QPushButton, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Menú Contextual Windows 11")
        self.resize(600, 400)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.mostrar_menu)

    def mostrar_menu(self, posicion: QPoint):
        menu = QMenu(self)
        
        # Flags para transparencia y bordes redondeados reales
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # -----------------------------------------------------------------
        # 1. CREAR LA BARRA HORIZONTAL DE ICONOS (Widget Personalizado)
        # -----------------------------------------------------------------
        contenedor_barra = QWidget()
        layout_barra = QHBoxLayout(contenedor_barra)
        # Ajustamos márgenes estrechos para que se vea compacto
        layout_barra.setContentsMargins(6, 4, 6, 4)
        layout_barra.setSpacing(4)

        # Definimos los botones rápidos (puedes usar iconos reales con setIcon)
        iconos_rapidos = [
            ("✂️", "Cortar"),
            ("📄", "Copiar"),
            ("✏️", "Cambiar nombre"),
            ("🗑️", "Eliminar")
        ]

        for texto, tooltip in iconos_rapidos:
            btn = QPushButton(texto)
            btn.setToolTip(tooltip)
            btn.setFixedSize(36, 36) # Botones perfectamente cuadrados
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Estilo individual para cada botón de la barra rápida
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px; /* Tamaño del emoji/icono */
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 0.05);
                }
            """)
            
            # Conectar la acción aquí (ej. btn.clicked.connect(self.tu_funcion))
            layout_barra.addWidget(btn)
            
        # Añadir un espacio flexible al final para empujar los botones a la izquierda si es necesario
        layout_barra.addStretch()

        # 2. INCORPORAR LA BARRA HORIZONTAL AL QMENU
        accion_barra = QWidgetAction(menu)
        accion_barra.setDefaultWidget(contenedor_barra)
        menu.addAction(accion_barra)
        
        # Separador entre la barra de iconos y las opciones de texto
        menu.addSeparator()

        # -----------------------------------------------------------------
        # 3. ACCIONES TRADICIONALES DE TEXTO
        # -----------------------------------------------------------------
        menu.addAction("Abrir")
        menu.addAction("Propiedades")

        # -----------------------------------------------------------------
        # 4. HOJA DE ESTILOS GENERAL (QSS)
        # -----------------------------------------------------------------
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(32, 32, 32, 0.9); /* Fondo Fluent Oscuro */
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                color: #FFFFFF;
            }
            QMenu::item {
                background-color: transparent;
                padding: 6px 40px 6px 12px; /* Padding ajustado */
                margin: 2px 2px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.08);
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.1);
                margin: 4px 6px;
            }
        """)

        # Sombra difuminada de Windows 11
        sombra = QGraphicsDropShadowEffect(menu)
        sombra.setBlurRadius(20)
        sombra.setColor(QColor(0, 0, 0, 150))
        sombra.setOffset(0, 5)
        menu.setGraphicsEffect(sombra)

        # Mostrar el menú
        menu.exec(self.mapToGlobal(posicion))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())
