"""Draws the gas theme banner: a 2x1 combined-cycle plant at dusk in
silhouette and light. Prints the SVG for GAS_ART in src/themes.py."""
import random
rnd = random.Random(7)
o = []
A = o.append
GROUND = 206
DARK = "#1f0820"   # structure silhouette
MID = "#341131"    # facade detail
EDGE = "#f9a8c4"   # rim light from the low sun (right)
LAMP = "#fdba74"

A('<svg viewBox="0 0 1200 240" preserveAspectRatio="xMaxYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">')
A(f'''<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22091f"/><stop offset=".45" stop-color="#5a1a4c"/><stop offset=".8" stop-color="#b3426b"/><stop offset="1" stop-color="#f08a8f"/></linearGradient>
<radialGradient id="sun" cx="1040" cy="206" r="260" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ffd6a5" stop-opacity=".9"/><stop offset=".25" stop-color="#fb9a8c" stop-opacity=".45"/><stop offset="1" stop-color="#fb7185" stop-opacity="0"/></radialGradient>
<linearGradient id="steel" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{DARK}"/><stop offset=".8" stop-color="{DARK}"/><stop offset="1" stop-color="#3a1236"/></linearGradient>
<linearGradient id="ground" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a0619"/><stop offset="1" stop-color="#0f030e"/></linearGradient>
<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5"/></filter>
<filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.2"/></filter>
<radialGradient id="lamp"><stop offset="0" stop-color="{LAMP}" stop-opacity=".9"/><stop offset="1" stop-color="{LAMP}" stop-opacity="0"/></radialGradient>
</defs>''')
A('<rect width="1200" height="240" fill="url(#sky)"/><rect width="1200" height="240" fill="url(#sun)"/>')
# high thin clouds
for y, x, w in ((38, 760, 260), (52, 980, 200), (70, 620, 180), (30, 1080, 140)):
    A(f'<ellipse cx="{x}" cy="{y}" rx="{w/2}" ry="3" fill="#fbcfe8" fill-opacity=".14" filter="url(#blur)"/>')
# distant ridge
pts = " ".join(f"{x},{GROUND - 18 - 10 * abs(((x / 170) % 2) - 1) - rnd.random() * 3:.0f}" for x in range(0, 1201, 30))
A(f'<path d="M0 {GROUND} L{pts} L1200 {GROUND} Z" fill="#4a1840" fill-opacity=".65"/>')

def tower(x, h, op):
    """Lattice transmission tower, base at GROUND."""
    t = GROUND - h; w = h * .22
    d = (f"M{x - w:.1f} {GROUND} L{x - 2:.1f} {t} L{x + 2:.1f} {t} L{x + w:.1f} {GROUND} "
         f"M{x - w * .55:.1f} {t + h * .45:.1f} L{x + w * .55:.1f} {t + h * .45:.1f} "
         f"M{x - w * .3:.1f} {t + h * .22:.1f} L{x + w * .7:.1f} {GROUND} M{x + w * .3:.1f} {t + h * .22:.1f} L{x - w * .7:.1f} {GROUND} "
         f"M{x - w * 1.3:.1f} {t + h * .12:.1f} H{x + w * 1.3:.1f} M{x - w:.1f} {t + h * .25:.1f} H{x + w:.1f}")
    A(f'<path d="{d}" fill="none" stroke="{DARK}" stroke-opacity="{op}" stroke-width="1.2"/>')
    return (x - w * 1.3, t + h * .12), (x + w * 1.3, t + h * .12)

# far line of towers marching left
prev = None
for x, h in ((560, 50), (640, 54), (720, 58)):
    l, r = tower(x, h, .55)
    if prev:
        A(f'<path d="M{prev[0]:.0f} {prev[1]:.0f} Q {(prev[0] + l[0]) / 2:.0f} {prev[1] + 9:.0f} {l[0]:.0f} {l[1]:.0f}" fill="none" stroke="{DARK}" stroke-opacity=".45"/>')
    prev = r

def rect(x, y, w, h, fill="url(#steel)", op=1):
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" fill-opacity="{op}"/>')

def rim(x, y, h):
    A(f'<path d="M{x} {y} V{y + h}" stroke="{EDGE}" stroke-opacity=".55" stroke-width="1"/>')

