#!/usr/bin/env python3
import sys
import base64
import json
import re
import urllib.request
import socket
import time
import urllib.parse

SUBSCRIPTION_URL = sys.argv[1]
OUTPUT_FILE = sys.argv[2]

def fetch_subscription(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = resp.read().decode('utf-8').strip()
            try:
                decoded = base64.b64decode(raw).decode('utf-8')
                return decoded.strip()
            except Exception:
                return raw
    except Exception as e:
        print(f"Failed to fetch subscription: {e}")
        sys.exit(1)

def parse_nodes(text):
    nodes = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('vmess://'):
            nodes.append(('vmess', line[8:]))
        elif line.startswith('vless://'):
            nodes.append(('vless', line[8:]))
        elif line.startswith('trojan://'):
            nodes.append(('trojan', line[9:]))
        elif line.startswith('ss://'):
            nodes.append(('ss', line[5:]))
    return nodes

def parse_vmess(encoded):
    try:
        j = json.loads(base64.b64decode(encoded).decode('utf-8'))
        return {'address': j['add'], 'port': int(j['port']), 'uuid': j['id'],
                'security': j.get('scy', 'auto'), 'network': j.get('net', 'tcp'),
                'sni': j.get('sni', j['add']), 'path': j.get('path', '/'),
                'type': j.get('type', 'none'), 'host': j.get('host', ''),
                'alpn': j.get('alpn', '')}
    except Exception:
        return None

def parse_vless(uri):
    # vless://uuid@addr:port?params#name
    try:
        m = re.match(r'([^@]+)@([^:]+):(\d+)(\?.*)?', uri)
        if not m: return None
        uuid, addr, port = m.group(1), m.group(2), int(m.group(3))
        params = urllib.parse.parse_qs(m.group(4)[1:]) if m.group(4) else {}
        return {'address': addr, 'port': port, 'uuid': uuid,
                'security': params.get('security', ['none'])[0],
                'flow': params.get('flow', [''])[0],
                'type': params.get('type', ['none'])[0],
                'sni': params.get('sni', [addr])[0],
                'path': params.get('path', ['/'])[0],
                'host': params.get('host', [''])[0]}
    except Exception:
        return None

def parse_trojan(uri):
    # trojan://password@addr:port?params#name
    try:
        m = re.match(r'([^@]+)@([^:]+):(\d+)(\?.*)?', uri)
        if not m: return None
        pwd, addr, port = m.group(1), m.group(2), int(m.group(3))
        params = urllib.parse.parse_qs(m.group(4)[1:]) if m.group(4) else {}
        return {'address': addr, 'port': port, 'password': pwd,
                'sni': params.get('sni', [addr])[0],
                'type': params.get('type', ['tcp'])[0],
                'path': params.get('path', ['/'])[0],
                'host': params.get('host', [''])[0]}
    except Exception:
        return None

def test_connection(host, port, timeout=2):
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return time.time() - start
    except Exception:
        pass
    return None

def build_xray_config(node_info, protocol):
    if protocol == 'vmess':
        outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": node_info['address'],
                    "port": node_info['port'],
                    "users": [{"id": node_info['uuid'], "security": node_info.get('security', 'auto')}]
                }]
            },
            "streamSettings": {
                "network": node_info.get('network', 'tcp'),
                "security": node_info.get('security', 'none')
            }
        }
        if node_info.get('network') == 'ws':
            outbound['streamSettings']['wsSettings'] = {
                "path": node_info.get('path', '/'),
                "headers": {"Host": node_info.get('host', '')}
            }
        if node_info.get('tls', ''):
            outbound['streamSettings']['tlsSettings'] = {"serverName": node_info.get('sni', '')}
    elif protocol == 'vless':
        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": node_info['address'],
                    "port": node_info['port'],
                    "users": [{"id": node_info['uuid'], "encryption": "none", "flow": node_info.get('flow', '')}]
                }]
            },
            "streamSettings": {
                "network": node_info.get('type', 'tcp'),
                "security": node_info.get('security', 'none'),
                "tcpSettings": {}
            }
        }
        if node_info.get('security') == 'xtls':
            outbound['streamSettings']['security'] = 'xtls'
            outbound['streamSettings']['xtlsSettings'] = {"serverName": node_info.get('sni', node_info['address'])}
        elif node_info.get('security') == 'tls':
            outbound['streamSettings']['security'] = 'tls'
            outbound['streamSettings']['tlsSettings'] = {"serverName": node_info.get('sni', node_info['address'])}
        if node_info.get('type') == 'ws':
            outbound['streamSettings']['wsSettings'] = {
                "path": node_info.get('path', '/'),
                "headers": {"Host": node_info.get('host', node_info['address'])}
            }
    elif protocol == 'trojan':
        outbound = {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": node_info['address'],
                    "port": node_info['port'],
                    "password": node_info['password']
                }]
            },
            "streamSettings": {
                "network": node_info.get('type', 'tcp'),
                "security": "tls",
                "tlsSettings": {"serverName": node_info.get('sni', node_info['address'])}
            }
        }
    else:
        return None

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 10808,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True}
        }],
        "outbounds": [outbound]
    }
    return config

def main():
    raw_text = fetch_subscription(SUBSCRIPTION_URL)
    nodes = parse_nodes(raw_text)
    if not nodes:
        print("No nodes found in subscription.")
        sys.exit(1)

    best = None
    best_latency = float('inf')
    for proto, data in nodes:
        if proto == 'vmess':
            info = parse_vmess(data)
        elif proto == 'vless':
            info = parse_vless(data)
        elif proto == 'trojan':
            info = parse_trojan(data)
        else:
            continue
        if not info:
            continue
        latency = test_connection(info['address'], info['port'])
        if latency and latency < best_latency:
            best_latency = latency
            best = (proto, info)

    if not best:
        print("No alive node found.")
        sys.exit(1)

    proto, info = best
    config = build_xray_config(info, proto)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Selected {proto} node {info['address']}:{info['port']} latency {best_latency*1000:.0f}ms")

if __name__ == '__main__':
    main()
