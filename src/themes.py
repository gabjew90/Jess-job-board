"""Visual themes for the dashboard and digest, chosen per repo by
config.json "theme". Shared code: both watchers carry every theme.

- "battery" (Gabriel): navy, electric blue and charge-green, with battery
  modules charging, a lightning bolt and circuit traces.
- "gas" (Jess): plum, rose and coral, with a gas turbine, a flame on the
  stack, rising heat and a pipeline.

Each theme gives CSS custom properties for light and dark mode, an inline
banner illustration (decorative: the page's text stays real HTML), the
band icons used on the board and in the digest, and section icons.
"""

BATTERY_ART = """
<svg viewBox="0 0 1200 240" preserveAspectRatio="xMaxYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1730"/><stop offset=".55" stop-color="#0f2a5c"/><stop offset="1" stop-color="#0a4b7a"/>
    </linearGradient>
    <linearGradient id="charge" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#a3e635"/>
    </linearGradient>
    <linearGradient id="bolt" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fde047"/><stop offset="1" stop-color="#f59e0b"/>
    </linearGradient>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M40 0H0V40" fill="none" stroke="#38bdf8" stroke-opacity=".08"/>
    </pattern>
  </defs>
  <rect width="1200" height="240" fill="url(#bg)"/>
  <rect width="1200" height="240" fill="url(#grid)"/>
  <g fill="none" stroke="#38bdf8" stroke-opacity=".35" stroke-width="2">
    <path d="M560 200H640V150H720"/><path d="M600 40H680V90H760"/><path d="M1180 200H1120V170"/>
    <circle cx="560" cy="200" r="4" fill="#38bdf8"/><circle cx="600" cy="40" r="4" fill="#38bdf8"/>
  </g>
  <path d="M520 120 C 560 70, 600 170, 640 120 S 720 70, 760 120" fill="none" stroke="#a3e635" stroke-opacity=".55" stroke-width="2.5"/>
  <g transform="translate(790 52)">
    <g>
      <rect x="0" y="12" width="92" height="136" rx="12" fill="#0b1730" stroke="#7dd3fc" stroke-width="3"/>
      <rect x="30" y="0" width="32" height="14" rx="4" fill="#7dd3fc"/>
      <rect x="10" y="98" width="72" height="40" rx="6" fill="url(#charge)"/>
      <rect x="10" y="74" width="72" height="18" rx="5" fill="url(#charge)" opacity=".75"/>
    </g>
    <g transform="translate(120 0)">
      <rect x="0" y="12" width="92" height="136" rx="12" fill="#0b1730" stroke="#7dd3fc" stroke-width="3"/>
      <rect x="30" y="0" width="32" height="14" rx="4" fill="#7dd3fc"/>
      <rect x="10" y="98" width="72" height="40" rx="6" fill="url(#charge)"/>
      <rect x="10" y="74" width="72" height="18" rx="5" fill="url(#charge)" opacity=".75"/>
      <rect x="10" y="50" width="72" height="18" rx="5" fill="url(#charge)" opacity=".55"/>
      <rect x="10" y="26" width="72" height="18" rx="5" fill="url(#charge)" opacity=".35"/>
    </g>
    <g transform="translate(240 0)">
      <rect x="0" y="12" width="92" height="136" rx="12" fill="#0b1730" stroke="#7dd3fc" stroke-width="3"/>
      <rect x="30" y="0" width="32" height="14" rx="4" fill="#7dd3fc"/>
      <rect x="10" y="98" width="72" height="40" rx="6" fill="url(#charge)"/>
      <rect x="10" y="74" width="72" height="18" rx="5" fill="url(#charge)" opacity=".75"/>
      <rect x="10" y="50" width="72" height="18" rx="5" fill="url(#charge)" opacity=".55"/>
    </g>
    <path d="M196 30 L160 92 H186 L170 150 L222 78 H194 L214 30 Z" fill="url(#bolt)" stroke="#0b1730" stroke-width="3" stroke-linejoin="round"/>
  </g>
</svg>
"""

GAS_ART = """
<svg viewBox="0 0 1200 240" preserveAspectRatio="xMaxYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4a1942"/><stop offset=".55" stop-color="#893168"/><stop offset="1" stop-color="#e0607e"/>
    </linearGradient>
    <linearGradient id="flame" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#fb7185"/><stop offset=".5" stop-color="#fdba74"/><stop offset="1" stop-color="#fef3c7"/>
    </linearGradient>
    <linearGradient id="metal" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fbe4ec"/><stop offset="1" stop-color="#e9b8cc"/>
    </linearGradient>
    <radialGradient id="glow" cx=".5" cy=".5" r=".5">
      <stop offset="0" stop-color="#fdba74" stop-opacity=".55"/><stop offset="1" stop-color="#fdba74" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="240" fill="url(#bg)"/>
  <g fill="none" stroke="#fde2e4" stroke-opacity=".25" stroke-width="3" stroke-linecap="round">
    <path d="M1010 60 c -14 -16 14 -30 0 -46"/><path d="M1040 66 c -14 -16 14 -30 0 -46"/>
  </g>
  <circle cx="1025" cy="70" r="60" fill="url(#glow)"/>
  <path d="M1025 22 C 1000 52, 1010 70, 1025 84 C 1040 70, 1052 52, 1025 22 Z" fill="url(#flame)"/>
  <path d="M1025 48 C 1015 62, 1019 72, 1025 80 C 1031 72, 1035 62, 1025 48 Z" fill="#fff7ed"/>
  <rect x="1006" y="84" width="38" height="96" rx="4" fill="url(#metal)" stroke="#4a1942" stroke-width="3"/>
  <g stroke="#4a1942" stroke-width="3" stroke-linejoin="round">
    <path d="M700 118 L760 96 H940 L1006 112 V160 L940 176 H760 L700 154 Z" fill="url(#metal)"/>
    <path d="M760 96 V176 M820 96 V176 M880 96 V176 M940 96 V176" fill="none" stroke-opacity=".55"/>
    <ellipse cx="700" cy="136" rx="14" ry="20" fill="#fbcfe8"/>
  </g>
  <g fill="none" stroke="#fbcfe8" stroke-opacity=".7" stroke-width="2.5" stroke-linecap="round">
    <path d="M640 120 H684"/><path d="M630 136 H684"/><path d="M640 152 H684"/>
  </g>
  <g stroke="#4a1942" stroke-width="3">
    <rect x="560" y="196" width="640" height="18" rx="9" fill="#f9a8d4"/>
    <rect x="740" y="190" width="10" height="30" rx="2" fill="#fbcfe8"/><rect x="1000" y="190" width="10" height="30" rx="2" fill="#fbcfe8"/>
    <circle cx="880" cy="182" r="14" fill="none" stroke="#fde2e4"/><path d="M880 168 V196 M866 182 H894" stroke="#fde2e4"/>
  </g>
</svg>
"""

