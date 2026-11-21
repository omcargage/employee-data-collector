def srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def luminance(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
    return 0.2126 * srgb_to_lin(r) + 0.7152 * srgb_to_lin(g) + 0.0722 * srgb_to_lin(b)

def contrast(hex1, hex2):
    l1 = luminance(hex1)
    l2 = luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

# Light mode checks
bg_light = '#F7F6F3'
card_light = '#FFFFFF'
colors_light = {
    'text-primary': '#181816',
    'text-secondary': '#54524C',
    'text-muted': '#6B6860',
    'primary': '#1F5C63',
    'status-steady': '#376842',
    'status-stretched': '#8A6014',
    'status-strained': '#AC4422',
    'status-overloaded': '#A12E44',
    'status-calibrating': '#3F5965',
}

print('=== LIGHT THEME CONTRAST RATIOS (on #FFFFFF / #F7F6F3) ===')
all_pass = True
for name, c in colors_light.items():
    cr_white = contrast(c, card_light)
    cr_bg = contrast(c, bg_light)
    is_ok = cr_white >= 4.5 and cr_bg >= 4.5
    if not is_ok:
        all_pass = False
    status_str = "PASS (>= 4.5:1)" if is_ok else "FAIL"
    print(f'{name:18} ({c}): {cr_white:5.2f}:1 on white, {cr_bg:5.2f}:1 on app bg -> {status_str}')

# Dark mode checks
card_dark = '#222422'
bg_dark = '#151615'
colors_dark = {
    'text-primary': '#F3F3F1',
    'text-secondary': '#C2C5BE',
    'text-muted': '#9DA09A',
    'primary': '#4AB1BC',
    'status-steady': '#78B585',
    'status-stretched': '#E5B65A',
    'status-strained': '#F08B6B',
    'status-overloaded': '#E06D83',
    'status-calibrating': '#8EB0BF',
}

print('\n=== DARK THEME CONTRAST RATIOS (on #222422 / #151615) ===')
for name, c in colors_dark.items():
    cr_card = contrast(c, card_dark)
    cr_bg = contrast(c, bg_dark)
    is_ok = cr_card >= 4.5 and cr_bg >= 4.5
    if not is_ok:
        all_pass = False
    status_str = "PASS (>= 4.5:1)" if is_ok else "FAIL"
    print(f'{name:18} ({c}): {cr_card:5.2f}:1 on card,  {cr_bg:5.2f}:1 on app bg -> {status_str}')

print('\n' + ('ALL CONTRAST RATIOS STRICTLY MEET WCAG AA (>= 4.5:1)!' if all_pass else 'SOME RATIOS FAILED!'))
