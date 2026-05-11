# server.py
# Este archivo implementa el servidor de chat tipo "Juatsapp" usando sockets TCP.
# Se encarga de aceptar conexiones, manejar los clientes, difundir mensajes,
# gestionar nicks, mensajes privados y la lista de usuarios conectados.

import socket
import threading
import datetime
import logging
import hashlib
import re

logging.basicConfig(
    filename="server.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

import base64
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

# Dirección IP donde escuchará el servidor.
# 0.0.0.0 significa que escuchará en todas las interfaces de red disponibles.
HOST = "0.0.0.0"

# Puerto donde el servidor estará escuchando conexiones entrantes.
PORT = 5000 #puerto TCP

# Lock (candado) para proteger el acceso concurrente a la estructura "clients"
# cuando varios hilos (clientes) la modifican al mismo tiempo.
clients_lock = threading.RLock()

# Diccionario que almacena la relación socket -> usuario autenticado.
# La llave es el socket del cliente, y el valor es el usuario que inició sesión.
# Antes se usaba como nickname, pero ahora el usuario será también el nombre visible.
clients = {}  # socket -> nickname

# Diccionario de usuarios registrados.
# Llave: usuario.
# Valor: contraseña.
# En este proyecto se guarda en memoria.
# Si se cierrasel servidor, los usuarios registrados se pierden.
registered_users = {}

# Llaves RSA del servidor.
# El servidor tendrá una llave privada para descifrar mensajes
# y una llave pública que compartirá con los clientes.
server_key = RSA.generate(2048)
server_private_key = server_key
server_public_key = server_key.publickey()

# Diccionario para guardar la llave pública de cada cliente conectado.
# Llave: socket del cliente.
# Valor: llave pública RSA del cliente.
client_public_keys = {}

recv_buffers = {}


def timestamp():
    """Devuelve la fecha y hora actual en formato YYYY-MM-DD HH:MM:SS."""
    # Se obtiene la fecha y hora actual y se convierte a cadena con el formato indicado.
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def sanitize_input(text):
    """
    Elimina caracteres peligrosos y espacios innecesarios.
    """
    text = text.strip()

    # Eliminar caracteres de control
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)

    return text


def validate_username(username):
    """
    Valida que el usuario tenga un formato seguro.
    """
    pattern = r"^[a-zA-Z0-9_]{3,20}$"
    return re.match(pattern, username)


def hash_password(password):
    """
    Genera hash SHA-256 de la contraseña.
    """
    return hashlib.sha256(password.encode()).hexdigest()

def encrypt_message(message, public_key):
    """
    Cifra un mensaje usando RSA-OAEP y la llave pública recibida.
    Devuelve el mensaje cifrado en Base64 para poder enviarlo por socket.
    """
    cipher = PKCS1_OAEP.new(public_key)
    encrypted_bytes = cipher.encrypt(message.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted_bytes).decode("utf-8")
    return encrypted_b64


def decrypt_message(encrypted_b64, private_key):
    """
    Descifra un mensaje en Base64 usando RSA-OAEP y la llave privada recibida.
    Devuelve el texto original.
    """
    encrypted_bytes = base64.b64decode(encrypted_b64.encode("utf-8"))
    cipher = PKCS1_OAEP.new(private_key)
    decrypted_bytes = cipher.decrypt(encrypted_bytes)
    return decrypted_bytes.decode("utf-8")


def send_encrypted(sock, message):
    """
    Envía un mensaje cifrado a un cliente específico usando la llave pública
    de ese cliente.
    """
    with clients_lock:
        public_key = client_public_keys.get(sock)

    if public_key is None:
        return

    encrypted_text = encrypt_message(message, public_key)
    sock.sendall((encrypted_text + "\n").encode("utf-8"))


def recv_encrypted(sock):
    """
    Recibe un mensaje cifrado desde un cliente.
    Lee hasta encontrar salto de línea para evitar problemas si TCP junta mensajes.
    """
    with clients_lock:
        buffer = recv_buffers.get(sock, "")

    while "\n" not in buffer:
        data = sock.recv(4096)

        if not data:
            return None

        buffer += data.decode("utf-8")

    encrypted_text, remaining = buffer.split("\n", 1)

    with clients_lock:
        recv_buffers[sock] = remaining

    encrypted_text = encrypted_text.strip()

    if encrypted_text == "":
        return ""

    plain_text = decrypt_message(encrypted_text, server_private_key)
    return plain_text


