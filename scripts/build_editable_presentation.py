"""Export the pitch's simple absolute-positioned Beamer layout as editable PPTX."""
from pathlib import Path
import re
from math import ceil

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Pt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/presentation'
INK, PAPER, MUTED = '26332E', 'F4F1E8', '647068'
deck = Presentation()
deck.slide_width, deck.slide_height = Cm(32), Cm(18)
deck.core_properties.title = 'MIMESIS: Seven-slide pitch'
deck.core_properties.author = 'Arjun Vijay Prakash'


def groups(line):
    result, depth, start = [], 0, 0
    for i, char in enumerate(line):
        if char == '{':
            if depth == 0:
                start = i + 1
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                result.append(line[start:i])
    return result


def text(slide, content, x, y, width, size=14, face='Inter Tight', color=INK, center=False, bold=False):
    chars_per_line = width * 28.346 / (size * .46)
    lines = sum(max(1, ceil(len(p) / chars_per_line)) for p in content.split('\n'))
    height = lines * size * 1.25 / 28.346 + .15
    box = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(width), Cm(height))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.TOP
    for i, paragraph in enumerate(content.split('\n')):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.text = paragraph
        p.alignment = PP_ALIGN.CENTER if center else PP_ALIGN.LEFT
        p.font.name, p.font.size = face, Pt(size)
        p.font.bold = bold
        p.font.color.rgb = RGBColor.from_string(color)
        p.space_before = p.space_after = Pt(0)
        p.line_spacing = 1.25
    return box


source = (SOURCE / 'mimesis-pitch.tex').read_text(encoding='utf-8')
frames = re.findall(r'\\begin\{frame\}\[plain\](.*?)\\end\{frame\}', source, re.S)
for index, body in enumerate(frames):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    dark = index == 6
    foreground = PAPER if dark else INK
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string(INK if dark else PAPER)
    for line in body.splitlines():
        if line.startswith(r'\heading'):
            text(slide, groups(line)[0], 1.5, 1.05, 29, 23, color=foreground, center=True, bold=True)
        elif line.startswith((r'\putimage', r'\putscreenshot')):
            x, y, w, filename = groups(line)
            path = SOURCE / filename
            with Image.open(path) as image:
                iw, ih = image.size
            crop = line.startswith(r'\putscreenshot')
            height = float(w) * ih / (iw - 480 if crop else iw)
            picture = slide.shapes.add_picture(str(path), Cm(float(x)), Cm(float(y)), Cm(float(w)), Cm(height))
            if crop:
                picture.crop_left = picture.crop_right = 240 / iw
        elif line.startswith(r'\puttext'):
            x, y, w, raw = groups(line)
            if r'\normalfont' in raw:
                text(slide, 'Arjun Vijay Prakash', float(x), float(y), float(w), 17, bold=True)
                text(slide, 'Grade XI, City Montessori School\nKanpur Road, Lucknow, India', float(x), float(y) + .8, float(w), 12)
                continue
            explicit_size = re.search(r'\\fontsize\{(\d+)\}', raw)
            size = int(explicit_size[1]) if explicit_size else (11 if r'\smallfont' in raw else 14)
            face = 'Newsreader' if r'\editorial' in raw else 'Inter Tight'
            cleaned = re.sub(r'\\href\{[^}]+\}\{(.*?)\}', r'\1', raw)
            cleaned = re.sub(r'\\(?:smallfont|bodyfont|selectfont|editorial|bfseries|normalfont)', '', cleaned)
            cleaned = re.sub(r'\\fontsize\{\d+\}\{\d+\}|\\vspace\{[^}]+\}|\\color\{[^}]+\}', '', cleaned)
            cleaned = cleaned.replace(r'\par', '\n').replace(r'\%', '%').replace('--', '–')
            cleaned = re.sub(r'\\[A-Za-z]+', '', cleaned).replace('{', '').replace('}', '').strip()
            text(slide, cleaned, float(x), float(y), float(w), size, face,
                 foreground if dark else (MUTED if r'\color{Muted}' in raw else INK),
                 bold=r'\bfseries' in raw and r'\normalfont' not in raw)
    text(slide, 'MIMESIS / NASA Space Apps 2026', 1.2, 17.12, 20, 11, color=PAPER if dark else MUTED)
    text(slide, f'{index + 1} / 7', 28.8, 17.12, 2, 11, color=PAPER if dark else MUTED)
deck.save(SOURCE / 'mimesis-editable.pptx')
print(f'Built {len(deck.slides)} slides with editable text and cropped original screenshots.')
