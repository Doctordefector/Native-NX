"""Instructions capstone decodes but a32.emit rejects (None) or leaves untranslated (UNDEF), by mnemonic.
Data words in .text show up too; real gaps stand out by count.   python tools/a32_gaps.py <ExeFS dir>"""
import collections, os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nxloader, a32
import capstone as cs

mods, _, _ = nxloader.load_program(sys.argv[1])
md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM)
rej = collections.Counter(); und = collections.Counter(); ex = {}
seen = set()
for m in mods:
    for o in range(m.text[0], m.text[0] + m.text[1], 4):
        w = struct.unpack_from('<I', m.image, o)[0]
        if w in seen: continue
        seen.add(w)
        r = a32.emit(w, m.base + o)
        if r is not None and not (isinstance(r, str) and 'UNDEF' in r): continue
        i = next(md.disasm_lite(struct.pack('<I', w), m.base + o), None)
        if not i: continue
        k = re.sub(r'(eq|ne|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)(\.|$)', r'\2', i[2])
        (rej if r is None else und)[k] += 1
        ex.setdefault(k, '%08x %s %s' % (w, i[2], i[3]))
for name, c in (('rejected (None)', rej), ('UNDEF', und)):
    print('== %s: %d distinct words' % (name, sum(c.values())))
    for k, n in c.most_common(60): print('  %6d %-12s e.g. %s' % (n, k, ex[k]))
