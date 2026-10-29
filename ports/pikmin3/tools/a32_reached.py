"""Words a32.emit rejects that the analysis reaches inside functions (fall-through or branch target), by mnemonic:
the real translation gaps.   python tools/a32_reached.py <ExeFS dir>"""
import collections, os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nxloader, codegen32
import capstone as cs
mods, _, _ = nxloader.load_program(sys.argv[1])
p = codegen32.Program32(mods); p.analyze()
md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM)
c = collections.Counter(); ex = {}
for f in p.funcs.values():
    for x in f.addrs:
        w, r = p.decode(x)
        if r is not None: continue
        prev = p.decode(x - 4)[1]
        if isinstance(prev, tuple) and prev[0] == 'bl': continue      # 'bl over a literal' idiom: data after the bl
        i = next(md.disasm_lite(struct.pack('<I', w), x), None)
        k = re.sub(r'(eq|ne|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)(\.|$)', r'\2', i[2]) if i else '?'
        c[k] += 1; ex.setdefault(k, '%x: %08x %s' % (x, w, (i[2] + ' ' + i[3]) if i else ''))
print('reached rejects:', sum(c.values()))
for k, n in c.most_common(40): print('  %6d %-10s %s' % (n, k, ex[k]))