def stack(x, top, r):
    """Exhaust stack with platforms, ladder cage and an aviation light."""
    A(f'<path d="M{x - r - 1} {GROUND} L{x - r + 1.5} {top} H{x + r - 1.5} L{x + r + 1} {GROUND} Z" fill="url(#steel)"/>')
    rim(x + r - 1.5, top, GROUND - top)
    for py in (top + 6, top + 44, top + 86):
        A(f'<rect x="{x - r - 3}" y="{py}" width="{2 * r + 6}" height="2" fill="{DARK}"/><path d="M{x - r - 3} {py - 4} H{x + r + 3}" stroke="{DARK}" stroke-width=".8"/>')
    A(f'<path d="M{x - r - 2} {top + 6} V{GROUND}" stroke="{MID}" stroke-width="1.5" stroke-dasharray="2 2"/>')
    A(f'<circle cx="{x}" cy="{top - 1}" r="5" fill="#f43f5e" fill-opacity=".55" filter="url(#glow)"/><circle cx="{x}" cy="{top - 1}" r="1.4" fill="#fecdd3"/>')
    # exhaust plume drifting left on the wind
    for i in range(8):
        A(f'<ellipse cx="{x - 8 - i * 20}" cy="{top - 6 - i * 1.5}" rx="{8 + i * 8}" ry="{5 + i * 3}" '
          f'fill="#fde2ec" fill-opacity="{.34 - i * .035:.2f}" filter="url(#blur)"/>')

def train(x0):
    """One gas turbine train: inlet filter house, GT enclosure, transition
    duct, HRSG with casing panels, stairs and steam drum, then the stack."""
    # inlet filter house on legs, louvered face
    fx, fy, fw, fh = x0, GROUND - 88, 36, 38
    rect(fx, fy, fw, fh)
    for i in range(1, 9):
        A(f'<path d="M{fx + 3} {fy + i * 4.2:.1f} H{fx + fw - 3}" stroke="{MID}" stroke-width="1.2"/>')
    for lx in (fx + 4, fx + fw - 6):
        rect(lx, fy + fh, 2, GROUND - fy - fh, DARK)
    A(f'<path d="M{fx + fw} {fy + 10} L{fx + fw + 14} {GROUND - 40} V{GROUND - 26} H{fx + fw}" fill="{DARK}"/>')
    # GT enclosure
    gx = fx + fw + 8
    rect(gx, GROUND - 40, 56, 40)
    for vx in range(gx + 6, gx + 52, 12):
        A(f'<rect x="{vx}" y="{GROUND - 34}" width="8" height="5" fill="{MID}"/>')
    A(f'<rect x="{gx + 22}" y="{GROUND - 49}" width="9" height="9" fill="{DARK}"/>')  # vent stack on roof
    # transition duct widening into the HRSG
    hx = gx + 56 + 16
    A(f'<path d="M{gx + 56} {GROUND - 38} L{hx} {GROUND - 104} V{GROUND} H{gx + 56} Z" fill="url(#steel)"/>')
    # HRSG body
    hw, hh = 56, 120
    rect(hx, GROUND - hh, hw, hh)
    rim(hx + hw, GROUND - hh, hh)
    for vx in range(hx + 8, hx + hw, 8):
        A(f'<path d="M{vx} {GROUND - hh + 4} V{GROUND - 4}" stroke="{MID}" stroke-width="1"/>')
    A(f'<path d="M{hx} {GROUND - hh + 30} H{hx + hw} M{hx} {GROUND - hh + 70} H{hx + hw}" stroke="{MID}" stroke-width="1.5"/>')
    # steam drum and risers on the roof
    A(f'<rect x="{hx + 10}" y="{GROUND - hh - 9}" width="{hw - 20}" height="7" rx="3.5" fill="{DARK}"/>')
    for vx in (hx + 16, hx + 30, hx + 44):
        A(f'<rect x="{vx}" y="{GROUND - hh - 3}" width="2" height="4" fill="{DARK}"/>')
    # switchback stair tower on the HRSG side
    sx = hx - 9
    A(f'<path d="M{sx} {GROUND} ' + " ".join(f"L{sx + (8 if i % 2 == 0 else 0)} {GROUND - (i + 1) * 13}" for i in range(9)) +
      f'" fill="none" stroke="{DARK}" stroke-width="1.4"/>')
    A(f'<path d="M{sx - 1} {GROUND - 117} V{GROUND} M{sx + 9} {GROUND - 117} V{GROUND}" stroke="{DARK}" stroke-width="1.2"/>')
    # stair landing lights
    for ly in (GROUND - 39, GROUND - 78):
        A(f'<circle cx="{sx + 4}" cy="{ly}" r="5" fill="url(#lamp)"/><circle cx="{sx + 4}" cy="{ly}" r="1" fill="#fff7ed"/>')
    # stack behind the HRSG outlet
    stack(hx + hw + 9, GROUND - 178, 8)
    rect(hx + hw, GROUND - 92, 10, 20)  # breeching to the stack
    return hx + hw + 18

