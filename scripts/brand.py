"""Shared palette for the profile SVGs.

The dark sweep is copied from the personal website (src/lib/sweep.ts) so the
profile and the site read as one identity. The light sweep is a darkened
variant: the website's pastel stops fall below 3:1 against GitHub's white
background, which is the WCAG floor for graphical objects.
"""

THEMES = {
    "dark": {
        "sweep": [("0%", "#FF9E8A"), ("34%", "#54E09C"), ("64%", "#2FD2CE"), ("100%", "#36ADEE")],
        "muted": "#8b949e",
        "ink": "#e6edf3",  # GitHub's primary text colour on dark
        "empty": "#161b22",  # GitHub's empty contribution square on dark
    },
    "light": {
        "sweep": [("0%", "#C4553F"), ("34%", "#1A8F5A"), ("64%", "#12827F"), ("100%", "#1F6FB2")],
        "muted": "#59636e",
        "ink": "#1f2328",  # GitHub's primary text colour on light
        "empty": "#eff2f5",  # GitHub's empty contribution square on light
    },
}

# System stacks only. An SVG loaded through <img> is sandboxed and cannot fetch
# web fonts, so anything else silently falls back to a serif.
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"


def gradient(gid: str, theme: str, x1: float, x2: float) -> str:
    """Horizontal sweep fixed in user space, so every bar or segment takes its
    colour from where it sits rather than restarting the sweep per shape."""
    stops = "".join(
        f'<stop offset="{off}" stop-color="{color}"/>' for off, color in THEMES[theme]["sweep"]
    )
    return (
        f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1}" y1="0" x2="{x2}" y2="0">'
        f"{stops}</linearGradient>"
    )
