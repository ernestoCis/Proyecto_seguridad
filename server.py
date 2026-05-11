# server.py
# Este archivo implementa el servidor de chat tipo "Juatsapp" usando sockets TCP.
# Se encarga de aceptar conexiones, manejar los clientes, difundir mensajes,
# gestionar nicks, mensajes privados y la lista de usuarios conectados.

import socket
import threading
import datetime

# Dirección IP donde escuchará el servidor.
# 0.0.0.0 significa que escuchará en todas las interfaces de red disponibles.
HOST = "0.0.0.0"

# Puerto donde el servidor estará escuchando conexiones entrantes.
PORT = 5000 #puerto TCP

# Lock (candado) para proteger el acceso concurrente a la estructura "clients"
# cuando varios hilos (clientes) la modifican al mismo tiempo.
clients_lock = threading.Lock()

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


def timestamp():
    """Devuelve la fecha y hora actual en formato YYYY-MM-DD HH:MM:SS."""
    # Se obtiene la fecha y hora actual y se convierte a cadena con el formato indicado.
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def broadcast(message, exclude_sock=None):
    """Envía message a todos los clientes excepto exclude_sock."""
    # Se copia la lista de sockets actuales bajo protección del candado
    # para evitar problemas si la lista cambia mientras se recorre.
    with clients_lock:
        sockets = list(clients.keys())
    # Se recorre cada socket conectado
    for sock in sockets:
        # Si este socket es el que se quiere excluir (por ejemplo, el que envió el mensaje),
        # se salta el envío a ese cliente.
        if sock is exclude_sock:
            continue
        try:
            # Se envía el mensaje codificado en UTF-8 a ese cliente.
            sock.sendall(message.encode("utf-8"))
        except Exception:
            # Si ocurre algún problema al enviar (cliente desconectado u otro error),
            # se elimina ese cliente del servidor.
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


def send_private(from_sock, from_nick, to_nick, text):
    """Envía un mensaje privado de from_nick a to_nick (solo ellos dos lo ven)."""
    # Se busca el socket que corresponde al nickname destino.
    target_sock = None
    with clients_lock:
        for sock, nick in clients.items():
            # Si el nick coincide con el nick al que queremos enviar el privado, lo guardamos.
            if nick == to_nick:
                target_sock = sock
                break

    # Si no se encontró el usuario destino, se le avisa al emisor que ese usuario no existe.
    if target_sock is None:
        try:
            from_sock.sendall(f"[{timestamp()}] [SERVER] Usuario '{to_nick}' no encontrado.\n".encode("utf-8"))
        except Exception:
            # Si incluso fallara este envío, solo se ignora la excepción.
            pass
        return

    # Se arma el mensaje de chat privado indicando origen, destino y contenido.
    msg = f"[{timestamp()}] [PRIVADO] {from_nick} → {to_nick}: {text}\n"
    # Este mensaje se envía tanto al que envió el privado como al destinatario,
    # para que ambos vean el historial.
    for s in (from_sock, target_sock):
        try:
            s.sendall(msg.encode("utf-8"))
        except Exception:
            # Si falla el envío a alguno de los dos, se ignora el error.
            pass


def remove_client(sock):
    # Elimina al cliente del diccionario de clientes de forma segura usando el lock.
    with clients_lock:
        nick = clients.pop(sock, None)
    try:
        # Se cierra el socket del cliente para liberar recursos.
        sock.close()
    except Exception:
        # Si falla el cierre, se ignora.
        pass
    # Si había un cliente ya registrado
    # se avisa a los demás que ese usuario se ha desconectado y se actualiza la lista.
    if nick:
        broadcast(f"[{timestamp()}] [SERVER] {nick} se ha desconectado.\n")
        broadcast_user_list()


