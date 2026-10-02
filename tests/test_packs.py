import json
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from packs import load_packs, atlases

class Packs(unittest.TestCase):
    def test_all_atlases_fit_actual_png_dimensions(self):
        count = 0
        for name, file in atlases():
            count += 1
            atlas=json.loads(file.read_text())
            for required in ['resting-smile','listening-blink','speaking-small','speaking-wide','speaking-rounded']:
                self.assertIn(required,atlas['frames'])
            for frame in atlas['frames'].values():
                image=file.parent/frame['image']
                with image.open('rb') as handle:header=handle.read(26)
                self.assertEqual(header[:8],b'\x89PNG\r\n\x1a\n')
                width,height=struct.unpack('>II',header[16:24])
                self.assertEqual(header[25],6) # truecolor RGBA
                self.assertLessEqual(frame['x']+frame['width'],width)
                self.assertLessEqual(frame['y']+frame['height'],height)
        self.assertEqual(count,10)
        self.assertEqual(load_packs()['neutral']['persona'],'')
