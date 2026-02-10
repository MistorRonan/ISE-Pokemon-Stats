import Server
import Client 
import json
import sys
with open("config.json") as file:
    config = json.load(file)

port : int = config["server"]["port"]
server_ip : str = config["server"]["ip"]
if __name__ == "__main__": 
    match sys.argv[2]:
        case "-port":
            port = int(sys.argv[3])
        case "-server_ip":
            server_ip = sys.argv[3]
        case _:
            print("Usage: python app.py <server|client> -port <port> -ip <ip>")
    match sys.argv[1]:
        case "-s":
            print(f"Starting server on port {port}")
            Server.start_server(port=port)
        case "-c":
            print(f"Starting client on port {port} and server ip {server_ip}")
            Client.start_client(port=port, server_ip=server_ip)
        case _:
            print("Usage: python app.py <server|client> -port <port> -server_ip <ip>")