def broadcast(message, exclude_sock=None):
    """Envía message cifrado a todos los clientes excepto exclude_sock."""
    with clients_lock:
        sockets = list(clients.keys())

    for sock in sockets:
        if sock is exclude_sock:
            continue

        try:
            send_encrypted(sock, message)
        except Exception:
            remove_client(sock)


def broadcast_user_list():
    """Manda a todos la lista de nicks conectados en formato [USERS] nick1,nick2,..."""
    # Se obtiene la lista de nicks actuales bajo el candado para evitar condiciones de carrera.
    with clients_lock:
        nicks = list(clients.values())
    # Se arma el mensaje especial que contiene la lista de usuarios.
    msg = "[USERS] " + ",".join(nicks) + "\n"
    # Se envía a todos los clientes conectados.
    broadcast(msg)


def send_private(from_sock, from_user, to_user, text):
    """Envía un mensaje privado cifrado de from_user a to_user."""
    target_sock = None

    with clients_lock:
        for sock, user in clients.items():
            if user == to_user:
                target_sock = sock
                break

    if target_sock is None:
        try:
            send_encrypted(
                from_sock,
                f"[{timestamp()}] [SERVER] Usuario '{to_user}' no encontrado.\n"
            )
        except Exception:
            pass

        return

    msg = f"[{timestamp()}] [PRIVADO] {from_user} → {to_user}: {text}\n"

    logging.info(f"Mensaje privado: {from_user} -> {to_user}")

    for s in (from_sock, target_sock):
        try:
            send_encrypted(s, msg)
        except Exception:
            pass


def remove_client(sock):
    # Elimina al cliente del diccionario de clientes de forma segura usando el lock.
    with clients_lock:
        nick = clients.pop(sock, None)
        client_public_keys.pop(sock, None)
        recv_buffers.pop(sock, None)
    try:
        # Se cierra el socket del cliente para liberar recursos.
        sock.close()
    except Exception:
        # Si falla el cierre, se ignora.
        pass
    # Si había un cliente ya registrado
    # se avisa a los demás que ese usuario se ha desconectado y se actualiza la lista.
    if nick:
        logging.info(f"Usuario desconectado: {nick}")
        broadcast(f"[{timestamp()}] [SERVER] {nick} se ha desconectado.\n")
        broadcast_user_list()


def exchange_keys_with_client(conn):
    """
    Intercambia llaves públicas RSA con el cliente.

    1. El servidor envía su llave pública.
    2. El cliente responde con su llave pública.
    3. El servidor guarda la llave pública del cliente.
    """

    # Enviar llave pública del servidor en formato PEM.
    server_public_pem = server_public_key.export_key().decode("utf-8")
    conn.sendall((server_public_pem + "\nEND_SERVER_PUBLIC_KEY\n").encode("utf-8"))

    # Recibir llave pública del cliente hasta encontrar el marcador final.
    buffer = ""

    while "END_CLIENT_PUBLIC_KEY" not in buffer:
        data = conn.recv(4096)

        if not data:
            return False

        buffer += data.decode("utf-8")

    client_public_pem = buffer.split("END_CLIENT_PUBLIC_KEY")[0].strip()
    client_public_key = RSA.import_key(client_public_pem)

    with clients_lock:
        client_public_keys[conn] = client_public_key

    return True