THEMES = {
    "battery": {
        "name": "battery",
        "light": {"bg": "#f3f7fc", "card": "#ffffff", "ink": "#0b1730", "muted": "#51607a",
                  "accent": "#1d4ed8", "accent2": "#0891b2", "border": "#d8e2f0", "head": "#e8f0fb"},
        "dark": {"bg": "#081226", "card": "#0e1c38", "ink": "#e6eefc", "muted": "#9fb0cc",
                 "accent": "#60a5fa", "accent2": "#22d3ee", "border": "#1e335c", "head": "#122650"},
        "bands": {"top": ("#a3e635", "#1a2e05"), "strong": ("#22d3ee", "#062a33"),
                  "possible": ("#93c5fd", "#0b2147"), "weak": ("#cbd5e1", "#1e293b"),
                  "misfit": ("#e2e8f0", "#475569")},
        "icons": {"top": "⚡", "strong": "🔋", "possible": "🔌", "weak": "▫️", "misfit": "·"},
        "mark": "⚡", "art": BATTERY_ART,
        "tagline": "Grid-scale storage · data center power · AI infrastructure",
    },
    "gas": {
        "name": "gas",
        "light": {"bg": "#fdf4f7", "card": "#ffffff", "ink": "#3b1236", "muted": "#7a5571",
                  "accent": "#a21caf", "accent2": "#e11d48", "border": "#f2d5e1", "head": "#fbe7ef"},
        "dark": {"bg": "#1d0b1b", "card": "#2a1027", "ink": "#fbe9f1", "muted": "#d3a9c2",
                 "accent": "#f0abfc", "accent2": "#fb7185", "border": "#4a1d44", "head": "#3a1535"},
        "bands": {"top": ("#fb7185", "#4c0519"), "strong": ("#f0abfc", "#3b0a3f"),
                  "possible": ("#fbcfe8", "#500724"), "weak": ("#ede4ea", "#4a3a45"),
                  "misfit": ("#f5eef2", "#7a6a74")},
        "icons": {"top": "🔥", "strong": "🌸", "possible": "💨", "weak": "▫️", "misfit": "·"},
        "mark": "🔥", "art": GAS_ART,
        "tagline": "Power development · on-site generation · data center power",
    },
}

import html
import logging

log = logging.getLogger(__name__)

DEFAULT = "battery"


def get(name: str | None) -> dict:
    key = (name or DEFAULT).strip().lower()
    if key not in THEMES:
        log.warning("Unknown theme %r; using %r", name, DEFAULT)
        key = DEFAULT
    return THEMES[key]


def css_vars(theme: dict) -> str:
    """:root custom properties for light mode, overridden in dark mode."""
    def block(vals):
        return " ".join(f"--{k}: {v};" for k, v in vals.items())
    bands = " ".join(f"--b-{b}: {bg}; --b-{b}-ink: {ink};"
                     for b, (bg, ink) in theme["bands"].items())
    return (f":root {{ color-scheme: light dark; {block(theme['light'])} {bands} }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root {{ {block(theme['dark'])} }} }}")


def banner_svg(theme: dict, title: str) -> str:
    """A standalone banner for the digest: the illustration plus the title,
    since a GitHub issue cannot overlay HTML text on an image."""
    art = theme["art"].strip()
    head, body = art.split(">", 1)
    font = 'font-family="system-ui, -apple-system, Segoe UI, sans-serif"'
    # A shade under the text so the art behind it never competes.
    text = ('<defs><linearGradient id="shade" x1="0" x2="1"><stop offset="0" stop-color="#000" '
            'stop-opacity=".45"/><stop offset=".6" stop-color="#000" stop-opacity="0"/>'
            '</linearGradient></defs><rect width="1200" height="240" fill="url(#shade)"/>'
            f'<text x="48" y="112" {font} font-size="46" font-weight="800" fill="#ffffff">{title}</text>'
            f'<text x="50" y="150" {font} font-size="18" fill="#ffffff" fill-opacity=".85">'
            f'{html.escape(theme["tagline"])}</text>')
    head = head.replace('preserveAspectRatio="xMaxYMid slice"', 'width="1200" height="240"')
    return head + ">" + body.replace("</svg>", text + "</svg>")
