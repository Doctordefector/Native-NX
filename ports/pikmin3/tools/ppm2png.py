"""Binary PPM (P6, the runtime's screenshots) to PNG, stdlib only.   python tools/ppm2png.py in.ppm [out.png]"""
import struct, sys, zlib
src = sys.argv[1]; dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit('.', 1)[0] + '.png'
d = open(src, 'rb').read()
f = d.split(maxsplit=4); assert f[0] == b'P6' and f[3] == b'255', 'not an 8-bit P6 PPM'
w, h = int(f[1]), int(f[2]); px = d[len(d) - w * h * 3:]
raw = b''.join(b'\0' + px[y * w * 3:(y + 1) * w * 3] for y in range(h))
chunk = lambda t, b: struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b))
open(dst, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
print(dst, w, h)