def handle_client(conn, addr):
    # Esta función se ejecuta en un hilo independiente por cada cliente.
    # Se encarga de recibir los mensajes del cliente, procesar comandos y
    # difundir mensajes al resto de usuarios.

    # El cliente GUI manda /nick automáticamente.

    # La variable "user" almacenará el usuario autenticado del cliente.
    # Este usuario también será el nombre visible dentro del chat.
    user = None

    try:
        # Antes de recibir usuario/contraseña, se realiza el intercambio
        # de llaves públicas RSA.
        if not exchange_keys_with_client(conn):
            return

        while True:
            text = recv_encrypted(conn)

            if text is None:
                break

            text = text.rstrip("\n")

            if not text:
                continue

            # 1) Aún no ha iniciado sesión
            # Antes de chatear, el cliente debe enviar /login USUARIO CONTRASEÑA.
            if user is None:
                if text.startswith("/login "):
                    parts = text.split(" ", 2)

                    if len(parts) < 3:
                        send_encrypted(
                            conn,
                            f"[{timestamp()}] [AUTH_ERROR] Uso: /login USUARIO CONTRASEÑA\n"
                        )
                        continue

                    username = sanitize_input(parts[1])
                    password = sanitize_input(parts[2])

                    # Validaciones básicas.
                    if username == "" or password == "":
                        send_encrypted(
                            conn,
                            f"[{timestamp()}] [AUTH_ERROR] Usuario y contraseña son obligatorios.\n"
                        )
                        continue

                    if not validate_username(username):
                        send_encrypted(
                            conn,
                            f"[{timestamp()}] [AUTH_ERROR] Usuario inválido.\n"
                        )

                        logging.warning(f"Intento de usuario inválido desde {addr}")

                        continue

                    if " " in username:
                        send_encrypted(
                            conn,
                            f"[{timestamp()}] [AUTH_ERROR] El usuario no puede contener espacios.\n"
                        )
                        continue

                    # Se protege el acceso a los diccionarios compartidos.
                    with clients_lock:

                        # Si el usuario no existe, se registra automáticamente.
                        if username not in registered_users:
                            registered_users[username] = hash_password(password)
                            logging.info(f"Nuevo usuario registrado: {username}")
                            auth_message = (
                                f"Usuario '{username}' registrado correctamente. "
                                f"Bienvenido {username}."
                            )

                        # Si el usuario ya existe, se valida la contraseña.
                        elif registered_users[username] == hash_password(password):
                            auth_message = f"Bienvenido de nuevo {username}."

                        # Si existe pero la contraseña no coincide, se rechaza.
                        else:
                            send_encrypted(
                                conn,
                                f"[{timestamp()}] [AUTH_ERROR] Usuario o contraseña incorrectos.\n"
                            )
                            logging.warning(
                                f"Intento de login fallido para usuario: {username}"
                            )
                            try:
                                conn.close()
                            except:
                                pass
                            return

                        # Validar que el usuario no esté conectado actualmente.
                        if username in clients.values():
                            send_encrypted(
                                conn,
                                f"[{timestamp()}] [AUTH_ERROR] El usuario '{username}' ya está conectado.\n"
                            )
                            try:
                                conn.close()
                            except:
                                pass
                            return

                        # El usuario autenticado se registra como usuario visible del chat.
                        clients[conn] = username

                    user = username

                    logging.info(f"Usuario autenticado: {user}")

                    # Avisar a los demás usuarios que este usuario entró.
                    broadcast(
                        f"[{timestamp()}] [SERVER] {user} se ha conectado.\n",
                        exclude_sock=conn
                    )

                    # Confirmar autenticación correcta al cliente primero.
                    # El cliente espera recibir [AUTH_OK] antes de abrir la ventana del chat.
                    send_encrypted(
                        conn,
                        f"[{timestamp()}] [AUTH_OK] {auth_message}\n"
                    )

                    # Después se envía la lista de usuarios actualizada.
                    broadcast_user_list()

                else:
                    send_encrypted(
                        conn,
                        f"[{timestamp()}] [AUTH_ERROR] Debes iniciar sesión con /login USUARIO CONTRASEÑA.\n"
                    )

                continue

            # 2) Usuario ya autenticado: comandos del chat
            # A partir de aquí, el usuario ya tiene un nick y puede usar más comandos.

            # Comando para salir del servidor de forma ordenada.
            if text == "/quit":
                # Se envía un mensaje de despedida al cliente.
                send_encrypted(conn, f"[{timestamp()}] Adiós!\n")
                # Se rompe el bucle, lo que llevará a cerrar la conexión en el finally.
                break

            # Comando para enviar mensaje privado a otro usuario.
            if text.startswith("/msg "):
                # Se espera el formato: /msg NICK mensaje...
                # Se divide en máximo 3 partes: "/msg", "NICK", "mensaje..."
                parts = text.split(" ", 2)
                # Si no se reciben las tres partes, la sintaxis es incorrecta.
                if len(parts) < 3:
                    send_encrypted(
                        conn,
                        f"[{timestamp()}] Uso: /msg NICK mensaje...\n"
                    )
                    continue
                # El segundo elemento es el nick destino.
                to_nick = sanitize_input(parts[1])
                # El resto de la cadena es el mensaje privado.
                msg_text = sanitize_input(parts[2])
                # Se valida que ambos, nick destino y mensaje, no estén vacíos.
                if not to_nick or not msg_text:
                    send_encrypted(
                        conn,
                        f"[{timestamp()}] Uso: /msg NICK mensaje...\n"
                    )
                    continue
                # Se envía el mensaje privado usando la función auxiliar.
                send_private(conn, user, to_nick, msg_text)
                # Se sigue el bucle sin difundir nada al canal general.
                continue

            # Mensaje normal o comando /aime /carlos
            # A partir de aquí, cualquier cosa que no sea un comando reconocido
            # se trata como mensaje general, salvo los comandos de imágenes.
            if text == "/aime":
                # Comando especial que envía un mensaje indicando una imagen asociada.
                broadcast(f"[{timestamp()}] {user}: [IMG] Imagenes/aime.jpg\n")
                continue
            if text == "/carlos":
                # Comando especial similar para otra imagen.
                broadcast(f"[{timestamp()}] {user}: [IMG] Imagenes/carlos.jpg\n")
                continue
            else:

                text = sanitize_input(text)

                if len(text) > 500:
                    send_encrypted(
                        conn,
                        f"[{timestamp()}] [ERROR] Mensaje demasiado largo.\n"
                    )
                    continue

                logging.info(f"Mensaje general de {user}")

                broadcast(f"[{timestamp()}] {user}: {text}\n")

    except Exception as e:
        # Cualquier excepción durante el manejo del cliente se imprime en logging
        # para depuración.
        logging.error(f"Error en handle_client: {e}")
    finally:
        # Al salir (por error o porque el cliente se desconectó), se elimina el cliente.
        remove_client(conn)