def handle_client(conn, addr):
    # Esta función se ejecuta en un hilo independiente por cada cliente.
    # Se encarga de recibir los mensajes del cliente, procesar comandos y
    # difundir mensajes al resto de usuarios.

    # El cliente GUI manda /nick automáticamente.

    # La variable "user" almacenará el usuario autenticado del cliente.
    # Este usuario también será el nombre visible dentro del chat.
    user = None

    try:
        # Bucle principal de comunicación con el cliente.
        while True:
            # Se recibe hasta 4096 bytes desde el socket del cliente.
            data = conn.recv(4096)
            # Si no se recibe nada, significa que el cliente cerró la conexión.
            if not data:
                break

            # Se decodifica el mensaje de bytes a cadena y se quita el salto de línea al final.
            text = data.decode("utf-8").rstrip("\n")
            # Si después de limpiar el texto queda vacío, se ignora y se sigue leyendo.
            if not text:
                continue

            # 1) Aún no ha iniciado sesión
            # Antes de chatear, el cliente debe enviar /login USUARIO CONTRASEÑA.
            if user is None:
                if text.startswith("/login "):
                    parts = text.split(" ", 2)

                    if len(parts) < 3:
                        conn.sendall(
                            f"[{timestamp()}] [AUTH_ERROR] Uso: /login USUARIO CONTRASEÑA\n"
                            .encode("utf-8")
                        )
                        continue

                    username = parts[1].strip()
                    password = parts[2].strip()

                    # Validaciones básicas.
                    if username == "" or password == "":
                        conn.sendall(
                            f"[{timestamp()}] [AUTH_ERROR] Usuario y contraseña son obligatorios.\n"
                            .encode("utf-8")
                        )
                        continue

                    if " " in username:
                        conn.sendall(
                            f"[{timestamp()}] [AUTH_ERROR] El usuario no puede contener espacios.\n"
                            .encode("utf-8")
                        )
                        continue

                    # Se protege el acceso a los diccionarios compartidos.
                    with clients_lock:

                        # Si el usuario no existe, se registra automáticamente.
                        if username not in registered_users:
                            registered_users[username] = password
                            auth_message = (
                                f"Usuario '{username}' registrado correctamente. "
                                f"Bienvenido {username}."
                            )

                        # Si el usuario ya existe, se valida la contraseña.
                        elif registered_users[username] == password:
                            auth_message = f"Bienvenido de nuevo {username}."

                        # Si existe pero la contraseña no coincide, se rechaza.
                        else:
                            conn.sendall(
                                f"[{timestamp()}] [AUTH_ERROR] Usuario o contraseña incorrectos.\n"
                                .encode("utf-8")
                            )
                            try:
                                conn.close()
                            except:
                                pass
                            return

                        # Validar que el usuario no esté conectado actualmente.
                        if username in clients.values():
                            conn.sendall(
                                f"[{timestamp()}] [AUTH_ERROR] El usuario '{username}' ya está conectado.\n"
                                .encode("utf-8")
                            )
                            try:
                                conn.close()
                            except:
                                pass
                            return

                        # El usuario autenticado se registra como usuario visible del chat.
                        clients[conn] = username

                    user = username

                    # Avisar a los demás usuarios que este usuario entró.
                    broadcast(
                        f"[{timestamp()}] [SERVER] {user} se ha conectado.\n",
                        exclude_sock=conn
                    )

                    # Enviar lista de usuarios actualizada.
                    broadcast_user_list()

                    # Confirmar autenticación correcta al cliente.
                    conn.sendall(
                        f"[{timestamp()}] [AUTH_OK] {auth_message}\n"
                        .encode("utf-8")
                    )

                else:
                    conn.sendall(
                        f"[{timestamp()}] [AUTH_ERROR] Debes iniciar sesión con /login USUARIO CONTRASEÑA.\n"
                        .encode("utf-8")
                    )

                continue

            # 2) Usuario ya autenticado: comandos del chat
            # A partir de aquí, el usuario ya tiene un nick y puede usar más comandos.

            # Comando para salir del servidor de forma ordenada.
            if text == "/quit":
                # Se envía un mensaje de despedida al cliente.
                conn.sendall(f"[{timestamp()}] Adiós!\n".encode("utf-8"))
                # Se rompe el bucle, lo que llevará a cerrar la conexión en el finally.
                break

            # Comando para enviar mensaje privado a otro usuario.
            if text.startswith("/msg "):
                # Se espera el formato: /msg NICK mensaje...
                # Se divide en máximo 3 partes: "/msg", "NICK", "mensaje..."
                parts = text.split(" ", 2)
                # Si no se reciben las tres partes, la sintaxis es incorrecta.
                if len(parts) < 3:
                    conn.sendall(
                        f"[{timestamp()}] Uso: /msg NICK mensaje...\n".encode("utf-8")
                    )
                    continue
                # El segundo elemento es el nick destino.
                to_nick = parts[1].strip()
                # El resto de la cadena es el mensaje privado.
                msg_text = parts[2].strip()
                # Se valida que ambos, nick destino y mensaje, no estén vacíos.
                if not to_nick or not msg_text:
                    conn.sendall(
                        f"[{timestamp()}] Uso: /msg NICK mensaje...\n".encode("utf-8")
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
                # Si no es ninguno de esos comandos, se trata como mensaje normal
                # y se difunde al resto de usuarios con su timestamp y nick.
                broadcast(f"[{timestamp()}] {user}: {text}\n")

    except Exception as e:
        # Cualquier excepción durante el manejo del cliente se imprime en consola
        # para depuración.
        print("Error en handle_client:", e)
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
            try:
                # Se envía un mensaje al cliente indicándole que el servidor está lleno.
                conn.sendall(
                    f"[{timestamp()}] [SERVER] Servidor lleno (máximo 5 usuarios conectados).\n".encode("utf-8")
                )
            except Exception:
                # Si falla el envío, se ignora.
                pass
            # Se cierra la conexión con el cliente rechazado.
            conn.close()
            # Se continúa con el siguiente intento de conexión.
            continue

        # Si hay espacio, se informa en consola la nueva conexión.
        print(f"[SERVER] Conexión desde {addr}")
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
