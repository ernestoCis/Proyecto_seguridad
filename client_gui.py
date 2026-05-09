# client_gui.py
# Este archivo implementa el cliente grafico "Juatsapp" usando PyQt5.
# Permite al usuario conectarse a un servidor de chat por TCP o por UDP,
# enviar y recibir mensajes en una interfaz tipo chat con lista de usuarios,
# manejo de conversaciones, mensajes privados e imagenes.

import sys
import socket
import threading
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLineEdit, QPushButton, QLabel, QListWidget,
    QStackedLayout, QComboBox, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal


# Direccion del servidor y puertos para TCP y UDP.
SERVER_HOST = "127.0.0.1" #Laptop: 192.168.100.52 / Local: 127.0.0.1
TCP_PORT = 5000
UDP_PORT = 5001


class ChatBubble(QLabel):
    """Burbuja de mensaje con soporte HTML y color segun si es mio o no."""
    def __init__(self, html_text, is_mine=False):
        # Crea una etiqueta que se usara como burbuja de chat.
        # html_text puede contener HTML para dar formato al mensaje.
        # is_mine indica si el mensaje es del propio usuario (color distinto).
        super().__init__(html_text)
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)

        base_style = """
            border-radius: 10px;
            padding: 8px;
            margin: 5px;
            font-size: 14px;
        """

        # Se elige el color de fondo dependiendo de si el mensaje es propio o de otros.
        if is_mine:
            bg = "#d4f8c6"  # verde claro tipo WhatsApp para mensajes propios
        else:
            bg = "#e0e0e0"  # gris para mensajes de otros

        self.setStyleSheet(f"background-color: {bg}; {base_style}")