def accept_loop(server_sock):
    # Esta función se encarga de aceptar nuevas conexiones en un bucle infinito.
    # Por cada conexión aceptada, crea un hilo para manejar a ese cliente.
    print(f"[SERVER] Escuchando en {HOST}:{PORT} ...")
    while True:
        # Se bloquea esperando que un nuevo cliente se conecte.
        conn, addr = server_sock.accept()

        # Limitar a máximo 5 usuarios
        # Se verifica cuántos clientes están ya conectados.
        with clients_lock:
            num_clients = len(clients)

        # Si el número de clientes llega al límite, se rechaza la nueva conexión.
        if num_clients >= 5:
            logging.warning(f"Conexión rechazada desde {addr}: servidor lleno")
            conn.close()
            continue

        # Si hay espacio, se informa en consola la nueva conexión.
        print(f"[SERVER] Conexión desde {addr}")
        logging.info(f"Nueva conexión desde {addr}")
        # Se crea un nuevo hilo que atenderá a este cliente.
        # daemon=True indica que el hilo no impedirá que el programa termine
        # si todos los demás hilos principales terminan.
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        # Se inicia el hilo para que comience a manejar al cliente.
        t.start()


def main():
    # Esta función configura el socket del servidor y arranca el bucle de aceptación.
    # Se crea un socket TCP (SOCK_STREAM) sobre IPv4 (AF_INET).
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Se configura la opción SO_REUSEADDR para permitir reutilizar rápidamente
    # la dirección y puerto cuando se reinicie el servidor.
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Se asocia el socket a la dirección y puerto definidos en HOST y PORT.
    server_sock.bind((HOST, PORT))
    # El servidor se pone en modo escucha con una cola máxima de 100 conexiones pendientes.
    server_sock.listen(100)
    try:
        # Se inicia el bucle principal que aceptará conexiones entrantes.
        accept_loop(server_sock)
    except KeyboardInterrupt:
        # Si el usuario detiene el servidor con Ctrl+C, se muestra este mensaje.
        print("\n[SERVER] Cerrando servidor.")
    finally:
        # Al finalizar, se cierra el socket del servidor para liberar el puerto.
        server_sock.close()


if __name__ == "__main__":
    main()
