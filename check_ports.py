import socket

ports = [1935, 8554, 8888, 9997]
for p in ports:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    r = s.connect_ex(('localhost', p))
    s.close()
    print('Port', p, ':', 'OPEN' if r == 0 else 'CLOSED')