class ChatWindow(QWidget):
    # Señal que se emite cuando se recibe un mensaje desde el socket.
    # Se usa para actualizar la interfaz en el hilo principal de Qt.
    message_received = pyqtSignal(str)

    def __init__(self, protocol, nickname, sock, initial_data=None):
        # protocol: "TCP" o "UDP"
        # nickname: nick ya validado por el servidor
        # sock: socket ya conectado y con el nick aceptado
        # initial_data: texto inicial recibido tras el /nick
        super().__init__()

        # Socket compartido por la ventana para enviar y recibir mensajes.
        self.sock = sock
        # Protocolo actual, cadena que indica si se esta usando TCP o UDP.
        self.protocol = protocol
        # Nick del usuario en este cliente.
        self.my_nick = nickname
        # current_target guarda el nick del usuario seleccionado para chat privado
        # Si es None, se esta en el chat grupal principal.
        self.current_target = None
        # current_conv_id identifica la conversacion activa (sala general o nick privado)
        self.current_conv_id = "Sala de chat"

        # Diccionario para marcar si hay mensajes sin leer por conversacion
        self.unread = {"Sala de chat": False}
        # Diccionario que almacena las conversaciones: conv_id -> (container, layout)
        self.conversations = {}

        # Configuracion de la ventana principal
        self.setWindowTitle("Juatsapp")
        self.resize(1000, 650)

        # ====== LAYOUT PRINCIPAL ======
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # ====== BARRA SUPERIOR: info de conexion + salir ======
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        # Etiqueta que muestra el nick y el protocolo en uso.
        self.lbl_info = QLabel(f"Conectado como: {self.my_nick} · Protocolo: {self.protocol}")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 14px;")
        top_bar.addWidget(self.lbl_info)

        # Boton Salir para cerrar la ventana de chat y volver al login.
        self.btn_exit = QPushButton("Salir")
        self.btn_exit.setMinimumHeight(30)
        self.btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
            QPushButton:pressed {
                background-color: #ac2925;
            }
        """)
        self.btn_exit.clicked.connect(self.exit_to_login)
        top_bar.addWidget(self.btn_exit)

        # Espaciador para empujar los elementos hacia la izquierda.
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # ====== LAYOUT MEDIO (lista de usuarios + area de chat) ======
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(5)
        main_layout.addLayout(mid_layout)

        # ---- Lista de usuarios a la izquierda ----
        # Incluye la opcion "Sala de chat", que representa el chat grupal.
        self.user_list = QListWidget()
        self.user_list.setMinimumWidth(150)
        self.user_list.addItem("Sala de chat")
        self.user_list.setCurrentRow(0)
        self.user_list.itemSelectionChanged.connect(self.on_user_selected)
        mid_layout.addWidget(self.user_list, 1)

        # ---- Area de chat a la derecha (QScrollArea + QStackedLayout) ----
        # La QScrollArea permite hacer scroll en las conversaciones largas.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        mid_layout.addWidget(self.scroll_area, 3)

        # Dentro de la scroll area se usa un QWidget con un QStackedLayout,
        # donde cada "pagina" representa una conversacion distinta.
        self.stack_container = QWidget()
        self.stack_layout = QStackedLayout(self.stack_container)
        self.scroll_area.setWidget(self.stack_container)

        # Conversacion inicial: la sala general de chat.
        group_container, _ = self.create_conversation("Sala de chat")
        self.stack_layout.setCurrentWidget(group_container)

        # ====== BARRA INFERIOR: caja de texto y botones ======
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        main_layout.addLayout(bottom)

        # Campo de texto donde se escribe el mensaje antes de enviarlo.
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Escribe un mensaje...")
        self.txt_input.setMinimumHeight(40)
        self.txt_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #cccccc;
                border-radius: 15px;
                padding-left: 10px;
                padding-right: 10px;
                font-size: 15px;
            }
            QLineEdit:focus {
                border: 2px solid #6cc070;
            }
        """)
        bottom.addWidget(self.txt_input)

        # Boton Enviar para mandar el mensaje actual.
        self.btn_send = QPushButton("Enviar")
        self.btn_send.setMinimumHeight(40)
        self.btn_send.setStyleSheet("""
            QPushButton {
                background-color: #6cc070;
                color: white;
                border: none;
                border-radius: 15px;
                padding: 10px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5bb563;
            }
            QPushButton:pressed {
                background-color: #4da653;
            }
        """)
        self.btn_send.clicked.connect(self.send_message)
        bottom.addWidget(self.btn_send)

        # Boton Limpiar para borrar las burbujas de la conversacion actual.
        self.btn_clear = QPushButton("Limpiar")
        self.btn_clear.setMinimumHeight(40)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                border: none;
                border-radius: 15px;
                padding: 10px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
            QPushButton:pressed {
                background-color: #ac2925;
            }
        """)
        self.btn_clear.clicked.connect(self.clear_chat)
        bottom.addWidget(self.btn_clear)

        # La senal message_received se conecta al metodo add_message,
        # que agrega el mensaje a la interfaz de chat.
        self.message_received.connect(self.add_message)

        # Si initial_data trae texto del servidor (por ejemplo, "Nick establecido" u otros),
        # se procesan esas lineas como si fueran mensajes entrantes.
        if initial_data:
            for line in initial_data.splitlines():
                self.message_received.emit(line)

        # Hilo de recepcion: se queda leyendo datos del socket y emite la senal message_received.
        if self.sock:
            t = threading.Thread(target=self.receive_loop, daemon=True)
            t.start()

    def exit_to_login(self):
        """Cerrar conexion y regresar a la pantalla de login."""
        # Envia /quit al servidor y cierra el socket si es posible.
        try:
            if self.sock:
                try:
                    self.sock.sendall("/quit\n".encode("utf-8"))
                except:
                    pass
                self.sock.close()
        except:
            pass

        # Cierra la ventana de chat actual.
        self.close()

        # Crea y muestra nuevamente la ventana de login.
        self.login_window = LoginWindow()
        self.login_window.show()

    # ==========================================================
    # Conversaciones
    # ==========================================================
    def create_conversation(self, conv_id):
        # Crea una nueva "conversacion" en el stacked layout si no existe.
        # conv_id puede ser "Sala de chat" para el grupo o el nick de un usuario para privados.
        if conv_id in self.conversations:
            return self.conversations[conv_id]

        # Cada conversacion tiene su propio contenedor y layout vertical.
        container = QWidget()
        layout = QVBoxLayout(container)
        # El stretch al final sirve para empujar las burbujas hacia arriba.
        layout.addStretch()

        self.conversations[conv_id] = (container, layout)
        self.stack_layout.addWidget(container)

        # Inicializar el estado de "no leido" si no existe.
        if conv_id not in self.unread:
            self.unread[conv_id] = False

        return container, layout

    def get_conv_layout(self, conv_id):
        # Devuelve el layout de la conversacion indicada, creandola si no existia.
        container, layout = self.create_conversation(conv_id)
        return layout

    # ==========================================================
    # Lista de usuarios
    # ==========================================================
    def update_user_list(self, names):
        # Actualiza la lista lateral de usuarios conectados segun "names".
        # Se mantiene la conversacion actual seleccionada si es posible.
        current = self.current_target

        # Eliminar el propio nick de la lista, para no chatear "con uno mismo".
        if self.my_nick:
            names = [n for n in names if n != self.my_nick]

        # Se deshabilitan las senales mientras se modifica la lista.
        self.user_list.blockSignals(True)
        self.user_list.clear()
        # Siempre se agrega la opcion principal de chat grupal.
        self.user_list.addItem("Sala de chat")

        # Se agregan los nicks de los otros usuarios conectados.
        for n in names:
            self.user_list.addItem(n)

        self.user_list.blockSignals(False)

        # Se intenta restaurar la seleccion anterior.
        if current is None:
            # Si no habia objetivo anterior, se vuelve a la sala general.
            self.user_list.setCurrentRow(0)
            self.current_conv_id = "Sala de chat"
        else:
            found = False
            # Buscar en la lista el usuario previamente seleccionado.
            for row in range(self.user_list.count()):
                if self.user_list.item(row).text() == current:
                    self.user_list.setCurrentRow(row)
                    self.current_conv_id = current
                    found = True
                    break
            # Si ya no existe el usuario, se regresa a la sala general.
            if not found:
                self.current_target = None
                self.current_conv_id = "Sala de chat"
                self.user_list.setCurrentRow(0)

        # Mostrar la conversacion asociada al usuario o sala seleccionada.
        container, _ = self.create_conversation(self.current_conv_id)
        self.stack_layout.setCurrentWidget(container)

    # ==========================================================
    # Unread (negritas)
    # ==========================================================
    def set_unread(self, conv_id, value):
        # Marca una conversacion como con mensajes sin leer (value True)
        # o sin pendientes (value False) y ajusta la fuente en la lista.
        self.unread[conv_id] = value
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if item.text() == conv_id:
                font = item.font()
                font.setBold(value)
                item.setFont(font)
                break

    # ==========================================================
    # Seleccion de chat
    # ==========================================================
    def on_user_selected(self):
        # Metodo llamado cuando el usuario selecciona un item en la lista lateral.
        item = self.user_list.currentItem()
        if not item:
            return

        text = item.text()
        # Si se selecciona "Sala de chat", se desactiva el modo privado.
        if text == "Sala de chat":
            self.current_target = None
            new_conv_id = "Sala de chat"
        else:
            # Si se selecciona un nick, la conversacion actual sera privada con ese usuario.
            self.current_target = text
            new_conv_id = text

        self.current_conv_id = new_conv_id
        # Al abrir la conversacion, se limpia el estado de no leidos.
        self.set_unread(new_conv_id, False)

        # Cambiar el panel del stacked layout a esta conversacion.
        container, _ = self.create_conversation(new_conv_id)
        self.stack_layout.setCurrentWidget(container)

    # ==========================================================
    # Recibir mensajes (TCP o UDP, usando recv igual)
    # ==========================================================
    def receive_loop(self):
        # Hilo que se queda leyendo mensajes desde el socket.
        # Cada linea recibida se envia a la interfaz a traves de la senal message_received.
        while True:
            try:
                data = self.sock.recv(4096)
                if not data:
                    # Si se recibe nada, se asume que el servidor se desconecto.
                    self.message_received.emit("[Servidor desconectado]")
                    break

                text = data.decode("utf-8")
                # Se separan las lineas por saltos de linea y se procesan una por una.
                for line in text.splitlines():
                    self.message_received.emit(line)

            except Exception:
                # Cualquier error rompe el bucle y termina el hilo de recepcion.
                break

    # ==========================================================
    # Enviar mensaje
    # ==========================================================
    def send_message(self):
        # Envía el contenido de la caja de texto al servidor.
        # Si hay un usuario seleccionado, se convierte en mensaje privado con /msg.
        msg = self.txt_input.text().strip()
        if not msg or not self.sock:
            return

        # Si es un comando /nick, se actualiza tambien el nick local mostrado en la barra superior.
        if msg.startswith("/nick "):
            parts = msg.split(" ", 1)
            if len(parts) == 2:
                self.my_nick = parts[1].strip()
                self.lbl_info.setText(f"Conectado como: {self.my_nick} · Protocolo: {self.protocol}")

        try:
            if self.current_target is None:
                # Mensaje grupal: se envia tal cual al servidor.
                self.sock.sendall((msg + "\n").encode("utf-8"))
            else:
                # Mensaje privado: se antepone /msg con el nick destino.
                cmd = f"/msg {self.current_target} {msg}"
                self.sock.sendall((cmd + "\n").encode("utf-8"))
        except Exception:
            # Si hay algun problema al enviar, se muestra un mensaje en el chat.
            self.message_received.emit("[ERROR] No se pudo enviar")

        # Limpiar el campo de entrada despues de enviar.
        self.txt_input.clear()

    # ==========================================================
    # Limpiar chat actual
    # ==========================================================
    def clear_chat(self):
        # Elimina todas las burbujas de la conversacion actual,
        # dejando solo el stretch final.
        _, layout = self.create_conversation(self.current_conv_id)
        # Se recorre el layout desde el final hasta el primero,
        # menos el ultimo elemento que es el stretch.
        for i in reversed(range(layout.count() - 1)):
            widget = layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    # ==========================================================
    # Añadir mensaje (texto, privados, imagenes) con estilos
    # ==========================================================
    def add_message(self, text):
        # Procesa un mensaje recibido como texto plano, detecta su tipo
        # (lista de usuarios, privado, imagen, servidor, etc.) y lo convierte
        # en HTML para mostrarlo en una burbuja con estilo.
        raw = text.strip()
        if not raw:
            return

        # Mensaje especial que contiene la lista de usuarios.
        if raw.startswith("[USERS] "):
            # Se extraen los nicks y se actualiza la lista lateral.
            names_str = raw[len("[USERS] "):]
            names = [n for n in names_str.split(",") if n]
            self.update_user_list(names)
            return

        conv_id = "Sala de chat"
        is_mine = False
        display_html = raw

        # Extraer timestamp entre corchetes iniciales, si existe.
        ts_str = ""
        rest = raw
        if raw.startswith("[") and "]" in raw:
            closing = raw.find("]")
            ts_str = raw[1:closing]           # contenido sin corchetes
            rest = raw[closing + 1:].strip()  # texto despues del timestamp

        # ---------- Mensajes privados ----------
        if "[PRIVADO]" in rest:
            priv_part = rest
            if priv_part.startswith("[PRIVADO] "):
                # Se quita la etiqueta [PRIVADO] para procesar solo "A -> B: mensaje"
                priv_part = priv_part[len("[PRIVADO] "):]

            sender = None
            msg_body = None

            # Se espera un formato parecido a "A -> B: mensaje"
            if ":" in priv_part and "→" in priv_part:
                header, msg_body = priv_part.split(":", 1)
                msg_body = msg_body.strip()
                header = header.strip()
                a, b = [p.strip() for p in header.split("→", 1)]
                sender = a

                # Determinar en que conversacion mostrar el mensaje privado.
                if self.my_nick and self.my_nick == a:
                    conv_id = b
                    is_mine = True
                elif self.my_nick and self.my_nick == b:
                    conv_id = a
                    is_mine = False
                else:
                    # Si el privado no es para este cliente, se manda al chat general.
                    conv_id = "Sala de chat"

                # Construir el HTML del mensaje privado sin la etiqueta [PRIVADO].
                ts_html = f'<span style="font-size:10px;color:#888888;">[{ts_str}]</span> ' if ts_str else ""
                sender_html = f'<b>{sender}:</b>' if sender else ""
                msg_html = msg_body if msg_body else ""
                display_html = f"{ts_html}{sender_html} {msg_html}".strip()
            else:
                # Si el formato no coincide, se muestra el texto tal cual.
                display_html = rest

        else:
            # ---------- Mensajes normales (grupo, imagenes, servidor) ----------
            sender = None
            msg_body = None

            # Detectar si el mensaje es del propio usuario por prefijo "mynick:".
            if self.my_nick and rest.startswith(f"{self.my_nick}:"):
                is_mine = True
                idx = rest.find(":")
                sender = rest[:idx]
                msg_body = rest[idx + 1:].strip()
            elif ":" in rest:
                # Otro formato general "nick: mensaje".
                idx = rest.find(":")
                sender = rest[:idx]
                msg_body = rest[idx + 1:].strip()

            if sender is not None and msg_body is not None:
                ts_html = f'<span style="font-size:10px;color:#888888;">[{ts_str}]</span> ' if ts_str else ""
                sender_html = f'<b>{sender}:</b>'

                # Deteccion de mensaje de imagen: comienza con [IMG].
                if msg_body.startswith("[IMG]"):
                    img_part = msg_body[len("[IMG]"):].strip()
                    # Se muestra una etiqueta de imagen en HTML.
                    img_html = f'<br><img src="{img_part}" width="200">'
                    display_html = f"{ts_html}{sender_html}{img_html}"
                else:
                    # Mensaje de texto normal.
                    msg_html = msg_body
                    display_html = f"{ts_html}{sender_html} {msg_html}"
            else:
                # Mensajes del servidor u otros formatos sin "nick: mensaje".
                if ts_str:
                    ts_html = f'<span style="font-size:10px;color:#888888;">[{ts_str}]</span> '
                    display_html = ts_html + rest
                else:
                    display_html = raw

            conv_id = "Sala de chat"

        # Se obtiene el layout de la conversacion correspondiente.
        layout = self.get_conv_layout(conv_id)
        # Se crea la burbuja con el HTML procesado y se indica si es mensaje propio.
        bubble = ChatBubble(display_html, is_mine=is_mine)
        # Se inserta la burbuja antes del stretch final.
        layout.insertWidget(layout.count() - 1, bubble)

        # Si el mensaje llega a una conversacion que no esta abierta,
        # se marca como no leido para que aparezca en negritas en la lista.
        if conv_id != self.current_conv_id:
            self.set_unread(conv_id, True)
        else:
            # Si la conversacion esta activa, se hace scroll al final.
            vsb = self.scroll_area.verticalScrollBar()
            vsb.setValue(vsb.maximum())


# ==========================================================
# Ventana de Login: protocolo + nickname (con validacion)
# ==========================================================
class LoginWindow(QWidget):
    def __init__(self):
        # Ventana inicial donde el usuario elige su nickname y el protocolo (TCP o UDP).
        super().__init__()
        self.setWindowTitle("Juatsapp - Conexión")
        self.resize(400, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Titulo de bienvenida.
        lbl_title = QLabel("Bienvenido a Juatsapp")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(lbl_title)

        # Campo para el nickname.
        lbl_nick = QLabel("Nickname (sin espacios):")
        layout.addWidget(lbl_nick)

        self.txt_nick = QLineEdit()
        self.txt_nick.setPlaceholderText("Escribe tu nickname...")
        self.txt_nick.setMinimumHeight(30)
        self.txt_nick.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #cccccc;
                border-radius: 10px;
                padding-left: 8px;
                padding-right: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #6cc070;
            }
        """)
        layout.addWidget(self.txt_nick)

        # Boton para intentar la conexion y entrar al chat.
        self.btn_enter = QPushButton("Entrar al chat")
        self.btn_enter.setMinimumHeight(35)
        self.btn_enter.setStyleSheet("""
            QPushButton {
                background-color: #6cc070;
                color: white;
                border: none;
                border-radius: 15px;
                padding: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5bb563;
            }
            QPushButton:pressed {
                background-color: #4da653;
            }
        """)
        self.btn_enter.clicked.connect(self.open_chat)
        layout.addWidget(self.btn_enter)

        # Referencia a la ventana de chat que se abrira luego.
        self.chat_window = None

    def open_chat(self):
        # Metodo que se ejecuta al presionar "Entrar al chat".
        # Se conecta al servidor usando el protocolo seleccionado
        # y valida el nickname antes de abrir la ventana de chat.

        nick = self.txt_nick.text().strip()
        # Validaciones basicas del nickname.
        if not nick:
            QMessageBox.warning(self, "Error", "Debes escribir un nickname.")
            return
        if " " in nick:
            QMessageBox.warning(self, "Error", "El nickname no puede contener espacios.")
            return

        protocol = "TCP"
        initial_data = ""  # contenido inicial que se enviara al ChatWindow

        try:
            if protocol == "TCP":
                # Conexion TCP al servidor.
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((SERVER_HOST, TCP_PORT))

                # Intento de leer un posible mensaje de "Servidor lleno".
                try:
                    data = s.recv(4096)
                    if data:
                        text = data.decode("utf-8")
                        if "Servidor lleno" in text:
                            QMessageBox.warning(self, "Servidor lleno",
                                                "El servidor TCP está lleno (máximo 5 usuarios).")
                            s.close()
                            return
                        # Si llega otro mensaje diferente, se ignora en este punto.
                except socket.timeout:
                    # Si se agota el tiempo, simplemente se continua.
                    pass
                except Exception:
                    pass

                # Enviar comando /nick al servidor.
                try:
                    s.sendall(f"/nick {nick}\n".encode("utf-8"))
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"No se pudo enviar el nickname:\n{e}")
                    s.close()
                    return

                # Leer respuesta del servidor para verificar si el nick fue aceptado.
                try:
                    data = s.recv(4096)
                    if not data:
                        QMessageBox.critical(self, "Error", "El servidor cerró la conexión.")
                        s.close()
                        return
                    text = data.decode("utf-8")

                    # Diferentes casos de error relacionados con el nickname o el servidor.
                    if "ya está en uso" in text:
                        QMessageBox.warning(self, "Nickname ocupado",
                                            "Ese nickname ya está en uso, elige otro.")
                        s.close()
                        return
                    if "Nombre inválido" in text or "nickname no puede" in text:
                        QMessageBox.warning(self, "Nickname inválido",
                                            "El nickname es inválido.")
                        s.close()
                        return
                    if "Servidor lleno" in text:
                        QMessageBox.warning(self, "Servidor lleno",
                                            "El servidor TCP está lleno (máximo 5 usuarios).")
                        s.close()
                        return

                    # Si llega aqui, el nick fue aceptado por el servidor TCP.
                    initial_data = text

                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Error recibiendo respuesta del servidor:\n{e}")
                    s.close()
                    return

        except Exception as e:
            # Cualquier error general de conexion se muestra en un cuadro de dialogo.
            QMessageBox.critical(self, "Error de conexión", f"No se pudo conectar al servidor:\n{e}")
            try:
                s.close()
            except:
                pass
            return

        # Si todo salio bien, se quita el timeout y se prepara el socket para chat.
        try:
            s.settimeout(None)
        except Exception:
            pass

        # Se crea la ventana de chat, pasando tambien el texto inicial recibido.
        self.chat_window = ChatWindow(protocol, nick, s, initial_data=initial_data)
        self.chat_window.show()
        # Se cierra la ventana de login.
        self.close()


# ==========================================================
# MAIN
# ==========================================================
if __name__ == "__main__":
    # Punto de entrada principal de la aplicacion.
    # Se crea la instancia de QApplication, se muestra el login
    # y se inicia el loop de eventos de Qt.
    app = QApplication(sys.argv)
    login = LoginWindow()
    login.show()
    sys.exit(app.exec_())
