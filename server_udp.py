# server_udp.py
# Este archivo implementa el servidor de chat Juatsapp usando UDP.
# A diferencia de la versión TCP, aquí no hay conexión persistente por cliente,
# sino que cada mensaje llega como un datagrama independiente.
# El servidor maneja nicks, mensajes grupales, privados, lista de usuarios y comandos básicos.

import socket
import datetime

# HOST indica en qué interfaz escuchará el servidor UDP.
# Una cadena vacía equivale a escuchar en todas las interfaces disponibles.
HOST = ""  #"0.0.0.0"

# Puerto donde el servidor UDP estará escuchando datagramas.
PORT = 5001  # puerto UDP

# Diccionario que relaciona la dirección del cliente con su nickname.
# La llave "addr" es una tupla (ip, puerto) y el valor es el apodo del usuario.
clients = {}  # addr -> nickname  (addr es una tupla (ip, puerto))


def timestamp():
    # Devuelve una cadena con la fecha y hora actual en el formato indicado.
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sendto(sock, addr, message):
    # Función auxiliar para enviar un mensaje a un cliente específico usando UDP.
    # Recibe el socket del servidor, la dirección del cliente y el mensaje como texto.
    try:
        # Se codifica el mensaje como UTF-8 y se envía al cliente indicado por "addr".
        sock.sendto(message.encode("utf-8"), addr)
    except Exception:
        # Si ocurre un error al enviar (por ejemplo, dirección inválida),
        # simplemente se ignora la excepción.
        pass


def broadcast(sock, message, exclude_addr=None):
    # Envía un mensaje a todos los clientes registrados en "clients".
    # Si se pasa "exclude_addr", ese cliente no recibe el mensaje (por ejemplo, el emisor).
    for addr, _nick in list(clients.items()):
        # Si se especifica una dirección a excluir, se salta ese cliente.
        if exclude_addr is not None and addr == exclude_addr:
            continue
        # Se usa la función auxiliar sendto para enviar el mensaje a cada cliente.
        sendto(sock, addr, message)


def broadcast_user_list(sock):
    # Envía a todos la lista de usuarios conectados, en el formato:
    # [USERS] nick1,nick2,...
    # Esta lista es utilizada por el cliente para actualizar el panel de usuarios conectados.
    nicks = list(clients.values())
    msg = "[USERS] " + ",".join(nicks) + "\n"
    # Se difunde el mensaje a todos los clientes.
    broadcast(sock, msg)


