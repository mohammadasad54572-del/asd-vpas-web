# decode_pcap.py
# Usage: python3 decode_pcap.py yourfile.pcapng output.txt
# Install: pip install scapy

from scapy.all import rdpcap, UDP, TCP, IP, Raw, DNS, DNSQR, DNSRR
import sys
from collections import Counter

def decode_pcap(input_file, output_file):
    print(f"Loading {input_file}...")
    pcap = rdpcap(input_file)
    print(f"Total packets: {len(pcap)}")

    # Auto-detect client IP (most frequent src)
    src_ips = Counter()
    for pkt in pcap:
        if IP in pkt:
            src_ips[pkt[IP].src] += 1
    CLIENT_IP = src_ips.most_common(1)[0][0]
    print(f"Client IP: {CLIENT_IP}")

    def direction(pkt):
        if IP in pkt:
            return 'C2S' if pkt[IP].src == CLIENT_IP else 'S2C'
        return 'C2S'

    def get_proto(pkt):
        if TCP in pkt:
            flags = pkt[TCP].flags
            f = ''
            if flags & 0x02: f += 'SYN'
            if flags & 0x10: f += 'ACK'
            if flags & 0x01: f += 'FIN'
            if flags & 0x04: f += 'RST'
            if flags & 0x08: f += 'PSH'
            if Raw in pkt:
                raw = bytes(pkt[Raw])
                for prefix in [b'GET ', b'POST', b'PUT ', b'DELETE', b'HEAD']:
                    if raw.startswith(prefix):
                        info = raw.split(b'\r\n')[0].decode(errors='replace')
                        return f'HTTP_REQ [{f}]', info
                if raw.startswith(b'HTTP/'):
                    info = raw.split(b'\r\n')[0].decode(errors='replace')
                    return f'HTTP_RESP [{f}]', info
                return f'TCP_DATA [{f}]', raw.hex()[:120]
            return f'TCP_CTRL [{f}]', ''

        elif UDP in pkt:
            if DNS in pkt:
                dns = pkt[DNS]
                if dns.qr == 0 and DNSQR in dns:
                    name = dns[DNSQR].qname.decode(errors='replace').rstrip('.')
                    return 'DNS_QUERY', name
                elif dns.qr == 1 and DNSRR in dns:
                    name = dns[DNSRR].rrname.decode(errors='replace').rstrip('.')
                    return 'DNS_RESP', name
            if Raw in pkt:
                return 'UDP_DATA', bytes(pkt[Raw]).hex()[:120]
            return 'UDP_DATA', ''

        return 'OTHER', ''

    lines = []
    lines.append('=' * 130)
    lines.append(f'  FILE: {input_file}')
    lines.append(f'  TOTAL PACKETS: {len(pcap)}   CLIENT IP: {CLIENT_IP}')
    lines.append('=' * 130)
    lines.append(f'{"NO":>6}  {"TIME":>10}  {"DIR":<4}  {"PROTO":<22}  {"SRC":<22}  {"DST":<22}  {"LEN":>5}  BODY / INFO')
    lines.append('-' * 130)

    base_time = None
    tcp_c = udp_c = dns_c = http_c = 0

    for i, pkt in enumerate(pcap):
        if IP not in pkt:
            continue

        ts = float(pkt.time)
        if base_time is None:
            base_time = ts
        rel = ts - base_time

        src_ip = pkt[IP].src
        dst_ip = pkt[IP].dst

        if TCP in pkt:
            sport, dport = pkt[TCP].sport, pkt[TCP].dport
            tcp_c += 1
        elif UDP in pkt:
            sport, dport = pkt[UDP].sport, pkt[UDP].dport
            udp_c += 1
            if DNS in pkt:
                dns_c += 1
        else:
            sport = dport = 0

        proto, body = get_proto(pkt)
        if 'HTTP' in proto:
            http_c += 1

        src = f'{src_ip}:{sport}'
        dst = f'{dst_ip}:{dport}'
        dirc = direction(pkt)

        lines.append(
            f'{i+1:>6}  {rel:>10.3f}  {dirc:<4}  {proto:<22}  {src:<22}  {dst:<22}  {len(pkt):>5}  {body}'
        )

    # Summary
    lines.append('')
    lines.append('=' * 130)
    lines.append('SUMMARY')
    lines.append('=' * 130)
    lines.append(f'  TCP     : {tcp_c}')
    lines.append(f'  UDP     : {udp_c}')
    lines.append(f'  DNS     : {dns_c}')
    lines.append(f'  HTTP    : {http_c}')

    ips = set()
    for pkt in pcap:
        if IP in pkt:
            ips.add(pkt[IP].src)
            ips.add(pkt[IP].dst)
    lines.append(f'  IPs     : {len(ips)}')
    lines.append('')
    lines.append('  ALL IPs:')
    for ip in sorted(ips):
        lines.append(f'    {ip}')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"Done! → {output_file}")
    print(f"TCP: {tcp_c}, UDP: {udp_c}, DNS: {dns_c}, HTTP: {http_c}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 decode_pcap.py input.pcapng output.txt")
        sys.exit(1)
    decode_pcap(sys.argv[1], sys.argv[2])