# two gas turbine trains
end1 = train(772)
end2 = train(end1 + 2)

# steam turbine hall between the trains and the condenser
tx = 650
A(f'<path d="M{tx} {GROUND} V{GROUND - 78} L{tx + 50} {GROUND - 88} L{tx + 104} {GROUND - 78} V{GROUND} Z" fill="url(#steel)"/>')
for row in range(3):
    for col in range(9):
        lit = rnd.random() < .45
        A(f'<rect x="{tx + 8 + col * 10.5:.1f}" y="{GROUND - 66 + row * 16}" width="6" height="7" '
          f'fill="{LAMP if lit else MID}" fill-opacity="{.85 if lit else 1}"/>')
A(f'<rect x="{tx + 40}" y="{GROUND - 22}" width="22" height="22" fill="{MID}"/>')  # truck door
# step-up transformers and the switchyard in front of the hall
for i, x in enumerate((tx - 46, tx - 24)):
    A(f'<rect x="{x}" y="{GROUND - 18}" width="16" height="18" fill="{DARK}"/>')
    for fx in range(x + 2, x + 16, 3):
        A(f'<path d="M{fx} {GROUND - 16} V{GROUND - 3}" stroke="{MID}"/>')
    A(f'<path d="M{x + 4} {GROUND - 18} V{GROUND - 26} M{x + 12} {GROUND - 18} V{GROUND - 26}" stroke="{DARK}" stroke-width="1.5"/>')
A(f'<path d="M{tx - 60} {GROUND - 40} H{tx - 4} M{tx - 56} {GROUND} V{GROUND - 40} M{tx - 8} {GROUND} V{GROUND - 40} '
  f'M{tx - 32} {GROUND} V{GROUND - 46}" stroke="{DARK}" stroke-width="1.4" fill="none"/>')
_, r = tower(590, 84, .9)
A(f'<path d="M{r[0]:.0f} {r[1]:.0f} Q {tx - 50} {GROUND - 50} {tx - 56} {GROUND - 40}" fill="none" stroke="{DARK}" stroke-opacity=".8"/>')

# air-cooled condenser: an elevated fan deck on A-frame legs, far right
cx0, cw, cy = end2 + 4, 1200 - end2 - 4, GROUND - 62
if cw > 40:
    rect(cx0, cy, cw + 40, 10, DARK)
    A(f'<path d="M{cx0} {cy - 22} ' + " ".join(f"L{cx0 + i * 14 + 7} {cy - 22 + (0 if i % 2 else 18)}" for i in range(int(cw / 14) + 3)) + f'" fill="none" stroke="{DARK}" stroke-width="2"/>')
    for lx in range(cx0 + 6, 1200 + 20, 26):
        A(f'<path d="M{lx} {cy + 10} L{lx - 6} {GROUND} M{lx} {cy + 10} L{lx + 6} {GROUND}" stroke="{DARK}" stroke-width="2"/>')

# pipe rack linking the trains to the steam turbine
A(f'<path d="M{tx + 104} {GROUND - 50} H{end2} M{tx + 104} {GROUND - 45} H{end2}" stroke="{DARK}" stroke-width="2.4"/>')
for px in range(tx + 112, end2, 18):
    A(f'<path d="M{px} {GROUND - 52} V{GROUND}" stroke="{DARK}" stroke-width="1.6"/>')

# ground, perimeter fence and yard lights
A(f'<rect x="0" y="{GROUND}" width="1200" height="{240 - GROUND}" fill="url(#ground)"/>')
A(f'<path d="M520 {GROUND + 6} H1200" stroke="{DARK}" stroke-width="1"/>' +
  "".join(f'<path d="M{x} {GROUND + 6} V{GROUND - 2}" stroke="{DARK}" stroke-width=".8"/>' for x in range(524, 1200, 9)))
for x in (628, 742, 868, 990, 1112):
    A(f'<path d="M{x} {GROUND + 4} V{GROUND - 30}" stroke="{DARK}" stroke-width="1.2"/>'
      f'<circle cx="{x}" cy="{GROUND - 31}" r="9" fill="url(#lamp)"/><circle cx="{x}" cy="{GROUND - 31}" r="1.3" fill="#fff7ed"/>')
# light pooling on the ground
A(f'<ellipse cx="880" cy="{GROUND + 10}" rx="320" ry="10" fill="{LAMP}" fill-opacity=".08" filter="url(#blur)"/>')
A('</svg>')
s = "\n".join(o)
print(s)
