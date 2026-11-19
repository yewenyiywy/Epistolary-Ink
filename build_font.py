"""Build the Epistolary Ink Latin alphabet from its artist-supplied density sheet."""
from pathlib import Path
import string
import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, label
from contourpy import contour_generator
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.ttLib import TTFont
from fontTools import subset
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source' / 'ink-density.png'
FONTS = ROOT / 'fonts'
FONTS.mkdir(exist_ok=True)
ROWS = [(0, 190, 145), (190, 360, 327), (360, 550, 493), (550, 724, 659)]
CHARS = string.ascii_uppercase + string.ascii_lowercase
SCALE = 5.7
LEVELS = [22, 55, 90, 125, 165, 205]
OPACITIES = [0.16, 0.18, 0.20, 0.25, 0.32, 0.46]

def outline(density, threshold, baseline, pad_x=0):
    pen = TTGlyphPen(None)
    data = np.pad(density.astype(float), 1)
    for contour in contour_generator(z=data).lines(threshold):
        points = [(round((x-1)*SCALE+pad_x), round((baseline-(y-1))*SCALE)) for x,y in contour]
        points = list(dict.fromkeys(points))
        if len(points) < 4:
            continue
        area = sum(x1*y2-x2*y1 for (x1,y1),(x2,y2) in zip(points, points[1:]+points[:1]))
        if abs(area) < 36:
            continue
        pen.moveTo(points[0])
        for pt in points[1:]:
            pen.lineTo(pt)
        pen.closePath()
    return pen.glyph()

def main():
    density = np.array(Image.open(SOURCE).convert('L'))
    glyphs = {'.notdef': TTGlyphPen(None).glyph(), 'space': TTGlyphPen(None).glyph()}
    metrics = {'.notdef': (480, 0), 'space': (275, 0)}
    cmap = {32:'space'}
    layers = {}
    for r,(top,bottom,base) in enumerate(ROWS):
        row = density[top:bottom]
        active = binary_closing((row >= 40).sum(axis=0)>1, iterations=6)
        labels, n = label(active)
        assert n == 13, (r, n)
        for i in range(1,14):
            char = CHARS[r*13+i-1]
            name = f'uni{ord(char):04X}'
            cols = np.flatnonzero(labels==i)
            left = max(0, cols[0]-7)
            right = min(row.shape[1],cols[-1]+8)
            cell = row[:,left:right]
            advance = round(cell.shape[1]*SCALE+15)
            glyphs[name] = outline(cell,55,base-top,15)
            metrics[name] = (advance,0)
            cmap[ord(char)] = name
            layers[name] = []
            for j,level in enumerate(LEVELS):
                layer = f'{name}.ink{j}'
                glyphs[layer] = outline(cell,level,base-top,15)
                metrics[layer] = (advance,0)
                layers[name].append((layer,j))
    order = list(glyphs)
    # Set actual side bearings so outline positions survive serialization.
    for name,glyph in glyphs.items():
        if glyph.numberOfContours > 0:
            glyph.recalcBounds(glyphs)
            metrics[name] = (metrics[name][0],glyph.xMin)
    fb = FontBuilder(1000,isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=850,descent=-330)
    fb.setupNameTable({'familyName':'Epistolary Ink','styleName':'Regular','uniqueFontIdentifier':'EpistolaryInk-Regular-0.1','fullName':'Epistolary Ink Regular','psName':'EpistolaryInk-Regular','version':'Version 0.1.0','copyright':'Copyright 2026 Wenyi Ye','licenseDescription':'SIL Open Font License 1.1','licenseInfoURL':'https://openfontlicense.org/'})
    fb.setupOS2(sTypoAscender=850,sTypoDescender=-330,usWinAscent=1050,usWinDescent=400,usWeightClass=400)
    fb.setupPost()
    fb.setupMaxp()
    fb.font.save(FONTS/'EpistolaryInk-Regular.ttf')
    regular = TTFont(FONTS/'EpistolaryInk-Regular.ttf')
    sub = subset.Subsetter()
    sub.populate(unicodes=sorted(cmap))
    sub.subset(regular)
    regular.save(FONTS/'EpistolaryInk-Regular.ttf')
    fb.font['COLR'] = buildCOLR(layers, version=0, glyphMap=fb.font.getReverseGlyphMap())
    fb.font['CPAL'] = buildCPAL([[(0.20,0.145,0.10,a) for a in OPACITIES]])
    for name_id, value in {1:'Epistolary Ink Color',3:'EpistolaryInk-Color-0.1',4:'Epistolary Ink Color',6:'EpistolaryInk-Color'}.items():
        for platform,encoding,language in [(3,1,1033),(1,0,0)]:
            fb.font['name'].setName(value,name_id,platform,encoding,language)
    fb.font.save(FONTS/'EpistolaryInk-Color.ttf')
    # WOFF2 needs Brotli. Python Brotli is preferred; Node's built-in encoder
    # is a portable fallback for development environments that have Node.js.
    import fontTools.ttLib.woff2 as woff2
    if not woff2.haveBrotli:
        class NodeBrotli:
            MODE_FONT = 2
            MODE_TEXT = 1
            @staticmethod
            def compress(data, mode=0):
                js = 'const fs=require("fs"),z=require("zlib");process.stdout.write(z.brotliCompressSync(fs.readFileSync(0),{params:{[z.constants.BROTLI_PARAM_MODE]:Number(process.argv[1])}}))'
                return subprocess.run(['node','-e',js,str(mode)],input=data,check=True,capture_output=True).stdout
            @staticmethod
            def decompress(data):
                return subprocess.run(['node','-e','process.stdout.write(require("zlib").brotliDecompressSync(require("fs").readFileSync(0)))'],input=data,check=True,capture_output=True).stdout
        woff2.brotli = NodeBrotli
        woff2.haveBrotli = True
    for variant in ('Regular','Color'):
        font = TTFont(FONTS/f'EpistolaryInk-{variant}.ttf')
        font.flavor = 'woff2'
        try:
            font.save(FONTS/f'EpistolaryInk-{variant}.woff2')
        except (ImportError, FileNotFoundError):
            # Build environments without Python Brotli can install requirements.txt.
            font.flavor = 'woff'
            font.save(FONTS/f'EpistolaryInk-{variant}.woff')

if __name__ == '__main__':
    main()