def main():
    # Función principal del servidor UDP.
    # Configura el socket, lo asocia a una dirección y entra en un ciclo infinito
    # recibiendo y procesando datagramas de los clientes.

    # Se crea un socket UDP (SOCK_DGRAM) sobre IPv4 (AF_INET).
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Se asocia el socket al HOST y PORT definidos.
    sock.bind((HOST, PORT))
    print(f"[UDP SERVER] Escuchando en {HOST}:{PORT} (UDP) ...")

    # Bucle principal del servidor: recibe datagramas y los procesa.
    while True:
        try:
            # recvfrom recibe un datagrama de hasta 4096 bytes y la dirección de origen.
            data, addr = sock.recvfrom(4096)
        except Exception as e:
            # Si se produce un error al recibir, se muestra en consola y se continúa.
            print("Error recvfrom:", e)
            continue

        # Se decodifica el mensaje de bytes a cadena y se quitan saltos de línea al final.
        text = data.decode("utf-8").rstrip("\n")
        # Si el texto queda vacío, se ignora este datagrama.
        if not text:
            continue

        # Se obtiene el nick asociado a la dirección de este cliente (si existe).
        nick = clients.get(addr)

        # Si no tiene nick todavía
        # Mientras este cliente no haya registrado un nickname, solo se aceptará el comando /nick.
        if nick is None:
            if text.startswith("/nick "):
                # Se extrae el nuevo nick, quitando la palabra "/nick " y espacios extra.
                newnick = text.split(" ", 1)[1].strip()

                # Validación básica: el nick no puede estar vacío ni contener espacios.
                if newnick == "" or " " in newnick:
                    sendto(sock, addr, f"[{timestamp()}] Nombre inválido (sin espacios).\n")
                    continue

                # Máximo 5 usuarios conectados
                # Antes de registrar un nuevo nick, se revisa si ya se alcanzó el límite de usuarios.
                if newnick not in clients.values() and len(clients) >= 5:
                    sendto(sock, addr, f"[{timestamp()}] [SERVER] Servidor UDP lleno (máx 5 usuarios).\n")
                    continue

                # Se verifica que el nick no esté ya en uso por otro cliente.
                if newnick in clients.values():
                    sendto(sock, addr, f"[{timestamp()}] Ese nickname ya está en uso.\n")
                    continue

                # Si pasó todas las validaciones, se registra al cliente en el diccionario.
                clients[addr] = newnick
                nick = newnick

                # Se informa al cliente cuál es su nick.
                sendto(sock, addr, f"[{timestamp()}] Nick UDP establecido como {nick}.\n")
                # Se avisa a los demás que este nuevo usuario se conectó.
                broadcast(sock, f"[{timestamp()}] [SERVER] {nick} se ha conectado (UDP).\n", exclude_addr=addr)
                # Se manda a todos la lista actualizada de usuarios.
                broadcast_user_list(sock)
            else:
                # Simplemente ignoramos cualquier cosa que no sea /nick.
                # Esto significa que si el cliente envía algo distinto antes de /nick, se desecha.
                pass
            # Se pasa a esperar el siguiente datagrama de este u otro cliente.
            continue

        # Ya tiene nick
        # A partir de aquí, el cliente ya está registrado y puede usar otros comandos.

        # Comando para cambiar el nickname después de haber establecido uno.
        if text.startswith("/nick "):
            newnick = text.split(" ", 1)[1].strip()

            # Se valida que el nuevo nick no sea vacío ni contenga espacios.
            if newnick == "" or " " in newnick:
                sendto(sock, addr, f"[{timestamp()}] Nombre inválido (sin espacios).\n")
                continue

            # Si el nuevo nick es el mismo que ya tiene, se avisa y no se hace nada.
            if newnick == nick:
                sendto(sock, addr, f"[{timestamp()}] Ya estás usando ese nickname.\n")
                continue

            # Si el nuevo nick ya está siendo usado por otro usuario, se rechaza el cambio.
            if newnick in clients.values():
                sendto(sock, addr, f"[{timestamp()}] Ese nickname ya está en uso.\n")
                continue

            # Si todo está bien, se actualiza el diccionario de clientes.
            old = nick
            clients[addr] = newnick
            nick = newnick

            # Se informa a todos que este usuario cambió de nombre.
            broadcast(sock, f"[{timestamp()}] [SERVER] {old} ahora es {newnick} (UDP).\n")
            # Se envía la lista de usuarios actualizada.
            broadcast_user_list(sock)
            continue

        # Comando para salir del servidor lógicamente.
        if text == "/quit":
            # Se envía un mensaje de despedida al cliente.
            sendto(sock, addr, f"[{timestamp()}] Adiós (UDP)!\n")
            # Se quita al usuario del diccionario de clientes.
            old = clients.pop(addr, None)
            if old:
                # Se avisa a los demás que este usuario se desconectó.
                broadcast(sock, f"[{timestamp()}] [SERVER] {old} se ha desconectado (UDP).\n")
                # Se actualiza la lista de usuarios para todos.
                broadcast_user_list(sock)
            # No hay conexión que cerrar, dado que es UDP, solo se deja de considerarlo en "clients".
            continue

        # Comando para mensaje privado en UDP.
        if text.startswith("/msg "):
            # Se espera el formato: /msg NICK mensaje...
            parts = text.split(" ", 2)
            # Si no hay al menos 3 partes, significa que faltan parámetros.
            if len(parts) < 3:
                sendto(sock, addr, f"[{timestamp()}] Uso: /msg NICK mensaje...\n")
                continue
            # Nick destino y texto del mensaje privado.
            to_nick = parts[1].strip()
            msg_text = parts[2].strip()
            # Validación básica de parámetros.
            if not to_nick or not msg_text:
                sendto(sock, addr, f"[{timestamp()}] Uso: /msg NICK mensaje...\n")
                continue

            # Se busca la dirección del usuario destino a partir del nick.
            target_addr = None
            for a, n in clients.items():
                if n == to_nick:
                    target_addr = a
                    break

            # Si no se encuentra al usuario destino, se informa al remitente.
            if target_addr is None:
                sendto(sock, addr, f"[{timestamp()}] [SERVER] Usuario '{to_nick}' no encontrado.\n")
                continue

            # Se arma el mensaje de chat privado y se envía tanto al emisor como al receptor.
            msg = f"[{timestamp()}] [PRIVADO] {nick} → {to_nick}: {msg_text}\n"
            sendto(sock, addr, msg)
            sendto(sock, target_addr, msg)
            continue

        # Comando especial /aime (imagen)
        # Difunde un mensaje indicando una imagen asociada a este comando.
        if text == "/aime":
            broadcast(sock, f"[{timestamp()}] {nick}: [IMG] Imagenes/aime.jpg\n")
            continue

        # Comando especial /carlos (imagen)
        # Similar al anterior pero con otra imagen.
        if text == "/carlos":
            broadcast(sock, f"[{timestamp()}] {nick}: [IMG] Imagenes/carlos.jpg\n")
            continue

        # Mensaje grupal normal
        # Si no se trata de ningún comando especial, se interpreta como mensaje de texto
        # y se difunde a todos los usuarios conectados.
        broadcast(sock, f"[{timestamp()}] {nick}: {text}\n")


if __name__ == "__main__":
    main()
